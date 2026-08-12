from __future__ import annotations

import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

import akshare as ak
import pandas as pd

from stock.structures.config import Config
from stock.utils.file_handles import get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_DIR = PROJECT_ROOT / "schemas"
SCHEMA_FILES = (
    "stock_basic.sql",
    "trade_calendar.sql",
    "daily_bar.sql",
    "financial_report.sql",
    "valuation_daily.sql",
    "index_bar.sql",
)
DB_NAME = "market.db"
REQUEST_INTERVAL = 2.0
HISTORY_YEARS = 5

BAR_COLS = ("date", "open", "high", "low", "close", "volume", "amount", "turnover")
FIN_COLS = ("report_date", "roe", "revenue_yoy", "netprofit_yoy", "gross_margin", "debt_ratio")
VAL_COLS = ("date", "value")
INDEX_COLS = ("date", "open", "high", "low", "close", "volume")


# ===========================================


def _to_ts(date_str: str) -> int:
    return int(datetime.strptime(str(date_str)[:10], "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp())


def _db_path(local_data_dir: Path) -> Path:
    path = local_data_dir if local_data_dir.is_absolute() else Path.cwd() / local_data_dir
    path.mkdir(parents=True, exist_ok=True)
    return path / DB_NAME


def _log_path(output_dir: Path) -> Path:
    path = output_dir if output_dir.is_absolute() else Path.cwd() / output_dir
    path.mkdir(parents=True, exist_ok=True)
    return path / "logging.log"


def _window_bounds(con: sqlite3.Connection, config: Config) -> tuple[int, int] | None:
    cutoff_ts = _to_ts(config.time_start.strftime("%Y-%m-%d"))
    start_needed_ts = cutoff_ts - 365 * HISTORY_YEARS * 86400
    end_ts = con.execute(
        "SELECT MAX(trade_date) FROM trade_calendar WHERE trade_date < ?", (cutoff_ts,)
    ).fetchone()[0]
    if end_ts is None:
        return None
    return start_needed_ts, end_ts


def _build_local_database(local_data_dir: Path) -> None:
    db = _db_path(local_data_dir)
    con = sqlite3.connect(db)
    try:
        for name in SCHEMA_FILES:
            con.executescript((SCHEMA_DIR / name).read_text(encoding="utf-8"))
        con.commit()
    finally:
        con.close()


def _rebuild_views(con: sqlite3.Connection, cutoff_ts: int, config: Config) -> None:
    pool = ", ".join(f"'{code}'" for codes in config.stocks.values() for code in codes) or "''"
    statements = [
        "DROP VIEW IF EXISTS v_stock_basic",
        f"CREATE VIEW v_stock_basic AS "
        f"SELECT code, name, sector FROM stock_basic WHERE code IN ({pool})",
        "DROP VIEW IF EXISTS v_trade_calendar",
        f"CREATE VIEW v_trade_calendar AS SELECT trade_date FROM trade_calendar WHERE trade_date < {cutoff_ts}",
        "DROP VIEW IF EXISTS v_daily_bar",
        f"CREATE VIEW v_daily_bar AS "
        f"SELECT b.code, b.date, b.open, b.high, b.low, b.close, b.volume, b.amount, b.turnover "
        f"FROM daily_bar b JOIN v_stock_basic s ON s.code = b.code WHERE b.date < {cutoff_ts}",
        "DROP VIEW IF EXISTS v_index_bar",
        f"CREATE VIEW v_index_bar AS "
        f"SELECT index_code, date, open, high, low, close, volume, amount "
        f"FROM index_bar WHERE date < {cutoff_ts}",
        "DROP VIEW IF EXISTS v_financial_report",
        f"CREATE VIEW v_financial_report AS "
        f"SELECT f.code, f.report_date, f.announce_date, f.roe, f.revenue_yoy, f.netprofit_yoy, "
        f"f.gross_margin, f.debt_ratio "
        f"FROM financial_report f JOIN v_stock_basic s ON s.code = f.code "
        f"WHERE f.report_date < {cutoff_ts}",
        "DROP VIEW IF EXISTS v_valuation_daily",
        f"CREATE VIEW v_valuation_daily AS "
        f"SELECT v.code, v.date, v.pe_ttm, v.pb, v.total_mv "
        f"FROM valuation_daily v JOIN v_stock_basic s ON s.code = v.code "
        f"WHERE v.date < {cutoff_ts}",
    ]
    for statement in statements:
        con.execute(statement)
    con.commit()


# ===========================================
# 模块 1: trade_calendar


def _fetch_trade_dates(logger: logging.Logger) -> pd.DataFrame | None:
    try:
        return ak.tool_trade_date_hist_sina()
    except Exception as exc:
        logger.warning("交易日历抓取失败: %s", exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)


def _build_trade_calendar(config: Config) -> bool:
    logger = get_logger(_log_path(config.output_dir))
    con = sqlite3.connect(_db_path(config.local_data_dir))
    try:
        logger.info("开始构建 trade_calendar")
        df = _fetch_trade_dates(logger)
        if df is None:
            return False
        rows = [(_to_ts(d),) for d in df["trade_date"]]
        con.executemany("INSERT OR REPLACE INTO trade_calendar(trade_date) VALUES (?)", rows)
        con.commit()
        count = con.execute("SELECT COUNT(*) FROM trade_calendar").fetchone()[0]
        logger.info("trade_calendar 构建完成: %d 个交易日", count)
        return True
    finally:
        con.close()


# ===========================================
# 模块 2: stock_basic


def _fetch_stock_names(logger: logging.Logger) -> dict[str, str] | None:
    try:
        df = ak.stock_info_a_code_name()
        return dict(zip(df["code"], df["name"]))
    except Exception as exc:
        logger.warning("股票名称抓取失败: %s", exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)


def _build_stock_basic(config: Config) -> bool:
    logger = get_logger(_log_path(config.output_dir))
    con = sqlite3.connect(_db_path(config.local_data_dir))
    total = sum(len(codes) for codes in config.stocks.values())
    try:
        logger.info("开始构建 stock_basic（%d 只）", total)
        names = _fetch_stock_names(logger)
        if names is None:
            return False
        for sector, codes in config.stocks.items():
            for code in codes:
                con.execute(
                    "INSERT OR REPLACE INTO stock_basic(code, name, sector) VALUES (?, ?, ?)",
                    (code, names.get(code, ""), sector),
                )
        con.commit()
        logger.info("stock_basic 构建完成: %d 只", total)
        return True
    finally:
        con.close()


# ===========================================
# 模块 3: daily_bar


def _daily_fetch_window(
    con: sqlite3.Connection, code: str, start_needed_ts: int, end_ts: int
) -> tuple[int, int] | None:
    row = con.execute(
        "SELECT MIN(date), MAX(date) FROM daily_bar WHERE code = ?", (code,)
    ).fetchone()
    if row is None or row[0] is None:
        return start_needed_ts, end_ts
    min_ts, max_ts = row
    if max_ts < end_ts and min_ts > start_needed_ts:
        return start_needed_ts, end_ts
    if max_ts < end_ts:
        window = max_ts + 86400, end_ts
    elif min_ts > start_needed_ts:
        window = start_needed_ts, min_ts - 86400
    else:
        return None
    return window if window[0] <= window[1] else None


def _fetch_daily_em(code: str, start: str, end: str, logger: logging.Logger) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily", start_date=start, end_date=end, adjust="qfq", timeout=20
        )
    except Exception as exc:
        logger.warning("%s 东财日线失败: %s", code, exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)
    if df.empty:
        return pd.DataFrame(columns=list(BAR_COLS))
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["日期"]).dt.strftime("%Y-%m-%d"),
            "open": pd.to_numeric(df["开盘"], errors="coerce"),
            "high": pd.to_numeric(df["最高"], errors="coerce"),
            "low": pd.to_numeric(df["最低"], errors="coerce"),
            "close": pd.to_numeric(df["收盘"], errors="coerce"),
            "volume": pd.to_numeric(df["成交量"], errors="coerce") * 100,
            "amount": pd.to_numeric(df["成交额"], errors="coerce"),
            "turnover": pd.to_numeric(df["换手率"], errors="coerce"),
        }
    )


