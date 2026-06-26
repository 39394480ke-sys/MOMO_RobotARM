"""STT 语音转文字。"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import requests

from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import resolve_secret_value  # noqa: E402
from .配置_config import secret_env_paths


def transcribe_audio(wav_bytes: bytes, config: dict[str, Any]) -> str:
    stt_cfg = config.get("stt", {})
    provider = str(stt_cfg.get("provider", "http")).lower()
    if provider == "mock":
        text = str(stt_cfg.get("mock_text") or os.environ.get("ARM_MOCK_STT_TEXT") or "").strip()
        if not text:
            text = input("mock STT，请输入模拟识别文本：").strip()
        return text or "没有识别到有效语音"
    if provider != "http":
        raise RuntimeError(f"不支持的 STT provider：{provider}")

    url = str(stt_cfg.get("url", "")).strip()
    if not url:
        raise RuntimeError("STT 服务地址未配置。")
    headers = {}
    api_key = resolve_secret_value(stt_cfg.get("api_key", ""), env_paths=secret_env_paths(config))
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
    data = {"model": stt_cfg.get("model", "whisper-1")}
    try:
        response = requests.post(url, headers=headers, files=files, data=data, timeout=float(stt_cfg.get("timeout_sec", 30)))
    except requests.RequestException as exc:
        raise RuntimeError("STT 服务不可用，请检查语音转文字服务是否启动。") from exc
    if response.status_code >= 400:
        raise RuntimeError(f"STT 服务返回错误：HTTP {response.status_code} {response.text[:200]}")
    text = _extract_text(response)
    if not text:
        raise RuntimeError("没有识别到有效语音")
    return text


def _extract_text(response: requests.Response) -> str:
    content_type = response.headers.get("content-type", "")
    if "json" not in content_type:
        return response.text.strip()
    payload = response.json()
    return _extract_text_from_payload(payload).strip()


def _extract_text_from_payload(payload: Any) -> str:
    if isinstance(payload, str):
        return payload
    if not isinstance(payload, dict):
        return ""
    for key in ("text", "transcript"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
    result = payload.get("result")
    if isinstance(result, dict) and isinstance(result.get("text"), str):
        return result["text"]
    choices = payload.get("choices")
    if isinstance(choices, list):
        parts: list[str] = []
        for choice in choices:
            if isinstance(choice, dict):
                if isinstance(choice.get("text"), str):
                    parts.append(choice["text"])
                message = choice.get("message")
                if isinstance(message, dict) and isinstance(message.get("content"), str):
                    parts.append(message["content"])
        return "\n".join(part.strip() for part in parts if part.strip())
    # 兼容一些服务把结果包在 JSON 字符串中。
    raw = json.dumps(payload, ensure_ascii=False)
    match = re.search(r'"text"\s*:\s*"([^"]+)"', raw)
    return match.group(1) if match else ""
