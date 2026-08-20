from __future__ import annotations

import io
import html
import os
import re
import sqlite3
import warnings
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", "/tmp/matplotlib_cache")
os.makedirs(os.environ["MPLCONFIGDIR"], exist_ok=True)
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/xdg_cache")
os.makedirs(os.environ["XDG_CACHE_HOME"], exist_ok=True)

import matplotlib

matplotlib.use("Agg")

from matplotlib import font_manager, pyplot as plt

from multimark import markdown_to_html

font_manager.fontManager.addfont("/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf")
plt.rcParams["font.sans-serif"] = ["DejaVu Sans", "Droid Sans Fallback", "Noto Sans CJK SC"]
plt.rcParams["axes.unicode_minus"] = False
plt.rcParams["svg.fonttype"] = "none"
warnings.filterwarnings("ignore", message=r"Glyph .* missing from font\(s\).*")


def _db(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _ts_to_date(ts: int) -> datetime:
    return datetime.fromtimestamp(ts, tz=timezone.utc)


def _fig_svg(fig) -> str:
    buf = io.StringIO()
    fig.savefig(buf, format="svg", bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()


def _load_daily(db_path: Path, code: str) -> list[tuple[datetime, float, float]]:
    con = _db(db_path)
    try:
        rows = con.execute(
            "SELECT date, close, amount FROM v_daily_bar WHERE code = ? "
            "ORDER BY date DESC LIMIT 250",
            (code,),
        ).fetchall()
    finally:
        con.close()
    return [
        (_ts_to_date(ts), float(close), float(amount))
        for ts, close, amount in reversed(rows)
        if close is not None and amount is not None
    ]


def _load_valuation(db_path: Path, code: str) -> list[tuple[datetime, float | None, float | None]]:
    con = _db(db_path)
    try:
        rows = con.execute(
            "SELECT date, pe_ttm, pb FROM v_valuation_daily WHERE code = ? "
            "ORDER BY date DESC LIMIT 250",
            (code,),
        ).fetchall()
    finally:
        con.close()
    return [
        (
            _ts_to_date(ts),
            float(pe) if pe is not None else None,
            float(pb) if pb is not None else None,
        )
        for ts, pe, pb in reversed(rows)
    ]


def _load_financial(db_path: Path, code: str) -> list[tuple[datetime, float | None, float | None, float | None]]:
    con = _db(db_path)
    try:
        rows = con.execute(
            "SELECT report_date, roe, revenue_yoy, netprofit_yoy FROM v_financial_report "
            "WHERE code = ? ORDER BY report_date DESC LIMIT 8",
            (code,),
        ).fetchall()
    finally:
        con.close()
    return [
        (
            _ts_to_date(ts),
            float(roe) if roe is not None else None,
            float(revenue) if revenue is not None else None,
            float(netprofit) if netprofit is not None else None,
        )
        for ts, roe, revenue, netprofit in reversed(rows)
    ]


def _price_ma_chart(daily: list[tuple[datetime, float, float]]) -> str:
    closes = [v for _, v, _ in daily]
    if len(closes) < 3:
        return ""
    x = list(range(len(closes)))
    fig, ax = plt.subplots(figsize=(7.2, 3.6), dpi=100)
    ax.plot(x, closes, label="收盘价", color="#2e5395", linewidth=1.6)
    ax.axhline(closes[-1], color="#2e5395", linestyle="--", linewidth=1.0, alpha=0.75, label="现价线")
    for name, window, color in (("MA5", 5, "#e07b00"), ("MA20", 20, "#2e7d32"), ("MA60", 60, "#8e24aa")):
        ma = [None] * len(closes)
        for i in range(len(closes)):
            if i + 1 >= window:
                ma[i] = sum(closes[i + 1 - window : i + 1]) / window
        ax.plot(x, ma, label=name, color=color, linewidth=1.2, linestyle="--")
        if ma[-1] is not None:
            ax.axhline(ma[-1], color=color, linestyle="--", linewidth=1.0, alpha=0.75, label=f"{name} 现价线")
    ax.set_title("价格与均线走势", fontsize=13)
    ax.grid(alpha=0.25)
    ax.legend(loc="upper left", ncol=4, fontsize=8)
    ax.set_xticks([x[0], x[len(x) // 2], x[-1]])
    ax.set_xticklabels([daily[0][0].strftime("%m-%d"), daily[len(daily) // 2][0].strftime("%m-%d"), daily[-1][0].strftime("%m-%d")])
    return _fig_svg(fig)


def _volume_price_chart(daily: list[tuple[datetime, float, float]]) -> str:
    if len(daily) < 3:
        return ""
    x = list(range(len(daily)))
    amounts = [amount / 1e8 for _, _, amount in daily]
    closes = [close for _, close, _ in daily]
    fig, ax1 = plt.subplots(figsize=(7.2, 3.6), dpi=100)
    ax1.bar(x, amounts, color="#cfe0f5", label="成交额(亿元)", alpha=0.9)
    ax1.set_ylabel("成交额(亿元)")
    ax2 = ax1.twinx()
    ax2.plot(x, closes, color="#2e5395", label="收盘价", linewidth=1.6)
    ax2.set_ylabel("收盘价")
    ax1.set_title("量价关系", fontsize=13)
    ax1.grid(alpha=0.2, axis="y")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    ax1.set_xticks([x[0], x[len(x) // 2], x[-1]])
    ax1.set_xticklabels([daily[0][0].strftime("%m-%d"), daily[len(daily) // 2][0].strftime("%m-%d"), daily[-1][0].strftime("%m-%d")])
    return _fig_svg(fig)


def _valuation_chart(rows: list[tuple[datetime, float | None, float | None]]) -> str:
    if len(rows) < 3:
        return ""
    x = list(range(len(rows)))
    pe = [v for _, v, _ in rows]
    pb = [v for _, _, v in rows]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11.0, 3.2), dpi=100)
    ax1.plot(x, pe, color="#c62828", linewidth=1.5, label="PE(TTM)")
    ax1.set_ylabel("PE(TTM)")
    ax1.set_title("PE(TTM) 历史走势", fontsize=13)
    ax1.grid(alpha=0.25)
    ax1.legend(fontsize=9, loc="upper left")
    ax1.set_xticks([x[0], x[len(x) // 2], x[-1]])
    ax1.set_xticklabels([rows[0][0].strftime("%m-%d"), rows[len(rows) // 2][0].strftime("%m-%d"), rows[-1][0].strftime("%m-%d")])
    ax2.plot(x, pb, color="#2e7d32", linewidth=1.5, label="PB")
    ax2.set_ylabel("PB")
    ax2.set_title("PB 历史走势", fontsize=13)
    ax2.grid(alpha=0.25)
    ax2.legend(fontsize=9, loc="upper left")
    ax2.set_xticks([x[0], x[len(x) // 2], x[-1]])
    ax2.set_xticklabels([rows[0][0].strftime("%m-%d"), rows[len(rows) // 2][0].strftime("%m-%d"), rows[-1][0].strftime("%m-%d")])
    return _fig_svg(fig)


def _financial_chart(rows: list[tuple[datetime, float | None, float | None, float | None]]) -> str:
    if len(rows) < 2:
        return ""
    labels = [d.strftime("%yQ%m") for d, _, _, _ in rows]
    x = list(range(len(rows)))
    revenue = [v if v is not None else 0 for _, _, v, _ in rows]
    netprofit = [v if v is not None else 0 for _, _, _, v in rows]
    roe = [v if v is not None else 0 for _, v, _, _ in rows]
    fig, ax1 = plt.subplots(figsize=(9.5, 4.0), dpi=100)
    width = 0.35
    ax1.bar([i - width / 2 for i in x], revenue, width=width, label="营收同比%", color="#4e79a7")
    ax1.bar([i + width / 2 for i in x], netprofit, width=width, label="净利同比%", color="#f28e2b")
    ax2 = ax1.twinx()
    ax2.plot(x, roe, color="#e15759", marker="o", label="ROE%")
    ax1.set_xticks(x)
    ax1.set_xticklabels(labels, rotation=30)
    ax1.set_title("财务指标走势", fontsize=13)
    ax1.grid(alpha=0.2, axis="y")
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2, loc="upper left", fontsize=9)
    return _fig_svg(fig)


def _factor_radar_chart(scores: dict[str, float]) -> str:
    if len(scores) < 3:
        return ""
    labels = list(scores)
    values = [scores[k] for k in labels]
    values += values[:1]
    angles = [n / len(labels) * 2 * 3.1415926 for n in range(len(labels))]
    angles += angles[:1]
    fig, ax = plt.subplots(figsize=(3.2, 3.2), dpi=100, subplot_kw=dict(polar=True))
    ax.fill(angles, values, color="#2e5395", alpha=0.25)
    ax.plot(angles, values, color="#2e5395", linewidth=1.8)
    ax.set_xticks(angles[:-1])
    ax.set_xticklabels(labels, fontsize=11)
    ax.set_ylim(0, 100)
    ax.set_title("因子评分雷达", fontsize=13)
    return _fig_svg(fig)


def _win_donut_chart(win_probability: float, risk_level: str) -> str:
    fig, ax = plt.subplots(figsize=(2.4, 2.4), dpi=100)
    ax.pie(
        [win_probability, 100 - win_probability],
        colors=["#2e7d32", "#e8e8e8"],
        startangle=90,
        counterclock=False,
        wedgeprops=dict(width=0.38),
    )
    ax.text(0, 0.08, f"{win_probability:.1f}%", ha="center", va="center", fontsize=15)
    ax.text(0, -0.18, "盈利概率", ha="center", va="center", fontsize=9, color="#555555")
    return _fig_svg(fig)


def _score_ring_chart(score: float) -> str:
    fig, ax = plt.subplots(figsize=(3.2, 3.2), dpi=100)
    ax.pie(
        [score, 100 - score],
        colors=["#2e5395", "#e8e8e8"],
        startangle=90,
        counterclock=False,
        wedgeprops=dict(width=0.38),
    )
    ax.text(0, 0.06, f"{score:.1f}", ha="center", va="center", fontsize=20)
    ax.text(0, -0.16, "综合评分 / 100", ha="center", va="center", fontsize=10, color="#555555")
    ax.set_title("综合评分环", fontsize=13)
    return _fig_svg(fig)


def _extract_meta(md: str) -> dict[str, str]:
    meta: dict[str, str] = {}
    for key in ("股票名称", "股票代码", "所属板块", "报告日期", "投资期限", "综合评分", "风险等级", "投资观点"):
        match = re.search(rf"\| {key} \| ([^|]+) \|", md)
        if match:
            meta[key] = match.group(1).strip()
    return meta


def _parse_factor_scores(md: str) -> dict[str, float]:
    scores: dict[str, float] = {}
    for name in ("动量", "趋势", "风险", "基本面"):
        match = re.search(rf"\| {name} \| \d+% \| ([\d.]+) \|", md)
        if match:
            scores[name] = float(match.group(1))
    return scores


def _parse_prediction(md: str) -> tuple[float | None, str | None]:
    win = None
    risk = None
    m = re.search(r"\| 盈利概率 \| ([\d.]+)% \|", md)
    if m:
        win = float(m.group(1))
    m = re.search(r"\| 风险等级 \| ([^|]+) \|", md)
    if m:
        risk = m.group(1).strip()
    return win, risk


def _parse_score(md: str) -> float | None:
    m = re.search(r"\| 综合评分 \| ([\d.]+)\s*/\s*100 \|", md)
    if m:
        return float(m.group(1))
    return None


def _inline_score_formula(body: str) -> str:
    pattern = re.compile(r"<p>综合评分：</p>\s*<pre><code>(.*?)</code></pre>", flags=re.S)

    def replace(match: re.Match) -> str:
        formula = html.escape(match.group(1).strip())
        return f'<p>综合评分：<span class="formula">{formula}</span></p>'

    return pattern.sub(replace, body)


def _split_prediction_section(body: str) -> str:
    pattern = re.compile(
        r'(<h2 id="sec-\d+">3\.4 未来收益预测</h2>)'
        r'(<figure[^>]*>.*?</figure>)'
        r'(\s*<p><strong>预测方法</strong></p>\s*<p>.*?</p>)',
        flags=re.S,
    )

    def replace(match: re.Match) -> str:
        return (
            match.group(1)
            + '<div class="split">'
            + f'<div class="split-left">{match.group(2)}</div>'
            + f'<div class="split-right">{match.group(3)}</div>'
            + "</div>"
        )

    return pattern.sub(replace, body)


def _un_numbered_disclaimer(body: str) -> str:
    pattern = re.compile(r'<h2 id="(sec-\d+)">3\.6 免责声明与合规说明</h2>')
    return pattern.sub(r'<h1 id="\1">免责声明与合规说明</h1>', body)


def _strip_title_paragraph(body: str, title: str) -> str:
    pattern = re.compile(rf'^<p><strong>{re.escape(title)}</strong></p>\s*')
    return pattern.sub("", body, count=1)


def _css() -> str:
    return """
<style>
  :root { --blue:#2e5395; --dark:#1f3864; --bg:#f5f7fa; }
  * { box-sizing: border-box; }
  body { margin:0; padding:32px; background:var(--bg); color:#333;
         font-family:"Noto Sans CJK SC","PingFang SC","Microsoft YaHei",sans-serif; }
  .container { max-width:1000px; margin:0 auto; background:#fff; border-radius:14px;
               box-shadow:0 6px 24px rgba(31,56,100,.10); padding:48px 56px; }
  .report-header { border-bottom:3px solid var(--blue); padding-bottom:18px; margin-bottom:28px; }
  .report-header h1 { margin:0; color:var(--dark); font-size:30px; border-bottom:none; }
  .report-header .sub { color:#667; margin-top:8px; font-size:14px; }
  .cards { display:flex; gap:16px; margin:24px 0 8px; }
  .card { flex:1; background:#f0f5ff; border:1px solid #d5e2ff; border-radius:12px;
          padding:18px; text-align:center; }
  .card .label { font-size:13px; color:#667; }
  .card .value { font-size:24px; font-weight:bold; color:var(--dark); margin-top:6px; }
  .toc { background:#f7f9fd; border:1px solid #e3e9f4; border-radius:10px;
         padding:16px 24px; margin:24px 0; }
  .toc a { color:var(--blue); text-decoration:none; margin-right:16px; }
  h1 { color:var(--dark); font-size:26px; border-bottom:2px solid var(--blue);
       padding-bottom:8px; margin:42px 0 18px; }
  h2 { color:var(--blue); font-size:21px; margin:34px 0 14px; }
  table { width:100%; border-collapse:collapse; margin:16px 0; }
  th { background:var(--blue); color:#fff; padding:9px 12px; text-align:left;
       font-weight:normal; }
  td { border:1px solid #dde3ec; padding:8px 12px; }
  tr:nth-child(even) td { background:#f7f9fd; }
  p { line-height:1.8; margin:12px 0; }
  figure { margin:28px 0; text-align:center; }
  figure svg { max-width:100%; height:auto; }
  .figure-row { display:flex; gap:16px; margin:28px 0; align-items:flex-start; }
  .figure-row > figure { flex:1 1 0; min-width:0; margin:0; }
  .figure-row > figure svg { height:215px; width:auto; max-width:100%; margin:0 auto; }
  .split { display:flex; gap:24px; margin:28px 0; align-items:flex-start; }
  .split-left { flex:0 0 42%; min-width:0; }
  .split-left figure svg { height:180px; width:auto; max-width:100%; margin:0 auto; }
  .split-right { flex:1 1 auto; min-width:0; }
  .split-right p:first-child { margin-top:0; }
  .formula { font-family:"SFMono-Regular",Consolas,"Liberation Mono",Menlo,monospace;
             background:#f3f5f9; border:1px solid #e3e9f4; border-radius:6px;
             padding:2px 8px; font-size:14px; color:var(--dark); }
  @media (max-width: 760px) {
    .figure-row, .split { flex-direction:column; }
    .split-left { flex:1 1 auto; }
    .split-left figure svg { height:auto; width:100%; }
    .figure-row > figure svg { height:auto; width:100%; }
  }
  .footer { margin-top:40px; padding-top:16px; border-top:1px solid #e3e9f4;
            color:#889; font-size:12px; }
</style>
"""


def _inject_figures(html: str, figures: dict[str, str]) -> tuple[str, list[tuple[int, str]]]:
    counter = 0
    toc: list[tuple[int, str]] = []

    def replace_heading(match: re.Match) -> str:
        nonlocal counter
        counter += 1
        level = int(match.group(1))
        text = match.group(2)
        toc.append((level, text))
        extra = figures.get(text, "")
        return f'<h{level} id="sec-{counter}">{text}</h{level}>{extra}'

    return re.sub(r"<h([12])>(.*?)</h\1>", replace_heading, html, flags=re.S), toc


def render_report_html(md: str, db_path: Path, code: str) -> str:
    daily = _load_daily(db_path, code)
    valuation = _load_valuation(db_path, code)
    financial = _load_financial(db_path, code)
    scores = _parse_factor_scores(md)
    win_probability, risk_level = _parse_prediction(md)
    score = _parse_score(md)

    figures: dict[str, str] = {}
    price = _price_ma_chart(daily)
    volume = _volume_price_chart(daily)
    if price or volume:
        charts = [f'<figure class="chart">{svg}</figure>' for svg in (price, volume) if svg]
        figures["3.1 行情与量价"] = (
            f'<div class="figure-row">{"".join(charts)}</div>'
            if len(charts) == 2
            else "".join(charts)
        )
    valuation_svg = _valuation_chart(valuation)
    financial_svg = _financial_chart(financial)
    charts = [f'<figure class="chart">{svg}</figure>' for svg in (valuation_svg, financial_svg) if svg]
    if charts:
        figures["3.2 财务与估值"] = "".join(charts)
    if scores:
        charts = []
        radar = _factor_radar_chart(scores)
        if radar:
            charts.append(f'<figure class="chart">{radar}</figure>')
        if score is not None:
            charts.append(f'<figure class="chart">{_score_ring_chart(score)}</figure>')
        if charts:
            figures["3.3 综合评分明细"] = (
                f'<div class="figure-row">{"".join(charts)}</div>'
                if len(charts) == 2
                else "".join(charts)
            )
    if win_probability is not None:
        figures["3.4 未来收益预测"] = f'<figure class="chart">{_win_donut_chart(win_probability, risk_level or "未知")}</figure>'

    meta = _extract_meta(md)
    title = f'{meta.get("股票名称", code)}（{meta.get("股票代码", code)}）量化投资研报'

    body = markdown_to_html(md, extensions=["table"])
    body, _ = _inject_figures(body, figures)
    body = _inline_score_formula(body)
    body = _split_prediction_section(body)
    body = _un_numbered_disclaimer(body)
    body = _strip_title_paragraph(body, title)

    cards = f"""
      <div class="cards">
        <div class="card"><div class="label">综合评分</div><div class="value">{meta.get("综合评分", "N/A")}</div></div>
        <div class="card"><div class="label">风险等级</div><div class="value">{meta.get("风险等级", "N/A")}</div></div>
        <div class="card"><div class="label">投资观点</div><div class="value">{meta.get("投资观点", "N/A")}</div></div>
      </div>
    """
    header = f"""
      <div class="report-header">
        <h1>{title}</h1>
        <div class="sub">
          {meta.get("所属板块", "")} · 报告日期 {meta.get("报告日期", "")} · 投资期限 {meta.get("投资期限", "")}
        </div>
      </div>
    """
    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{meta.get("股票名称", code)}（{meta.get("股票代码", code)}）量化投资研报</title>
{_css()}
</head>
<body>
<div class="container">
  {header}
  {cards}
  {body}
  <div class="footer">本报告基于公开历史数据与量化模型生成，仅用于研究分析，不构成投资建议。</div>
</div>
</body>
</html>
"""