def _fetch_daily_sina(code: str, start: str, end: str, logger: logging.Logger) -> pd.DataFrame | None:
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        df = ak.stock_zh_a_daily(symbol=prefix + code, start_date=start, end_date=end, adjust="qfq")
    except Exception as exc:
        logger.warning("%s 新浪日线失败: %s", code, exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)
    if df.empty:
        return pd.DataFrame(columns=list(BAR_COLS))
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
            "open": pd.to_numeric(df["open"], errors="coerce"),
            "high": pd.to_numeric(df["high"], errors="coerce"),
            "low": pd.to_numeric(df["low"], errors="coerce"),
            "close": pd.to_numeric(df["close"], errors="coerce"),
            "volume": pd.to_numeric(df["volume"], errors="coerce"),
            "amount": pd.to_numeric(df["amount"], errors="coerce")
            if "amount" in df.columns
            else float("nan"),
            "turnover": pd.to_numeric(df["turnover"], errors="coerce") * 100
            if "turnover" in df.columns
            else float("nan"),
        }
    )


def _insert_daily_bars(con: sqlite3.Connection, code: str, df: pd.DataFrame) -> None:
    rows = [
        (code, _to_ts(r.date), float(r.open), float(r.high), float(r.low), float(r.close),
         float(r.volume), float(r.amount), float(r.turnover))
        for r in df.itertuples(index=False)
    ]
    if rows:
        con.executemany(
            "INSERT OR REPLACE INTO daily_bar(code, date, open, high, low, close, volume, amount, turnover) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()


def _build_daily_bar(config: Config) -> bool:
    logger = get_logger(_log_path(config.output_dir))
    con = sqlite3.connect(_db_path(config.local_data_dir))
    total = sum(len(codes) for codes in config.stocks.values())
    try:
        bounds = _window_bounds(con, config)
        if bounds is None:
            logger.warning("daily_bar 构建失败: 交易日历为空")
            return False
        start_needed_ts, end_ts = bounds
        logger.info("开始构建 daily_bar")
        for codes in config.stocks.values():
            for code in codes:
                window = _daily_fetch_window(con, code, start_needed_ts, end_ts)
                if window is None:
                    continue
                start = datetime.fromtimestamp(window[0], tz=timezone.utc).strftime("%Y%m%d")
                end = datetime.fromtimestamp(window[1], tz=timezone.utc).strftime("%Y%m%d")
                df = _fetch_daily_em(code, start, end, logger)
                if df is None:
                    df = _fetch_daily_sina(code, start, end, logger)
                if df is None:
                    logger.warning("daily_bar 构建失败: %s", code)
                    return False
                _insert_daily_bars(con, code, df)
        logger.info("daily_bar 构建完成: %d 只", total)
        return True
    finally:
        con.close()


# ===========================================
# 模块 4: financial_report


def _financial_fetch_year(
    con: sqlite3.Connection, code: str, cutoff_ts: int, start_needed_year: int
) -> int | None:
    row = con.execute(
        "SELECT MIN(report_date), MAX(report_date) FROM financial_report WHERE code = ?", (code,)
    ).fetchone()
    if row is None or row[0] is None:
        return start_needed_year
    min_ts, max_ts = row
    min_year = datetime.fromtimestamp(min_ts, tz=timezone.utc).year
    max_year = datetime.fromtimestamp(max_ts, tz=timezone.utc).year
    cutoff_year = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).year
    if min_year > start_needed_year:
        return start_needed_year
    if max_year < cutoff_year:
        return max_year
    return None


