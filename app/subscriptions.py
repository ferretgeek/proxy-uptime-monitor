from __future__ import annotations

import base64
import binascii
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import httpx
import yaml
from yaml.events import AliasEvent, CollectionEndEvent, CollectionStartEvent

from .security import (
    mask_endpoint,
    normalize_display_name,
    sanitize_exception,
    stable_fingerprint,
)

SUPPORTED_PROTOCOLS = {
    "shadowsocks",
    "vmess",
    "vless",
    "trojan",
    "hysteria2",
    "tuic",
    "anytls",
    "socks",
    "http",
}
MAX_SUBSCRIPTION_BYTES = 5 * 1024 * 1024
MAX_NODES = 2000
MAX_YAML_EVENTS = 50_000
MAX_YAML_ALIASES = 128
MAX_YAML_DEPTH = 32
MAX_EXPANDED_VALUES = 20_000
URI_PREFIXES = (
    "ss://",
    "vmess://",
    "vless://",
    "trojan://",
    "hysteria2://",
    "hy2://",
    "tuic://",
    "anytls://",
    "socks://",
    "socks5://",
    "http://",
    "https://",
)


@dataclass(frozen=True)
class NodeCandidate:
    name: str
    protocol: str
    endpoint_mask: str
    outbound: dict[str, Any]
    fingerprint: str


class SubscriptionError(RuntimeError):
    def __init__(self, error_type: str, message: str):
        super().__init__(message)
        self.error_type = error_type
        self.safe_message = message


def _validate_yaml_events(value: str) -> None:
    events = 0
    aliases = 0
    depth = 0
    try:
        for event in yaml.parse(value):
            events += 1
            if events > MAX_YAML_EVENTS:
                raise SubscriptionError("unsafe_subscription", "订阅 YAML 节点过多")
            if isinstance(event, AliasEvent):
                aliases += 1
                if aliases > MAX_YAML_ALIASES:
                    raise SubscriptionError("unsafe_subscription", "订阅 YAML 别名过多")
            elif isinstance(event, CollectionStartEvent):
                depth += 1
                if depth > MAX_YAML_DEPTH:
                    raise SubscriptionError("unsafe_subscription", "订阅 YAML 嵌套过深")
            elif isinstance(event, CollectionEndEvent):
                depth -= 1
    except yaml.YAMLError as exc:
        raise SubscriptionError("parse_error", "订阅 YAML 无法解析") from exc


def _bounded_plain_copy(value: Any) -> Any:
    budget = MAX_EXPANDED_VALUES
    active: set[int] = set()

    def copy_item(item: Any, depth: int) -> Any:
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > MAX_YAML_DEPTH:
            raise SubscriptionError("unsafe_subscription", "订阅展开后的结构过大")
        if isinstance(item, dict):
            marker = id(item)
            if marker in active:
                raise SubscriptionError("unsafe_subscription", "订阅包含循环引用")
            active.add(marker)
            try:
                return {
                    copy_item(key, depth + 1): copy_item(child, depth + 1)
                    for key, child in item.items()
                }
            finally:
                active.remove(marker)
        if isinstance(item, list):
            marker = id(item)
            if marker in active:
                raise SubscriptionError("unsafe_subscription", "订阅包含循环引用")
            active.add(marker)
            try:
                return [copy_item(child, depth + 1) for child in item]
            finally:
                active.remove(marker)
        if isinstance(item, (str, int, float, bool)) or item is None:
            return item
        raise SubscriptionError("unsafe_subscription", "订阅包含不支持的数据类型")

    return copy_item(value, 0)


def _decode_base64(value: str) -> str:
    compact = re.sub(r"\s+", "", value)
    padding = "=" * (-len(compact) % 4)
    try:
        return base64.urlsafe_b64decode(compact + padding).decode("utf-8-sig")
    except (binascii.Error, UnicodeDecodeError) as exc:
        raise ValueError("Base64 内容无效") from exc


