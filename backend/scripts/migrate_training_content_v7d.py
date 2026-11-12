"""Explicit, backed-up upgrade. Default is dry-run; never run at server startup."""
import argparse
import asyncio
import json
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


async def run(args):
    # Same model registration as seed, only when the operator actually invokes this CLI.
    import scripts.seed_training_labs  # noqa: F401
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from core.config import get_settings
    from core.database import resolve_database_url, is_sqlite_url
    from core.migrations import assert_schema_ready
    from modules.training.catalog_migration import upgrade, restore
    url=resolve_database_url(get_settings())
    # A dry-run must not bootstrap an empty database as an incidental side effect.
    if is_sqlite_url(url):
        database=make_url(url).database
        if not database or database==':memory:' or not Path(database).is_file():
            raise ValueError('请先完成数据库首次配置；内容迁移不会创建空库')
    engine=create_async_engine(url,pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(assert_schema_ready)
        async with async_sessionmaker(engine,expire_on_commit=False)() as db:
            if args.restore:
                return await restore(db,args.restore,dry_run=not args.apply)
            return await upgrade(db,dry_run=not args.apply,backup_path=args.backup)
    finally:
        await engine.dispose()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply',action='store_true',help='显式写入；省略则仅演练')
    parser.add_argument('--backup',help='写入前保存的新备份路径，已存在的文件拒绝覆盖')
    parser.add_argument('--restore',help='从D完整备份恢复；已被用户再次修改的条目跳过')
    parser.add_argument('--report',help='将结果保存为新的JSON文件')
    args=parser.parse_args()
    if args.apply and not args.restore and not args.backup: parser.error('--apply需要--backup')
    result=asyncio.run(run(args))
    if args.report:
        from modules.training.catalog_migration import write_new
        write_new(args.report,result)
    print(json.dumps(result,ensure_ascii=False,indent=2))
