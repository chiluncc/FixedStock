from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from rich.console import Console
from rich.table import Table

from stock.structures.config import Config
from stock.ui.data_build import prepare_local_data
from stock.ui.data_analysis import generate_analysis_data

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CONFIG = PROJECT_ROOT / "config" / "config.json"
REQUIRED_KEYS = ("local_data_dir", "output_dir", "time_start", "time_position", "stocks")

console = Console()


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
        portfolio_power=float(raw.get("portfolio_power", 0.7)),
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
        config.local_data_dir.mkdir(parents=True, exist_ok=True)
        config.output_dir.mkdir(parents=True, exist_ok=True)

        success = prepare_local_data(config)
        total = sum(len(codes) for codes in config.stocks.values())
        title = "[bold green]数据初始化成功[/bold green]" if success else "[bold red]数据初始化失败[/bold red]"
        table = Table(title=title, show_header=False, title_justify="left")
        table.add_column("项目", style="bold cyan")
        table.add_column("内容")
        table.add_row("初始化", "成功" if success else "失败")
        table.add_row("股票数量", f"{total} 只（{len(config.stocks)} 个板块）")
        table.add_row("买入日期", str(config.time_start.date()))
        table.add_row("持股时长", f"{config.time_position} 个交易日")
        table.add_row("数据目录", str(config.local_data_dir))
        table.add_row("输出目录", str(config.output_dir))
        console.print(table)
        if not success:
            sys.exit(1)

        success = generate_analysis_data(config)
        if not success:
            console.print("[bold red]报告生成失败[/bold red]")
            sys.exit(1)
        
        console.print("[bold green]全部报告生成完成[/bold green]")

    except Exception as exc:
        console.print(f"[bold red]错误: {exc}[/bold red]")
        sys.exit(1)


if __name__ == "__main__":
    main()