def _normalize_financial(df: pd.DataFrame, date_col: str, cols: dict[str, str]) -> pd.DataFrame:
    out = pd.DataFrame(
        {"report_date": pd.to_datetime(df[date_col], errors="coerce").dt.strftime("%Y-%m-%d")}
    )
    for db_col, src_col in cols.items():
        if src_col in df.columns:
            out[db_col] = pd.to_numeric(
                df[src_col].astype(str).str.replace("%", "", regex=False), errors="coerce"
            )
        else:
            out[db_col] = float("nan")
    return out.dropna(subset=["report_date"])


def _fetch_financial_sina(code: str, start_year: str, logger: logging.Logger) -> pd.DataFrame | None:
    try:
        df = ak.stock_financial_analysis_indicator(symbol=code, start_year=start_year)
    except Exception as exc:
        logger.warning("%s 新浪财报失败: %s", code, exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)
    if df.empty:
        return pd.DataFrame(columns=list(FIN_COLS))
    cols = {
        "roe": "净资产收益率(%)",
        "revenue_yoy": "主营业务收入增长率(%)",
        "netprofit_yoy": "净利润增长率(%)",
        "gross_margin": "销售毛利率(%)",
        "debt_ratio": "资产负债率(%)",
    }
    return _normalize_financial(df, "日期", cols)


def _fetch_financial_ths(code: str, logger: logging.Logger) -> pd.DataFrame | None:
    try:
        df = ak.stock_financial_abstract_ths(symbol=code)
    except Exception as exc:
        logger.warning("%s 同花顺财报失败: %s", code, exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)
    if df.empty:
        return pd.DataFrame(columns=list(FIN_COLS))
    cols = {
        "roe": "净资产收益率",
        "revenue_yoy": "营业总收入同比增长率",
        "netprofit_yoy": "净利润同比增长率",
        "gross_margin": "销售毛利率",
        "debt_ratio": "资产负债率",
    }
    return _normalize_financial(df, "报告期", cols)


