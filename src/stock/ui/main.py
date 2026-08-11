"""命令行入口：加载赛事配置、建立数据与输出路径。"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from stock.structures.config import Config
from stock.ui.data_build import prepare_local_data

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.json"
REQUIRED_KEYS = ("local_data_dir", "output_dir", "time_start", "time_position", "stocks")


def load_config(config_path: Path) -> Config:
    if not config_path.is_file():
        print(f"错误: 配置文件不存在: {config_path}", file=sys.stderr)
        sys.exit(1)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        print(f"错误: 配置缺少字段: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return Config(
        local_data_dir=Path(raw["local_data_dir"]),
        output_dir=Path(raw["output_dir"]),
        stocks=raw["stocks"],
        time_start=datetime.strptime(raw["time_start"], "%Y-%m-%d"),
        time_position=int(raw["time_position"]),
    )


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="股票量化研报数据处理入口")
    parser.add_argument(
        "-c",
        "--config",
        default=str(DEFAULT_CONFIG),
        help=f"配置文件路径（默认: {DEFAULT_CONFIG}）",
    )
    args = parser.parse_args(argv)

    try:
        config = load_config(Path(args.config))
        for label, path in (("数据", config.local_data_dir), ("输出", config.output_dir)):
            path.mkdir(parents=True, exist_ok=True)
            print(f"{label}目录: {path}")
        prepare_local_data(config)
        total = sum(len(codes) for codes in config.stocks.values())
        print(
            f"配置加载成功: {len(config.stocks)} 个板块 / {total} 只股票，"
            f"持有 {config.time_position} 个交易日，买入时点 {config.time_start.date()}"
        )
    except Exception as exc:
        print(f"错误: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
