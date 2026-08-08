import asyncio

import app.executor as executor_module

from app.executor import (
    TARGETS,
    EndpointProbeResult,
    NodeExecutor,
    NodeProbeResult,
    NodeProbeSample,
    ServiceResult,
)
from app.targets import DEFAULT_TARGET_KEYS, normalize_target_keys


def test_child_process_options_are_portable(monkeypatch):
    monkeypatch.setattr(executor_module.os, "name", "nt")
    assert executor_module._child_process_options(new_session=True) == {}
    monkeypatch.setattr(executor_module.os, "name", "posix")
    options = executor_module._child_process_options(new_session=True)
    assert options["preexec_fn"] is executor_module._child_limits
    assert options["start_new_session"] is True


def _result(service: str, status: str, reachable: bool) -> ServiceResult:
    return ServiceResult(
        service=service,
        status=status,
        reachable=reachable,
        dns_ok=reachable,
        tcp_ok=reachable,
        tls_ok=reachable,
        http_code=200 if reachable else None,
        latency_ms=180.0 if reachable else None,
        error_type=None if status == "available" else status,
    )


def test_legacy_challenge_results_count_as_fully_available():
    result = NodeExecutor._summarize(
        [
            _result("google", "available", True),
            _result("chatgpt", "captcha", True),
            _result("grok", "captcha", True),
        ]
    )
    assert result["status"] == "online"
    assert result["health_score"] == 100.0
    assert result["error_type"] is None


def test_partial_transport_success_is_degraded_not_offline():
    result = NodeExecutor._summarize(
        [
            _result("google", "available", True),
            _result("chatgpt", "captcha", True),
            _result("grok", "proxy_error", False),
        ]
    )
    assert result["status"] == "degraded"
    assert result["health_score"] == 66.7


def test_login_page_is_reachable_but_not_fully_healthy():
    results = [
        _result("google", "available", True),
        _result("chatgpt", "login_required", True),
        _result("grok", "available", True),
    ]
    result = NodeExecutor._summarize(results)
    assert result["status"] == "degraded"
    assert result["health_score"] > 80


def test_complete_proxy_failure_remains_offline():
    result = NodeExecutor._summarize(
        [
            _result(service, "proxy_error", False)
            for service in ("google", "chatgpt", "grok")
        ]
    )
    assert result["status"] == "offline"
    assert result["health_score"] == 0.0


def test_added_services_do_not_change_default_selection():
    assert DEFAULT_TARGET_KEYS == ("google", "chatgpt", "grok")
    assert normalize_target_keys(None) == DEFAULT_TARGET_KEYS
    assert len(TARGETS) == 15
    assert {
        "x",
        "claude",
        "wikipedia",
        "github",
        "nodejs",
        "python",
        "perplexity",
        "youtube",
        "nexusmods",
        "huggingface",
        "cloudflare",
        "linuxdo",
    }.issubset(TARGETS)


def test_all_uncertain_results_are_not_reported_as_offline():
    result = NodeExecutor._summarize(
        [
            _result(service, "uncertain", True)
            for service in DEFAULT_TARGET_KEYS
        ]
    )
    assert result["status"] == "unknown"
    assert result["health_score"] > 0


def test_working_node_probe_with_failed_websites_is_degraded():
    website = NodeExecutor._summarize(
        [
            _result(service, "proxy_error", False)
            for service in DEFAULT_TARGET_KEYS
        ]
    )
    combined = NodeExecutor._combine_summary(
        website,
        NodeProbeResult(
            status="available",
            reachable=True,
            latency_ms=226.0,
            latency_p50_ms=226.0,
            latency_p95_ms=241.0,
            jitter_ms=7.0,
            successes=3,
            samples=3,
            http_code=204,
            target="Google 204",
            error_type=None,
        ),
    )
    assert combined["status"] == "degraded"
    assert combined["error_type"] == "proxy_error"
    assert combined["health_score"] == 80.0
    assert combined["node_latency_ms"] == 226.0
    assert combined["website_status"] == "offline"
    assert combined["latency_avg_ms"] is None


def test_zero_success_node_probe_has_zero_health_not_free_jitter_points():
    website = NodeExecutor._summarize(
        [
            _result(service, "proxy_error", False)
            for service in DEFAULT_TARGET_KEYS
        ]
    )
    combined = NodeExecutor._combine_summary(
        website,
        NodeProbeResult(
            status="proxy_error",
            reachable=False,
            latency_ms=None,
            latency_p50_ms=None,
            latency_p95_ms=None,
            jitter_ms=None,
            successes=0,
            samples=2,
            http_code=None,
            target="自动备用",
            error_type="proxy_error",
        ),
    )
    assert combined["status"] == "offline"
    assert combined["health_score"] == 0.0


def test_partial_node_probe_has_explicit_unstable_result():
    website = NodeExecutor._summarize(
        [_result(service, "available", True) for service in DEFAULT_TARGET_KEYS]
    )
    combined = NodeExecutor._combine_summary(
        website,
        NodeProbeResult(
            status="unstable",
            reachable=True,
            latency_ms=310.0,
            latency_p50_ms=310.0,
            latency_p95_ms=310.0,
            jitter_ms=0.0,
            successes=1,
            samples=3,
            http_code=204,
            target="Google 204",
            error_type="timeout",
        ),
    )
    assert combined["status"] == "degraded"
    assert combined["error_type"] == "node_probe_unstable"
    assert combined["website_status"] == "online"
    assert combined["node_probe_successes"] == 1