def _insert_financial(con: sqlite3.Connection, code: str, df: pd.DataFrame, cutoff_ts: int) -> None:
    rows = []
    for r in df.itertuples(index=False):
        ts = _to_ts(r.report_date)
        if ts > cutoff_ts:
            continue
        values = [
            None if pd.isna(v) else float(v)
            for v in (r.roe, r.revenue_yoy, r.netprofit_yoy, r.gross_margin, r.debt_ratio)
        ]
        rows.append((code, ts, None, *values))
    if rows:
        con.executemany(
            "INSERT OR REPLACE INTO financial_report(code, report_date, announce_date, roe, revenue_yoy, "
            "netprofit_yoy, gross_margin, debt_ratio) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()


def _build_financial_report(config: Config) -> bool:
    logger = get_logger(_log_path(config.output_dir))
    con = sqlite3.connect(_db_path(config.local_data_dir))
    total = sum(len(codes) for codes in config.stocks.values())
    try:
        cutoff_ts = _to_ts(config.time_start.strftime("%Y-%m-%d"))
        start_needed_year = datetime.fromtimestamp(cutoff_ts, tz=timezone.utc).year - HISTORY_YEARS
        logger.info("开始构建 financial_report")
        for codes in config.stocks.values():
            for code in codes:
                year = _financial_fetch_year(con, code, cutoff_ts, start_needed_year)
                if year is None:
                    continue
                df = _fetch_financial_sina(code, str(year), logger)
                if df is None:
                    df = _fetch_financial_ths(code, logger)
                if df is None:
                    logger.warning("financial_report 构建失败: %s", code)
                    return False
                _insert_financial(con, code, df, cutoff_ts)
        logger.info("financial_report 构建完成: %d 只", total)
        return True
    finally:
        con.close()


# ===========================================
# 模块 5: valuation_daily


def _valuation_fetch_window(
    con: sqlite3.Connection, code: str, start_needed_ts: int, end_ts: int
) -> tuple[int, int] | None:
    row = con.execute(
        "SELECT MIN(date), MAX(date) FROM valuation_daily WHERE code = ?", (code,)
    ).fetchone()
    if row is None or row[0] is None:
        return start_needed_ts, end_ts
    min_ts, max_ts = row
    if max_ts + 86400 < end_ts and min_ts - 86400 > start_needed_ts:
        return start_needed_ts, end_ts
    if max_ts + 86400 < end_ts:
        window = max_ts + 86400, end_ts
    elif min_ts - 86400 > start_needed_ts:
        window = start_needed_ts, min_ts - 86400
    else:
        return None
    return window if window[0] <= window[1] else None


def _fetch_valuation(code: str, indicator: str, logger: logging.Logger) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_valuation_baidu(symbol=code, indicator=indicator, period="近五年")
    except Exception as exc:
        logger.warning("%s 估值(%s)抓取失败: %s", code, indicator, exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)
    if df.empty:
        return pd.DataFrame(columns=list(VAL_COLS))
    return pd.DataFrame(
        {
            "date": pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d"),
            "value": pd.to_numeric(df["value"], errors="coerce"),
        }
    ).dropna(subset=["date"])


def _insert_valuation(
    con: sqlite3.Connection, code: str, pe: pd.DataFrame, pb: pd.DataFrame, window: tuple[int, int]
) -> None:
    merged = pe.merge(pb, on="date", suffixes=("_pe", "_pb"))
    start_ts, end_window_ts = window
    rows = []
    for r in merged.itertuples(index=False):
        ts = _to_ts(r.date)
        if not (start_ts <= ts <= end_window_ts):
            continue
        pe_v = None if pd.isna(r.value_pe) else float(r.value_pe)
        pb_v = None if pd.isna(r.value_pb) else float(r.value_pb)
        if pe_v is None and pb_v is None:
            continue
        rows.append((code, ts, pe_v, pb_v, None))
    if rows:
        con.executemany(
            "INSERT OR REPLACE INTO valuation_daily(code, date, pe_ttm, pb, total_mv) VALUES (?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()


def _build_valuation_daily(config: Config) -> bool:
    logger = get_logger(_log_path(config.output_dir))
    con = sqlite3.connect(_db_path(config.local_data_dir))
    total = sum(len(codes) for codes in config.stocks.values())
    try:
        bounds = _window_bounds(con, config)
        if bounds is None:
            logger.warning("valuation_daily 构建失败: 交易日历为空")
            return False
        start_needed_ts, end_ts = bounds
        logger.info("开始构建 valuation_daily")
        for codes in config.stocks.values():
            for code in codes:
                window = _valuation_fetch_window(con, code, start_needed_ts, end_ts)
                if window is None:
                    continue
                pe = _fetch_valuation(code, "市盈率(TTM)", logger)
                pb = _fetch_valuation(code, "市净率", logger)
                if pe is None or pb is None:
                    logger.warning("valuation_daily 构建失败: %s", code)
                    return False
                _insert_valuation(con, code, pe, pb, window)
        logger.info("valuation_daily 构建完成: %d 只", total)
        return True
    finally:
        con.close()


# ===========================================
# 模块 6: index_bar


def _index_fetch_window(
    con: sqlite3.Connection, index_code: str, start_needed_ts: int, end_ts: int
) -> tuple[int, int] | None:
    row = con.execute(
        "SELECT MIN(date), MAX(date) FROM index_bar WHERE index_code = ?", (index_code,)
    ).fetchone()
    if row is None or row[0] is None:
        return start_needed_ts, end_ts
    min_ts, max_ts = row
    if max_ts < end_ts and min_ts > start_needed_ts:
        return start_needed_ts, end_ts
    if max_ts < end_ts:
        window = max_ts + 86400, end_ts
    elif min_ts > start_needed_ts:
        window = start_needed_ts, min_ts - 86400
    else:
        return None
    return window if window[0] <= window[1] else None


def _fetch_index_series(index_code: str, logger: logging.Logger) -> pd.DataFrame | None:
    try:
        df = ak.stock_zh_index_daily(symbol=f"sh{index_code}")
    except Exception as exc:
        logger.warning("指数 %s 抓取失败: %s", index_code, exc)
        return None
    finally:
        time.sleep(REQUEST_INTERVAL)
    if df.empty:
        return pd.DataFrame(columns=list(INDEX_COLS))
    return df


def _insert_index_bars(
    con: sqlite3.Connection, index_code: str, df: pd.DataFrame, window: tuple[int, int]
) -> None:
    start_ts, end_window_ts = window
    rows = [
        (index_code, _to_ts(r.date), float(r.open), float(r.high), float(r.low),
         float(r.close), float(r.volume), None)
        for r in df.itertuples(index=False)
        if start_ts < _to_ts(r.date) <= end_window_ts
    ]
    if rows:
        con.executemany(
            "INSERT OR REPLACE INTO index_bar(index_code, date, open, high, low, close, volume, amount) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows,
        )
        con.commit()


def _build_index_bar(config: Config) -> bool:
    logger = get_logger(_log_path(config.output_dir))
    con = sqlite3.connect(_db_path(config.local_data_dir))
    try:
        bounds = _window_bounds(con, config)
        if bounds is None:
            logger.warning("index_bar 构建失败: 交易日历为空")
            return False
        start_needed_ts, end_ts = bounds
        logger.info("开始构建 index_bar")
        for index_code in ("000300", "000905"):
            window = _index_fetch_window(con, index_code, start_needed_ts, end_ts)
            if window is None:
                continue
            df = _fetch_index_series(index_code, logger)
            if df is None:
                logger.warning("index_bar 构建失败: %s", index_code)
                return False
            _insert_index_bars(con, index_code, df, window)
        logger.info("index_bar 构建完成: 2 个指数")
        return True
    finally:
        con.close()


# ===========================================


def prepare_local_data(config: Config) -> bool:
    try:
        _build_local_database(config.local_data_dir)
    except Exception as exc:
        get_logger(_log_path(config.output_dir)).error("建库失败: %s", exc)
        return False
    for builder in (
        _build_trade_calendar,
        _build_stock_basic,
        _build_daily_bar,
        _build_financial_report,
        _build_valuation_daily,
        _build_index_bar,
    ):
        if not builder(config):
            return False
    con = sqlite3.connect(_db_path(config.local_data_dir))
    try:
        cutoff_ts = _to_ts(config.time_start.strftime("%Y-%m-%d"))
        _rebuild_views(con, cutoff_ts, config)
    finally:
        con.close()
    get_logger(_log_path(config.output_dir)).info(
        "视图重建完成: v_stock_basic / v_trade_calendar / v_daily_bar / v_index_bar / v_financial_report / v_valuation_daily"
    )
    return True
