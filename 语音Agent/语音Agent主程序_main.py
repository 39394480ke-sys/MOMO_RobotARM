"""阶段十语音 Agent 主程序。"""

from __future__ import annotations

import argparse

from agent.path_utils import AGENT_ROOT, ensure_project_root_on_path
from agent.对话应用_agent_app import AgentApp
from agent.配置_config import load_config

ensure_project_root_on_path()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="阶段十：语音 Agent / 对话控制系统")
    parser.add_argument("--config", default=str(AGENT_ROOT / "Agent配置.yaml"), help="配置文件路径")
    parser.add_argument("--no-tts", action="store_true", help="禁用 TTS 播报")
    parser.add_argument("--force-new-session", action="store_true", help="启动时创建新会话")
    parser.add_argument("--max-record-sec", type=float, default=None, help="最大录音秒数")

    subparsers = parser.add_subparsers(dest="command")
    subparsers.add_parser("shell", help="进入交互 shell")

    ask_parser = subparsers.add_parser("ask", help="文本询问")
    ask_parser.add_argument("text", nargs=argparse.REMAINDER)

    subparsers.add_parser("voice", help="执行一轮语音对话")

    listen_parser = subparsers.add_parser("listen", help="长驻语音监听")
    listen_parser.add_argument("--warmup", action="store_true", help="启动 listen 前先 warmup")

    say_parser = subparsers.add_parser("say", help="只播报一段文本")
    say_parser.add_argument("text", nargs=argparse.REMAINDER)

    subparsers.add_parser("warmup", help="预热 Agent backend")
    subparsers.add_parser("reset-session", help="重置会话缓存")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    config = load_config(args.config)
    if args.no_tts:
        config.setdefault("tts", {})["enabled"] = False
    if args.max_record_sec is not None:
        config.setdefault("audio", {})["max_record_sec"] = float(args.max_record_sec)

    app = AgentApp(config, force_new_session=bool(args.force_new_session))
    command = args.command or "shell"

    if command == "shell":
        app.run_shell()
    elif command == "ask":
        text = " ".join(args.text).strip()
        app.ask_text(text, speak=not args.no_tts)
    elif command == "voice":
        app.run_voice_turn(speak=not args.no_tts)
    elif command == "listen":
        app.run_listen_loop(warmup=bool(args.warmup), speak=not args.no_tts)
    elif command == "say":
        text = " ".join(args.text).strip()
        print(text)
        app.say(text)
    elif command == "warmup":
        app.warmup()
    elif command == "reset-session":
        app.reset_session()
    else:
        parser.print_help()
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
