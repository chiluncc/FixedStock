from __future__ import annotations

import math
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from stock.structures.report import (
    ActivityIndicators,
    Conclusion,
    FactorScores,
    FinancialQuality,
    InvestmentView,
    MaAlignment,
    MomentumIndicators,
    PredictionResult,
    PricePerformance,
    RiskAnalysis,
    RiskLevel,
    StockReport,
    TrendIndicators,
    ValuationIndicators,
    VolatilityIndicators,
)

FACTOR_WEIGHTS = np.array([0.35, 0.25, 0.25, 0.15])


def _ts_to_date(ts: int) -> datetime.date:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date()


def _clip(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _pct_high(series: pd.Series, value: float) -> float:
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if clean.empty:
        return 50.0
    return float((clean <= value).mean() * 100.0)


def _max_drawdown_series(close: pd.Series, window: int) -> pd.Series:
    def _mdd(values: np.ndarray) -> float:
        peak = np.maximum.accumulate(values)
        return float((values / peak - 1.0).min())

    return close.rolling(window).apply(_mdd, raw=True)


def _severity_grade(bounds: tuple[float, float, float, float], value: float, default: int = 3) -> int:
    if not np.isfinite(value):
        return default
    if value < bounds[0]:
        return 1
    if value < bounds[1]:
        return 2
    if value < bounds[2]:
        return 3
    if value < bounds[3]:
        return 4
    return 5


def _ma_alignment(ma5: float, ma20: float, ma60: float) -> MaAlignment:
    if ma5 > ma20 > ma60:
        return MaAlignment.BULLISH
    if ma5 < ma20 < ma60:
        return MaAlignment.BEARISH
    return MaAlignment.MIXED


def _financial_quality(fin: pd.DataFrame) -> tuple[FinancialQuality, float]:
    if fin.empty:
        return FinancialQuality(None, None, None, None, None, None, 50.0), 50.0

    metric_cols = ("roe", "revenue_yoy", "netprofit_yoy", "gross_margin", "debt_ratio")
    latest = next(
        (row for row in fin.sort_values("report_date", ascending=False).itertuples(index=False)
         if any(pd.notna(getattr(row, col)) for col in metric_cols)),
        None,
    )
    if latest is None:
        return FinancialQuality(None, None, None, None, None, None, 50.0), 50.0

    weights = {
        "roe": 0.30,
        "revenue_yoy": 0.20,
        "netprofit_yoy": 0.20,
        "gross_margin": 0.20,
        "debt_ratio": 0.10,
    }
    total_weight = 0.0
    quality = 0.0
    for col, weight in weights.items():
        value = getattr(latest, col)
        if pd.isna(value):
            continue
        hist = pd.to_numeric(fin[col], errors="coerce").dropna()
        if hist.empty:
            continue
        if col == "debt_ratio":
            score = 100.0 - _pct_high(hist, float(value))
        else:
            score = _pct_high(hist, float(value))
        quality += weight * score
        total_weight += weight

    quality_score = quality / total_weight if total_weight > 0 else 50.0
    return FinancialQuality(
        report_date=_ts_to_date(int(latest.report_date)),
        roe=float(latest.roe) if pd.notna(latest.roe) else None,
        revenue_yoy=float(latest.revenue_yoy) if pd.notna(latest.revenue_yoy) else None,
        netprofit_yoy=float(latest.netprofit_yoy) if pd.notna(latest.netprofit_yoy) else None,
        gross_margin=float(latest.gross_margin) if pd.notna(latest.gross_margin) else None,
        debt_ratio=float(latest.debt_ratio) if pd.notna(latest.debt_ratio) else None,
        quality_score=quality_score,
    ), quality_score


def _valuation(val: pd.DataFrame) -> tuple[ValuationIndicators, float]:
    if val.empty:
        return ValuationIndicators(None, None, None, None, 50.0), 50.0

    pe_series = pd.to_numeric(val["pe_ttm"], errors="coerce").dropna()
    pe_series = pe_series[pe_series > 0]
    pb_series = pd.to_numeric(val["pb"], errors="coerce").dropna()
    pb_series = pb_series[pb_series > 0]

    pe_current = float(pe_series.iloc[-1]) if not pe_series.empty else None
    pb_current = float(pb_series.iloc[-1]) if not pb_series.empty else None
    pe_pct = _pct_high(pe_series, pe_current) if pe_current is not None else None
    pb_pct = _pct_high(pb_series, pb_current) if pb_current is not None else None

    scores = []
    if pe_pct is not None:
        scores.append(100.0 - pe_pct)
    if pb_pct is not None:
        scores.append(100.0 - pb_pct)
    valuation_score = float(np.mean(scores)) if scores else 50.0

    return (
        ValuationIndicators(
            pe_ttm=pe_current,
            pb=pb_current,
            pe_percentile=pe_pct,
            pb_percentile=pb_pct,
            valuation_score=valuation_score,
        ),
        valuation_score,
    )


def _prediction(close: pd.Series, ret: pd.Series, holding_days: int) -> PredictionResult:
    features = []
    labels = []
    drawdowns = []
    n = len(close)
    for i in range(60, n - holding_days):
        r20 = close.iloc[i] / close.iloc[i - 20] - 1.0
        r60 = close.iloc[i] / close.iloc[i - 60] - 1.0
        vol20 = float(ret.iloc[i - 19:i + 1].std() * math.sqrt(252))
        ma20 = float(close.iloc[i - 19:i + 1].mean())
        dev20 = close.iloc[i] / ma20 - 1.0
        label = close.iloc[i + holding_days] / close.iloc[i] - 1.0
        fwd = close.iloc[i + 1:i + holding_days + 1].to_numpy(dtype=float)
        mdd = float((fwd / np.maximum.accumulate(fwd) - 1.0).min())
        features.append([r20, r60, vol20, dev20])
        labels.append(label)
        drawdowns.append(mdd)

    if not features:
        return PredictionResult(0, False, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    feat_arr = np.asarray(features, dtype=float)
    label_arr = np.asarray(labels, dtype=float)
    mdd_arr = np.asarray(drawdowns, dtype=float)
    mean = feat_arr.mean(axis=0)
    std = feat_arr.std(axis=0)
    std_safe = np.where(std == 0.0, 1.0, std)

    current = np.array(
        [
            close.iloc[-1] / close.iloc[-21] - 1.0,
            close.iloc[-1] / close.iloc[-61] - 1.0,
            float(ret.iloc[-20:].std() * math.sqrt(252)),
            close.iloc[-1] / float(close.iloc[-20:].mean()) - 1.0,
        ]
    )
    z_current = (current - mean) / std_safe
    z_history = (feat_arr - mean) / std_safe
    diff = z_history - z_current
    dist = np.sqrt(np.sum(FACTOR_WEIGHTS * diff * diff, axis=1))
    order = np.argsort(dist)
    k = min(200, len(dist))
    selected = order[:k]
    selected_labels = label_arr[selected]
    selected_mdd = mdd_arr[selected]

    return PredictionResult(
        sample_count=int(k),
        sample_sufficient=len(dist) >= 50,
        mean_return=float(selected_labels.mean() * 100.0),
        win_probability=float((selected_labels > 0).mean() * 100.0),
        downside_5pct=float(np.percentile(selected_labels, 5) * 100.0),
        avg_max_drawdown=float(selected_mdd.mean() * 100.0),
        expected_low=float(np.percentile(selected_labels, 10) * 100.0),
        expected_high=float(np.percentile(selected_labels, 90) * 100.0),
    )


def _risk_analysis(daily: pd.DataFrame, index_300: pd.DataFrame, holding_days: int) -> RiskAnalysis:
    stock = daily[["date", "close"]].copy()
    stock["ret"] = stock["close"].pct_change()
    index = index_300[["date", "close"]].copy()
    index["iret"] = index["close"].pct_change()
    merged = stock.merge(index, on="date", suffixes=("", "_idx")).dropna()
    merged = merged.tail(250)

    if len(merged) > 2:
        index_var = float(merged["iret"].var())
        correlation = float(merged["ret"].corr(merged["iret"]))
        beta = float(merged["ret"].cov(merged["iret"]) / index_var) if index_var > 0 else 0.0
    else:
        correlation = 0.0
        beta = 0.0

    ret = daily["close"].pct_change()
    r_hold = (daily["close"] / daily["close"].shift(holding_days) - 1.0) * 100.0
    vol_hold = float(ret.rolling(holding_days).std().iloc[-1] * math.sqrt(252) * 100.0) if len(daily) > holding_days else float("nan")
    downside5 = float(r_hold.quantile(0.05)) if not r_hold.dropna().empty else float("nan")
    avg_amount_20d = float(daily["amount"].tail(holding_days).mean()) if len(daily) >= holding_days else 0.0

    return RiskAnalysis(
        correlation_csi300=correlation,
        beta_csi300=beta,
        annualized_vol_20d=vol_hold,
        downside_5pct=downside5,
        avg_amount_20d=avg_amount_20d,
    )


def _analyze_stock(
    code: str,
    name: str,
    sector: str | None,
    daily: pd.DataFrame,
    fin: pd.DataFrame,
    val: pd.DataFrame,
    index_300: pd.DataFrame,
    report_date: datetime.date,
    holding_days: int,
) -> StockReport:
    daily = daily.sort_values("date").reset_index(drop=True)
    close = pd.to_numeric(daily["close"], errors="coerce").astype(float)
    amount = pd.to_numeric(daily["amount"], errors="coerce").astype(float)
    turnover = pd.to_numeric(daily["turnover"], errors="coerce").astype(float)
    ret = close.pct_change()

    def _return_n(n: int) -> float:
        return float((close.iloc[-1] / close.iloc[-1 - n] - 1.0) * 100.0) if len(close) > n else float("nan")

    last250 = close.tail(250)
    low_250, high_250 = float(last250.min()), float(last250.max())
    position_pct = 50.0 if high_250 == low_250 else float((close.iloc[-1] - low_250) / (high_250 - low_250) * 100.0)

    ma5 = float(close.rolling(5).mean().iloc[-1]) if len(close) >= 5 else float("nan")
    ma20 = float(close.rolling(20).mean().iloc[-1]) if len(close) >= 20 else float("nan")
    ma60 = float(close.rolling(60).mean().iloc[-1]) if len(close) >= 60 else float("nan")

    r20 = (close / close.shift(20) - 1.0) * 100.0
    r60 = (close / close.shift(60) - 1.0) * 100.0
    r20_clean = r20.dropna()
    r60_clean = r60.dropna()
    current_r20 = _return_n(20)
    current_r60 = _return_n(60)
    m20 = _pct_high(r20_clean, current_r20) if np.isfinite(current_r20) else 50.0
    m60 = _pct_high(r60_clean, current_r60) if np.isfinite(current_r60) else 50.0
    momentum_score = 0.65 * m20 + 0.35 * m60

    dev20 = (close.iloc[-1] / ma20 - 1.0) * 100.0 if np.isfinite(ma20) and ma20 > 0 else 0.0
    dev60 = (close.iloc[-1] / ma60 - 1.0) * 100.0 if np.isfinite(ma60) and ma60 > 0 else 0.0
    ma20_score = _clip(50.0 + dev20 * 10.0)
    ma60_score = _clip(50.0 + dev60 * 5.0)
    alignment = _ma_alignment(ma5, ma20, ma60)
    trend_score = 0.4 * ma20_score + 0.3 * ma60_score + 0.3 * (100.0 if alignment is MaAlignment.BULLISH else 0.0 if alignment is MaAlignment.BEARISH else 50.0)

    vol_hist = ret.rolling(holding_days).std() * math.sqrt(252) * 100.0
    mdd_hist = _max_drawdown_series(close, holding_days + 1) * 100.0
    current_vol = float(vol_hist.iloc[-1]) if np.isfinite(vol_hist.iloc[-1]) else float("nan")
    current_mdd20 = float(mdd_hist.iloc[-1]) if np.isfinite(mdd_hist.iloc[-1]) else float("nan")
    r_hold = (close / close.shift(holding_days) - 1.0) * 100.0
    r_hold_clean = r_hold.dropna()
    downside5 = float(r_hold_clean.quantile(0.05)) if not r_hold_clean.empty else float("nan")

    vol_score = 100.0 - _pct_high(vol_hist.dropna(), current_vol) if np.isfinite(current_vol) else 50.0
    mdd_score = _pct_high(mdd_hist.dropna(), current_mdd20) if np.isfinite(current_mdd20) else 50.0
    downside_score = _pct_high(r_hold_clean, downside5) if np.isfinite(downside5) else 50.0
    risk_score = 0.5 * vol_score + 0.3 * mdd_score + 0.2 * downside_score

    financial, fin_quality_score = _financial_quality(fin)
    valuation, valuation_score = _valuation(val)
    fundamental_score = 0.5 * fin_quality_score + 0.5 * valuation_score
    factor_scores = FactorScores(
        momentum=float(momentum_score),
        trend=float(trend_score),
        risk=float(risk_score),
        fundamental=float(fundamental_score),
    )

    composite_score = (
        0.35 * factor_scores.momentum
        + 0.25 * factor_scores.trend
        + 0.20 * factor_scores.risk
        + 0.20 * factor_scores.fundamental
    )

    vol_grade = _severity_grade((20.0, 35.0, 50.0, 70.0), current_vol)
    mdd_grade = _severity_grade((5.0, 10.0, 15.0, 20.0), abs(current_mdd20))
    downside_grade = _severity_grade((5.0, 10.0, 15.0, 25.0), abs(downside5))
    risk_severity = max(vol_grade, mdd_grade, downside_grade)
    risk_level = {
        1: RiskLevel.LOW,
        2: RiskLevel.MID_LOW,
        3: RiskLevel.MEDIUM,
        4: RiskLevel.MID_HIGH,
        5: RiskLevel.HIGH,
    }[risk_severity]
    risk_penalty = {1: 0, 2: 5, 3: 10, 4: 15, 5: 20}[risk_severity]
    adjusted_score = composite_score - risk_penalty
    if adjusted_score >= 65:
        investment_view = InvestmentView.BULLISH
    elif adjusted_score < 45:
        investment_view = InvestmentView.BEARISH
    else:
        investment_view = InvestmentView.NEUTRAL

    prediction = _prediction(close, ret, holding_days)
    risk = _risk_analysis(daily, index_300, holding_days)

    amount_ratio = (
        float(amount.tail(5).mean() / amount.tail(20).mean())
        if len(amount) >= 20 and amount.tail(20).mean() > 0
        else float("nan")
    )
    amount_score = _clip(50.0 + (amount_ratio - 1.0) / 0.4 * 50.0) if np.isfinite(amount_ratio) else 50.0
    current_turnover = float(turnover.iloc[-1])
    turnover_pct = (
        _pct_high(turnover.tail(250).dropna(), current_turnover)
        if np.isfinite(current_turnover)
        else 50.0
    )
    activity_score = 0.6 * amount_score + 0.4 * turnover_pct

    return StockReport(
        code=code,
        name=name,
        sector=sector,
        report_date=report_date,
        holding_days=holding_days,
        price=PricePerformance(
            current_price=float(close.iloc[-1]),
            return_5d=_return_n(5),
            return_20d=current_r20,
            return_60d=current_r60,
            return_250d=_return_n(250),
            position_pct=position_pct,
        ),
        trend=TrendIndicators(
            ma5=ma5,
            ma20=ma20,
            ma60=ma60,
            alignment=alignment,
            above_ma5=bool(np.isfinite(ma5) and close.iloc[-1] > ma5),
            above_ma20=bool(np.isfinite(ma20) and close.iloc[-1] > ma20),
            above_ma60=bool(np.isfinite(ma60) and close.iloc[-1] > ma60),
        ),
        momentum=MomentumIndicators(return_20d=current_r20, return_60d=current_r60),
        activity=ActivityIndicators(
            amount_ratio_5_20=amount_ratio,
            turnover=current_turnover,
            activity_score=float(activity_score),
        ),
        volatility=VolatilityIndicators(
            annualized_vol_20d=current_vol,
            max_drawdown_20d=current_mdd20,
            max_drawdown_250d=float(_max_drawdown_series(close, 251).iloc[-1]) if len(close) >= 251 else float("nan"),
            downside_5pct=downside5,
        ),
        financial=financial,
        valuation=valuation,
        factors=factor_scores,
        conclusion=Conclusion(
            composite_score=float(composite_score),
            risk_severity=risk_severity,
            risk_level=risk_level,
            adjusted_score=float(adjusted_score),
            investment_view=investment_view,
        ),
        prediction=prediction,
        risk=risk,
        investment_summary=None,
        investment_analysis=None,
    )


def analyze_stock_reports(db_path: Path, holding_days: int) -> list[StockReport]:
    db_path = Path(db_path)
    if not db_path.is_file():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        basic = pd.read_sql_query(
            "SELECT code, name, sector FROM v_stock_basic ORDER BY code", con
        )
        daily = pd.read_sql_query(
            "SELECT code, date, close, amount, turnover FROM v_daily_bar", con
        )
        fin = pd.read_sql_query(
            "SELECT code, report_date, roe, revenue_yoy, netprofit_yoy, gross_margin, debt_ratio "
            "FROM v_financial_report",
            con,
        )
        val = pd.read_sql_query(
            "SELECT code, date, pe_ttm, pb FROM v_valuation_daily", con
        )
        index_300 = pd.read_sql_query(
            "SELECT index_code, date, close FROM v_index_bar WHERE index_code = '000300'", con
        )
        trade = pd.read_sql_query("SELECT trade_date FROM v_trade_calendar", con)
        raw_trade = pd.read_sql_query("SELECT trade_date FROM trade_calendar", con)

        data_cutoff = int(trade["trade_date"].max())
        later = raw_trade.loc[raw_trade["trade_date"] > data_cutoff, "trade_date"]
        cutoff_ts = int(later.min()) if not later.empty else data_cutoff + 86400
        report_date = _ts_to_date(cutoff_ts)

        daily_by_code = {code: group for code, group in daily.groupby("code")}
        fin_by_code = {code: group for code, group in fin.groupby("code")}
        val_by_code = {code: group for code, group in val.groupby("code")}

        reports = []
        for row in basic.itertuples(index=False):
            code = row.code
            reports.append(
                _analyze_stock(
                    code=code,
                    name=row.name,
                    sector=row.sector,
                    daily=daily_by_code.get(code, pd.DataFrame()),
                    fin=fin_by_code.get(code, pd.DataFrame()),
                    val=val_by_code.get(code, pd.DataFrame()),
                    index_300=index_300,
                    report_date=report_date,
                    holding_days=holding_days,
                )
            )
        return reports
    finally:
        con.close()
