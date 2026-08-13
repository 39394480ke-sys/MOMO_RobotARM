"""Victory 手势触发 Camera Hub 拍照。"""

from __future__ import annotations

import json
import queue
import threading
import time
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any


SnapshotClient = Callable[[], dict[str, Any]]
_STOP_JOB = object()
_CAPTURE_JOB = object()


class VictorySnapshotController:
    """单次触发、冷却并要求手势释放后才重新上膛。"""

    def __init__(
        self,
        config: Mapping[str, Any] | None = None,
        *,
        snapshot_client: SnapshotClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        cfg = dict(config or {})
        self.enabled = bool(cfg.get("enabled", False))
        self.target_gesture = str(cfg.get("gesture", "Victory")).strip() or "Victory"
        self.camera_hub_url = str(cfg.get("camera_hub_url", "http://127.0.0.1:8020")).rstrip("/")
        self.cooldown_sec = max(0.0, float(cfg.get("cooldown_sec", 5.0)))
        self.timeout_sec = max(0.2, float(cfg.get("timeout_sec", 8.0)))
        self.stop_timeout_sec = max(0.05, float(cfg.get("stop_timeout_sec", self.timeout_sec + 0.5)))
        self._clock = clock
        self._snapshot_client = snapshot_client or self._post_snapshot
        self._lock = threading.RLock()

        self._jobs: queue.Queue[object] = queue.Queue(maxsize=1)
        self._stop_event = threading.Event()
        self._stop_event.set()
        self._worker: threading.Thread | None = None
        self._generation = 0
        self._running = False
        self._accepting = False
        self._closed = False
        self._job_executing = False
        self._lifecycle_error = ""

        self._armed = self.enabled
        self._latched = False
        self._release_observed = False
        self._in_flight = False
        self._cooldown_until = 0.0
        self._trigger_count = 0
        self._success_count = 0
        self._last_triggered_at = 0.0
        self._last_completed_at = 0.0
        self._last_snapshot: dict[str, Any] | None = None
        self._last_error = ""
        if self.enabled:
            self.start()

    def start(self) -> dict[str, Any]:
        with self._lock:
            now = self._clock()
            if not self.enabled:
                return self._status_locked(now)
            if self._closed:
                self._lifecycle_error = "Victory 拍照控制器已关闭，不能重新启动。"
                return self._status_locked(now)
            if self._worker is not None and self._worker.is_alive():
                if not self._running:
                    self._lifecycle_error = "上一个 Victory 拍照请求仍在停止中，已拒绝重新启动。"
                return self._status_locked(now)

            self._generation += 1
            generation = self._generation
            stop_event = threading.Event()
            jobs: queue.Queue[object] = queue.Queue(maxsize=1)
            worker = threading.Thread(
                target=self._worker_loop,
                args=(stop_event, jobs, generation),
                name="victory-snapshot",
                daemon=True,
            )
            self._stop_event = stop_event
            self._jobs = jobs
            self._worker = worker
            self._running = True
            self._accepting = True
            self._job_executing = False
            self._in_flight = False
            self._lifecycle_error = ""
            worker.start()
            return self._status_locked(now)

    def stop(self) -> dict[str, Any]:
        with self._lock:
            generation = self._generation
            stop_event = self._stop_event
            jobs = self._jobs
            worker = self._worker
            self._accepting = False
            self._running = False
            stop_event.set()
            canceled = self._drain_jobs_locked(jobs)
            if canceled and not self._job_executing:
                self._in_flight = False
                self._last_error = "Victory 拍照任务已在执行前取消。"
            try:
                jobs.put_nowait(_STOP_JOB)
            except queue.Full:
                pass

        if worker and worker.is_alive() and worker is not threading.current_thread():
            worker.join(timeout=self.stop_timeout_sec)

        with self._lock:
            worker_alive = bool(worker and worker.is_alive())
            if worker_alive and generation == self._generation:
                # urllib 的同步请求无法可靠地从另一线程取消。使该代结果失效，
                # 明确报告停止超时，且在旧 worker 退出前拒绝重启。
                self._generation += 1
                self._in_flight = False
                self._job_executing = False
                self._lifecycle_error = (
                    f"Victory 拍照请求在 {self.stop_timeout_sec:g}s 内未结束；"
                    "后台请求可能仍在收尾，完成前不允许重启。"
                )
            elif not worker_alive:
                if self._worker is worker:
                    self._worker = None
                self._job_executing = False
                self._in_flight = False
            return self._status_locked(self._clock())

    def close(self) -> None:
        with self._lock:
            self._closed = True
            self._accepting = False
        self.stop()

    def observe(self, gesture: Mapping[str, Any] | None) -> dict[str, Any]:
        data = dict(gesture or {})
        raw = str(data.get("raw") or "").strip()
        stable = str(data.get("stable") or "").strip()
        is_victory = raw == self.target_gesture and stable == self.target_gesture
        now = self._clock()
        with self._lock:
            if not self.enabled or self._closed or not self._running or not self._accepting:
                return self._status_locked(now)
            if self._latched and raw != self.target_gesture:
                self._release_observed = True
            if (
                self._latched
                and self._release_observed
                and not self._in_flight
                and now >= self._cooldown_until
            ):
                self._latched = False
                self._armed = True
            if is_victory and self._armed and not self._in_flight:
                self._armed = False
                self._latched = True
                self._release_observed = False
                self._in_flight = True
                self._trigger_count += 1
                self._last_triggered_at = now
                self._last_error = ""
                try:
                    self._jobs.put_nowait(_CAPTURE_JOB)
                except queue.Full:
                    self._complete_capture(
                        self._generation,
                        None,
                        RuntimeError("拍照任务队列忙。"),
                    )
            return self._status_locked(now)

    def status(self) -> dict[str, Any]:
        with self._lock:
            return self._status_locked(self._clock())

    def _worker_loop(
        self,
        stop_event: threading.Event,
        jobs: queue.Queue[object],
        generation: int,
    ) -> None:
        try:
            while not stop_event.is_set():
                try:
                    job = jobs.get(timeout=0.2)
                except queue.Empty:
                    continue
                try:
                    if job is _STOP_JOB or stop_event.is_set():
                        with self._lock:
                            if generation == self._generation and not self._job_executing:
                                self._in_flight = False
                        break
                    with self._lock:
                        if generation != self._generation or not self._accepting:
                            self._in_flight = False
                            continue
                        self._job_executing = True
                    try:
                        result = self._snapshot_client()
                    except Exception as exc:
                        self._complete_capture(generation, None, exc)
                    else:
                        self._complete_capture(generation, result, None)
                finally:
                    jobs.task_done()
        finally:
            with self._lock:
                if generation == self._generation:
                    self._running = False
                    self._accepting = False
                    self._job_executing = False
                    self._in_flight = False

    def _complete_capture(
        self,
        generation: int,
        result: dict[str, Any] | None,
        error: Exception | None,
    ) -> None:
        completed_at = self._clock()
        with self._lock:
            if generation != self._generation:
                return
            self._job_executing = False
            self._in_flight = False
            self._last_completed_at = completed_at
            self._cooldown_until = completed_at + self.cooldown_sec
            if error is None:
                self._success_count += 1
                self._last_snapshot = dict(result or {})
                self._last_error = ""
            else:
                self._last_snapshot = None
                self._last_error = str(error)

    @staticmethod
    def _drain_jobs_locked(jobs: queue.Queue[object]) -> int:
        canceled = 0
        while True:
            try:
                job = jobs.get_nowait()
            except queue.Empty:
                return canceled
            else:
                if job is _CAPTURE_JOB:
                    canceled += 1
                jobs.task_done()

    def _post_snapshot(self) -> dict[str, Any]:
        request = urllib.request.Request(
            f"{self.camera_hub_url}/api/v1/snapshots",
            data=b"",
            headers={"Accept": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=self.timeout_sec) as response:
            payload = json.load(response)
        if not isinstance(payload, dict):
            raise RuntimeError("Camera Hub 拍照接口返回格式不正确。")
        return payload

    def _status_locked(self, now: float) -> dict[str, Any]:
        worker_alive = bool(self._worker and self._worker.is_alive())
        accepting = bool(self.enabled and self._running and self._accepting and not self._closed)
        return {
            "enabled": self.enabled,
            "gesture": self.target_gesture,
            "running": bool(self._running),
            "accepting": accepting,
            "closed": bool(self._closed),
            "worker_alive": worker_alive,
            "stop_pending": bool(worker_alive and not self._running),
            "armed": bool(self._armed and accepting),
            "in_flight": bool(self._in_flight),
            "release_required": bool(self._latched and not self._release_observed),
            "release_observed": bool(self._release_observed),
            "cooldown_sec": self.cooldown_sec,
            "cooldown_remaining_sec": round(max(0.0, self._cooldown_until - now), 3),
            "trigger_count": self._trigger_count,
            "success_count": self._success_count,
            "last_triggered_at": self._last_triggered_at or None,
            "last_completed_at": self._last_completed_at or None,
            "last_snapshot": dict(self._last_snapshot) if self._last_snapshot is not None else None,
            "last_error": self._lifecycle_error or self._last_error,
            "capture_error": self._last_error,
            "lifecycle_error": self._lifecycle_error,
        }
