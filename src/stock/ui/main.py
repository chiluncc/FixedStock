from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.table import Table

from stock.structures.config import Config
from stock.ui.data_build import DB_NAME, prepare_local_data

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.json"
REQUIRED_KEYS = ("local_data_dir", "output_dir", "time_start", "time_position", "stocks")

console = Console()


def _resolve(path: Path) -> Path:
    return path if path.is_absolute() else Path.cwd() / path


def load_config(config_path: Path) -> Config:
    if not config_path.is_file():
        console.print(f"[bold red]错误: 配置文件不存在: {config_path}[/bold red]")
        sys.exit(1)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    missing = [key for key in REQUIRED_KEYS if key not in raw]
    if missing:
        console.print(f"[bold red]错误: 配置缺少字段: {', '.join(missing)}[/bold red]")
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
        data_dir = _resolve(config.local_data_dir)
        output_dir = _resolve(config.output_dir)
        data_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        prepare_local_data(config)

        total = sum(len(codes) for codes in config.stocks.values())
        table = Table(title="数据初始化结果", show_header=False, title_justify="left")
        table.add_column("项目", style="bold cyan")
        table.add_column("内容")
        table.add_row("初始化", "成功")
        table.add_row("股票数量", f"{total} 只（{len(config.stocks)} 个板块）")
        table.add_row("买入日期", str(config.time_start.date()))
        table.add_row("持股时长", f"{config.time_position} 个交易日")
        table.add_row("数据目录", str(data_dir))
        table.add_row("输出目录", str(output_dir))
        console.print(table)
    except Exception as exc:
        console.print(f"[bold red]错误: {exc}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
