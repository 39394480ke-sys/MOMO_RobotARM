"""语音录入模块。"""

from __future__ import annotations

import io
import threading
import time
import wave
from pathlib import Path
from typing import Any

import numpy as np

from .配置_config import config_base_dir, resolve_path


def audio_input_unavailable_message() -> str:
    return "录音不可用：未安装或无法使用 sounddevice。文本 ask 模式仍然可以使用。"


def record_until_enter(config: dict[str, Any]) -> bytes:
    """按 Enter 开始录音，再按 Enter 停止，返回 WAV bytes。"""

    try:
        import sounddevice as sd  # type: ignore
    except Exception as exc:
        raise RuntimeError(audio_input_unavailable_message()) from exc

    audio_cfg = config.get("audio", {})
    sample_rate = int(audio_cfg.get("sample_rate", 16000))
    channels = int(audio_cfg.get("channels", 1))
    max_record_sec = float(audio_cfg.get("max_record_sec", 20))

    input("按 Enter 开始录音...")
    print("录音中，再按 Enter 停止。")
    stop_event = threading.Event()
    chunks: list[np.ndarray] = []

    def wait_for_enter() -> None:
        try:
            input()
        finally:
            stop_event.set()

    def callback(indata, frames, time_info, status) -> None:  # noqa: ANN001
        if status:
            print(f"录音警告：{status}")
        chunks.append(indata.copy())

    thread = threading.Thread(target=wait_for_enter, daemon=True)
    thread.start()
    started = time.time()
    with sd.InputStream(samplerate=sample_rate, channels=channels, dtype="float32", callback=callback):
        while not stop_event.is_set() and time.time() - started < max_record_sec:
            time.sleep(0.05)
    if not chunks:
        raise RuntimeError("没有录到有效音频。")
    audio = np.concatenate(chunks, axis=0)
    audio = np.clip(audio, -1.0, 1.0)
    pcm = (audio * 32767.0).astype(np.int16)
    wav_bytes = _pcm_to_wav_bytes(pcm.tobytes(), sample_rate, channels, sample_width=2)
    if bool(audio_cfg.get("save_last_wav", True)):
        save_wav(wav_bytes, resolve_path(audio_cfg.get("last_wav_path", "runtime/audio/last_record.wav"), config_base_dir(config)))
    return wav_bytes


def save_wav(audio_bytes: bytes, path: str | Path) -> None:
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(audio_bytes)


def _pcm_to_wav_bytes(pcm_bytes: bytes, sample_rate: int, channels: int, sample_width: int = 2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(sample_width)
        wav.setframerate(sample_rate)
        wav.writeframes(pcm_bytes)
    return buffer.getvalue()

