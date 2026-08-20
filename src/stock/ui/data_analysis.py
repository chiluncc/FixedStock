from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tqdm import tqdm

from stock.agent.agent import ReportAgent
from stock.structures.config import Config
from stock.structures.report import StockReport
from stock.utils.file_handles import get_logger, txt_save
from stock.utils.report_html import render_report_html
from stock.utils.tools.auto import analyze_stock_reports


def _as_html(config: Config, stock: StockReport) -> Path:
    folder = config.output_dir / "stocks" / f"stock_{stock.code}"
    folder.mkdir(parents=True, exist_ok=True)
    html = render_report_html(
        stock.as_md(),
        config.local_data_dir / "market.db",
        stock.code,
    )
    out_path = folder / f"stock_{stock.code}.html"
    out_path.write_text(html, encoding="utf-8")
    return out_path


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
        _as_html(config, stock)


def _llm_analysis(config: Config, stock: list[StockReport], threads: int = 16) -> list[StockReport]:
    main_logger = get_logger(config.output_dir / "logging.log")

    def _process_stock(stock: StockReport) -> StockReport | None:
        folder = config.output_dir / "stocks" / f"stock_{stock.code}"
        folder.mkdir(parents=True, exist_ok=True)
        logger = get_logger(folder / "logging.log")
        return ReportAgent(config, logger)(stock)

    completed: list[StockReport] = []
    with ThreadPoolExecutor(max_workers=max(1, min(threads, len(stock) or 1))) as pool:
        futures = {pool.submit(_process_stock, item): item for item in stock}
        for future in tqdm(as_completed(futures), desc="LLM Analysis", total=len(futures)):
            item = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                main_logger.error("股票 %s LLM 分析异常: %s", item.code, exc)
                continue
            if result is None:
                main_logger.error("股票 %s LLM 分析未完成", item.code)
                continue
            completed.append(result)
    return completed


def generate_analysis_data(config: Config) -> bool:
    try:
        stocks = _get_foundation_data(config)
        completed = _llm_analysis(config, stocks)
        _save_date(config, completed)
        return len(completed) == len(stocks)
    except Exception as exc:
        try:
            config.output_dir.mkdir(parents=True, exist_ok=True)
            get_logger(config.output_dir / "logging.log").error("数据分析失败: %s", exc)
        except Exception:
            pass
        return False
