import base64
import json

from app.subscriptions import parse_subscription_content, parse_uri


PEPPER = "unit-test-pepper"


def _b64(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode()).decode().rstrip("=")


def test_parse_vless_reality_ws_uri():
    node = parse_uri(
        "vless://11111111-1111-1111-1111-111111111111@edge.example.com:443"
        "?security=reality&sni=www.example.org&pbk=publickey&sid=abcd"
        "&type=ws&host=cdn.example.org&path=%2Fgateway#东京入口",
        PEPPER,
    )
    assert node.name == "东京入口"
    assert node.protocol == "vless"
    assert node.endpoint_mask == "*.example.com:443"
    assert node.outbound["tls"]["reality"]["public_key"] == "publickey"
    assert node.outbound["transport"]["type"] == "ws"


def test_parse_vmess_and_shadowsocks_list():
    vmess = {
        "v": "2",
        "ps": "VMess 测试",
        "add": "vm.example.com",
        "port": "443",
        "id": "22222222-2222-2222-2222-222222222222",
        "aid": "0",
        "net": "ws",
        "host": "cdn.example.com",
        "path": "/ws",
        "tls": "tls",
        "sni": "cdn.example.com",
    }
    ss_credentials = _b64("aes-128-gcm:test-password")
    raw = "\n".join(
        (
            f"vmess://{_b64(json.dumps(vmess, ensure_ascii=False))}",
            f"ss://{ss_credentials}@ss.example.net:8388#SS%20测试",
        )
    )
    encoded_subscription = base64.b64encode(raw.encode()).decode()
    nodes, warnings = parse_subscription_content(encoded_subscription, PEPPER)
    assert not warnings
    assert {node.protocol for node in nodes} == {"vmess", "shadowsocks"}
    assert all("test-password" not in node.endpoint_mask for node in nodes)


def test_parse_clash_yaml_and_skip_unsupported():
    content = """
proxies:
  - name: 主线路
    type: trojan
    server: trojan.example.com
    port: 443
    password: test-only
    sni: front.example.com
    skip-cert-verify: false
  - name: 不支持
    type: wireguard
    server: wg.example.com
    port: 51820
"""
    nodes, warnings = parse_subscription_content(content, PEPPER)
    assert len(nodes) == 1
    assert nodes[0].protocol == "trojan"
    assert warnings and "暂不支持" in warnings[0]


def test_deduplicates_identical_nodes():
    uri = "trojan://test-password@edge.example.com:443?sni=edge.example.com#节点"
    nodes, _warnings = parse_subscription_content(f"{uri}\n{uri}", PEPPER)
    assert len(nodes) == 1


def test_parse_clash_anytls():
    content = """
proxies:
  - name: AnyTLS 测试
    type: anytls
    server: anytls.example.com
    port: 443
    password: test-only
    sni: front.example.com
    client-fingerprint: chrome
    skip-cert-verify: false
    idle-session-check-interval: 30
    idle-session-timeout: 30
    min-idle-session: 1
"""
    nodes, warnings = parse_subscription_content(content, PEPPER)
    assert not warnings
    assert len(nodes) == 1
    node = nodes[0]
    assert node.protocol == "anytls"
    assert node.outbound["password"] == "test-only"  # pragma: allowlist secret
    assert node.outbound["tls"]["server_name"] == "front.example.com"
    assert node.outbound["idle_session_check_interval"] == "30s"
    assert node.outbound["idle_session_timeout"] == "30s"
    assert node.outbound["min_idle_session"] == 1
