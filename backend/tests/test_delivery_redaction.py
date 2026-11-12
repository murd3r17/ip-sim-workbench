"""Delivery regressions: HTTP config views and fragmented terminal input stay private."""
import json
import uuid
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from modules.deploy.models import ChangeLevel, DeployStatus, DeployTask, ConfigVersion
from modules.deploy.router import compare_versions, get_deploy_task
from modules.webssh.session_logger import TerminalSessionLogger
from core.redaction import redact_payload, redact_sensitive


def synthetic_value():
    # Generated at runtime; no real credential or reusable fixture secret.
    return uuid.uuid4().hex


@pytest.mark.asyncio
async def test_version_comparison_never_exposes_sensitive_diff():
    markers = [synthetic_value(), synthetic_value()]
    versions = [ConfigVersion(id=i + 1, device_id=1, version_number=i + 1,
                               config_snapshot=f"password cipher {marker}\nsysname R{i}",
                               created_at=datetime(2026, 10, 11))
                for i, marker in enumerate(markers)]
    result = await compare_versions(1, 2, AsyncMock(get=AsyncMock(side_effect=versions)), {})
    payload = json.dumps(result)
    assert all(marker not in payload for marker in markers)
    assert "sysname" in payload


@pytest.mark.asyncio
async def test_task_details_redact_all_config_and_output_fields():
    marker = synthetic_value()
    config = f"password cipher {marker}"
    task = DeployTask(id=1, transaction_id="synthetic", device_id=1, batch_id=None,
                           operator_id=1, change_level=ChangeLevel.DAILY,
                           status=DeployStatus.SUCCESS, engine="sim", config_content=config,
                           result_output=config, rollback_output=config, error_message=config, backup_config=config,
                           verified=True, verify_diff=config, execution_mode="simulated", created_at=datetime(2026, 10, 11))
    result = await get_deploy_task(1, AsyncMock(get=AsyncMock(side_effect=[task, None])),
                                   {"role": "user", "user_id": 1})
    assert marker not in json.dumps(result)
    assert task.backup_config == config  # Response masking never edits stored snapshots.


@pytest.fixture
def terminal_log(tmp_path, monkeypatch):
    monkeypatch.setattr("modules.webssh.session_logger.get_settings",
                        lambda: SimpleNamespace(log_dir=str(tmp_path), webssh_log_retention_days=30))
    logger = TerminalSessionLogger(1, "192.0.2.1", "synthetic")
    yield logger
    logger.close()


def log_text(logger):
    from pathlib import Path
    return Path(logger._file_path).read_text(encoding="utf-8")


def test_password_prompt_and_input_may_arrive_character_by_character(terminal_log):
    marker = synthetic_value()
    for char in "Password:":
        terminal_log.log_output(char)
    for char in marker:
        terminal_log.log_input(char)
    terminal_log.log_input("\r")
    terminal_log.log_input("display version\r")
    terminal_log.close()
    entries = [json.loads(line) for line in log_text(terminal_log).splitlines()]
    inputs = "".join(entry.get("data", "") for entry in entries if entry["type"] == "input")
    assert marker not in inputs
    assert marker[1:] not in inputs
    assert "display version" in inputs


@pytest.mark.parametrize("direction", ["input", "output"])
def test_config_redaction_handles_fragments_and_flushes_partial_line(terminal_log, direction):
    marker = synthetic_value()
    data = f"local-user example password cipher {marker}"
    write = getattr(terminal_log, f"log_{direction}")
    for char in data:
        write(char)
    terminal_log.close()
    entries = [json.loads(line) for line in log_text(terminal_log).splitlines()]
    payload = "".join(entry.get("data", "") for entry in entries if entry["type"] == direction)
    assert marker not in payload
    assert "******" in payload


def test_password_echo_stays_masked_after_submit(terminal_log):
    marker = synthetic_value()
    terminal_log.log_output("Password:")
    terminal_log.log_input(marker + "\r")
    terminal_log.log_output(marker + "\r\n")
    terminal_log.close()
    assert marker not in log_text(terminal_log)


def test_terminal_log_close_is_idempotent(terminal_log):
    terminal_log.close()
    terminal_log.close()


@pytest.mark.parametrize("prefix", [
    "authentication-mode simple plain ",
    "authentication-mode hmac-sha256 1 cipher ",
    "area-authentication-mode md5 cipher ",
    "domain-authentication-mode md5 cipher ",
    "snmp-agent usm-user v3 audit authentication-mode sha cipher ",
    "snmp-agent usm-user v3 audit privacy-mode aes128 cipher ",
])
def test_authentication_config_secrets_keep_command_prefix_only(prefix):
    marker = synthetic_value()
    assert redact_sensitive(prefix + marker) == prefix + "******"


@pytest.mark.parametrize("command", ["authentication-mode aaa", "authentication-mode scheme",
                                    "authentication-mode password", "authentication-mode none"])
def test_authentication_method_selection_without_secret_is_preserved(command):
    assert redact_sensitive(command) == command


def test_quoted_and_structured_secret_fields_are_masked_but_business_keys_survive():
    marker = synthetic_value()
    original = {"password": marker, "api_key": marker, "nested": {"access_token": marker},
                "key": "business-field", "monkey": "visible", "max_tokens": 100}
    masked = redact_payload(original)
    assert marker not in json.dumps(masked)
    assert masked["key"] == "business-field"
    assert masked["monkey"] == "visible"
    assert masked["max_tokens"] == 100
    assert original["password"] == marker
    quoted = json.dumps({"password": marker + '\\"suffix', "api_key": marker, "key": "business-field"})
    result = redact_sensitive(quoted)
    assert marker not in result
    assert json.loads(result)["key"] == "business-field"


@pytest.mark.parametrize("blank_output", ["", "\r\n", "\x1b[0m\r\n"])
def test_password_echo_on_new_line_remains_masked(terminal_log, blank_output):
    marker = synthetic_value()
    terminal_log.log_output("Password:\r\n")
    terminal_log.log_input(marker + "\r")
    terminal_log.log_output(blank_output + marker + "\r\n")
    terminal_log.log_output("display version\r\n")
    terminal_log.close()
    payload = log_text(terminal_log)
    assert marker not in payload
    assert "display version" in payload


@pytest.mark.parametrize("direction", ["input", "output"])
def test_overlong_or_edited_lines_cannot_leak_a_tail(terminal_log, direction):
    marker = synthetic_value()
    write = getattr(terminal_log, f"log_{direction}")
    write("x" * 65540)
    write(marker + "\n")
    write("pass\x08word cipher " + marker + "\n")
    write("display version\n")
    terminal_log.close()
    payload = log_text(terminal_log)
    assert marker not in payload
    assert "display version" in payload
