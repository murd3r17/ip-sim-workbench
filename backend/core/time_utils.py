# -*- coding: utf-8 -*-
"""V7-A A-07：统一时间输出契约。

当前数据库中的 ``DateTime`` 列（MySQL DATETIME / SQLite TEXT）不保存时区，
而全部写入方都使用 ``datetime.now(timezone.utc)``。因此读回值的真实含义是
UTC，但 ``isoformat()`` 会丢掉偏移，前端 ``new Date("...")`` 会当成本地时间，
同一事件相差 8 小时（UX-09）。

本模块只改变“序列化时的解释”，不批量修改历史数据：
- ``as_utc(value)``：naive 值按 UTC 解释，aware 值原样返回；
- ``iso_utc(value)``：输出带 ``+00:00`` 的 ISO 8601 字符串。

已知例外：若某列历史上由 ``datetime.now()``（本地时间）写入，则不能直接套用。
逐步核实的来源表见 ``docs/ops/V7.0-A批执行报告.md`` 的“时间来源与迁移表”。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Annotated, Optional

from pydantic import PlainSerializer


def as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso_utc(value: datetime | None) -> str | None:
    normalized = as_utc(value)
    return normalized.isoformat() if normalized is not None else None


def pydantic_iso_utc(value: datetime | None) -> str | None:
    """pydantic 字段序列化：统一输出 ``...Z``（与 health/monitor 既有写法一致）。"""
    normalized = as_utc(value)
    if normalized is None:
        return None
    return normalized.isoformat().replace("+00:00", "Z")


# 给仍声明为 datetime 的响应模型使用：出参带 Z，不改数据库与查询逻辑。
UtcDatetime = Annotated[datetime, PlainSerializer(pydantic_iso_utc, return_type=Optional[str], when_used="json")]


def now_utc() -> datetime:
    return datetime.now(timezone.utc)
