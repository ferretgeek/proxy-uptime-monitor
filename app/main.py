from __future__ import annotations

import asyncio
import json
import logging
import logging.handlers
import mimetypes
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path
from typing import Any, Annotated, Literal
from urllib.parse import urlsplit

import uvicorn
from fastapi import (
    Cookie,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, Field

from . import __version__
from .analytics import (
    dashboard,
    latency_summary,
    list_events,
    node_page,
    node_detail,
    node_trend,
    system_status,
    trend,
)
from .config import AppConfig
from .database import Database, iso_now, parse_time, utc_now
from .engine import MonitorEngine
from .executor import NodeExecutor
from .locations import COUNTRIES, normalize_country_code
from .security import (
    LoginRateLimiter,
    SecretBox,
    hash_password,
    opaque_token,
    safe_origin_matches,
    sanitize_exception,
    token_digest,
    verify_password,
)
from .storage import StorageManager
from .targets import public_target_catalog


SESSION_COOKIE = "airport_session"
CSRF_COOKIE = "airport_csrf"
SESSION_DAYS = 30
SESSION_MAX_AGE_SECONDS = SESSION_DAYS * 24 * 60 * 60
CONFIG = AppConfig.from_env()
DATABASE = Database(CONFIG.database_path)
SECRET_BOX = SecretBox(CONFIG.encryption_key)
STORAGE = StorageManager(CONFIG)
LOGIN_LIMITER = LoginRateLimiter()
DUMMY_PASSWORD_HASH = hash_password("constant-time-dummy-password")

# Windows 注册表可能把 .svg 映射成非标准的 image/svg；在 nosniff 下会导致
# 浏览器拒绝品牌图标。统一为标准 MIME，确保本机验收与 Linux 部署行为一致。
mimetypes.add_type("image/svg+xml", ".svg", strict=True)
mimetypes.add_type("image/svg+xml", ".svg", strict=False)


def configure_logging() -> None:
    CONFIG.ensure_runtime_directories()
    handler = logging.handlers.RotatingFileHandler(
        CONFIG.log_dir / "app.log",
        maxBytes=25 * 1024 * 1024,
        backupCount=20,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S%z",
        )
    )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(getattr(logging, CONFIG.log_level, logging.INFO))
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").disabled = True


configure_logging()
LOGGER = logging.getLogger("airport_monitor.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    CONFIG.ensure_runtime_directories()
    DATABASE.migrate()
    engine = MonitorEngine(
        DATABASE,
        SECRET_BOX,
        NodeExecutor(CONFIG.sing_box_path, CONFIG.runtime_dir),
        CONFIG.session_pepper,
        STORAGE,
    )
    app.state.engine = engine
    await engine.start()
    try:
        yield
    finally:
        await engine.stop()


app = FastAPI(
    title="航迹机场订阅实际可用度监测平台",
    version=__version__,
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(CONFIG.allowed_hosts))


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "style-src-elem 'self'; style-src-attr 'unsafe-inline'; "
        "img-src 'self' data:; connect-src 'self'; font-src 'self'; "
        "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; "
        "form-action 'self'"
    )
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    errors = [
        {
            "field": ".".join(str(part) for part in item.get("loc", [])[1:]),
            "message": item.get("msg", "输入无效"),
            "type": item.get("type", "validation_error"),
        }
        for item in exc.errors()
    ]
    return JSONResponse(
        status_code=422, content={"detail": "提交内容校验失败", "errors": errors}
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(_request: Request, exc: Exception) -> JSONResponse:
    LOGGER.error("请求处理失败：%s", sanitize_exception(exc))
    return JSONResponse(
        status_code=500, content={"detail": "服务内部错误，请稍后重试"}
    )


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=256)


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    url: str = Field(min_length=8, max_length=4096)
    enabled: bool = True
    refresh_interval_minutes: int = Field(default=360, ge=15, le=10080)


class SubscriptionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    url: str | None = Field(default=None, max_length=4096)
    enabled: bool | None = None
    refresh_interval_minutes: int | None = Field(default=None, ge=15, le=10080)


class NodeEnableRequest(BaseModel):
    enabled: bool


class NodeBatchEnableRequest(BaseModel):
    node_ids: list[int] = Field(min_length=1, max_length=500)
    enabled: bool


class NodeRegionRequest(BaseModel):
    country_code: str = Field(min_length=2, max_length=2)


class BatchCheckRequest(BaseModel):
    node_ids: list[int] = Field(min_length=1, max_length=500)


class SettingsUpdate(BaseModel):
    check_interval_minutes: int | None = None
    offline_check_interval_minutes: int | None = None
    timeout_seconds: int | None = None
    retry_count: int | None = None
    max_concurrency: int | None = None
    jitter_seconds: int | None = None
    scheduler_paused: bool | None = None
    raw_retention_days: int | None = None
    hourly_retention_days: int | None = None
    node_probe_enabled: bool | None = None
    enabled_targets: list[str] | None = Field(
        default=None, min_length=1, max_length=15
    )


class NotificationUpdate(BaseModel):
    enabled: bool
    endpoint: str | None = Field(default=None, max_length=4096)
    clear_endpoint: bool = False
    event_types: list[Literal["failure", "recovery"]] = Field(
        default_factory=lambda: ["failure", "recovery"]
    )
    cooldown_minutes: int = Field(default=30, ge=5, le=1440)


def _remote_fingerprint(request: Request) -> str:
    remote = request.client.host if request.client else "unknown"
    agent = request.headers.get("user-agent", "")[:300]
    return token_digest(f"{remote}|{agent}", CONFIG.session_pepper)


def _set_session_cookies(
    response: Response,
    session_token: str,
    csrf_token: str | None,
    max_age: int = SESSION_MAX_AGE_SECONDS,
) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        session_token,
        max_age=max_age,
        httponly=True,
        secure=False,
        samesite="strict",
        path="/",
    )
    if csrf_token:
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token,
            max_age=max_age,
            httponly=False,
            secure=False,
            samesite="strict",
            path="/",
        )


def _validate_origin(request: Request) -> None:
    if not safe_origin_matches(
        request.headers.get("origin"), request.headers.get("host", "")
    ):
        raise HTTPException(status_code=403, detail="请求来源校验失败")


async def require_admin(
    request: Request,
    response: Response,
    airport_session: Annotated[str | None, Cookie()] = None,
) -> dict[str, Any]:
    if not airport_session:
        raise HTTPException(status_code=401, detail="请先登录")
    digest = token_digest(airport_session, CONFIG.session_pepper)
    row = DATABASE.fetch_one(
        "SELECT s.token_hash,s.csrf_hash,s.expires_at,s.last_seen_at,"
        "s.remote_fingerprint,a.id AS admin_id,a.username "
        "FROM sessions s JOIN admins a ON a.id=s.admin_id WHERE s.token_hash=?",
        (digest,),
    )
    expires_at = parse_time(row["expires_at"]) if row else None
    now = utc_now()
    if (
        not row
        or not expires_at
        or expires_at <= now
        or row["remote_fingerprint"] != _remote_fingerprint(request)
    ):
        if row:
            DATABASE.execute("DELETE FROM sessions WHERE token_hash=?", (digest,))
        raise HTTPException(status_code=401, detail="会话已失效，请重新登录")
    last_seen = parse_time(row["last_seen_at"])
    if not last_seen or utc_now() - last_seen > timedelta(minutes=5):
        DATABASE.execute(
            "UPDATE sessions SET last_seen_at=? WHERE token_hash=?",
            (iso_now(), digest),
        )
    csrf_token = request.cookies.get(CSRF_COOKIE, "")
    if request.url.path != "/api/auth/logout":
        valid_csrf_token = (
            csrf_token
            if csrf_token
            and token_digest(csrf_token, CONFIG.session_pepper) == row["csrf_hash"]
            else None
        )
        remaining_seconds = max(1, int((expires_at - now).total_seconds()))
        _set_session_cookies(
            response,
            airport_session,
            valid_csrf_token,
            max_age=remaining_seconds,
        )
    request.state.admin = row
    return row


