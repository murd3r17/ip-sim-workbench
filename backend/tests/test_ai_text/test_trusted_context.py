# -*- coding: utf-8 -*-
"""C-R2：page_data 默认不可信；仅后端回读的正向证据可信。"""
import json
from datetime import datetime, timedelta, timezone

from modules.ai_text.trusted_context import sanitize

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)


def _data(**kw):
    return json.dumps(kw, ensure_ascii=False)


def test_client_payload_without_source_is_untrusted():
    out = sanitize(_data(device="R1", status="up"), selection="R1", now=NOW)
    assert out.trusted is False
    assert "client_supplied_unverified" in out.meta["reasons"]


def test_client_sim_label_is_not_server_evidence():
    out = sanitize(_data(source="sim", device="R1", status="up"), selection="R1", now=NOW)
    assert out.trusted is False


def test_selection_is_exact_not_substring():
    out = sanitize(_data(source="sim", device="R2"), selection="R20", now=NOW)
    assert out.trusted is False


def test_client_claimed_real_is_downgraded():
    out = sanitize(_data(source="real", device="R1"), selection="R1", now=NOW)
    assert out.trusted is False
    assert "client_supplied_unverified" in out.meta["reasons"]


def test_production_default_checks_old_timestamp_without_now():
    # 不传 now：生产默认用服务器当前时间；2020 年快照必须过期。
    out = sanitize(_data(source="snapshot", device="R1", collected_at="2020-01-01T00:00:00+00:00"), selection="R1")
    assert out.trusted is False


def test_server_verified_fresh_evidence_is_trusted():
    out = sanitize(
        _data(source="sim", device="R1", collected_at=NOW.isoformat(), evidence_id=7),
        selection="R1", now=NOW, server_verified=True,
    )
    assert out.trusted is True
    assert out.meta["evidence_id"] == 7


def test_server_verified_stale_is_untrusted():
    old = (NOW - timedelta(minutes=130)).isoformat()
    out = sanitize(
        _data(source="snapshot", device="R1", collected_at=old),
        selection="R1", now=NOW, server_verified=True,
    )
    assert out.trusted is False
    assert "stale" in out.meta["reasons"]


def test_unparsed_payload_is_untrusted_but_kept():
    out = sanitize("R1 的接口都 up", selection="R1", now=NOW)
    assert out.trusted is False
    assert out.text == "R1 的接口都 up"
