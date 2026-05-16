"""查看统一日志。"""

from __future__ import annotations

import argparse

from integration.config_loader import load_config
from integration.log_manager import LogManager


def main() -> int:
    parser = argparse.ArgumentParser(description="查看系统集成日志")
    parser.add_argument("service", nargs="?", default="system", help="system / web_api / vision / agent / gui")
    parser.add_argument("--lines", type=int, default=100)
    args = parser.parse_args()
    for line in LogManager(load_config()).tail_log(args.service, args.lines):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

