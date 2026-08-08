from __future__ import annotations

import asyncio
import json
import math
import os
import random
import shutil
import signal
import socket
import statistics
import tempfile
from dataclasses import asdict, dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit

from .database import percentile
from .locations import resolve_exit_location
from .targets import TARGETS, normalize_target_keys

try:
    import resource
except ImportError:  # pragma: no cover - 仅用于本地 Windows 开发检查
    resource = None  # type: ignore[assignment]


REACHABLE_INTERSTITIAL_MARKERS = (
    "cf-chl-",
    "challenge-platform",
    "captcha",
    "recaptcha",
    "hcaptcha",
    "just a moment",
    "verify you are human",
    "verification required",
    "security check",
    "checking your browser",
    "performing security verification",
    "enable javascript and cookies to continue",
    "unusual traffic",
    "arkose",
    "turnstile",
    "人机验证",
    "安全验证",
    "验证您是真人",
)
REGION_MARKERS = (
    "unsupported_country",
    "not available in your country",
    "not available in your region",
    "country is not supported",
    "region is not supported",
    "service is not available in your location",
    "content is not available in your country",
    "legal reasons",
    "geo-blocked",
    "地区不可用",
    "所在地区",
    "区域限制",
)
LOGIN_MARKERS = (
    "sign in",
    "log in",
    "login",
    "accounts.google.com",
    "auth.openai.com",
    "继续登录",
    "登录",
    "continue with email",
    "continue with google",
)
BLOCK_MARKERS = (
    "access denied",
    "forbidden",
    "blocked",
    "request rejected",
    "temporarily blocked",
    "automated requests",
    "rate limit exceeded",
    "访问被拒绝",
)
STATUS_SCORES = {
    "available": 100.0,
    "login_required": 82.0,
    "uncertain": 45.0,
    "content_mismatch": 45.0,
    "response_error": 32.0,
    "service_error": 35.0,
    "region_blocked": 20.0,
    "service_blocked": 10.0,
    "timeout": 0.0,
    "dns_error": 0.0,
    "tcp_error": 0.0,
    "tls_error": 0.0,
    "proxy_error": 0.0,
    "proxy_configuration": 0.0,
}
NODE_PROBE_TARGETS: tuple[tuple[str, str], ...] = (
    ("Google 204", "https://www.gstatic.com/generate_204"),
    ("Cloudflare 204", "https://cp.cloudflare.com/generate_204"),
)
NODE_PROBE_SAMPLE_COUNT = 3
TCP_ENDPOINT_TYPES = frozenset(
    {"anytls", "http", "shadowsocks", "socks", "trojan", "vless", "vmess"}
)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _child_limits() -> None:
    try:
        os.nice(10)
    except OSError:
        pass
    if resource is not None:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (256, 256))
            resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
            resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        except (ValueError, OSError):
            pass


def _child_process_options(*, new_session: bool = False) -> dict[str, Any]:
    """Return POSIX-only hardening without breaking local Windows execution."""
    if os.name != "posix":
        return {}
    options: dict[str, Any] = {"preexec_fn": _child_limits}
    if new_session:
        options["start_new_session"] = True
    return options


def _free_local_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    return any(marker in text for marker in markers)


@dataclass
class ServiceResult:
    service: str
    status: str
    reachable: bool
    dns_ok: bool
    tcp_ok: bool
    tls_ok: bool
    http_code: int | None = None
    latency_ms: float | None = None
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    ttfb_ms: float | None = None
    redirect_count: int = 0
    final_host_class: str = "unknown"
    feature_ok: bool = False
    error_type: str | None = None


@dataclass
class NodeProbeSample:
    success: bool
    latency_ms: float | None
    http_code: int | None
    error_type: str | None


@dataclass
class NodeProbeResult:
    status: str
    reachable: bool
    latency_ms: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    jitter_ms: float | None
    successes: int
    samples: int
    http_code: int | None
    target: str
    error_type: str | None
    latency_method: str | None = None
    endpoint_status: str | None = None
    endpoint_successes: int | None = None
    endpoint_samples: int | None = None
    endpoint_latency_ms: float | None = None
    endpoint_latency_p50_ms: float | None = None
    endpoint_latency_p95_ms: float | None = None
    endpoint_jitter_ms: float | None = None


@dataclass
class EndpointProbeResult:
    status: str
    latency_ms: float | None
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    jitter_ms: float | None
    successes: int
    samples: int
    error_type: str | None


