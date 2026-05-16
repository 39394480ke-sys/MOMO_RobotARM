"""TTS 语音播报。"""

from __future__ import annotations

import base64
import io
import re
import wave
from typing import Any

import numpy as np
import requests


def speak_text(text: str, config: dict[str, Any]) -> None:
    tts_cfg = config.get("tts", {})
    if not bool(tts_cfg.get("enabled", True)):
        return
    content = str(text or "").strip()
    if not content:
        return
    for chunk in _split_text(content):
        try:
            audio_bytes, content_type = _request_tts(chunk, tts_cfg)
            _play_audio(audio_bytes, content_type, config)
        except Exception as exc:
            print(f"TTS 播放警告：{exc}")


def _request_tts(text: str, tts_cfg: dict[str, Any]) -> tuple[bytes, str]:
    provider = str(tts_cfg.get("provider", "http")).lower()
    if provider != "http":
        raise RuntimeError(f"不支持的 TTS provider：{provider}")
    url = str(tts_cfg.get("url", "")).strip()
    if not url:
        raise RuntimeError("TTS 服务地址未配置。")
    headers = {}
    api_key = str(tts_cfg.get("api_key", "")).strip()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": tts_cfg.get("model", "tts-1"),
        "voice": tts_cfg.get("voice", "default"),
        "input": text,
    }
    response = requests.post(url, headers=headers, json=payload, timeout=float(tts_cfg.get("timeout_sec", 30)))
    if response.status_code >= 400:
        raise RuntimeError(f"TTS 服务返回错误：HTTP {response.status_code} {response.text[:200]}")
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        data = response.json()
        audio = _extract_audio_from_json(data)
        return audio, str(data.get("format") or data.get("content_type") or "audio/wav")
    return response.content, content_type


def _extract_audio_from_json(data: dict[str, Any]) -> bytes:
    for key in ("audio", "audio_base64", "data"):
        value = data.get(key)
        if isinstance(value, str):
            if value.startswith("data:"):
                value = value.split(",", 1)[-1]
            return base64.b64decode(value)
    raise RuntimeError("TTS JSON 响应中没有 audio/audio_base64/data 字段。")


def _play_audio(audio_bytes: bytes, content_type: str, config: dict[str, Any]) -> None:
    try:
        import sounddevice as sd  # type: ignore
    except Exception as exc:
        raise RuntimeError("sounddevice 不可用，无法播放 TTS。") from exc

    if audio_bytes[:4] == b"RIFF" or "wav" in content_type:
        sample_rate, pcm = _read_wav(audio_bytes)
        sd.play(pcm, sample_rate)
        sd.wait()
        return
    if "pcm" in content_type or content_type in {"", "audio/raw"}:
        sample_rate = int(config.get("audio", {}).get("sample_rate", 16000))
        pcm = np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        sd.play(pcm, sample_rate)
        sd.wait()
        return
    raise RuntimeError(f"暂不支持播放此音频格式：{content_type or 'unknown'}")


def _read_wav(audio_bytes: bytes) -> tuple[int, np.ndarray]:
    with wave.open(io.BytesIO(audio_bytes), "rb") as wav:
        sample_rate = wav.getframerate()
        channels = wav.getnchannels()
        sample_width = wav.getsampwidth()
        frames = wav.readframes(wav.getnframes())
    if sample_width == 2:
        pcm = np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
    elif sample_width == 4:
        pcm = np.frombuffer(frames, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        pcm = np.frombuffer(frames, dtype=np.uint8).astype(np.float32)
        pcm = (pcm - 128.0) / 128.0
    if channels > 1:
        pcm = pcm.reshape(-1, channels)
    return sample_rate, pcm


def _split_text(text: str, limit: int = 180) -> list[str]:
    pieces = re.split(r"([。！？!?；;\n])", text)
    chunks: list[str] = []
    current = ""
    for item in pieces:
        if not item:
            continue
        if len(current) + len(item) > limit and current:
            chunks.append(current.strip())
            current = item
        else:
            current += item
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text[:limit]]

