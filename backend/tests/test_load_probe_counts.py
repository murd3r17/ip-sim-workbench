from scripts.load_probe import ENDPOINTS, report
import asyncio

import httpx
import pytest


def test_empty_load_run_cannot_pass():
    result = {"samples": {n: [] for n, *_ in ENDPOINTS},
              "errors": {n: {} for n, *_ in ENDPOINTS},
              "attempts": {n: 0 for n, *_ in ENDPOINTS}, "request_count": 0}
    output, passed = report(result, 30, 0, "http://127.0.0.1")
    assert not passed
    assert all(row["violations"] for row in output["endpoints"])


def test_http_failure_is_not_double_counted_in_denominator():
    result = {"samples": {n: [10] * 100 for n, *_ in ENDPOINTS},
              "errors": {n: {"HTTP 500": 3} for n, *_ in ENDPOINTS},
              "attempts": {n: 100 for n, *_ in ENDPOINTS}, "request_count": 700}
    output, passed = report(result, 30, 10, "http://127.0.0.1")
    assert not passed
    assert all(row["requests"] == 100 and row["error_rate"] == .03 for row in output["endpoints"])


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [httpx.Response(302, headers={"Location": "/login"}),
                                      httpx.Response(200, text="<html>login</html>"),
                                      httpx.Response(200, json={"detail": "failed"})])
async def test_redirects_and_success_status_error_bodies_are_not_valid_samples(monkeypatch, response):
    import scripts.load_probe as probe
    real_client = httpx.AsyncClient
    requests = []
    async def handle(request):
        requests.append(request)
        await asyncio.sleep(.001)
        return response
    def client(**kwargs):
        return real_client(**kwargs, transport=httpx.MockTransport(handle))
    monkeypatch.setattr(httpx, "AsyncClient", client)
    result = await probe.run("http://isolated.invalid", 16, .03, "fixture-token")
    summary, passed = probe.report(result, 16, .03, "http://isolated.invalid")
    assert not passed
    assert all(row["errors"] == row["requests"] and row["requests"] > 0 for row in summary["endpoints"])
    assert all(request.method == "GET" for request in requests)


def test_error_rate_threshold_uses_unrounded_fraction():
    result = {"samples": {n: [10] * 4990 for n, *_ in ENDPOINTS},
              "errors": {n: {"HTTP 500": 100} for n, *_ in ENDPOINTS},
              "attempts": {n: 4990 for n, *_ in ENDPOINTS}, "request_count": 34930}
    _, passed = report(result, 30, 10, "http://isolated.invalid")
    assert not passed  # 100/4990 > 2%, although a four-decimal display rounds to .0200.


@pytest.mark.parametrize("name,body", [
    ("devices", [{"id": 1}]), ("deploy/tasks", []), ("training/labs", [{"id": 1}]), ("alarms", []),
    ("dashboard/summary", {"generated_at": "fixture", "devices": {}, "tasks": {}, "alarms": {}, "services": {}}),
    ("system/info", {"app_name": "fixture", "database_status": "healthy", "llm_status": "healthy", "device_count": 3}),
    ("monitor/stats", {"totalDevices": 3, "onlineDevices": 3, "activeAlarms": 0, "warningAlarms": 0}),
])
def test_expected_api_shapes_remain_valid(name, body):
    from scripts.load_probe import response_error
    assert response_error(name, httpx.Response(200, json=body)) is None