def _first(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key)
    return values[0] if values else default


def _as_bool(value: Any) -> bool:
    return str(value).lower() in {"1", "true", "yes", "on"}


def _integer(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        return default


def _duration(value: Any) -> str:
    text = str(value or "").strip()
    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        return f"{text}s"
    return text


def _valid_port(value: Any) -> int:
    port = _integer(value)
    if not 1 <= port <= 65535:
        raise ValueError("节点端口无效")
    return port


def _tls_options(
    security: str,
    server: str,
    query: dict[str, list[str]],
    *,
    default_enabled: bool = False,
) -> dict[str, Any] | None:
    enabled = default_enabled or security.lower() in {"tls", "reality"}
    if not enabled:
        return None
    server_name = _first(query, "sni") or _first(query, "peer") or server
    tls: dict[str, Any] = {
        "enabled": True,
        "server_name": server_name,
        "insecure": _as_bool(
            _first(query, "allowInsecure") or _first(query, "insecure")
        ),
    }
    alpn = _first(query, "alpn")
    if alpn:
        tls["alpn"] = [part.strip() for part in alpn.split(",") if part.strip()]
    fingerprint = _first(query, "fp") or _first(query, "client-fingerprint")
    if fingerprint and fingerprint.lower() not in {"none", "randomized"}:
        tls["utls"] = {"enabled": True, "fingerprint": fingerprint}
    if security.lower() == "reality":
        public_key = _first(query, "pbk") or _first(query, "public-key")
        short_id = _first(query, "sid") or _first(query, "short-id")
        if not public_key:
            raise ValueError("Reality 节点缺少公钥")
        tls["reality"] = {
            "enabled": True,
            "public_key": public_key,
            "short_id": short_id,
        }
    return tls


def _transport_options(
    transport_type: str, query: dict[str, list[str]]
) -> dict[str, Any] | None:
    kind = (transport_type or "tcp").lower()
    host = _first(query, "host")
    path = unquote(_first(query, "path", "/"))
    if kind in {"tcp", "none"}:
        return None
    if kind == "ws":
        result: dict[str, Any] = {"type": "ws", "path": path or "/"}
        if host:
            result["headers"] = {"Host": host}
        early_data = _integer(_first(query, "ed"))
        if early_data:
            result["max_early_data"] = early_data
            result["early_data_header_name"] = _first(
                query, "eh", "Sec-WebSocket-Protocol"
            )
        return result
    if kind in {"grpc", "gun"}:
        return {
            "type": "grpc",
            "service_name": unquote(
                _first(query, "serviceName") or _first(query, "service-name")
            ),
        }
    if kind in {"http", "h2"}:
        result = {"type": "http", "path": path or "/"}
        if host:
            result["host"] = [item.strip() for item in host.split(",") if item.strip()]
        return result
    if kind == "httpupgrade":
        result = {"type": "httpupgrade", "path": path or "/"}
        if host:
            result["host"] = host
        return result
    if kind == "quic":
        return {"type": "quic"}
    raise ValueError(f"暂不支持传输类型：{kind}")


def _candidate(
    name: str,
    protocol: str,
    server: str,
    port: int,
    outbound: dict[str, Any],
    fingerprint_pepper: str,
) -> NodeCandidate:
    protocol = protocol.lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"暂不支持节点协议：{protocol}")
    outbound = dict(outbound)
    outbound["type"] = protocol
    outbound["tag"] = "proxy"
    canonical = json.dumps(outbound, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return NodeCandidate(
        name=normalize_display_name(name),
        protocol=protocol,
        endpoint_mask=mask_endpoint(server, port),
        outbound=outbound,
        fingerprint=stable_fingerprint(canonical, fingerprint_pepper),
    )


def parse_vmess(uri: str, pepper: str) -> NodeCandidate:
    payload = uri.split("://", 1)[1].strip()
    data = json.loads(_decode_base64(payload))
    if not isinstance(data, dict):
        raise ValueError("VMess 节点格式无效")
    server = str(data.get("add", "")).strip()
    port = _valid_port(data.get("port"))
    uuid = str(data.get("id", "")).strip()
    if not server or not uuid:
        raise ValueError("VMess 节点缺少服务器或 UUID")
    query = {
        "sni": [str(data.get("sni") or data.get("serverName") or "")],
        "host": [str(data.get("host") or "")],
        "path": [str(data.get("path") or "/")],
        "alpn": [str(data.get("alpn") or "")],
        "fp": [str(data.get("fp") or "")],
        "allowInsecure": [str(data.get("allowInsecure") or "")],
    }
    outbound: dict[str, Any] = {
        "server": server,
        "server_port": port,
        "uuid": uuid,
        "security": str(data.get("scy") or data.get("security") or "auto"),
        "alter_id": _integer(data.get("aid"), 0),
    }
    tls = _tls_options(
        str(data.get("tls") or data.get("security") or ""),
        server,
        query,
    )
    transport = _transport_options(str(data.get("net") or "tcp"), query)
    if tls:
        outbound["tls"] = tls
    if transport:
        outbound["transport"] = transport
    return _candidate(
        str(data.get("ps") or "VMess 节点"),
        "vmess",
        server,
        port,
        outbound,
        pepper,
    )


def parse_standard_uri(uri: str, pepper: str) -> NodeCandidate:
    parsed = urlsplit(uri)
    scheme = parsed.scheme.lower()
    protocol = {"hy2": "hysteria2", "socks5": "socks"}.get(scheme, scheme)
    server = parsed.hostname or ""
    port = _valid_port(parsed.port)
    query = parse_qs(parsed.query, keep_blank_values=True)
    name = unquote(parsed.fragment) or f"{protocol.upper()} 节点"
    user = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if not server:
        raise ValueError("节点服务器为空")

    if protocol == "vless":
        if not user:
            raise ValueError("VLESS 节点缺少 UUID")
        outbound: dict[str, Any] = {
            "server": server,
            "server_port": port,
            "uuid": user,
        }
        flow = _first(query, "flow")
        if flow:
            outbound["flow"] = flow
        tls = _tls_options(_first(query, "security"), server, query)
        transport = _transport_options(_first(query, "type", "tcp"), query)
        if tls:
            outbound["tls"] = tls
        if transport:
            outbound["transport"] = transport
        return _candidate(name, protocol, server, port, outbound, pepper)

    if protocol == "trojan":
        token = user or password
        if not token:
            raise ValueError("Trojan 节点缺少密码")
        outbound = {
            "server": server,
            "server_port": port,
            "password": token,
            "tls": _tls_options(
                _first(query, "security", "tls"),
                server,
                query,
                default_enabled=True,
            ),
        }
        transport = _transport_options(_first(query, "type", "tcp"), query)
        if transport:
            outbound["transport"] = transport
        return _candidate(name, protocol, server, port, outbound, pepper)

    if protocol == "hysteria2":
        token = user if not password else f"{user}:{password}"
        if not token:
            raise ValueError("Hysteria2 节点缺少密码")
        outbound = {
            "server": server,
            "server_port": port,
            "password": token,
            "tls": _tls_options(
                "tls", server, query, default_enabled=True
            ),
        }
        server_ports = _first(query, "mport") or _first(query, "ports")
        if server_ports:
            outbound.pop("server_port", None)
            outbound["server_ports"] = [
                item.strip() for item in server_ports.split(",") if item.strip()
            ]
        obfs_type = _first(query, "obfs")
        obfs_password = _first(query, "obfs-password")
        if obfs_type and obfs_password:
            outbound["obfs"] = {"type": obfs_type, "password": obfs_password}
        return _candidate(name, protocol, server, port, outbound, pepper)

    if protocol == "tuic":
        if not user or not password:
            raise ValueError("TUIC 节点缺少 UUID 或密码")
        outbound = {
            "server": server,
            "server_port": port,
            "uuid": user,
            "password": password,
            "congestion_control": _first(query, "congestion_control", "cubic"),
            "udp_relay_mode": _first(query, "udp_relay_mode", "native"),
            "tls": _tls_options("tls", server, query, default_enabled=True),
        }
        return _candidate(name, protocol, server, port, outbound, pepper)

    if protocol == "anytls":
        token = user or password
        if not token:
            raise ValueError("AnyTLS 节点缺少密码")
        outbound = {
            "server": server,
            "server_port": port,
            "password": token,
            "tls": _tls_options("tls", server, query, default_enabled=True),
        }
        interval = _first(query, "idle_session_check_interval") or _first(
            query, "idle-session-check-interval"
        )
        timeout = _first(query, "idle_session_timeout") or _first(
            query, "idle-session-timeout"
        )
        minimum = _integer(
            _first(query, "min_idle_session")
            or _first(query, "min-idle-session"),
            -1,
        )
        if interval:
            outbound["idle_session_check_interval"] = _duration(interval)
        if timeout:
            outbound["idle_session_timeout"] = _duration(timeout)
        if minimum >= 0:
            outbound["min_idle_session"] = minimum
        return _candidate(name, protocol, server, port, outbound, pepper)

    if protocol in {"socks", "http"}:
        outbound = {"server": server, "server_port": port}
        if user:
            outbound["username"] = user
        if password:
            outbound["password"] = password
        if scheme == "https":
            outbound["tls"] = _tls_options(
                "tls", server, query, default_enabled=True
            )
        return _candidate(name, protocol, server, port, outbound, pepper)

    raise ValueError(f"暂不支持节点协议：{protocol}")


def parse_shadowsocks(uri: str, pepper: str) -> NodeCandidate:
    raw = uri.split("://", 1)[1]
    fragment = ""
    if "#" in raw:
        raw, fragment = raw.split("#", 1)
    query_text = ""
    if "?" in raw:
        raw, query_text = raw.split("?", 1)
    name = unquote(fragment) or "Shadowsocks 节点"
    query = parse_qs(query_text, keep_blank_values=True)
    if "@" not in raw:
        raw = _decode_base64(raw)
    credentials, endpoint = raw.rsplit("@", 1)
    if ":" not in credentials:
        credentials = _decode_base64(credentials)
    method, password = credentials.split(":", 1)
    parsed_endpoint = urlsplit(f"ss://x@{endpoint}")
    server = parsed_endpoint.hostname or ""
    port = _valid_port(parsed_endpoint.port)
    if not method or not password or not server:
        raise ValueError("Shadowsocks 节点字段不完整")
    outbound: dict[str, Any] = {
        "server": server,
        "server_port": port,
        "method": unquote(method),
        "password": unquote(password),
    }
    plugin_value = _first(query, "plugin")
    if plugin_value:
        plugin_parts = unquote(plugin_value).split(";")
        outbound["plugin"] = plugin_parts[0]
        if len(plugin_parts) > 1:
            outbound["plugin_opts"] = ";".join(plugin_parts[1:])
    return _candidate(name, "shadowsocks", server, port, outbound, pepper)


def parse_uri(uri: str, pepper: str) -> NodeCandidate:
    uri = uri.strip()
    scheme = uri.split("://", 1)[0].lower()
    if scheme == "vmess":
        return parse_vmess(uri, pepper)
    if scheme == "ss":
        return parse_shadowsocks(uri, pepper)
    return parse_standard_uri(uri, pepper)


def _clash_tls(proxy: dict[str, Any], server: str) -> dict[str, Any] | None:
    enabled = bool(proxy.get("tls")) or proxy.get("type") in {
        "trojan",
        "hysteria2",
        "hy2",
        "tuic",
        "anytls",
    }
    if not enabled:
        return None
    result: dict[str, Any] = {
        "enabled": True,
        "server_name": str(proxy.get("servername") or proxy.get("sni") or server),
        "insecure": bool(proxy.get("skip-cert-verify", False)),
    }
    alpn = proxy.get("alpn")
    if isinstance(alpn, list):
        result["alpn"] = [str(item) for item in alpn]
    fingerprint = proxy.get("client-fingerprint")
    if fingerprint:
        result["utls"] = {"enabled": True, "fingerprint": str(fingerprint)}
    reality = proxy.get("reality-opts")
    if isinstance(reality, dict) and reality.get("public-key"):
        result["reality"] = {
            "enabled": True,
            "public_key": str(reality["public-key"]),
            "short_id": str(reality.get("short-id") or ""),
        }
    return result


def _clash_transport(proxy: dict[str, Any]) -> dict[str, Any] | None:
    network = str(proxy.get("network") or "tcp").lower()
    if network == "ws":
        opts = proxy.get("ws-opts") if isinstance(proxy.get("ws-opts"), dict) else {}
        result: dict[str, Any] = {
            "type": "ws",
            "path": str(opts.get("path") or "/"),
        }
        headers = opts.get("headers")
        if isinstance(headers, dict):
            result["headers"] = {str(k): str(v) for k, v in headers.items()}
        return result
    if network == "grpc":
        opts = (
            proxy.get("grpc-opts")
            if isinstance(proxy.get("grpc-opts"), dict)
            else {}
        )
        return {
            "type": "grpc",
            "service_name": str(
                opts.get("grpc-service-name") or opts.get("service-name") or ""
            ),
        }
    if network in {"h2", "http"}:
        opts = (
            proxy.get("h2-opts") if isinstance(proxy.get("h2-opts"), dict) else {}
        )
        result = {"type": "http", "path": str(opts.get("path") or "/")}
        host = opts.get("host")
        if isinstance(host, list):
            result["host"] = [str(item) for item in host]
        elif host:
            result["host"] = [str(host)]
        return result
    if network in {"tcp", "none"}:
        return None
    raise ValueError(f"暂不支持 Clash 传输类型：{network}")


def parse_clash_proxy(proxy: dict[str, Any], pepper: str) -> NodeCandidate:
    raw_type = str(proxy.get("type") or "").lower()
    protocol = {
        "ss": "shadowsocks",
        "socks5": "socks",
        "hy2": "hysteria2",
    }.get(raw_type, raw_type)
    server = str(proxy.get("server") or "").strip()
    port = _valid_port(proxy.get("port"))
    name = normalize_display_name(str(proxy.get("name") or f"{protocol} 节点"))
    if not server:
        raise ValueError("Clash 节点缺少服务器")
    outbound: dict[str, Any] = {"server": server, "server_port": port}

    if protocol == "shadowsocks":
        outbound.update(
            method=str(proxy.get("cipher") or ""),
            password=str(proxy.get("password") or ""),
        )
        if proxy.get("plugin"):
            outbound["plugin"] = str(proxy["plugin"])
            plugin_opts = proxy.get("plugin-opts")
            if isinstance(plugin_opts, dict):
                outbound["plugin_opts"] = ";".join(
                    f"{key}={value}" for key, value in plugin_opts.items()
                )
    elif protocol == "vmess":
        outbound.update(
            uuid=str(proxy.get("uuid") or ""),
            security=str(proxy.get("cipher") or "auto"),
            alter_id=_integer(proxy.get("alterId") or proxy.get("alter-id"), 0),
        )
    elif protocol == "vless":
        outbound["uuid"] = str(proxy.get("uuid") or "")
        if proxy.get("flow"):
            outbound["flow"] = str(proxy["flow"])
    elif protocol == "trojan":
        outbound["password"] = str(proxy.get("password") or "")
    elif protocol == "hysteria2":
        outbound["password"] = str(proxy.get("password") or proxy.get("auth") or "")
        ports = proxy.get("ports")
        if ports:
            outbound.pop("server_port", None)
            outbound["server_ports"] = (
                [str(item) for item in ports]
                if isinstance(ports, list)
                else [str(ports)]
            )
        obfs = proxy.get("obfs")
        obfs_password = proxy.get("obfs-password")
        if obfs and obfs_password:
            outbound["obfs"] = {
                "type": str(obfs),
                "password": str(obfs_password),
            }
    elif protocol == "tuic":
        outbound.update(
            uuid=str(proxy.get("uuid") or ""),
            password=str(proxy.get("password") or ""),
            congestion_control=str(proxy.get("congestion-controller") or "cubic"),
            udp_relay_mode=str(proxy.get("udp-relay-mode") or "native"),
        )
    elif protocol == "anytls":
        password = str(proxy.get("password") or "")
        if not password:
            raise ValueError("AnyTLS 节点缺少密码")
        outbound["password"] = password
        interval = proxy.get("idle-session-check-interval")
        timeout = proxy.get("idle-session-timeout")
        minimum = proxy.get("min-idle-session")
        if interval:
            outbound["idle_session_check_interval"] = _duration(interval)
        if timeout:
            outbound["idle_session_timeout"] = _duration(timeout)
        if minimum is not None:
            outbound["min_idle_session"] = _integer(minimum)
    elif protocol in {"socks", "http"}:
        if proxy.get("username"):
            outbound["username"] = str(proxy["username"])
        if proxy.get("password"):
            outbound["password"] = str(proxy["password"])
    else:
        raise ValueError(f"暂不支持 Clash 节点协议：{raw_type}")

    if protocol in {"vmess", "vless", "trojan"}:
        tls = _clash_tls(proxy, server)
        transport = _clash_transport(proxy)
        if tls:
            outbound["tls"] = tls
        if transport:
            outbound["transport"] = transport
    elif protocol in {"hysteria2", "tuic", "anytls"}:
        outbound["tls"] = _clash_tls(proxy, server)
    return _candidate(name, protocol, server, port, outbound, pepper)


def parse_singbox_outbound(
    outbound: dict[str, Any], pepper: str
) -> NodeCandidate:
    protocol = str(outbound.get("type") or "").lower()
    if protocol not in SUPPORTED_PROTOCOLS:
        raise ValueError(f"不支持 sing-box 出站类型：{protocol}")
    server = str(outbound.get("server") or "").strip()
    port = _valid_port(outbound.get("server_port"))
    if not server:
        raise ValueError("sing-box 出站缺少服务器")
    cleaned = _bounded_plain_copy(outbound)
    name = normalize_display_name(str(cleaned.pop("tag", "") or f"{protocol} 节点"))
    for unsafe_key in (
        "detour",
        "bind_interface",
        "routing_mark",
        "netns",
        "network_strategy",
    ):
        cleaned.pop(unsafe_key, None)
    return _candidate(name, protocol, server, port, cleaned, pepper)


def _looks_like_uri_list(text: str) -> bool:
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return bool(lines) and sum(line.startswith(URI_PREFIXES) for line in lines) >= max(
        1, len(lines) // 2
    )


def parse_subscription_content(text: str, pepper: str) -> tuple[list[NodeCandidate], list[str]]:
    text = text.lstrip("\ufeff").strip()
    if not text:
        raise SubscriptionError("empty_subscription", "订阅返回了空内容")
    decoded = text
    if not _looks_like_uri_list(text) and not text.startswith(("{", "[", "proxies:")):
        try:
            possible = _decode_base64(text)
            if (
                _looks_like_uri_list(possible)
                or possible.startswith(("{", "["))
                or re.search(r"(?m)^\s*proxies\s*:", possible)
            ):
                decoded = possible
        except ValueError:
            pass

    candidates: list[NodeCandidate] = []
    warnings: list[str] = []
    structured: Any = None
    if decoded.startswith(("{", "[")):
        try:
            structured = json.loads(decoded)
        except json.JSONDecodeError:
            structured = None
    if structured is None and (
        re.search(r"(?m)^\s*proxies\s*:", decoded)
        or re.search(r"(?m)^\s*outbounds\s*:", decoded)
    ):
        _validate_yaml_events(decoded)
        try:
            structured = yaml.safe_load(decoded)
        except yaml.YAMLError as exc:
            raise SubscriptionError("parse_error", "订阅 YAML 无法解析") from exc

    raw_items: list[Any]
    parser_kind = "uri"
    if isinstance(structured, dict) and isinstance(structured.get("proxies"), list):
        raw_items = structured["proxies"]
        parser_kind = "clash"
    elif isinstance(structured, dict) and isinstance(structured.get("outbounds"), list):
        raw_items = structured["outbounds"]
        parser_kind = "singbox"
    elif isinstance(structured, list):
        raw_items = structured
        parser_kind = "singbox"
    else:
        raw_items = [
            line.strip()
            for line in decoded.splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]

    for index, item in enumerate(raw_items[:MAX_NODES], start=1):
        try:
            if parser_kind == "clash" and isinstance(item, dict):
                candidates.append(parse_clash_proxy(_bounded_plain_copy(item), pepper))
            elif parser_kind == "singbox" and isinstance(item, dict):
                candidates.append(
                    parse_singbox_outbound(_bounded_plain_copy(item), pepper)
                )
            elif isinstance(item, str) and item.startswith(URI_PREFIXES):
                candidates.append(parse_uri(item, pepper))
            else:
                warnings.append(f"第 {index} 项不是支持的节点格式")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            warnings.append(f"第 {index} 项已跳过：{sanitize_exception(exc)}")
    if len(raw_items) > MAX_NODES:
        warnings.append(f"订阅超过 {MAX_NODES} 个节点，超出部分已忽略")

    unique: dict[str, NodeCandidate] = {}
    for candidate in candidates:
        unique[candidate.fingerprint] = candidate
    if not unique:
        detail = warnings[0] if warnings else "没有发现支持的节点"
        raise SubscriptionError("no_supported_nodes", detail)
    return list(unique.values()), warnings[:20]


async def fetch_subscription(url: str, timeout_seconds: int = 20) -> str:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise SubscriptionError("invalid_url", "订阅地址格式无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SubscriptionError("invalid_url", "订阅地址必须是有效的 HTTP/HTTPS 地址")
    headers = {
        "User-Agent": "AirportAvailabilityMonitor/1.0",
        "Accept": "text/plain, application/yaml, application/json, */*",
    }
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=True,
            trust_env=False,
            headers=headers,
        ) as client:
            async with client.stream("GET", url) as response:
                response.raise_for_status()
                content = bytearray()
                async for chunk in response.aiter_bytes():
                    content.extend(chunk)
                    if len(content) > MAX_SUBSCRIPTION_BYTES:
                        raise SubscriptionError(
                            "subscription_too_large", "订阅内容超过 5 MiB 安全上限"
                        )
    except SubscriptionError:
        raise
    except httpx.TimeoutException as exc:
        raise SubscriptionError("timeout", "订阅刷新超时") from exc
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        raise SubscriptionError("http_error", f"订阅服务器返回 HTTP {code}") from exc
    except (httpx.HTTPError, OSError) as exc:
        message = sanitize_exception(exc)
        if "certificate" in message.lower() or "ssl" in message.lower():
            raise SubscriptionError("tls_error", "订阅服务器 TLS 校验失败") from exc
        raise SubscriptionError("network_error", "无法连接订阅服务器") from exc
    try:
        return bytes(content).decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return bytes(content).decode("gb18030")
        except UnicodeDecodeError as exc:
            raise SubscriptionError("encoding_error", "订阅文本编码无法识别") from exc