def test_node_probe_uses_fallback_then_collects_three_samples(monkeypatch):
    executor = NodeExecutor(None, None)  # type: ignore[arg-type]
    samples = iter(
        (
            NodeProbeSample(False, None, None, "timeout"),
            NodeProbeSample(True, 240.0, 204, None),
            NodeProbeSample(True, 220.0, 204, None),
            NodeProbeSample(True, 230.0, 204, None),
        )
    )

    async def fake_once(_url, _port, _timeout):
        return next(samples)

    monkeypatch.setattr(executor, "_probe_node_latency_once", fake_once)
    result = asyncio.run(executor._probe_node_latency(1080, 5))
    assert result.status == "available"
    assert result.target == "Cloudflare 204"
    assert result.successes == 3
    assert result.samples == 3
    assert result.latency_ms == 230.0


def test_tcp_endpoint_handshake_never_replaces_protocol_path_latency(monkeypatch):
    executor = NodeExecutor(None, None)  # type: ignore[arg-type]
    tunnel = NodeProbeResult(
        status="available",
        reachable=True,
        latency_ms=920.0,
        latency_p50_ms=920.0,
        latency_p95_ms=980.0,
        jitter_ms=32.0,
        successes=3,
        samples=3,
        http_code=204,
        target="Google 204",
        error_type=None,
    )

    async def fake_endpoint(_outbound, _timeout):
        return EndpointProbeResult(
            status="available",
            latency_ms=2.35,
            latency_p50_ms=2.35,
            latency_p95_ms=2.84,
            jitter_ms=0.28,
            successes=3,
            samples=3,
            error_type=None,
        )

    monkeypatch.setattr(executor, "_probe_tcp_endpoint", fake_endpoint)
    result = asyncio.run(
        executor._with_endpoint_latency(
            {"type": "anytls", "server": "example.com", "server_port": 443},
            tunnel,
            3,
        )
    )
    assert result is not None
    assert result.latency_ms == 920.0
    assert result.latency_p95_ms == 980.0
    assert result.jitter_ms == 32.0
    assert result.latency_method == "protocol_urltest"
    assert result.endpoint_latency_ms == 2.35
    assert result.endpoint_latency_p95_ms == 2.84
    assert result.endpoint_jitter_ms == 0.28
    assert result.endpoint_successes == 3
    assert result.successes == 3
    assert result.target == "Google 204"


def test_tcp_endpoint_probe_performs_three_real_local_handshakes():
    executor = NodeExecutor(None, None)  # type: ignore[arg-type]

    async def scenario():
        server = await asyncio.start_server(
            lambda _reader, writer: writer.close(),
            "127.0.0.1",
            0,
        )
        port = int(server.sockets[0].getsockname()[1])
        try:
            return await executor._probe_tcp_endpoint(
                {
                    "type": "anytls",
                    "server": "127.0.0.1",
                    "server_port": port,
                },
                1,
            )
        finally:
            server.close()
            await server.wait_closed()

    result = asyncio.run(scenario())
    assert result.status == "available"
    assert result.successes == 3
    assert result.samples == 3
    assert result.latency_ms is not None


def test_udp_node_keeps_protocol_aware_urltest_and_labels_method():
    executor = NodeExecutor(None, None)  # type: ignore[arg-type]
    tunnel = NodeProbeResult(
        status="available",
        reachable=True,
        latency_ms=430.0,
        latency_p50_ms=430.0,
        latency_p95_ms=460.0,
        jitter_ms=15.0,
        successes=3,
        samples=3,
        http_code=204,
        target="Google 204",
        error_type=None,
    )
    result = asyncio.run(
        executor._with_endpoint_latency(
            {"type": "tuic", "server": "example.com", "server_port": 443},
            tunnel,
            3,
        )
    )
    assert result is not None
    assert result.latency_ms == 430.0
    assert result.latency_method == "protocol_urltest"
    assert result.endpoint_status is None
    assert result.endpoint_latency_ms is None


def test_unstable_direct_endpoint_does_not_downgrade_working_proxy_path():
    website = NodeExecutor._summarize(
        [_result(service, "available", True) for service in DEFAULT_TARGET_KEYS]
    )
    combined = NodeExecutor._combine_summary(
        website,
        NodeProbeResult(
            status="available",
            reachable=True,
            latency_ms=226.0,
            latency_p50_ms=226.0,
            latency_p95_ms=241.0,
            jitter_ms=7.0,
            successes=3,
            samples=3,
            http_code=204,
            target="Google 204",
            error_type=None,
            latency_method="protocol_urltest",
            endpoint_status="unstable",
            endpoint_successes=2,
            endpoint_samples=3,
            endpoint_latency_ms=2.35,
        ),
    )
    assert combined["status"] == "online"
    assert combined["error_type"] is None
    assert combined["node_latency_ms"] == 226.0
    assert combined["node_endpoint_latency_ms"] == 2.35
    assert combined["node_probe_successes"] == 3
    assert combined["node_endpoint_successes"] == 2
