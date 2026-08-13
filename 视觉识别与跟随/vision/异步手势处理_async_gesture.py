"""固定频率、单槽最新帧的异步手势处理。"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Mapping
from typing import Any


class AsyncGestureProcessor:
    """让耗时的手势推理不阻塞实时人脸跟随结果发布。"""

    def __init__(
        self,
        detector: Any,
        config: Mapping[str, Any] | None = None,
        *,
        clock: Callable[[], float] = time.time,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        cfg = dict(config or {})
        self.detector = detector
        self.enabled = bool(cfg.get("enabled", True)) and bool(cfg.get("async_enabled", True))
        self.process_hz = max(0.2, float(cfg.get("process_hz", 5.0)))
        self.process_interval_sec = 1.0 / self.process_hz
        self.stale_timeout_sec = max(
            self.process_interval_sec,
            float(cfg.get("stale_timeout_sec", max(0.5, 2.5 * self.process_interval_sec))),
        )
        self.join_timeout_sec = max(0.1, float(cfg.get("worker_join_timeout_sec", 2.0)))
        self._clock = clock
        self._monotonic = monotonic

        self._condition = threading.Condition(threading.RLock())
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._stop_event.set()
        self._generation = 0
        self._running = False
        self._accepting = False
        self._next_submit_at = 0.0
        self._pending: tuple[Any, Any, float | None] | None = None
        self._latest_sample: dict[str, Any] | None = None
        self._sample_id = 0
        self._last_consumed_sample_id = 0
        self._submitted_frames = 0
        self._overwritten_frames = 0
        self._last_error = ""

    def start(self) -> dict[str, Any]:
        with self._condition:
            if not self.enabled:
                return self._status_locked()
            if self._thread is not None and self._thread.is_alive():
                if not self._running:
                    self._last_error = "上一轮手势识别线程尚未退出，已拒绝重新启动。"
                return self._status_locked()

            self._generation += 1
            generation = self._generation
            stop_event = threading.Event()
            thread = threading.Thread(
                target=self._worker_loop,
                args=(stop_event, generation),
                name="gesture-latest-frame",
                daemon=True,
            )
            self._stop_event = stop_event
            self._thread = thread
            self._running = True
            self._accepting = True
            self._next_submit_at = 0.0
            self._pending = None
            self._latest_sample = None
            self._last_consumed_sample_id = self._sample_id
            self._last_error = ""
            thread.start()
            return self._status_locked()

    def stop(self) -> dict[str, Any]:
        with self._condition:
            stop_event = self._stop_event
            thread = self._thread
            self._running = False
            self._accepting = False
            self._pending = None
            stop_event.set()
            self._condition.notify_all()

        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=self.join_timeout_sec)

        with self._condition:
            if thread and thread.is_alive():
                self._last_error = (
                    f"手势识别在 {self.join_timeout_sec:g}s 内未结束；"
                    "旧线程退出前不允许重启。"
                )
            elif self._thread is thread:
                self._thread = None
            self._pending = None
            return self._status_locked()

    def submit(
        self,
        frame: Any,
        *,
        source_frame_id: Any,
        frame_received_at: float | None,
    ) -> bool:
        """按固定 cadence 覆盖投递最新帧，不补跑错过的周期。"""

        now = self._monotonic()
        with self._condition:
            if not self.enabled or not self._running or not self._accepting or frame is None:
                return False
            if now < self._next_submit_at:
                return False
            self._next_submit_at = now + self.process_interval_sec
            if self._pending is not None:
                self._overwritten_frames += 1
            copied = frame.copy() if hasattr(frame, "copy") else frame
            self._pending = (copied, source_frame_id, frame_received_at)
            self._submitted_frames += 1
            self._condition.notify()
            return True

    def consume(self) -> tuple[dict[str, Any], bool, bool]:
        """返回手势、新样本标记、以及是否可安全推进 Victory 状态机。"""

        now = self._clock()
        with self._condition:
            sample = dict(self._latest_sample) if self._latest_sample is not None else None
            if sample is None:
                return self._waiting_result_locked(), False, False
            sample_id = int(sample.get("sample_id", 0) or 0)
            is_new = sample_id > self._last_consumed_sample_id
            if is_new:
                self._last_consumed_sample_id = sample_id

        frame_received_at = self._optional_float(sample.get("frame_received_at"))
        processed_at = self._optional_float(sample.get("processed_at"))
        source_frame_id = sample.get("source_frame_id")
        reference_at = frame_received_at if frame_received_at is not None else processed_at
        age_sec = max(0.0, now - reference_at) if reference_at is not None else None
        stale = age_sec is None or age_sec > self.stale_timeout_sec
        message = str(sample.get("message", "") or "")
        trusted = source_frame_id is not None and frame_received_at is not None
        valid = bool(sample.get("available", False)) and not message and trusted and not stale
        sample.update(
            {
                "async": True,
                "cached": not is_new,
                "stale": stale,
                "age_sec": round(age_sec, 6) if age_sec is not None else None,
                "trusted_source": trusted,
            }
        )
        return sample, is_new, valid

    def status(self) -> dict[str, Any]:
        with self._condition:
            return self._status_locked()

    def _worker_loop(self, stop_event: threading.Event, generation: int) -> None:
        try:
            while not stop_event.is_set():
                with self._condition:
                    while self._pending is None and not stop_event.is_set():
                        self._condition.wait(timeout=0.5)
                    if stop_event.is_set():
                        break
                    job = self._pending
                    self._pending = None
                if job is None:
                    continue
                frame, source_frame_id, frame_received_at = job
                started_at = self._monotonic()
                try:
                    detected = self.detector.detect(frame)
                except Exception as exc:
                    detected = {
                        "available": False,
                        "raw": "",
                        "stable": "",
                        "confidence": 0.0,
                        "stable_frames": 0,
                        "message": f"手势识别线程异常：{exc}",
                    }
                completed_at = self._clock()
                latency_sec = max(0.0, self._monotonic() - started_at)
                with self._condition:
                    if stop_event.is_set() or generation != self._generation:
                        continue
                    self._sample_id += 1
                    self._latest_sample = {
                        **dict(detected or {}),
                        "sample_id": self._sample_id,
                        "source_frame_id": source_frame_id,
                        "frame_received_at": frame_received_at,
                        "processed_at": completed_at,
                        "inference_latency_sec": round(latency_sec, 6),
                    }
        finally:
            with self._condition:
                if generation == self._generation:
                    self._running = False
                    self._accepting = False
                self._condition.notify_all()

    def _waiting_result_locked(self) -> dict[str, Any]:
        detector_available = bool(getattr(self.detector, "available", False))
        detector_error = str(getattr(self.detector, "last_error", "") or "")
        return {
            "available": detector_available,
            "raw": "",
            "stable": "",
            "confidence": 0.0,
            "stable_frames": 0,
            "message": detector_error or "正在等待首个异步手势样本。",
            "async": True,
            "cached": False,
            "stale": False,
            "age_sec": None,
            "trusted_source": False,
            "sample_id": None,
            "source_frame_id": None,
            "frame_received_at": None,
            "processed_at": None,
            "inference_latency_sec": None,
        }

    def _status_locked(self) -> dict[str, Any]:
        thread_alive = bool(self._thread and self._thread.is_alive())
        latest_id = self._latest_sample.get("sample_id") if self._latest_sample else None
        return {
            "enabled": self.enabled,
            "running": bool(self._running),
            "accepting": bool(self._accepting),
            "thread_alive": thread_alive,
            "stop_pending": bool(thread_alive and not self._running),
            "process_hz": self.process_hz,
            "stale_timeout_sec": self.stale_timeout_sec,
            "pending": self._pending is not None,
            "submitted_frames": self._submitted_frames,
            "overwritten_frames": self._overwritten_frames,
            "latest_sample_id": latest_id,
            "last_error": self._last_error,
        }

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        if value is None:
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None