async def require_csrf(
    request: Request,
    admin: Annotated[dict[str, Any], Depends(require_admin)],
) -> dict[str, Any]:
    _validate_origin(request)
    header_token = request.headers.get("x-csrf-token", "")
    cookie_token = request.cookies.get(CSRF_COOKIE, "")
    if (
        not header_token
        or not cookie_token
        or header_token != cookie_token
        or token_digest(header_token, CONFIG.session_pepper) != admin["csrf_hash"]
    ):
        raise HTTPException(status_code=403, detail="会话安全令牌校验失败")
    return admin


def _validate_http_url(value: str, label: str) -> str:
    value = value.strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{label}格式无效") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise HTTPException(
            status_code=422, detail=f"{label}必须是有效的 HTTP/HTTPS 地址"
        )
    return value


def _safe_subscription(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "name": row["name"],
        "enabled": bool(row["enabled"]),
        "refresh_interval_minutes": row["refresh_interval_minutes"],
        "last_refresh_at": row["last_refresh_at"],
        "next_refresh_at": row["next_refresh_at"],
        "last_error_type": row["last_error_type"],
        "last_error_message": row["last_error_message"],
        "node_count": row["node_count"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "url_configured": True,
    }


@app.get("/api/health")
async def health() -> dict[str, Any]:
    DATABASE.fetch_one("SELECT 1 AS ok")
    admin = DATABASE.fetch_one("SELECT COUNT(*) AS n FROM admins")
    return {
        "status": "ok",
        "version": __version__,
        "scheduler": bool(getattr(app.state, "engine", None)),
        "admin_initialized": bool(admin and admin["n"]),
        "time": iso_now(),
    }


@app.post("/api/auth/login")
async def login(payload: LoginRequest, request: Request, response: Response):
    _validate_origin(request)
    limiter_key = request.client.host if request.client else "unknown"
    allowed, retry_after = LOGIN_LIMITER.allowed(limiter_key)
    if not allowed:
        response.headers["Retry-After"] = str(retry_after)
        raise HTTPException(
            status_code=429, detail=f"尝试次数过多，请在 {retry_after} 秒后重试"
        )
    row = DATABASE.fetch_one(
        "SELECT id,username,password_hash FROM admins WHERE username=?",
        (payload.username.strip(),),
    )
    valid = verify_password(
        payload.password, row["password_hash"] if row else DUMMY_PASSWORD_HASH
    )
    if not row or not valid:
        LOGIN_LIMITER.failure(limiter_key)
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    LOGIN_LIMITER.success(limiter_key)
    session_token = opaque_token()
    csrf_token = opaque_token(24)
    now = iso_now()
    expires = (utc_now() + timedelta(days=SESSION_DAYS)).isoformat(
        timespec="seconds"
    )
    DATABASE.execute(
        "INSERT INTO sessions(token_hash,admin_id,csrf_hash,created_at,expires_at,"
        "last_seen_at,remote_fingerprint) VALUES (?,?,?,?,?,?,?)",
        (
            token_digest(session_token, CONFIG.session_pepper),
            row["id"],
            token_digest(csrf_token, CONFIG.session_pepper),
            now,
            expires,
            now,
            _remote_fingerprint(request),
        ),
    )
    _set_session_cookies(response, session_token, csrf_token)
    return {"username": row["username"], "expires_at": expires}


@app.post("/api/auth/logout")
async def logout(
    request: Request,
    response: Response,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    token = request.cookies.get(SESSION_COOKIE, "")
    if token:
        DATABASE.execute(
            "DELETE FROM sessions WHERE token_hash=?",
            (token_digest(token, CONFIG.session_pepper),),
        )
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")
    return {"ok": True}


@app.get("/api/auth/me")
async def me(admin: Annotated[dict[str, Any], Depends(require_admin)]):
    return {"username": admin["username"], "expires_at": admin["expires_at"]}


@app.get("/api/dashboard")
async def get_dashboard(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    result = dashboard(DATABASE)
    result["hardware"] = CONFIG.hardware_profile
    return result


@app.get("/api/targets")
async def get_targets(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    return {
        "items": public_target_catalog(),
        "enabled": DATABASE.get_settings()["enabled_targets"],
    }


@app.get("/api/trend")
async def get_trend(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    days: int = Query(default=7, ge=1, le=30),
):
    return {"points": trend(DATABASE, days)}


@app.get("/api/latency-summary")
async def get_latency_summary(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=10, le=100),
    search: str = Query(default="", max_length=120),
    country: str = Query(default="", max_length=2),
    sort: str = Query(
        default="score",
        pattern="^(score|availability|node_latency|website_latency|name|country)$",
    ),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
):
    return latency_summary(
        DATABASE,
        page=page,
        page_size=page_size,
        search=search,
        country=country,
        sort=sort,
        direction=direction,
        enabled_only=True,
    )


@app.get("/api/subscriptions")
async def get_subscriptions(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    rows = DATABASE.fetch_all(
        "SELECT * FROM subscriptions ORDER BY enabled DESC,name"
    )
    return {"items": [_safe_subscription(row) for row in rows]}


@app.post("/api/subscriptions", status_code=201)
async def create_subscription(
    payload: SubscriptionCreate,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    url = _validate_http_url(payload.url, "订阅地址")
    now = iso_now()
    subscription_id = DATABASE.execute(
        "INSERT INTO subscriptions(name,url_encrypted,enabled,"
        "refresh_interval_minutes,next_refresh_at,created_at,updated_at)"
        " VALUES (?,?,?,?,?,?,?)",
        (
            payload.name.strip(),
            SECRET_BOX.encrypt_text(url),
            int(payload.enabled),
            payload.refresh_interval_minutes,
            now,
            now,
            now,
        ),
    )
    task_id = await app.state.engine.request_refresh(
        subscription_id, admin["username"]
    )
    row = DATABASE.fetch_one(
        "SELECT * FROM subscriptions WHERE id=?", (subscription_id,)
    )
    return {"item": _safe_subscription(row), "task_id": task_id}


@app.put("/api/subscriptions/{subscription_id}")
async def update_subscription(
    subscription_id: int,
    payload: SubscriptionUpdate,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    current = DATABASE.fetch_one(
        "SELECT * FROM subscriptions WHERE id=?", (subscription_id,)
    )
    if not current:
        raise HTTPException(status_code=404, detail="订阅不存在")
    changes = payload.model_dump(exclude_unset=True)
    refresh_needed = False
    name = changes.get("name", current["name"])
    enabled = int(changes.get("enabled", bool(current["enabled"])))
    interval = changes.get(
        "refresh_interval_minutes", current["refresh_interval_minutes"]
    )
    encrypted = current["url_encrypted"]
    if changes.get("url"):
        url = _validate_http_url(changes["url"], "订阅地址")
        encrypted = SECRET_BOX.encrypt_text(url)
        refresh_needed = True
    if enabled and not current["enabled"]:
        refresh_needed = True
    DATABASE.execute(
        "UPDATE subscriptions SET name=?,url_encrypted=?,enabled=?,"
        "refresh_interval_minutes=?,next_refresh_at=?,updated_at=? WHERE id=?",
        (
            str(name).strip(),
            encrypted,
            enabled,
            interval,
            iso_now() if refresh_needed else current["next_refresh_at"],
            iso_now(),
            subscription_id,
        ),
    )
    task_id = (
        await app.state.engine.request_refresh(subscription_id, admin["username"])
        if refresh_needed
        else None
    )
    row = DATABASE.fetch_one(
        "SELECT * FROM subscriptions WHERE id=?", (subscription_id,)
    )
    return {"item": _safe_subscription(row), "task_id": task_id}


@app.delete("/api/subscriptions/{subscription_id}")
async def delete_subscription(
    subscription_id: int,
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    row = DATABASE.fetch_one(
        "SELECT id FROM subscriptions WHERE id=?", (subscription_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="订阅不存在")
    DATABASE.execute("DELETE FROM subscriptions WHERE id=?", (subscription_id,))
    return {"ok": True}


@app.post("/api/subscriptions/{subscription_id}/refresh")
async def refresh_subscription(
    subscription_id: int,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    try:
        task_id = await app.state.engine.request_refresh(
            subscription_id, admin["username"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"task_id": task_id}


@app.get("/api/nodes")
async def get_nodes(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=10, le=100),
    search: str = Query(default="", max_length=120),
    status_filter: str = Query(default="", alias="status", max_length=20),
    country: str = Query(default="", max_length=2),
    service: str = Query(default="", max_length=32),
    sort: str = Query(default="status", max_length=20),
    direction: str = Query(default="asc", pattern="^(asc|desc)$"),
    enabled_only: bool = Query(default=False),
):
    return node_page(
        DATABASE,
        page=page,
        page_size=page_size,
        search=search,
        status=status_filter,
        country=country,
        service=service,
        sort=sort,
        direction=direction,
        enabled_only=enabled_only,
    )


@app.put("/api/nodes/enabled-batch")
async def set_nodes_enabled_batch(
    payload: NodeBatchEnableRequest,
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    node_ids = tuple(dict.fromkeys(payload.node_ids))
    if any(node_id <= 0 for node_id in node_ids):
        raise HTTPException(status_code=422, detail="节点编号无效")
    placeholders = ",".join("?" for _ in node_ids)
    target_value = int(payload.enabled)
    checked_at = iso_now()
    with DATABASE.transaction() as connection:
        rows = connection.execute(
            f"SELECT id FROM nodes WHERE source_present=1 AND id IN ({placeholders})",
            node_ids,
        ).fetchall()
        if len(rows) != len(node_ids):
            raise HTTPException(
                status_code=409, detail="部分节点已发生变化，请刷新列表后重试"
            )
        cursor = connection.execute(
            "UPDATE nodes SET enabled=?,next_check_at=?,circuit_open_until=NULL,"
            f"updated_at=? WHERE id IN ({placeholders}) AND enabled<>?",
            (
                target_value,
                checked_at if payload.enabled else None,
                checked_at,
                *node_ids,
                target_value,
            ),
        )
    return {
        "ok": True,
        "enabled": payload.enabled,
        "matched": len(node_ids),
        "updated": cursor.rowcount,
    }


@app.get("/api/nodes/{node_id}")
async def get_node(
    node_id: int,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    result = node_detail(DATABASE, node_id)
    if not result:
        raise HTTPException(status_code=404, detail="节点不存在")
    return result


@app.get("/api/nodes/{node_id}/trend")
async def get_node_trend(
    node_id: int,
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    days: int = Query(default=7, ge=1, le=30),
):
    row = DATABASE.fetch_one(
        "SELECT id FROM nodes WHERE id=? AND source_present=1", (node_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="节点不存在")
    return {"node_id": node_id, "days": days, "points": node_trend(DATABASE, node_id, days)}


@app.put("/api/nodes/{node_id}/enabled")
async def set_node_enabled(
    node_id: int,
    payload: NodeEnableRequest,
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    row = DATABASE.fetch_one(
        "SELECT id FROM nodes WHERE id=? AND source_present=1", (node_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="节点不存在")
    DATABASE.execute(
        "UPDATE nodes SET enabled=?,next_check_at=?,circuit_open_until=NULL,"
        "updated_at=? WHERE id=?",
        (int(payload.enabled), iso_now() if payload.enabled else None, iso_now(), node_id),
    )
    return {"ok": True, "enabled": payload.enabled}


@app.put("/api/nodes/{node_id}/region")
async def set_node_region(
    node_id: int,
    payload: NodeRegionRequest,
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    row = DATABASE.fetch_one(
        "SELECT id FROM nodes WHERE id=? AND source_present=1", (node_id,)
    )
    if not row:
        raise HTTPException(status_code=404, detail="节点不存在")
    country_code = normalize_country_code(payload.country_code)
    if country_code != payload.country_code.strip().upper():
        raise HTTPException(status_code=422, detail="不支持的国家或地区代码")
    DATABASE.execute(
        "UPDATE nodes SET country_code=?,region_name=?,location_source='manual',"
        "location_checked_at=?,location_provider_count=0,exit_ip_mask=NULL,"
        "updated_at=? WHERE id=?",
        (
            country_code,
            COUNTRIES[country_code],
            iso_now(),
            iso_now(),
            node_id,
        ),
    )
    return {
        "ok": True,
        "country_code": country_code,
        "region_name": COUNTRIES[country_code],
    }


@app.post("/api/nodes/{node_id}/locate")
async def locate_node(
    node_id: int,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    try:
        task_id = await app.state.engine.locate_node(
            node_id, admin["username"]
        )
    except ValueError as exc:
        status_code = 404 if "不存在" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"task_id": task_id}


@app.post("/api/nodes/{node_id}/check")
async def check_single_node(
    node_id: int,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    try:
        task_id = await app.state.engine.check_node(node_id, admin["username"])
    except ValueError as exc:
        status_code = 404 if "不存在" in str(exc) else 422
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    return {"task_id": task_id}


@app.post("/api/tasks/check-all")
async def check_all_nodes(
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    try:
        task_id = await app.state.engine.check_all(admin["username"])
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task_id": task_id}


@app.post("/api/tasks/check-batch")
async def check_batch_nodes(
    payload: BatchCheckRequest,
    admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    try:
        task_id = await app.state.engine.check_nodes(
            payload.node_ids, admin["username"]
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"task_id": task_id}


@app.get("/api/tasks")
async def get_tasks(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    rows = DATABASE.fetch_all(
        "SELECT id,kind,status,total,completed,succeeded,failed,created_at,"
        "started_at,finished_at,requested_by,message FROM tasks "
        "ORDER BY created_at DESC LIMIT 100"
    )
    return {"items": rows}


@app.get("/api/events")
async def get_events(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
    limit: int = Query(default=100, ge=1, le=500),
):
    return {"items": list_events(DATABASE, limit)}


@app.get("/api/settings")
async def get_settings(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    return DATABASE.get_settings()


@app.put("/api/settings")
async def put_settings(
    payload: SettingsUpdate,
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    changes = payload.model_dump(exclude_none=True)
    previous = DATABASE.get_settings()
    try:
        updated = DATABASE.update_settings(changes)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    interval_shortened = (
        (
            "check_interval_minutes" in changes
            and int(updated["check_interval_minutes"])
            < int(previous["check_interval_minutes"])
        )
        or (
            "offline_check_interval_minutes" in changes
            and int(updated["offline_check_interval_minutes"])
            < int(previous["offline_check_interval_minutes"])
        )
    )
    scheduler_resumed = (
        changes.get("scheduler_paused") is False
        and bool(previous["scheduler_paused"])
    )
    targets_changed = (
        "enabled_targets" in changes
        and updated["enabled_targets"] != previous["enabled_targets"]
    )
    probe_changed = (
        "node_probe_enabled" in changes
        and updated["node_probe_enabled"] != previous["node_probe_enabled"]
    )
    if interval_shortened or scheduler_resumed or targets_changed or probe_changed:
        DATABASE.reschedule_enabled_nodes()
    return updated


@app.get("/api/system")
async def get_system(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    result = system_status(DATABASE, STORAGE)
    result["engine"] = {
        "active_checks": app.state.engine.active_checks,
        "queue_depth": app.state.engine.queue.qsize(),
        "refreshing_subscriptions": len(
            app.state.engine.refreshing_subscriptions
        ),
        "observer_status": app.state.engine.observer_status,
        "observer_interface": app.state.engine.observer_interface,
        "observer_reason": app.state.engine.observer_reason,
        "sing_box_version": "1.13.14",
        "app_version": __version__,
    }
    result["hardware"] = CONFIG.hardware_profile
    return result


@app.post("/api/system/maintenance")
async def run_maintenance(
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    snapshot = await asyncio.to_thread(STORAGE.snapshot)
    result = await asyncio.to_thread(
        DATABASE.maintenance,
        reason="manual",
        aggressive=snapshot.pressure in {"warning", "critical"},
    )
    result["logs"] = await asyncio.to_thread(STORAGE.enforce_log_cap)
    result["storage"] = (await asyncio.to_thread(STORAGE.snapshot)).as_dict()
    return result


@app.get("/api/notifications")
async def get_notifications(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    row = DATABASE.fetch_one("SELECT * FROM notification_config WHERE id=1")
    return {
        "enabled": bool(row["enabled"]),
        "endpoint_configured": bool(row["endpoint_encrypted"]),
        "event_types": json.loads(row["event_types_json"]),
        "cooldown_minutes": row["cooldown_minutes"],
    }


@app.put("/api/notifications")
async def put_notifications(
    payload: NotificationUpdate,
    _admin: Annotated[dict[str, Any], Depends(require_csrf)],
):
    current = DATABASE.fetch_one(
        "SELECT endpoint_encrypted FROM notification_config WHERE id=1"
    )
    endpoint_encrypted = current["endpoint_encrypted"] if current else None
    if payload.clear_endpoint:
        endpoint_encrypted = None
    elif payload.endpoint:
        endpoint = _validate_http_url(payload.endpoint, "通知端点")
        endpoint_encrypted = SECRET_BOX.encrypt_text(endpoint)
    if payload.enabled and not endpoint_encrypted:
        raise HTTPException(status_code=422, detail="启用通知前需要配置通知端点")
    DATABASE.execute(
        "UPDATE notification_config SET enabled=?,endpoint_encrypted=?,"
        "event_types_json=?,cooldown_minutes=?,updated_at=? WHERE id=1",
        (
            int(payload.enabled),
            endpoint_encrypted,
            json.dumps(payload.event_types, separators=(",", ":")),
            payload.cooldown_minutes,
            iso_now(),
        ),
    )
    return await get_notifications(_admin)


@app.get("/api/export/nodes.csv")
async def export_nodes(
    _admin: Annotated[dict[str, Any], Depends(require_admin)],
):
    content = DATABASE.safe_export_csv()
    return Response(
        content=content,
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": 'attachment; filename="airport-monitor-nodes.csv"'
        },
    )


STATIC_DIR = CONFIG.static_dir
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/favicon.svg", include_in_schema=False)
async def favicon():
    return FileResponse(STATIC_DIR / "favicon.svg", media_type="image/svg+xml")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon_ico():
    return FileResponse(STATIC_DIR / "favicon.ico", media_type="image/x-icon")


@app.get("/{path:path}", include_in_schema=False)
async def frontend(path: str):
    if path.startswith("api/"):
        raise HTTPException(status_code=404, detail="接口不存在")
    return FileResponse(
        STATIC_DIR / "index.html",
        media_type="text/html",
        headers={"Cache-Control": "no-store"},
    )


def run() -> None:
    uvicorn.run(
        app,
        host=CONFIG.bind_host,
        port=CONFIG.port,
        access_log=False,
        server_header=False,
        date_header=True,
        workers=1,
        timeout_keep_alive=10,
        limit_concurrency=100,
        backlog=128,
    )


if __name__ == "__main__":
    run()
