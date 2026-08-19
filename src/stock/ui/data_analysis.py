from __future__ import annotations

from stock.structures.config import Config
from stock.structures.report import StockReport
from stock.utils.tools.auto import analyze_stock_reports
from stock.utils.file_handles import get_logger, txt_save


def _get_foundation_data(config: Config) -> list[StockReport]:
    db_path = config.local_data_dir / "market.db"
    return analyze_stock_reports(db_path, config.time_position)


def _save_date(config: Config, stocks: list[StockReport]) -> None:
    out_root = config.output_dir / "stocks"
    out_root.mkdir(parents=True, exist_ok=True)
    for stock in stocks:
        folder = out_root / f"stock_{stock.code}"
        folder.mkdir(parents=True, exist_ok=True)
        txt_save(stock.as_md(), folder / f"stock_{stock.code}.md")


def generate_analysis_data(config: Config) -> bool:
    try:
        stocks = _get_foundation_data(config)
        _save_date(config, stocks)
        return True
    except Exception as exc:
        try:
            config.output_dir.mkdir(parents=True, exist_ok=True)
            get_logger(config.output_dir / "logging.log").error("数据分析失败: %s", exc)
        except Exception:
            pass
        return False
