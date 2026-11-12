# -*- coding: utf-8 -*-
"""CA-07：知识检索的有界缓存（不缓存最终答案）。

- 键包含规范查询、top_k、知识 provider/workspace 指纹；
- TTL 默认 300s，LRU 上限 128；
- 只缓存检索片段，不缓存模型回答、授权决定或危险命令判断；
- 语料更新后必须显式 invalidate（或等 TTL），不得把旧片段说成新语料。
"""
from __future__ import annotations

import hashlib
import json
from copy import deepcopy
import time
from collections import OrderedDict
from typing import Any, Awaitable, Callable

from core.config import get_settings
from core.request_metrics import note_cache

_TTL = 300.0
_MAX = 128
_CACHE: "OrderedDict[str, tuple[float, Any]]" = OrderedDict()
_STATS = {"hit": 0, "miss": 0, "evict": 0}


def _fingerprint(service) -> str:
    s = get_settings()
    provider = getattr(service, "provider", service)
    # Bind the actual service, including credential scope, rather than a global
    # default that may point to a different endpoint/workspace. Secrets are hashed
    # here and never kept in the cache key or emitted as metadata.
    fields = {key: str(getattr(provider, key, "")) for key in
              ("base_url", "workspace_slug", "workspace_id", "dataset_id", "dataset_name",
               "api_key", "username", "password", "corpus_dir", "storage_dir")}
    fields["type"] = type(provider).__module__ + "." + type(provider).__qualname__
    fields["index_config"] = str(getattr(s, "knowledge_index_config", ""))
    if hasattr(service, "resolve_workspace_id"):
        fields["resolved_workspace"] = service.resolve_workspace_id(None)
    if hasattr(provider, "_scan_files") and hasattr(provider, "_compute_signature"):
        fields["files"] = provider._compute_signature(provider._scan_files())
    if not any(fields[key] for key in ("base_url", "workspace_slug", "corpus_dir")):
        fields["instance"] = id(provider)
    return hashlib.sha256(json.dumps(fields, sort_keys=True, default=str).encode()).hexdigest()


def _key(service, query: str, top_k: int) -> str:
    raw = f"{_fingerprint(service)}|{top_k}|{query.strip().lower()}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def invalidate() -> None:
    _CACHE.clear()


def stats() -> dict:
    return {**_STATS, "size": len(_CACHE)}


async def cached_search(
    service: Any,
    query: str,
    top_k: int,
    loader: Callable[[], Awaitable[Any]] | None = None,
) -> Any:
    now = time.monotonic()
    key = _key(service, query, top_k)
    hit = _CACHE.get(key)
    if hit and hit[0] > now:
        _CACHE.move_to_end(key)
        _STATS["hit"] += 1
        note_cache("hit")
        return deepcopy(hit[1])
    _STATS["miss"] += 1
    note_cache("miss")
    value = await (loader() if loader is not None else service.search(query, None, top_k))
    if not isinstance(value, list) or not all(isinstance(hit, dict) for hit in value):
        raise ValueError("知识检索返回格式不正确")
    _CACHE[key] = (time.monotonic() + _TTL, deepcopy(value))
    _CACHE.move_to_end(key)
    while len(_CACHE) > _MAX:
        _CACHE.popitem(last=False)
        _STATS["evict"] += 1
    return value
