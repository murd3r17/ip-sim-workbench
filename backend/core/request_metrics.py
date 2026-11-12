"""Bounded, request-local timings without prompts, tool arguments or secrets.

Bind only around awaited producer work, never across a consumer yield. These
are server observations, not browser paint/TTFT or per-HTTP network timings.
"""
from contextlib import contextmanager, nullcontext
from contextvars import ContextVar
from functools import wraps
import time

_active = ContextVar("copilot_request_metrics", default=None)
_STAGES = ("retrieval", "tool")


class RequestMetrics:
    def __init__(self):
        self.started = time.perf_counter()
        self.finished = None
        self.first_content = None
        self.first_progress = None
        self.first_evidence = None
        self.records = []
        self.cache = None

    @contextmanager
    def bind(self):
        token = _active.set(self)
        try:
            yield
        finally:
            _active.reset(token)

    @contextmanager
    def measure(self, stage):
        if stage not in _STAGES or len(self.records) >= 128:
            yield
            return
        record = {"stage": stage, "status": "running", "started": time.perf_counter(),
                  "finished": None}
        self.records.append(record)
        try:
            yield
            record["status"] = "completed"
        except BaseException as exc:
            record["status"] = "cancelled" if type(exc).__name__ in {
                "CancelledError", "RequestCancelled"} else "failed"
            record["error_type"] = type(exc).__name__
            raise
        finally:
            record["finished"] = time.perf_counter()

    def note_content(self):
        if self.first_content is None:
            self.first_content = time.perf_counter()

    def note_event(self, event):
        kind = event.get("type")
        if kind == "progress" and event.get("message") and self.first_progress is None:
            self.first_progress = time.perf_counter()
        if (kind == "tool" and event.get("evidence_id")
                and event.get("source") == "server_observed"
                and event.get("status") in {"ok", "empty", "partial"}
                and self.first_evidence is None):
            self.first_evidence = time.perf_counter()
        if kind == "token" and event.get("text"):
            self.note_content()

    def finish(self):
        if self.finished is None:
            self.finished = time.perf_counter()

    def snapshot(self):
        now = self.finished if self.finished is not None else time.perf_counter()
        records = [{"stage": r["stage"], "status": r["status"],
                    "elapsed_ms": round(1000 * ((r["finished"] or now) - r["started"]), 3),
                    **({"error_type": r["error_type"]} if "error_type" in r else {})}
                   for r in self.records]
        stages = {}
        for stage in _STAGES:
            observed = [r for r in records if r["stage"] == stage]
            stages[stage] = {"count": len(observed),
                "elapsed_ms": round(sum(r["elapsed_ms"] for r in observed), 3) if observed else None,
                "status": "observed" if observed else "not_observed"}
        return {"schema_version": 1,
            "scope": "server_request_before_durable_finish_excludes_network_and_paint",
            "request_elapsed_ms": round((now - self.started) * 1000, 3),
            "first_safe_content_ms": (round((self.first_content - self.started) * 1000, 3)
                                      if self.first_content is not None else None),
            "first_progress_ms": (round((self.first_progress - self.started) * 1000, 3)
                                  if self.first_progress is not None else None),
            "first_evidence_event_ms": (round((self.first_evidence - self.started) * 1000, 3)
                                        if self.first_evidence is not None else None),
            "stages": stages, "observations": records,
            "knowledge_cache": dict(self.cache) if self.cache is not None else None}


def measure_stage(stage):
    metrics = _active.get()
    return metrics.measure(stage) if metrics is not None else nullcontext()


def timed_stage(stage):
    def decorate(fn):
        @wraps(fn)
        async def measured(*args, **kwargs):
            with measure_stage(stage):
                return await fn(*args, **kwargs)
        return measured
    return decorate


def note_cache(outcome):
    metrics = _active.get()
    if metrics is not None and outcome in {"hit", "miss"}:
        if metrics.cache is None:
            metrics.cache = {"hits": 0, "misses": 0}
        metrics.cache[{"hit": "hits", "miss": "misses"}[outcome]] += 1