class NodeExecutor:
    def __init__(self, sing_box_path: Path, runtime_dir: Path):
        self.sing_box_path = sing_box_path
        self.runtime_dir = runtime_dir

    def _singbox_config(
        self, outbound: dict[str, Any], port: int
    ) -> dict[str, Any]:
        cleaned = json.loads(json.dumps(outbound))
        cleaned["tag"] = "proxy"
        return {
            "log": {"disabled": False, "level": "warn", "timestamp": False},
            "dns": {
                "servers": [
                    {
                        "type": "local",
                        "tag": "local",
                    }
                ]
            },
            "inbounds": [
                {
                    "type": "mixed",
                    "tag": "probe-in",
                    "listen": "127.0.0.1",
                    "listen_port": port,
                }
            ],
            "outbounds": [cleaned],
            "route": {
                "final": "proxy",
                "auto_detect_interface": True,
                "default_domain_resolver": {
                    "server": "local",
                    "strategy": "prefer_ipv4",
                },
            },
        }

    async def check_node(
        self,
        outbound: dict[str, Any],
        timeout_seconds: int,
        retry_count: int,
        target_keys: list[str] | tuple[str, ...] | None = None,
        resolve_location: bool = False,
        node_probe_enabled: bool = True,
    ) -> dict[str, Any]:
        selected_targets = normalize_target_keys(target_keys)
        started_at = _now()
        best: dict[str, Any] | None = None
        detected_location: dict[str, Any] | None = None
        attempts = 0
        for attempt in range(retry_count + 1):
            attempts = attempt + 1
            result = await self._single_attempt(
                outbound,
                timeout_seconds,
                selected_targets,
                resolve_location=resolve_location and detected_location is None,
                node_probe_enabled=node_probe_enabled,
            )
            if result.get("location"):
                detected_location = result["location"]
            if best is None or result["health_score"] > best["health_score"]:
                best = result
            if result["status"] == "online":
                break
            if attempt < retry_count:
                await asyncio.sleep((0.55 * (2**attempt)) + random.uniform(0.1, 0.65))
        if best is None:
            raise RuntimeError("节点检测没有产生结果")
        if attempts > 1 and best["status"] in {"online", "degraded"}:
            best["health_score"] = round(
                max(0.0, float(best["health_score"]) - 5.0 * (attempts - 1)),
                1,
            )
        best["started_at"] = started_at
        best["finished_at"] = _now()
        best["attempt_count"] = attempts
        best["location"] = detected_location
        best["location_attempted"] = resolve_location
        return best

    async def _single_attempt(
        self,
        outbound: dict[str, Any],
        timeout_seconds: int,
        target_keys: tuple[str, ...],
        *,
        resolve_location: bool = False,
        node_probe_enabled: bool = True,
    ) -> dict[str, Any]:
        port = _free_local_port()
        temp_root = Path(
            tempfile.mkdtemp(prefix="probe-", dir=self.runtime_dir)
        )
        os.chmod(temp_root, 0o700)
        config_path = temp_root / "config.json"
        config_path.write_text(
            json.dumps(
                self._singbox_config(outbound, port),
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            encoding="utf-8",
        )
        os.chmod(config_path, 0o600)
        proxy: asyncio.subprocess.Process | None = None
        stdout_task: asyncio.Task[bytes] | None = None
        stderr_task: asyncio.Task[bytes] | None = None
        location_task: asyncio.Task[dict[str, Any] | None] | None = None
        try:
            valid = await self._validate_config(config_path)
            if not valid:
                return self._failed_summary(
                    "proxy_configuration", target_keys, node_probe_enabled
                )
            proxy = await asyncio.create_subprocess_exec(
                str(self.sing_box_path),
                "run",
                "-c",
                str(config_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **_child_process_options(new_session=True),
            )
            if proxy.stdout is None or proxy.stderr is None:
                return self._failed_summary(
                    "proxy_error", target_keys, node_probe_enabled
                )
            stdout_task = asyncio.create_task(proxy.stdout.read(256 * 1024))
            stderr_task = asyncio.create_task(proxy.stderr.read(256 * 1024))
            ready = await self._wait_ready(proxy, port, min(5.0, timeout_seconds / 2))
            if not ready:
                return self._failed_summary(
                    "proxy_error", target_keys, node_probe_enabled
                )
            tunnel_probe = (
                await self._probe_node_latency(
                    port,
                    min(8, max(4, timeout_seconds - 2)),
                )
                if node_probe_enabled
                else None
            )
            node_probe = await self._with_endpoint_latency(
                outbound,
                tunnel_probe,
                min(5, max(2, timeout_seconds // 2)),
            )
            if resolve_location:
                location_task = asyncio.create_task(
                    self._detect_exit_location(
                        port,
                        min(8, max(4, timeout_seconds - 2)),
                    )
                )
            target_semaphore = asyncio.Semaphore(min(4, len(target_keys)))

            async def probe(service: str) -> ServiceResult:
                async with target_semaphore:
                    return await self._probe_service(
                        service,
                        TARGETS[service],
                        port,
                        timeout_seconds,
                        temp_root,
                    )

            service_results = await asyncio.gather(
                *(probe(service) for service in target_keys),
                return_exceptions=True,
            )
            normalized: list[ServiceResult] = []
            for service, item in zip(target_keys, service_results, strict=True):
                if isinstance(item, ServiceResult):
                    normalized.append(item)
                else:
                    normalized.append(
                        ServiceResult(
                            service=service,
                            status="proxy_error",
                            reachable=False,
                            dns_ok=False,
                            tcp_ok=False,
                            tls_ok=False,
                            error_type="probe_internal",
                        )
                    )
            summary = self._combine_summary(
                self._summarize(normalized),
                node_probe,
            )
            if location_task is not None:
                try:
                    summary["location"] = await location_task
                except (OSError, ValueError):
                    summary["location"] = None
            return summary
        except (asyncio.TimeoutError, OSError):
            return self._failed_summary(
                "proxy_error", target_keys, node_probe_enabled
            )
        finally:
            if proxy is not None:
                await self._terminate(proxy)
            for task in (stdout_task, stderr_task):
                if task is not None and not task.done():
                    task.cancel()
            if location_task is not None and not location_task.done():
                location_task.cancel()
            shutil.rmtree(temp_root, ignore_errors=True)

    async def _validate_config(self, config_path: Path) -> bool:
        try:
            process = await asyncio.create_subprocess_exec(
                str(self.sing_box_path),
                "check",
                "-c",
                str(config_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                **_child_process_options(),
            )
            await asyncio.wait_for(process.wait(), timeout=6)
            return process.returncode == 0
        except (asyncio.TimeoutError, OSError):
            return False

    async def _wait_ready(
        self, process: asyncio.subprocess.Process, port: int, timeout: float
    ) -> bool:
        deadline = asyncio.get_running_loop().time() + timeout
        while asyncio.get_running_loop().time() < deadline:
            if process.returncode is not None:
                return False
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection("127.0.0.1", port), timeout=0.25
                )
                writer.close()
                await writer.wait_closed()
                return True
            except (OSError, asyncio.TimeoutError):
                await asyncio.sleep(0.1)
        return False

    async def _terminate(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if os.name != "posix":
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=2)
            except asyncio.TimeoutError:
                process.kill()
                try:
                    await asyncio.wait_for(process.wait(), timeout=1)
                except asyncio.TimeoutError:
                    pass
            return
        try:
            os.killpg(process.pid, signal.SIGTERM)
            await asyncio.wait_for(process.wait(), timeout=2)
        except (ProcessLookupError, asyncio.TimeoutError):
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=1)
            except asyncio.TimeoutError:
                pass

    async def _fetch_location_text(
        self,
        url: str,
        port: int,
        timeout_seconds: int,
    ) -> str | None:
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--fail",
            "--connect-timeout",
            str(min(5, timeout_seconds)),
            "--max-time",
            str(timeout_seconds),
            "--max-filesize",
            "131072",
            "--compressed",
            "--socks5-hostname",
            f"127.0.0.1:{port}",
            "--user-agent",
            "AirportMonitor/2 exit-location-check",
            "--header",
            "Accept: application/json,text/plain;q=0.8",
            url,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                **_child_process_options(),
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds + 2
            )
        except asyncio.TimeoutError:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            return None
        except OSError:
            return None
        if process.returncode != 0 or not stdout or len(stdout) > 131072:
            return None
        return stdout.decode("utf-8", errors="replace")

    async def _detect_exit_location(
        self,
        port: int,
        timeout_seconds: int,
    ) -> dict[str, Any] | None:
        trace_text = await self._fetch_location_text(
            "https://www.cloudflare.com/cdn-cgi/trace",
            port,
            timeout_seconds,
        )
        if not trace_text:
            return None
        trace = {}
        for line in trace_text.splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                trace[key.strip()] = value.strip()
        exit_ip = trace.get("ip", "")
        country_code = trace.get("loc", "")
        if not exit_ip:
            return None
        encoded_ip = quote(exit_ip, safe=":")
        ipwho_url = (
            f"https://ipwho.is/{encoded_ip}"
            "?fields=success,ip,country,country_code,region,city"
        )
        ipapi_url = f"https://ipapi.co/{encoded_ip}/json/"
        ipwho_text, ipapi_text = await asyncio.gather(
            self._fetch_location_text(ipwho_url, port, timeout_seconds),
            self._fetch_location_text(ipapi_url, port, timeout_seconds),
        )
        observations: list[dict[str, Any]] = [
            {"country_code": country_code}
        ]
        for provider, text in (("ipwho", ipwho_text), ("ipapi", ipapi_text)):
            if not text:
                continue
            try:
                payload = json.loads(text)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            if provider == "ipwho":
                if payload.get("success") is False:
                    continue
                observations.append(
                    {
                        "country_code": payload.get("country_code"),
                        "country": payload.get("country"),
                        "region": payload.get("region"),
                        "city": payload.get("city"),
                    }
                )
            elif not payload.get("error"):
                observations.append(
                    {
                        "country_code": payload.get("country_code"),
                        "country": payload.get("country_name"),
                        "region": payload.get("region"),
                        "city": payload.get("city"),
                    }
                )
        return resolve_exit_location(exit_ip, observations)

    async def _with_endpoint_latency(
        self,
        outbound: dict[str, Any],
        tunnel_probe: NodeProbeResult | None,
        timeout_seconds: int,
    ) -> NodeProbeResult | None:
        if tunnel_probe is None:
            return None
        protocol = str(outbound.get("type") or "").lower()
        protocol_probe = replace(
            tunnel_probe,
            latency_method="protocol_urltest",
        )
        if protocol not in TCP_ENDPOINT_TYPES:
            return protocol_probe

        endpoint = await self._probe_tcp_endpoint(outbound, timeout_seconds)
        return replace(
            protocol_probe,
            endpoint_status=endpoint.status,
            endpoint_successes=endpoint.successes,
            endpoint_samples=endpoint.samples,
            endpoint_latency_ms=endpoint.latency_ms,
            endpoint_latency_p50_ms=endpoint.latency_p50_ms,
            endpoint_latency_p95_ms=endpoint.latency_p95_ms,
            endpoint_jitter_ms=endpoint.jitter_ms,
        )

    async def _probe_tcp_endpoint(
        self,
        outbound: dict[str, Any],
        timeout_seconds: int,
    ) -> EndpointProbeResult:
        server = str(outbound.get("server") or "").strip()
        try:
            server_port = int(outbound.get("server_port"))
        except (TypeError, ValueError):
            server_port = 0
        if not server or not 1 <= server_port <= 65535:
            return EndpointProbeResult(
                "unavailable", None, None, None, None, 0, 0, "proxy_configuration"
            )

        latencies: list[float] = []
        errors: list[str] = []
        for sample_index in range(NODE_PROBE_SAMPLE_COUNT):
            started = asyncio.get_running_loop().time()
            writer: asyncio.StreamWriter | None = None
            try:
                _reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(
                        server,
                        server_port,
                        happy_eyeballs_delay=0.25,
                        interleave=1,
                    ),
                    timeout=timeout_seconds,
                )
                latencies.append(
                    round(
                        (asyncio.get_running_loop().time() - started) * 1000,
                        2,
                    )
                )
            except socket.gaierror:
                errors.append("dns_error")
            except asyncio.TimeoutError:
                errors.append("timeout")
            except OSError:
                errors.append("tcp_error")
            finally:
                if writer is not None:
                    writer.close()
                    try:
                        await asyncio.wait_for(writer.wait_closed(), timeout=0.5)
                    except (asyncio.TimeoutError, OSError):
                        pass
            if sample_index < NODE_PROBE_SAMPLE_COUNT - 1:
                await asyncio.sleep(0.06 + random.uniform(0.0, 0.04))

        successes = len(latencies)
        status = (
            "available"
            if successes == NODE_PROBE_SAMPLE_COUNT
            else "unstable"
            if successes
            else "unavailable"
        )
        return EndpointProbeResult(
            status=status,
            latency_ms=round(statistics.median(latencies), 2) if latencies else None,
            latency_p50_ms=(
                round(statistics.median(latencies), 2) if latencies else None
            ),
            latency_p95_ms=percentile(latencies, 95),
            jitter_ms=(
                round(statistics.pstdev(latencies), 2)
                if len(latencies) > 1
                else 0.0
                if latencies
                else None
            ),
            successes=successes,
            samples=NODE_PROBE_SAMPLE_COUNT,
            error_type=errors[-1] if errors and status != "available" else None,
        )

    async def _probe_node_latency(
        self,
        port: int,
        timeout_seconds: int,
    ) -> NodeProbeResult:
        selected_target = NODE_PROBE_TARGETS[0]
        first = await self._probe_node_latency_once(
            selected_target[1], port, timeout_seconds
        )
        if not first.success:
            fallback = NODE_PROBE_TARGETS[1]
            fallback_first = await self._probe_node_latency_once(
                fallback[1], port, timeout_seconds
            )
            if not fallback_first.success:
                error_type = fallback_first.error_type or first.error_type or "timeout"
                return NodeProbeResult(
                    status=error_type,
                    reachable=False,
                    latency_ms=None,
                    latency_p50_ms=None,
                    latency_p95_ms=None,
                    jitter_ms=None,
                    successes=0,
                    samples=2,
                    http_code=fallback_first.http_code or first.http_code,
                    target="自动备用",
                    error_type=error_type,
                )
            selected_target = fallback
            samples = [fallback_first]
        else:
            samples = [first]

        for _ in range(NODE_PROBE_SAMPLE_COUNT - 1):
            await asyncio.sleep(0.06 + random.uniform(0.0, 0.04))
            samples.append(
                await self._probe_node_latency_once(
                    selected_target[1], port, timeout_seconds
                )
            )
        latencies = [
            float(sample.latency_ms)
            for sample in samples
            if sample.success and sample.latency_ms is not None
        ]
        successes = len(latencies)
        status = "available" if successes == len(samples) else "unstable"
        error_type = next(
            (
                sample.error_type
                for sample in reversed(samples)
                if not sample.success and sample.error_type
            ),
            None,
        )
        return NodeProbeResult(
            status=status,
            reachable=successes > 0,
            latency_ms=(
                round(statistics.median(latencies), 2) if latencies else None
            ),
            latency_p50_ms=(
                round(statistics.median(latencies), 2) if latencies else None
            ),
            latency_p95_ms=percentile(latencies, 95),
            jitter_ms=(
                round(statistics.pstdev(latencies), 2)
                if len(latencies) > 1
                else 0.0
                if latencies
                else None
            ),
            successes=successes,
            samples=len(samples),
            http_code=next(
                (
                    sample.http_code
                    for sample in reversed(samples)
                    if sample.success and sample.http_code
                ),
                None,
            ),
            target=selected_target[0],
            error_type=error_type if status != "available" else None,
        )

    async def _probe_node_latency_once(
        self,
        url: str,
        port: int,
        timeout_seconds: int,
    ) -> NodeProbeSample:
        marker = "__AIRPORT_NODE_PROBE__"
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-redirs",
            "2",
            "--connect-timeout",
            str(max(2, min(5, timeout_seconds - 1))),
            "--max-time",
            str(timeout_seconds),
            "--socks5-hostname",
            f"127.0.0.1:{port}",
            "--user-agent",
            "AirportMonitor/2 node-latency-probe",
            "--header",
            "Cache-Control: no-cache",
            "--output",
            os.devnull,
            "--write-out",
            marker + "%{http_code}|%{time_total}|%{ssl_verify_result}",
            url,
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                **_child_process_options(),
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds + 2
            )
        except asyncio.TimeoutError:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            return NodeProbeSample(False, None, None, "timeout")
        except OSError:
            return NodeProbeSample(False, None, None, "proxy_error")

        text = stdout.decode("utf-8", errors="replace")
        meta = text.rsplit(marker, 1)[-1] if marker in text else ""
        http_code: int | None = None
        total_seconds = 0.0
        ssl_verify = 0
        try:
            code_text, total_text, verify_text = meta.split("|", 2)
            http_code = int(code_text) or None
            total_seconds = float(total_text)
            ssl_verify = int(verify_text)
        except (TypeError, ValueError):
            pass
        latency_ms = round(total_seconds * 1000, 2) if total_seconds else None
        if process.returncode != 0:
            return NodeProbeSample(
                False,
                latency_ms,
                http_code,
                self._curl_error_type(process.returncode, ssl_verify),
            )
        if ssl_verify != 0:
            return NodeProbeSample(False, latency_ms, http_code, "tls_error")
        if http_code is None:
            return NodeProbeSample(False, latency_ms, None, "response_error")
        if 200 <= http_code < 500:
            return NodeProbeSample(True, latency_ms, http_code, None)
        return NodeProbeSample(False, latency_ms, http_code, "response_error")

    async def _probe_service(
        self,
        service: str,
        definition: dict[str, Any],
        port: int,
        timeout_seconds: int,
        temp_root: Path,
    ) -> ServiceResult:
        body_path = temp_root / f"{service}.body"
        header_path = temp_root / f"{service}.headers"
        marker = "__AIRPORT_PROBE_META__"
        write_out = (
            marker
            + "%{http_code}|%{time_namelookup}|%{time_connect}|"
            "%{time_appconnect}|%{time_starttransfer}|%{time_total}|"
            "%{num_redirects}|%{ssl_verify_result}|%{url_effective}"
        )
        command = [
            "curl",
            "--silent",
            "--show-error",
            "--location",
            "--max-redirs",
            "6",
            "--connect-timeout",
            str(max(3, min(10, timeout_seconds - 2))),
            "--max-time",
            str(timeout_seconds),
            "--max-filesize",
            "786432",
            "--compressed",
            "--socks5-hostname",
            f"127.0.0.1:{port}",
            "--user-agent",
            (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/126 Safari/537.36"
            ),
            "--header",
            "Accept-Language: zh-CN,zh;q=0.9,en;q=0.7",
            "--output",
            str(body_path),
            "--dump-header",
            str(header_path),
            "--write-out",
            write_out,
            definition["url"],
        ]
        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                **_child_process_options(),
            )
            stdout, _stderr = await asyncio.wait_for(
                process.communicate(), timeout=timeout_seconds + 3
            )
        except asyncio.TimeoutError:
            if "process" in locals() and process.returncode is None:
                process.kill()
                await process.wait()
            return self._error_result(service, "timeout", 28)
        except OSError:
            return self._error_result(service, "proxy_error", 97)

        meta_text = stdout.decode("utf-8", errors="replace")
        meta = meta_text.rsplit(marker, 1)[-1] if marker in meta_text else ""
        values = meta.split("|", 8)
        http_code: int | None = None
        metrics = [0.0] * 5
        redirects = 0
        ssl_verify = 1
        final_url = definition["url"]
        if len(values) == 9:
            try:
                http_code = int(values[0]) or None
                metrics = [float(item) for item in values[1:6]]
                redirects = int(values[6])
                ssl_verify = int(values[7])
                final_url = values[8]
            except (ValueError, TypeError):
                pass

        if process.returncode not in {0, 63}:
            return self._error_result(
                service,
                self._curl_error_type(process.returncode, ssl_verify),
                process.returncode,
                http_code=http_code,
                metrics=metrics,
                redirects=redirects,
            )
        if ssl_verify != 0:
            return self._error_result(
                service,
                "tls_error",
                process.returncode,
                http_code=http_code,
                metrics=metrics,
                redirects=redirects,
            )

        try:
            body = body_path.read_bytes()[:786432].decode("utf-8", errors="ignore").lower()
        except OSError:
            body = ""
        final_parts = urlsplit(final_url)
        final_host = (final_parts.hostname or "").lower()
        feature_ok = _contains_any(body, tuple(definition["features"]))
        final_class = (
            "login"
            if any(
                marker in final_parts.path.lower()
                for marker in ("/login", "/signin", "/sign-in", "/auth")
            )
            else self._classify_final_host(final_host, definition, body)
        )
        status = self._classify_page(
            http_code, body, feature_ok, final_class
        )
        reachable = status in {
            "available",
            "login_required",
            "content_mismatch",
            "uncertain",
            "response_error",
            "service_error",
            "region_blocked",
            "service_blocked",
        }
        dns_s, connect_s, appconnect_s, ttfb_s, total_s = metrics
        return ServiceResult(
            service=service,
            status=status,
            reachable=reachable,
            dns_ok=True,
            tcp_ok=connect_s > 0 or reachable,
            tls_ok=appconnect_s > 0 or reachable,
            http_code=http_code,
            latency_ms=round(total_s * 1000, 2) if total_s else None,
            dns_ms=round(dns_s * 1000, 2) if dns_s else 0.0,
            tcp_ms=(
                round(max(0.0, connect_s - dns_s) * 1000, 2)
                if connect_s
                else None
            ),
            tls_ms=(
                round(max(0.0, appconnect_s - connect_s) * 1000, 2)
                if appconnect_s
                else None
            ),
            ttfb_ms=round(ttfb_s * 1000, 2) if ttfb_s else None,
            redirect_count=redirects,
            final_host_class=final_class,
            feature_ok=feature_ok,
            error_type=None if status in {"available", "login_required"} else status,
        )

    @staticmethod
    def _curl_error_type(code: int | None, ssl_verify: int) -> str:
        if ssl_verify:
            return "tls_error"
        if code in {5, 97}:
            return "proxy_error"
        if code == 6:
            return "dns_error"
        if code in {7, 52, 55, 56}:
            return "tcp_error"
        if code == 28:
            return "timeout"
        if code in {35, 51, 58, 59, 60, 64, 77, 82, 83, 90, 91}:
            return "tls_error"
        return "proxy_error"

    @staticmethod
    def _classify_final_host(
        host: str, definition: dict[str, Any], body: str
    ) -> str:
        if host in definition["hosts"] or any(
            host.endswith(f".{target}") for target in definition["hosts"]
        ):
            return "target"
        if host in definition["login_hosts"] or _contains_any(body, LOGIN_MARKERS):
            return "login"
        if _contains_any(body, REACHABLE_INTERSTITIAL_MARKERS):
            return "target"
        return "other"

    @staticmethod
    def _classify_page(
        http_code: int | None,
        body: str,
        feature_ok: bool,
        final_class: str,
    ) -> str:
        # 安全挑战中间页已经证明代理完成了 DNS、TCP、TLS 和目标网站 HTTP
        # 往返。平台只评估节点能否真实出站，因此这类页面按成功到达处理，
        # 不再产生单独状态或降低节点健康度。
        if _contains_any(body, REACHABLE_INTERSTITIAL_MARKERS):
            return "available"
        if _contains_any(body, REGION_MARKERS) or http_code == 451:
            return "region_blocked"
        if final_class == "login":
            return "login_required"
        if http_code is not None and http_code >= 500:
            return "service_error"
        if _contains_any(body, BLOCK_MARKERS) or http_code in {401, 403, 429}:
            return "service_blocked"
        if feature_ok and http_code is not None and 200 <= http_code < 400:
            return "available"
        if http_code is not None and 200 <= http_code < 400:
            return "uncertain"
        if http_code is not None:
            return "response_error"
        return "uncertain"

    def _error_result(
        self,
        service: str,
        error_type: str,
        _code: int | None,
        *,
        http_code: int | None = None,
        metrics: list[float] | None = None,
        redirects: int = 0,
    ) -> ServiceResult:
        metrics = metrics or [0.0] * 5
        dns_s, connect_s, appconnect_s, ttfb_s, total_s = metrics
        return ServiceResult(
            service=service,
            status=error_type,
            reachable=False,
            dns_ok=error_type != "dns_error",
            tcp_ok=connect_s > 0
            and error_type not in {"tcp_error", "proxy_error", "timeout"},
            tls_ok=appconnect_s > 0 and error_type != "tls_error",
            http_code=http_code,
            latency_ms=round(total_s * 1000, 2) if total_s else None,
            dns_ms=round(dns_s * 1000, 2) if dns_s else None,
            tcp_ms=(
                round(max(0.0, connect_s - dns_s) * 1000, 2)
                if connect_s
                else None
            ),
            tls_ms=(
                round(max(0.0, appconnect_s - connect_s) * 1000, 2)
                if appconnect_s
                else None
            ),
            ttfb_ms=round(ttfb_s * 1000, 2) if ttfb_s else None,
            redirect_count=redirects,
            error_type=error_type,
        )

    @staticmethod
    def _failed_summary(
        error_type: str,
        target_keys: tuple[str, ...] | list[str] | None = None,
        node_probe_enabled: bool = True,
    ) -> dict[str, Any]:
        selected_targets = normalize_target_keys(target_keys)
        services = [
            asdict(
                ServiceResult(
                    service=service,
                    status=error_type,
                    reachable=False,
                    dns_ok=False,
                    tcp_ok=False,
                    tls_ok=False,
                    error_type=error_type,
                )
            )
            for service in selected_targets
        ]
        return {
            "status": "offline",
            "health_score": 0.0,
            "latency_avg_ms": None,
            "latency_p50_ms": None,
            "latency_p95_ms": None,
            "error_type": error_type,
            "website_status": "offline",
            "website_health_score": 0.0,
            "website_error_type": error_type,
            "node_probe_status": error_type if node_probe_enabled else None,
            "node_latency_ms": None,
            "node_latency_p50_ms": None,
            "node_latency_p95_ms": None,
            "node_jitter_ms": None,
            "node_probe_successes": 0 if node_probe_enabled else None,
            "node_probe_samples": 0 if node_probe_enabled else None,
            "node_probe_http_code": None,
            "node_probe_target": None,
            "node_probe_error_type": error_type if node_probe_enabled else None,
            "node_latency_method": None,
            "node_endpoint_status": None,
            "node_endpoint_successes": None,
            "node_endpoint_samples": None,
            "node_endpoint_latency_ms": None,
            "node_endpoint_latency_p50_ms": None,
            "node_endpoint_latency_p95_ms": None,
            "node_endpoint_jitter_ms": None,
            "services": services,
        }

    @staticmethod
    def _combine_summary(
        website: dict[str, Any],
        node_probe: NodeProbeResult | None,
    ) -> dict[str, Any]:
        result = dict(website)
        result["website_status"] = website["status"]
        result["website_health_score"] = website["health_score"]
        result["website_error_type"] = website.get("error_type")
        if node_probe is None:
            result.update(
                {
                    "node_probe_status": None,
                    "node_latency_ms": None,
                    "node_latency_p50_ms": None,
                    "node_latency_p95_ms": None,
                    "node_jitter_ms": None,
                    "node_probe_successes": None,
                    "node_probe_samples": None,
                    "node_probe_http_code": None,
                    "node_probe_target": None,
                    "node_probe_error_type": None,
                    "node_latency_method": None,
                    "node_endpoint_status": None,
                    "node_endpoint_successes": None,
                    "node_endpoint_samples": None,
                    "node_endpoint_latency_ms": None,
                    "node_endpoint_latency_p50_ms": None,
                    "node_endpoint_latency_p95_ms": None,
                    "node_endpoint_jitter_ms": None,
                }
            )
            return result

        sample_count = max(1, node_probe.samples)
        success_ratio = node_probe.successes / sample_count
        latency = node_probe.latency_ms
        if latency is None:
            latency_score = 0.0
        elif latency <= 350:
            latency_score = 100.0
        elif latency <= 1000:
            latency_score = 100.0 - (latency - 350.0) * 25.0 / 650.0
        elif latency <= 3000:
            latency_score = 75.0 - (latency - 1000.0) * 30.0 / 2000.0
        else:
            latency_score = 35.0
        jitter = node_probe.jitter_ms
        jitter_score = (
            0.0
            if node_probe.successes == 0
            else 100.0
            if jitter is None or jitter <= 40
            else max(20.0, 100.0 - (jitter - 40.0) * 0.45)
        )
        if node_probe.successes == 0:
            link_health = 0.0
            health = 0.0
        else:
            link_health = (
                success_ratio * 75.0
                + latency_score * 0.15
                + jitter_score * 0.10
            )
            website_health = max(
                0.0,
                min(100.0, float(website.get("health_score") or 0.0)),
            )
            health = round(link_health * 0.8 + website_health * 0.2, 1)
        website_status = str(website.get("status") or "unknown")
        if (
            node_probe.successes == sample_count
            and website_status == "online"
        ):
            status = "online"
            error_type = None
        elif node_probe.successes > 0:
            status = "degraded"
            error_type = (
                website.get("error_type")
                if node_probe.successes == sample_count
                else "node_probe_unstable"
            ) or "website_degraded"
        else:
            status = "offline"
            error_type = node_probe.error_type or "proxy_error"
        result.update(
            {
                "status": status,
                "health_score": health,
                "error_type": error_type,
                "node_probe_status": node_probe.status,
                "node_latency_ms": node_probe.latency_ms,
                "node_latency_p50_ms": node_probe.latency_p50_ms,
                "node_latency_p95_ms": node_probe.latency_p95_ms,
                "node_jitter_ms": node_probe.jitter_ms,
                "node_probe_successes": node_probe.successes,
                "node_probe_samples": node_probe.samples,
                "node_probe_http_code": node_probe.http_code,
                "node_probe_target": node_probe.target,
                "node_probe_error_type": node_probe.error_type,
                "node_latency_method": node_probe.latency_method,
                "node_endpoint_status": node_probe.endpoint_status,
                "node_endpoint_successes": node_probe.endpoint_successes,
                "node_endpoint_samples": node_probe.endpoint_samples,
                "node_endpoint_latency_ms": node_probe.endpoint_latency_ms,
                "node_endpoint_latency_p50_ms": node_probe.endpoint_latency_p50_ms,
                "node_endpoint_latency_p95_ms": node_probe.endpoint_latency_p95_ms,
                "node_endpoint_jitter_ms": node_probe.endpoint_jitter_ms,
            }
        )
        return result

    @staticmethod
    def _summarize(results: list[ServiceResult]) -> dict[str, Any]:
        if not results:
            return {
                "status": "unknown",
                "health_score": 0.0,
                "latency_avg_ms": None,
                "latency_p50_ms": None,
                "latency_p95_ms": None,
                "error_type": "no_targets",
                "services": [],
            }
        # 兼容升级前留下的旧记录：旧版的 captcha 结论只表示目标网站已经返回
        # 中间页，在新的“外网能否打开”口径下等同于 available。
        effective_statuses = [
            "available" if result.status == "captcha" else result.status
            for result in results
        ]
        content_scores = [
            STATUS_SCORES.get(status, 0.0) for status in effective_statuses
        ]
        transport_scores = []
        for result in results:
            if result.reachable:
                transport_scores.append(100.0)
            elif result.tls_ok:
                transport_scores.append(65.0)
            elif result.tcp_ok:
                transport_scores.append(35.0)
            elif result.dns_ok:
                transport_scores.append(15.0)
            else:
                transport_scores.append(0.0)
        transport_health = sum(transport_scores) / len(transport_scores)
        content_health = sum(content_scores) / len(content_scores)
        # 节点健康首先回答“代理链路能否真实出站”。登录页、地区限制等仍保留
        # 为服务级状态，但不能把已经完成 DNS/TCP/TLS/HTTP 往返的节点误判为
        # 代理故障。
        health = round(transport_health * 0.8 + content_health * 0.2, 1)
        reachable = sum(result.reachable for result in results)
        uncertain = sum(
            status in {"uncertain", "content_mismatch"}
            for status in effective_statuses
        )
        degraded_statuses = {
            "login_required",
            "region_blocked",
            "service_blocked",
            "service_error",
            "response_error",
        }
        if uncertain == len(results):
            status = "unknown"
        elif reachable == len(results) and not any(
            status in degraded_statuses for status in effective_statuses
        ):
            status = "online"
        elif reachable > 0 or transport_health >= 25:
            status = "degraded"
        else:
            status = "offline"
        latencies = [
            result.latency_ms
            for result in results
            if result.latency_ms is not None and result.reachable
        ]
        error_counts: dict[str, int] = {}
        for result in results:
            if result.error_type and result.error_type != "captcha":
                error_counts[result.error_type] = error_counts.get(result.error_type, 0) + 1
        error_type = (
            max(error_counts, key=error_counts.get)
            if error_counts and status != "online"
            else None
        )
        return {
            "status": status,
            "health_score": health,
            "latency_avg_ms": (
                round(statistics.fmean(latencies), 2) if latencies else None
            ),
            "latency_p50_ms": (
                round(statistics.median(latencies), 2) if latencies else None
            ),
            "latency_p95_ms": (
                round(percentile(latencies, 95) or 0.0, 2) if latencies else None
            ),
            "error_type": error_type,
            "services": [asdict(result) for result in results],
        }
