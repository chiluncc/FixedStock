from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from tqdm import tqdm

from stock.agent.agent import ReportAgent
from stock.structures.config import Config
from stock.structures.report import StockReport
from stock.utils.file_handles import get_logger, json_save, txt_save
from stock.utils.report_html import render_report_html
from stock.utils.tools.auto import analyze_stock_reports

REPORT_DIR_NAME = "个股投资研报"
PORTFOLIO_MIN_SCORE = 50.0
PORTFOLIO_MIN_WEIGHT = 0.02
PORTFOLIO_DECIMALS = 4


def _report_folder(config: Config) -> Path:
    folder = config.output_dir / REPORT_DIR_NAME
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _save_report(config: Config, stock: StockReport) -> bool:
    config.output_dir.mkdir(parents=True, exist_ok=True)
    logger = get_logger(config.output_dir / "logging.log")
    folder = _report_folder(config)
    md = stock.as_md()
    txt_save(md, folder / f"{stock.code}.md")
    try:
        html = render_report_html(md, config.local_data_dir / "market.db", stock.code)
    except Exception as exc:
        logger.error("股票 %s HTML 渲染失败: %s", stock.code, exc)
        return False
    try:
        from stock.utils.report_pdf import html_to_pdf

        pdf = html_to_pdf(html)
        (folder / f"{stock.code}.pdf").write_bytes(pdf)
    except Exception as exc:
        logger.error("股票 %s PDF 生成失败，回退 HTML: %s", stock.code, exc)
        (folder / f"{stock.code}.html").write_text(html, encoding="utf-8")
    return True


def _write_portfolio(config: Config, stocks: list[StockReport]) -> dict[str, float | int]:
    eligible = [
        (stock.code, stock.conclusion.composite_score)
        for stock in stocks
        if stock.conclusion.composite_score >= PORTFOLIO_MIN_SCORE
    ]
    raw = {code: score ** config.portfolio_power for code, score in eligible}
    total = sum(raw.values())
    shares: dict[str, float] = {}
    if total > 0:
        for code, score in eligible:
            share = raw[code] / total
            shares[code] = share if share >= PORTFOLIO_MIN_WEIGHT else 0.0
    portfolio: dict[str, float | int] = {
        stock.code: (
            round(shares.get(stock.code, 0.0), PORTFOLIO_DECIMALS)
            if shares.get(stock.code, 0.0) > 0
            else 0
        )
        for stock in sorted(stocks, key=lambda s: s.code)
    }
    config.output_dir.mkdir(parents=True, exist_ok=True)
    json_save(portfolio, config.output_dir / "Portfolio.json")
    return portfolio


def _get_foundation_data(config: Config) -> list[StockReport]:
    db_path = config.local_data_dir / "market.db"
    return analyze_stock_reports(db_path, config.time_position)


def _save_date(config: Config, stocks: list[StockReport]) -> int:
    saved = 0
    for stock in stocks:
        if _save_report(config, stock):
            saved += 1
    return saved


def _llm_analysis(config: Config, stock: list[StockReport], threads: int = 16) -> list[StockReport]:
    main_logger = get_logger(config.output_dir / "logging.log")

    def _process_stock(stock: StockReport) -> StockReport | None:
        folder = config.output_dir / "logs" / f"stock_{stock.code}"
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
        _write_portfolio(config, completed)
        return len(completed) == len(stocks)
    except Exception as exc:
        try:
            config.output_dir.mkdir(parents=True, exist_ok=True)
            get_logger(config.output_dir / "logging.log").error("数据分析失败: %s", exc)
        except Exception:
            pass
        return False
