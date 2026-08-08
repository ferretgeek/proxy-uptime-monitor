from __future__ import annotations

import asyncio
import json
import logging
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import psutil

from .connectivity import ObserverLinkState, observer_link_state
from .database import Database, iso_now, parse_time, utc_now
from .executor import NodeExecutor
from .locations import infer_location
from .security import SecretBox, sanitize_exception
from .storage import StorageManager
from .subscriptions import (
    SubscriptionError,
    fetch_subscription,
    parse_subscription_content,
)
from .telemetry import normalized_system_cpu_percent, read_hardware_temperatures


LOGGER = logging.getLogger("airport_monitor.engine")
MAX_QUEUE_DEPTH = 512
MAX_BATCH_NODES = 500


@dataclass(frozen=True)
class CheckJob:
    task_id: str
    node_id: int
    manual: bool
    force_location: bool = False


class MonitorEngine:
    def __init__(
        self,
        database: Database,
        secret_box: SecretBox,
        executor: NodeExecutor,
        session_pepper: str,
        storage: StorageManager,
    ):
        self.database = database
        self.secret_box = secret_box
        self.executor = executor
        self.session_pepper = session_pepper
        self.storage = storage
        self.queue: asyncio.Queue[CheckJob] = asyncio.Queue(maxsize=MAX_QUEUE_DEPTH)
        self.queued_nodes: set[int] = set()
        self.refreshing_subscriptions: set[int] = set()
        self.active_checks = 0
        self._concurrency_condition = asyncio.Condition()
        self._background: list[asyncio.Task[Any]] = []
        self._running = False
        self._process = psutil.Process()
        self._last_maintenance: datetime | None = None
        self._notification_sent: dict[tuple[int, str], datetime] = {}
        self.observer_status = "unknown"
        self.observer_interface: str | None = None
        self.observer_reason = "starting"

    async def start(self) -> None:
        if self._running:
            return
        if not self.executor.sing_box_path.is_file():
            raise RuntimeError("sing-box 执行器不存在")
        self._running = True
        await self._sample_observer_link(initial=True)
        for index in range(8):
            self._background.append(
                asyncio.create_task(self._worker(index), name=f"probe-worker-{index}")
            )
        self._background.extend(
            (
                asyncio.create_task(self._scheduler_loop(), name="scheduler"),
                asyncio.create_task(self._metrics_loop(), name="metrics"),
                asyncio.create_task(self._observer_loop(), name="observer-link"),
            )
        )
        LOGGER.info("监测引擎已启动")

    async def stop(self) -> None:
        self._running = False
        for task in self._background:
            task.cancel()
        if self._background:
            await asyncio.gather(*self._background, return_exceptions=True)
        self._background.clear()
        LOGGER.info("监测引擎已安全停止")

    async def _sample_observer_link(self, *, initial: bool = False) -> None:
        state: ObserverLinkState = await asyncio.to_thread(observer_link_state)
        previous = self.observer_status
        if initial:
            previous_row = self.database.fetch_one(
                "SELECT status FROM observer_samples "
                "ORDER BY sampled_at DESC LIMIT 1"
            )
            previous = (
                str(previous_row["status"])
                if previous_row
                else "unknown"
            )
        self.database.record_observer_sample(
            state.status,
            state.interface,
            state.reason,
        )
        self.observer_status = state.status
        self.observer_interface = state.interface
        self.observer_reason = state.reason
        if state.status == "online" and previous != "online":
            changed = self.database.reschedule_enabled_nodes(
                clear_circuit=True
            )
            self.database.execute(
                "INSERT INTO events(event_type,severity,title,detail,created_at) "
                "VALUES ('observer_recovery','success','监测网络已恢复',?,?)",
                (
                    f"已立即恢复 {changed} 个节点的自动检测",
                    iso_now(),
                ),
            )
            LOGGER.info("监测网络已恢复，%s 个节点已提前复测", changed)
        elif state.status == "offline" and previous == "online":
            self.database.execute(
                "INSERT INTO events(event_type,severity,title,detail,created_at) "
                "VALUES ('observer_failure','warning','监测网络不可用',?,?)",
                (
                    "节点归责检测已暂停，网络恢复后会立即全量复测",
                    iso_now(),
                ),
            )
            LOGGER.warning("监测网络不可用：%s", state.reason)

    async def _observer_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(30)
                await self._sample_observer_link()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.observer_status = "unknown"
                self.observer_reason = "observer_probe_error"
                LOGGER.error(
                    "监测机网络状态检测失败：%s",
                    sanitize_exception(exc),
                )

    def _create_task(
        self, kind: str, total: int, requested_by: str, message: str | None = None
    ) -> str:
        task_id = str(uuid.uuid4())
        now = iso_now()
        status = "queued" if total else "completed"
        self.database.execute(
            "INSERT INTO tasks(id,kind,status,total,completed,succeeded,failed,"
            "created_at,started_at,finished_at,requested_by,message)"
            " VALUES (?,?,?,?,0,0,0,?,?,?,?,?)",
            (
                task_id,
                kind,
                status,
                total,
                now,
                now if total else None,
                now if not total else None,
                requested_by,
                message,
            ),
        )
        return task_id

    async def enqueue_nodes(
        self,
        node_ids: list[int],
        *,
        kind: str,
        requested_by: str,
        manual: bool,
        force_location: bool = False,
    ) -> str:
        unique = []
        seen: set[int] = set()
        for node_id in node_ids:
            if node_id not in seen and node_id not in self.queued_nodes:
                unique.append(node_id)
                seen.add(node_id)
        if len(unique) > MAX_BATCH_NODES:
            raise ValueError(f"单次最多提交 {MAX_BATCH_NODES} 个节点")
        available_slots = self.queue.maxsize - self.queue.qsize()
        if len(unique) > available_slots:
            raise ValueError("检测队列繁忙，请等待当前任务完成后重试")
        task_id = self._create_task(
            kind,
            len(unique),
            requested_by,
            None if unique else "没有可排队的节点",
        )
        for node_id in unique:
            self.queued_nodes.add(node_id)
            await self.queue.put(
                CheckJob(task_id, node_id, manual, force_location)
            )
        return task_id

    async def check_node(self, node_id: int, requested_by: str = "admin") -> str:
        row = self.database.fetch_one(
            "SELECT id FROM nodes WHERE id=? AND source_present=1", (node_id,)
        )
        if not row:
            raise ValueError("节点不存在或已从订阅移除")
        return await self.enqueue_nodes(
            [node_id],
            kind="single_check",
            requested_by=requested_by,
            manual=True,
        )

    async def locate_node(
        self, node_id: int, requested_by: str = "admin"
    ) -> str:
        row = self.database.fetch_one(
            "SELECT id FROM nodes WHERE id=? AND source_present=1", (node_id,)
        )
        if not row:
            raise ValueError("节点不存在或已从订阅移除")
        return await self.enqueue_nodes(
            [node_id],
            kind="location_check",
            requested_by=requested_by,
            manual=True,
            force_location=True,
        )

    async def check_all(self, requested_by: str = "admin") -> str:
        rows = self.database.fetch_all(
            "SELECT id FROM nodes WHERE enabled=1 AND source_present=1 ORDER BY id"
        )
        return await self.enqueue_nodes(
            [int(row["id"]) for row in rows],
            kind="full_check",
            requested_by=requested_by,
            manual=True,
        )

    async def check_nodes(
        self,
        node_ids: list[int],
        requested_by: str = "admin",
    ) -> str:
        if not node_ids:
            raise ValueError("请至少选择一个节点")
        placeholders = ",".join("?" for _ in node_ids)
        rows = self.database.fetch_all(
            f"SELECT id FROM nodes WHERE id IN ({placeholders}) "
            "AND source_present=1 AND enabled=1 ORDER BY id",
            tuple(node_ids),
        )
        valid_ids = [int(row["id"]) for row in rows]
        if not valid_ids:
            raise ValueError("所选节点不存在或已停用")
        return await self.enqueue_nodes(
            valid_ids,
            kind="batch_check",
            requested_by=requested_by,
            manual=True,
        )

    async def request_refresh(
        self, subscription_id: int, requested_by: str = "admin"
    ) -> str:
        row = self.database.fetch_one(
            "SELECT id FROM subscriptions WHERE id=?", (subscription_id,)
        )
        if not row:
            raise ValueError("订阅不存在")
        task_id = self._create_task("subscription_refresh", 1, requested_by)
        asyncio.create_task(
            self.refresh_subscription(subscription_id, task_id),
            name=f"subscription-refresh-{subscription_id}",
        )
        return task_id

    async def refresh_subscription(
        self, subscription_id: int, task_id: str | None = None
    ) -> None:
        if subscription_id in self.refreshing_subscriptions:
            if task_id:
                self._finish_task(task_id, False, "订阅刷新已在进行")
            return
        self.refreshing_subscriptions.add(subscription_id)
        try:
            row = self.database.fetch_one(
                "SELECT * FROM subscriptions WHERE id=?", (subscription_id,)
            )
            if not row:
                if task_id:
                    self._finish_task(task_id, False, "订阅不存在")
                return
            url = self.secret_box.decrypt_text(row["url_encrypted"])
            content = await fetch_subscription(url)
            candidates, warnings = parse_subscription_content(
                content, self.session_pepper
            )
            now = iso_now()
            next_refresh = (
                utc_now() + timedelta(minutes=int(row["refresh_interval_minutes"]))
            ).isoformat(timespec="seconds")
            with self.database.transaction() as connection:
                connection.execute(
                    "UPDATE nodes SET source_present=0 WHERE subscription_id=?",
                    (subscription_id,),
                )
                for candidate in candidates:
                    encrypted = self.secret_box.encrypt_json(candidate.outbound)
                    country_code, region_name = infer_location(
                        candidate.name, candidate.endpoint_mask
                    )
                    existing = connection.execute(
                        "SELECT id,country_code,region_name,location_source FROM nodes "
                        "WHERE subscription_id=? AND fingerprint=?",
                        (subscription_id, candidate.fingerprint),
                    ).fetchone()
                    if existing:
                        if existing["location_source"] in {"auto", "manual"}:
                            country_code = existing["country_code"]
                            region_name = existing["region_name"]
                            location_source = existing["location_source"]
                        else:
                            location_source = (
                                "name" if country_code != "ZZ" else "unknown"
                            )
                        connection.execute(
                            "UPDATE nodes SET name=?,protocol=?,endpoint_mask=?,"
                            "config_encrypted=?,country_code=?,region_name=?,"
                            "location_source=?,source_present=1,updated_at=? WHERE id=?",
                            (
                                candidate.name,
                                candidate.protocol,
                                candidate.endpoint_mask,
                                encrypted,
                                country_code,
                                region_name,
                                location_source,
                                now,
                                existing["id"],
                            ),
                        )
                    else:
                        due = (
                            utc_now() + timedelta(seconds=random.randint(5, 90))
                        ).isoformat(timespec="seconds")
                        connection.execute(
                            "INSERT INTO nodes("
                            "subscription_id,fingerprint,name,protocol,endpoint_mask,"
                            "config_encrypted,country_code,region_name,"
                            "location_source,"
                            "enabled,source_present,current_status,"
                            "health_score,next_check_at,created_at,updated_at"
                            ") VALUES (?,?,?,?,?,?,?,?,?,1,1,'pending',0,?,?,?)",
                            (
                                subscription_id,
                                candidate.fingerprint,
                                candidate.name,
                                candidate.protocol,
                                candidate.endpoint_mask,
                                encrypted,
                                country_code,
                                region_name,
                                "name" if country_code != "ZZ" else "unknown",
                                due,
                                now,
                                now,
                            ),
                        )
                connection.execute(
                    "UPDATE nodes SET enabled=0,current_status='removed',updated_at=? "
                    "WHERE subscription_id=? AND source_present=0",
                    (now, subscription_id),
                )
                count = connection.execute(
                    "SELECT COUNT(*) AS n FROM nodes WHERE subscription_id=? "
                    "AND source_present=1",
                    (subscription_id,),
                ).fetchone()["n"]
                connection.execute(
                    "UPDATE subscriptions SET last_refresh_at=?,next_refresh_at=?,"
                    "last_error_type=NULL,last_error_message=NULL,node_count=?,updated_at=? "
                    "WHERE id=?",
                    (now, next_refresh, count, now, subscription_id),
                )
                connection.execute(
                    "INSERT INTO events(subscription_id,event_type,severity,title,detail,"
                    "created_at) VALUES (?, 'subscription_refresh', 'info', "
                    "'订阅刷新完成', ?, ?)",
                    (
                        subscription_id,
                        f"已同步 {count} 个节点"
                        + (f"，跳过 {len(warnings)} 项" if warnings else ""),
                        now,
                    ),
                )
            if task_id:
                self._finish_task(
                    task_id,
                    True,
                    f"已同步 {len(candidates)} 个节点"
                    + (f"，有 {len(warnings)} 条兼容性提示" if warnings else ""),
                )
        except SubscriptionError as exc:
            self._record_refresh_error(
                subscription_id, exc.error_type, exc.safe_message, task_id
            )
        except Exception as exc:
            LOGGER.error("订阅刷新出现内部错误：%s", sanitize_exception(exc))
            self._record_refresh_error(
                subscription_id, "internal_error", "订阅刷新出现内部错误", task_id
            )
        finally:
            self.refreshing_subscriptions.discard(subscription_id)

    def _record_refresh_error(
        self,
        subscription_id: int,
        error_type: str,
        message: str,
        task_id: str | None,
    ) -> None:
        now = iso_now()
        retry_at = (utc_now() + timedelta(minutes=15)).isoformat(timespec="seconds")
        with self.database.transaction() as connection:
            connection.execute(
                "UPDATE subscriptions SET last_error_type=?,last_error_message=?,"
                "next_refresh_at=?,updated_at=? WHERE id=?",
                (error_type, message[:200], retry_at, now, subscription_id),
            )
            connection.execute(
                "INSERT INTO events(subscription_id,event_type,severity,title,detail,"
                "created_at) VALUES (?, 'subscription_error', 'warning',"
                "'订阅刷新失败', ?, ?)",
                (subscription_id, message[:200], now),
            )
        if task_id:
            self._finish_task(task_id, False, message)

    def _finish_task(self, task_id: str, succeeded: bool, message: str) -> None:
        now = iso_now()
        self.database.execute(
            "UPDATE tasks SET status='completed',completed=total,succeeded=?,failed=?,"
            "finished_at=?,message=? WHERE id=?",
            (int(succeeded), int(not succeeded), now, message[:300], task_id),
        )

    async def _worker(self, _index: int) -> None:
        while self._running:
            job = await self.queue.get()
            try:
                async with self._concurrency_condition:
                    while self.active_checks >= int(
                        self.database.get_settings()["max_concurrency"]
                    ):
                        await self._concurrency_condition.wait()
                    self.active_checks += 1
                await self._run_job(job)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("节点检测任务出现内部错误：%s", sanitize_exception(exc))
                self._advance_task(job.task_id, False, "节点检测内部错误")
            finally:
                self.queued_nodes.discard(job.node_id)
                async with self._concurrency_condition:
                    self.active_checks = max(0, self.active_checks - 1)
                    self._concurrency_condition.notify_all()
                self.queue.task_done()

    async def _run_job(self, job: CheckJob) -> None:
        node = self.database.fetch_one(
            "SELECT * FROM nodes WHERE id=?", (job.node_id,)
        )
        if not node or not node["source_present"]:
            self._advance_task(job.task_id, False, "节点已不存在")
            return
        if not job.manual and not node["enabled"]:
            self._advance_task(job.task_id, False, "节点已停用")
            return
        settings = self.database.get_settings()
        previous_status = node["current_status"]
        outbound = self.secret_box.decrypt_json(node["config_encrypted"])
        location_checked = parse_time(node.get("location_checked_at"))
        resolve_location = (
            job.force_location
            or (
                node.get("location_source") != "manual"
                and (
                    location_checked is None
                    or utc_now() - location_checked > timedelta(hours=12)
                )
            )
        )
        result = await self.executor.check_node(
            outbound,
            int(settings["timeout_seconds"]),
            int(settings["retry_count"]),
            list(settings["enabled_targets"]),
            resolve_location=resolve_location,
            node_probe_enabled=bool(settings["node_probe_enabled"]),
        )
        jitter = random.randint(0, int(settings["jitter_seconds"]))
        interval_key = (
            "offline_check_interval_minutes"
            if result["status"] == "offline"
            else "check_interval_minutes"
        )
        next_check = (
            utc_now()
            + timedelta(
                minutes=int(settings[interval_key]),
                seconds=jitter,
            )
        ).isoformat(timespec="seconds")
        self.database.record_check(
            job.task_id,
            job.node_id,
            result,
            next_check,
        )
        succeeded = result["status"] in {"online", "degraded"}
        self._advance_task(
            job.task_id,
            succeeded,
            None if succeeded else result.get("error_type") or "检测未通过",
        )
        if (
            previous_status in {"online", "degraded"}
            and result["status"] == "offline"
        ):
            await self._send_notification(job.node_id, "failure", node["name"])
        elif (
            previous_status not in {"online", "degraded", "pending"}
            and succeeded
        ):
            await self._send_notification(job.node_id, "recovery", node["name"])

    def _advance_task(
        self, task_id: str, succeeded: bool, message: str | None = None
    ) -> None:
        now = iso_now()
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT total,completed FROM tasks WHERE id=?", (task_id,)
            ).fetchone()
            if not row:
                return
            completed = int(row["completed"]) + 1
            final = completed >= int(row["total"])
            connection.execute(
                "UPDATE tasks SET completed=?,succeeded=succeeded+?,failed=failed+?,"
                "status=?,finished_at=?,message=COALESCE(?,message) WHERE id=?",
                (
                    completed,
                    int(succeeded),
                    int(not succeeded),
                    "completed" if final else "running",
                    now if final else None,
                    message[:300] if message else None,
                    task_id,
                ),
            )

    async def _scheduler_loop(self) -> None:
        while self._running:
            try:
                settings = self.database.get_settings()
                if (
                    not settings["scheduler_paused"]
                    and self.observer_status == "online"
                ):
                    await self._schedule_due_subscriptions()
                    await self._schedule_due_nodes(settings)
                if (
                    self._last_maintenance is None
                    or utc_now() - self._last_maintenance > timedelta(hours=6)
                ):
                    snapshot = await asyncio.to_thread(self.storage.snapshot)
                    await asyncio.to_thread(
                        self.database.maintenance,
                        reason=f"storage_{snapshot.pressure}",
                        aggressive=snapshot.pressure in {"warning", "critical"},
                    )
                    await asyncio.to_thread(self.storage.enforce_log_cap)
                    self._last_maintenance = utc_now()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.error("调度循环错误：%s", sanitize_exception(exc))
            await asyncio.sleep(15)

    async def _schedule_due_subscriptions(self) -> None:
        rows = self.database.fetch_all(
            "SELECT id FROM subscriptions WHERE enabled=1 AND "
            "(next_refresh_at IS NULL OR next_refresh_at<=?) LIMIT 5",
            (iso_now(),),
        )
        for row in rows:
            subscription_id = int(row["id"])
            if subscription_id in self.refreshing_subscriptions:
                continue
            task_id = self._create_task("scheduled_refresh", 1, "scheduler")
            asyncio.create_task(
                self.refresh_subscription(subscription_id, task_id),
                name=f"scheduled-refresh-{subscription_id}",
            )

    async def _schedule_due_nodes(self, settings: dict[str, Any]) -> None:
        limit = max(4, int(settings["max_concurrency"]) * 4)
        rows = self.database.fetch_all(
            "SELECT id FROM nodes WHERE enabled=1 AND source_present=1 "
            "AND (next_check_at IS NULL OR next_check_at<=?) "
            "ORDER BY COALESCE(next_check_at,'') LIMIT ?",
            (iso_now(), limit),
        )
        ids = [
            int(row["id"])
            for row in rows
            if int(row["id"]) not in self.queued_nodes
        ]
        if ids:
            await self.enqueue_nodes(
                ids,
                kind="scheduled_check",
                requested_by="scheduler",
                manual=False,
            )

    async def _metrics_loop(self) -> None:
        self._process.cpu_percent(None)
        psutil.cpu_percent(interval=None, percpu=False)
        while self._running:
            try:
                memory = psutil.virtual_memory()
                disk = psutil.disk_usage("/")
                snapshot, temperatures = await asyncio.gather(
                    asyncio.to_thread(self.storage.snapshot),
                    asyncio.to_thread(
                        read_hardware_temperatures,
                        self.storage.config.runtime_dir,
                    ),
                )
                cpu_temperature, disk_temperature = temperatures
                system_cpu = normalized_system_cpu_percent(
                    psutil.cpu_percent(interval=None, percpu=False)
                )
                if snapshot.pressure != "critical":
                    self.database.execute(
                        "INSERT OR REPLACE INTO system_metrics("
                        "sampled_at,system_cpu_percent,system_memory_percent,"
                        "system_memory_used_mb,disk_percent,disk_free_gb,"
                        "process_cpu_percent,process_memory_mb,active_checks,queue_depth,"
                        "cpu_temperature_c,disk_temperature_c"
                        ") VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            iso_now(),
                            system_cpu,
                            memory.percent,
                            round(memory.used / 1024 / 1024, 2),
                            disk.percent,
                            round(disk.free / 1024 / 1024 / 1024, 2),
                            self._process.cpu_percent(None),
                            round(
                                self._process.memory_info().rss / 1024 / 1024, 2
                            ),
                            self.active_checks,
                            self.queue.qsize(),
                            cpu_temperature,
                            disk_temperature,
                        ),
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                LOGGER.warning("资源指标采集失败：%s", sanitize_exception(exc))
            await asyncio.sleep(60)

    async def _send_notification(
        self, node_id: int, event_type: str, node_name: str
    ) -> None:
        config = self.database.fetch_one(
            "SELECT * FROM notification_config WHERE id=1"
        )
        if not config or not config["enabled"] or not config["endpoint_encrypted"]:
            return
        try:
            event_types = json.loads(config["event_types_json"])
        except json.JSONDecodeError:
            return
        if event_type not in event_types:
            return
        key = (node_id, event_type)
        last = self._notification_sent.get(key)
        cooldown = timedelta(minutes=int(config["cooldown_minutes"]))
        if last and utc_now() - last < cooldown:
            return
        endpoint = self.secret_box.decrypt_text(config["endpoint_encrypted"])
        payload = {
            "event": event_type,
            "title": "节点异常" if event_type == "failure" else "节点恢复",
            "node": node_name,
            "time": iso_now(),
            "source": "航迹监测平台",
        }
        try:
            async with httpx.AsyncClient(
                timeout=5, follow_redirects=False, trust_env=False
            ) as client:
                response = await client.post(endpoint, json=payload)
                if 200 <= response.status_code < 300:
                    self._notification_sent[key] = utc_now()
        except httpx.HTTPError:
            LOGGER.warning("通知发送失败，端点信息已隐藏")
