from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken


SCRYPT_N = 2**15
SCRYPT_R = 8
SCRYPT_P = 1
SENSITIVE_KEYS = {
    "url",
    "subscription_url",
    "password",
    "token",
    "secret",
    "uuid",
    "private_key",
    "public_key",
    "short_id",
    "authorization",
    "cookie",
}
URI_PATTERN = re.compile(
    r"\b(?:https?|ss|vmess|vless|trojan|hysteria2|hy2|tuic|socks5?)://[^\s]+",
    re.IGNORECASE,
)


class SecretBox:
    def __init__(self, key: str):
        try:
            self._fernet = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeEncodeError) as exc:
            raise RuntimeError("AIRPORT_ENCRYPTION_KEY 不是有效 Fernet 密钥") from exc

    def encrypt_text(self, value: str) -> str:
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt_text(self, value: str) -> str:
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise RuntimeError("加密数据无法解密，请确认密钥未变化") from exc

    def encrypt_json(self, value: dict[str, Any]) -> str:
        raw = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return self.encrypt_text(raw)

    def decrypt_json(self, value: str) -> dict[str, Any]:
        result = json.loads(self.decrypt_text(value))
        if not isinstance(result, dict):
            raise RuntimeError("加密节点配置格式无效")
        return result


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode("ascii")


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("管理员密码至少需要 12 个字符")
    salt = os.urandom(16)
    derived = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=32,
        maxmem=64 * 1024 * 1024,
    )
    return "$".join(
        (
            "scrypt",
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.urlsafe_b64encode(salt).decode("ascii"),
            base64.urlsafe_b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    try:
        kind, n, r, p, salt_text, expected_text = encoded.split("$", 5)
        if kind != "scrypt":
            return False
        salt = base64.urlsafe_b64decode(salt_text)
        expected = base64.urlsafe_b64decode(expected_text)
        actual = hashlib.scrypt(
            password.encode("utf-8"),
            salt=salt,
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(expected),
            maxmem=64 * 1024 * 1024,
        )
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def opaque_token(length: int = 32) -> str:
    return secrets.token_urlsafe(length)


def token_digest(token: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"), token.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def stable_fingerprint(value: str, pepper: str) -> str:
    return hmac.new(
        pepper.encode("utf-8"), value.encode("utf-8"), hashlib.sha256
    ).hexdigest()


def normalize_display_name(value: str, fallback: str = "未命名节点") -> str:
    cleaned = re.sub(r"[\x00-\x1f\x7f]", "", value or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned[:100] or fallback)


def mask_endpoint(host: str, port: int | str | None = None) -> str:
    host = (host or "").strip().strip("[]")
    masked = "已隐藏"
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        parts = host.split(".")
        masked = f"{parts[0]}.{parts[1]}.*.*"
    elif ":" in host:
        groups = [part for part in host.split(":") if part]
        masked = f"{groups[0] if groups else '*'}:*:*"
    elif "." in host:
        parts = host.split(".")
        masked = f"*.{'.'.join(parts[-2:])}" if len(parts) >= 2 else "*.已隐藏"
    elif host:
        masked = f"{host[:2]}***"
    return f"{masked}:{port}" if port else masked


def sanitize_exception(value: Any) -> str:
    text = str(value)
    text = URI_PATTERN.sub("<敏感地址已隐藏>", text)
    text = re.sub(
        r"(?i)\b(password|token|secret|authorization|cookie)\s*[:=]\s*\S+",
        r"\1=<已隐藏>",
        text,
    )
    return text[:500]


def scrub_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key.lower() in SENSITIVE_KEYS:
                result[key] = "<已隐藏>"
            else:
                result[key] = scrub_mapping(item)
        return result
    if isinstance(value, list):
        return [scrub_mapping(item) for item in value]
    if isinstance(value, str):
        return URI_PATTERN.sub("<敏感地址已隐藏>", value)
    return value


def safe_origin_matches(origin: str | None, host_header: str) -> bool:
    if not origin:
        return True
    try:
        parsed = urlsplit(origin)
        return parsed.scheme in {"http", "https"} and parsed.netloc == host_header
    except ValueError:
        return False


@dataclass
class LoginLimiterEntry:
    attempts: list[float]
    blocked_until: float = 0.0


class LoginRateLimiter:
    def __init__(self, max_attempts: int = 5, window_seconds: int = 600):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._entries: dict[str, LoginLimiterEntry] = {}

    def allowed(self, key: str) -> tuple[bool, int]:
        now = time.monotonic()
        entry = self._entries.setdefault(key, LoginLimiterEntry([]))
        if entry.blocked_until > now:
            return False, max(1, int(entry.blocked_until - now))
        entry.attempts = [
            stamp for stamp in entry.attempts if now - stamp < self.window_seconds
        ]
        return True, 0

    def failure(self, key: str) -> None:
        now = time.monotonic()
        entry = self._entries.setdefault(key, LoginLimiterEntry([]))
        entry.attempts.append(now)
        if len(entry.attempts) >= self.max_attempts:
            extra = min(1800, 30 * (2 ** (len(entry.attempts) - self.max_attempts)))
            entry.blocked_until = now + extra

    def success(self, key: str) -> None:
        self._entries.pop(key, None)
