"""Replay an encrypted MySQL backup into a new named database and verify upgrade.

The configured DB is the isolated destination. SOURCE_DB_* defines the read-only
source to compare. Never migrates the source or overwrites an existing database.
Credentials and SQL data stay in memory; report contains only identities/hashes.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
from decimal import Decimal
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import subprocess
import sys
import uuid

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def require(value, reason):
    if not value:
        raise ValueError(reason)


def scalar(value):
    if isinstance(value, bytes):
        return {'bytes': value.hex()}
    if isinstance(value, (date, datetime, Decimal)):
        return {type(value).__name__: str(value)}
    return value


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def capture_database(engine, columns=None, expected_promotions=None):
    from sqlalchemy import inspect, text
    with engine.connect() as conn:
        inspector = inspect(conn)
        tables = sorted(inspector.get_table_names())
        result = {}
        for table in tables:
            if table == 'alembic_version':
                continue
            if columns is not None and table not in columns:
                continue
            names = columns[table] if columns else [col['name'] for col in inspector.get_columns(table)]
            quote = engine.dialect.identifier_preparer.quote_identifier
            rows = conn.execute(text('SELECT ' + ','.join(quote(col) for col in names) + ' FROM ' + quote(table)))
            encoded = []
            for row in rows:
                values = list(row)
                if table == 'topology_runtime_check' and expected_promotions:
                    if values[names.index('id')] in expected_promotions:
                        values[names.index('version_id')] = None
                encoded.append(canonical([scalar(value) for value in values]))
            encoded.sort()
            result[table] = {'columns': names, 'rows': len(encoded),
                             'content_sha256': hashlib.sha256(canonical(encoded).encode()).hexdigest()}
        revision = conn.execute(text('SELECT version_num FROM alembic_version')).scalar_one() if 'alembic_version' in tables else None
        return {'tables': result, 'revision': revision}


def run(args):
    from cryptography.fernet import Fernet
    from sqlalchemy import create_engine, inspect, text
    from sqlalchemy.engine import URL
    from core.config import get_settings
    from core.database import resolve_database_url
    from core.live_evidence import capture_binding, binding_unchanged
    from core.migrations import assert_schema_ready, prepare_database, _head
    from core.runtime_identity import runtime_identity

    settings = get_settings()
    require(settings.db_backend == 'mysql' and settings.db_url == '' and settings.db_name == args.expect_database,
            'explicit_target_database_required')
    require(re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,62}', args.expect_database), 'unsafe_database_name')
    fields = {key: os.environ['SOURCE_DB_' + key.upper()] for key in ('host', 'port', 'name', 'user', 'password')}
    source_settings = settings.model_copy(update={f'db_{key}': int(value) if key == 'port' else value for key, value in fields.items()})
    source_identity = runtime_identity(source_settings)
    target_identity = runtime_identity(settings)
    require((fields['host'], int(fields['port']), fields['name']) != (settings.db_host, settings.db_port, settings.db_name), 'source_target_collision')
    require(settings.db_host in {'127.0.0.1', 'localhost'}, 'local_isolated_target_required')
    encrypted = args.backup.read_bytes()
    sql = Fernet(settings.fernet_key.encode()).decrypt(encrypted)
    require(b'CREATE TABLE' in sql and not re.search(rb'(?mi)^\s*(USE\s|CREATE\s+DATABASE\b)', sql), 'single_database_dump_required')
    start = capture_binding(settings)
    source_url = resolve_database_url(source_settings).replace('mysql+aiomysql', 'mysql+pymysql')
    target_url = resolve_database_url(settings).replace('mysql+aiomysql', 'mysql+pymysql')
    source = create_engine(source_url)
    target = create_engine(target_url)
    admin = create_engine(URL.create('mysql+pymysql', username=settings.db_user, password=settings.db_password,
                                    host=settings.db_host, port=settings.db_port))
    report = {'schema': 1, 'producer': 'verify_live_migration', 'run_id': uuid.uuid4().hex,
              'source_identity': source_identity, 'target_identity': target_identity,
              'backup': {'encrypted_sha256': hashlib.sha256(encrypted).hexdigest(), 'sql_sha256': hashlib.sha256(sql).hexdigest(), 'encrypted_bytes': len(encrypted)},
              'ok': False}
    try:
        before_source = capture_database(source)
        require(before_source['tables'] and before_source['revision'] == '0001_initial', 'recognized_legacy_source_required')
        with admin.begin() as conn:
            require(args.expect_database not in inspect(conn).get_schema_names(), 'target_already_exists')
            conn.execute(text('CREATE DATABASE `' + args.expect_database + '` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci'))
            # The dump is data, not trusted code. Its executor cannot affect the
            # source or any other schema, even if SQL names another database.
            restore_user = 'restore_' + uuid.uuid4().hex[:12]
            restore_password = secrets.token_urlsafe(32)
            # MySQL database-level grants interpret underscores as wildcards.
            grant_database = args.expect_database.replace('_', r'\_')
            conn.exec_driver_sql("CREATE USER %s@'localhost' IDENTIFIED BY %s", (restore_user, restore_password))
            conn.exec_driver_sql('GRANT ALL PRIVILEGES ON `' + grant_database + "`.* TO %s@'localhost'", (restore_user,))
        environment = dict(os.environ, MYSQL_PWD=restore_password)
        restore_engine = create_engine(URL.create('mysql+pymysql', username=restore_user,
                                      password=restore_password, host=settings.db_host,
                                      port=settings.db_port, database=settings.db_name))
        try:
            with restore_engine.connect() as conn:
                grants = [row[0] for row in conn.exec_driver_sql('SHOW GRANTS')]
                expected_grant = 'GRANT ALL PRIVILEGES ON `' + grant_database + '`.* TO '
                require(len(grants) == 2 and all(row.startswith('GRANT USAGE ON *.* TO ') or row.startswith(expected_grant) for row in grants),
                        'restore_account_not_exclusively_target_scoped')
                require(any(row.startswith(expected_grant) for row in grants), 'restore_account_missing_target_grant')
        finally:
            restore_engine.dispose()
        restored = subprocess.run([str(args.mysql_client), '--no-defaults', '--host='+settings.db_host,
                                   '--port='+str(settings.db_port), '--user='+restore_user,
                                   '--default-character-set=utf8mb4', '--binary-mode', args.expect_database],
                                  env=environment, input=sql, capture_output=True, timeout=120)
        require(restored.returncode == 0, 'restore_failed_details_suppressed')
        restored_state = capture_database(target)
        report['source_before'] = before_source
        report['restored_before'] = restored_state
        report['restore_privilege_scope'] = {'database': args.expect_database, 'new_account': True,
            'global_privileges': False, 'show_grants_sha256': hashlib.sha256(canonical(sorted(grants)).encode()).hexdigest()}
        require(restored_state == before_source, 'backup_does_not_match_current_source')
        columns = {name: value['columns'] for name, value in before_source['tables'].items()}
        with target.connect() as conn:
            rows = conn.execute(text("SELECT c.id, c.version_id, v.source_name FROM topology_runtime_check c JOIN topology_version v ON c.version_id=v.id AND c.topology_id=v.topology_id WHERE v.source_type='ensp'"))
            promotions = {check_id: version for check_id, version, name in rows if name == f'ensp-runtime-check-{check_id}'}
        expected_after = capture_database(target, columns, promotions)
        report['expected_after_original_columns'] = expected_after
        prepare_database(target_url, backup_file=str(args.backup))
        after = capture_database(target, columns)
        with target.connect() as conn:
            assert_schema_ready(conn)
            confirmed = dict(conn.execute(text('SELECT id, confirmed_version_id FROM topology_runtime_check')).all())
        report['expected_runtime_promotions'] = [{'check_id': key, 'old_version_id': value, 'confirmed_version_id': value} for key, value in sorted(promotions.items())]
        repeated = prepare_database(target_url, backup_file=str(args.backup))
        after_repeat = capture_database(target, columns)
        after_source = capture_database(source)
        report.update(target_after=after, target_repeated=after_repeat, source_after=after_source,
                      repeat_was_noop=repeated is None)
        report['checks'] = {
            'restore_matches_source': restored_state == before_source,
            'all_original_data_preserved': after['tables'] == expected_after['tables'],
            'only_proven_runtime_promotions': all(value == promotions.get(key) for key, value in confirmed.items()),
            'upgraded_to_head': after['revision'] == _head(),
            'repeat_idempotent': repeated is None and after == after_repeat,
            'source_unchanged': before_source == after_source,
        }
        finish = capture_binding(settings)
        report.update(binding={'start': start, 'finish': finish}, started_at=start['captured_at'], finished_at=finish['captured_at'])
        report['checks']['build_runtime_unchanged'] = binding_unchanged(start, finish)
        report['ok'] = all(report['checks'].values())
        return report
    finally:
        source.dispose()
        target.dispose()
        admin.dispose()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backup', type=Path, required=True)
    parser.add_argument('--mysql-client', type=Path, required=True)
    parser.add_argument('--expect-database', required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args(argv)
    logging.disable(logging.CRITICAL)
    try:
        report = run(args)
    except Exception as exc:
        report = {'schema': 1, 'producer': 'verify_live_migration', 'ok': False, 'error_type': type(exc).__name__}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, ensure_ascii=False, indent=2)
    print(json.dumps({'ok': report['ok'], 'report': str(args.report), 'checks': report.get('checks', {})}))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
