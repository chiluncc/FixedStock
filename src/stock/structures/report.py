from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from enum import Enum


class MaAlignment(str, Enum):
    BULLISH = "多头排列"
    BEARISH = "空头排列"
    MIXED = "纠缠"


class RiskLevel(str, Enum):
    LOW = "低"
    MID_LOW = "中低"
    MEDIUM = "中等"
    MID_HIGH = "中高"
    HIGH = "高"


class InvestmentView(str, Enum):
    BULLISH = "偏多"
    NEUTRAL = "中性"
    BEARISH = "偏空"


@dataclass(frozen=True)
class PricePerformance:
    current_price: float
    return_5d: float
    return_20d: float
    return_60d: float
    return_250d: float
    position_pct: float


@dataclass(frozen=True)
class TrendIndicators:
    ma5: float
    ma20: float
    ma60: float
    alignment: MaAlignment
    above_ma5: bool
    above_ma20: bool
    above_ma60: bool


@dataclass(frozen=True)
class MomentumIndicators:
    return_20d: float
    return_60d: float


@dataclass(frozen=True)
class ActivityIndicators:
    amount_ratio_5_20: float
    turnover: float
    activity_score: float


@dataclass(frozen=True)
class VolatilityIndicators:
    annualized_vol_20d: float
    max_drawdown_20d: float
    max_drawdown_250d: float
    downside_5pct: float


@dataclass(frozen=True)
class FinancialQuality:
    report_date: date | None
    roe: float | None
    revenue_yoy: float | None
    netprofit_yoy: float | None
    gross_margin: float | None
    debt_ratio: float | None
    quality_score: float


@dataclass(frozen=True)
class ValuationIndicators:
    pe_ttm: float | None
    pb: float | None
    pe_percentile: float | None
    pb_percentile: float | None
    valuation_score: float


@dataclass(frozen=True)
class FactorScores:
    momentum: float
    trend: float
    risk: float
    fundamental: float


@dataclass(frozen=True)
class Conclusion:
    composite_score: float
    risk_severity: int
    risk_level: RiskLevel
    adjusted_score: float
    investment_view: InvestmentView


@dataclass(frozen=True)
class PredictionResult:
    sample_count: int
    sample_sufficient: bool
    mean_return: float
    win_probability: float
    downside_5pct: float
    avg_max_drawdown: float
    expected_low: float
    expected_high: float


@dataclass(frozen=True)
class RiskAnalysis:
    correlation_csi300: float
    beta_csi300: float
    annualized_vol_20d: float
    downside_5pct: float
    avg_amount_20d: float


@dataclass
class StockReport:
    code: str
    name: str
    sector: str | None
    report_date: date
    holding_days: int

    price: PricePerformance
    trend: TrendIndicators
    momentum: MomentumIndicators
    activity: ActivityIndicators
    volatility: VolatilityIndicators
    financial: FinancialQuality
    valuation: ValuationIndicators
    factors: FactorScores
    conclusion: Conclusion
    prediction: PredictionResult
    risk: RiskAnalysis

    investment_summary: str | None
    investment_analysis: str | None

    def as_md(self) -> str:
        def _num(value: float | None, digits: int = 2) -> str:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return "N/A"
            return f"{value:.{digits}f}"

        def _pct(value: float | None, digits: int = 2) -> str:
            if value is None or (isinstance(value, float) and math.isnan(value)):
                return "N/A"
            return f"{value:.{digits}f}%"

        def _position(above: bool) -> str:
            return "上方" if above else "下方"

        sector = self.sector or "-"
        report_date = self.report_date.strftime("%Y-%m-%d")
        summary = self.investment_summary if self.investment_summary is not None else "<investment_summary>尚未完成</investment_summary>"
        analysis = self.investment_analysis if self.investment_analysis is not None else "<investment_analysis>尚未完成</investment_analysis>"

        parts = [
            f"**{self.name}（{self.code}）量化投资研报**",
            "",
            "# 一、股票介绍",
            "",
            "| 项目 | 内容 |",
            "|---|---|",
            f"| 股票名称 | {self.name} |",
            f"| 股票代码 | {self.code} |",
            f"| 所属板块 | {sector} |",
            f"| 报告日期 | {report_date} |",
            f"| 投资期限 | {self.holding_days} 个交易日 |",
            "",
            f"本报告对该股票进行独立的量化分析，重点评估其未来 {self.holding_days} 个交易日内的价格趋势、量价结构、风险特征、财务质量与估值水平。",
            "",
            "# 二、投资研报",
            "",
            "## 2.1 投资观点摘要",
            "",
            "| 项目 | 结论 |",
            "|---|---|",
            f"| 综合评分 | {_num(self.conclusion.composite_score, 1)} / 100 |",
            f"| 风险等级 | {self.conclusion.risk_level.value} |",
            f"| 投资观点 | {self.conclusion.investment_view.value} |",
            "",
            summary,
            "",
            "## 2.2 投资分析",
            "",
            analysis,
            "",
            "# 三、详细信息",
            "",
            "## 3.1 行情与量价",
            "",
            "**历史价格表现**",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| 当前价格 | {_num(self.price.current_price)} 元 |",
            f"| 近 5 交易日涨跌幅 | {_pct(self.price.return_5d)} |",
            f"| 近 20 交易日涨跌幅 | {_pct(self.price.return_20d)} |",
            f"| 近 60 交易日涨跌幅 | {_pct(self.price.return_60d)} |",
            f"| 近 250 交易日涨跌幅 | {_pct(self.price.return_250d)} |",
            "",
            f"当前价格在近 250 日区间中处于 {_num(self.price.position_pct, 1)}% 分位。近 5、20、60、250 个交易日的涨跌幅分别为 {_pct(self.price.return_5d)}、{_pct(self.price.return_20d)}、{_pct(self.price.return_60d)}、{_pct(self.price.return_250d)}。",
            "",
            "**趋势指标**",
            "",
            "| 指标 | 当前值 | 位置判断 |",
            "|---|---:|---|",
            f"| MA5 | {_num(self.trend.ma5)} | 股价位于其 {_position(self.trend.above_ma5)} |",
            f"| MA20 | {_num(self.trend.ma20)} | 股价位于其 {_position(self.trend.above_ma20)} |",
            f"| MA60 | {_num(self.trend.ma60)} | 股价位于其 {_position(self.trend.above_ma60)} |",
            f"| 均线排列 | {self.trend.alignment.value} | 趋势状态 |",
            "",
            f"当前均线呈{self.trend.alignment.value}，股价分别位于 MA5、MA20、MA60 的{_position(self.trend.above_ma5)}、{_position(self.trend.above_ma20)}、{_position(self.trend.above_ma60)}。",
            "",
            "**动量指标**",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| 20 日收益率 | {_pct(self.momentum.return_20d)} |",
            f"| 60 日收益率 | {_pct(self.momentum.return_60d)} |",
            "",
            f"20 日收益率为 {_pct(self.momentum.return_20d)}，60 日收益率为 {_pct(self.momentum.return_60d)}。",
            "",
            "**成交活跃度**",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| 近 5 日平均成交额 / 近 20 日平均成交额 | {_num(self.activity.amount_ratio_5_20)} |",
            f"| 当前换手率 | {_pct(self.activity.turnover)} |",
            f"| 成交活跃度评分 | {_num(self.activity.activity_score, 1)} / 100 |",
            "",
            f"近 5 日与近 20 日平均成交额比值为 {_num(self.activity.amount_ratio_5_20)}，当前换手率为 {_pct(self.activity.turnover)}，成交活跃度评分为 {_num(self.activity.activity_score, 1)} 分。",
            "",
            "**波动风险**",
            "",
            "| 指标 | 数值 |",
            "|---|---:|",
            f"| 近 {self.holding_days} 日年化波动率 | {_pct(self.volatility.annualized_vol_20d)} |",
            f"| 近 {self.holding_days} 日最大回撤 | {_pct(self.volatility.max_drawdown_20d)} |",
            f"| 近 250 日最大回撤 | {_pct(self.volatility.max_drawdown_250d)} |",
            f"| 最差 5% 分位 | {_pct(self.volatility.downside_5pct)} |",
            "",
            f"近 {self.holding_days} 日年化波动率为 {_pct(self.volatility.annualized_vol_20d)}，近 {self.holding_days} 日最大回撤为 {_pct(self.volatility.max_drawdown_20d)}，近 250 日最大回撤为 {_pct(self.volatility.max_drawdown_250d)}，最差 5% 分位为 {_pct(self.volatility.downside_5pct)}。",
            "",
            "## 3.2 财务与估值",
            "",
            "**财务质量**",
            "",
            "| 指标 | 最新报告期数值 |",
            "|---|---:|",
            f"| 报告期 | {self.financial.report_date.strftime('%Y-%m-%d') if self.financial.report_date else 'N/A'} |",
            f"| ROE | {_pct(self.financial.roe)} |",
            f"| 营收同比增长率 | {_pct(self.financial.revenue_yoy)} |",
            f"| 归母净利润同比增长率 | {_pct(self.financial.netprofit_yoy)} |",
            f"| 毛利率 | {_pct(self.financial.gross_margin)} |",
            f"| 资产负债率 | {_pct(self.financial.debt_ratio)} |",
            "",
            f"最新报告期 ROE 为 {_pct(self.financial.roe)}，营收同比增长 {_pct(self.financial.revenue_yoy)}，归母净利润同比增长 {_pct(self.financial.netprofit_yoy)}，毛利率 {_pct(self.financial.gross_margin)}，资产负债率 {_pct(self.financial.debt_ratio)}。",
            "",
            "**估值水平**",
            "",
            "| 指标 | 当前值 | 自身近 5 年分位 |",
            "|---|---:|---:|",
            f"| PE(TTM) | {_num(self.valuation.pe_ttm)} 倍 | {_pct(self.valuation.pe_percentile, 1)} |",
            f"| PB | {_num(self.valuation.pb)} 倍 | {_pct(self.valuation.pb_percentile, 1)} |",
            "",
            f"PE(TTM) 为 {_num(self.valuation.pe_ttm)} 倍，PB 为 {_num(self.valuation.pb)} 倍，分别处于自身近 5 年的 {_pct(self.valuation.pe_percentile, 1)} 和 {_pct(self.valuation.pb_percentile, 1)} 分位。",
            "",
            "## 3.3 综合评分明细",
            "",
            "| 因子 | 权重 | 得分 |",
            "|---|---:|---:|",
            f"| 动量 | 35% | {_num(self.factors.momentum, 1)} |",
            f"| 趋势 | 25% | {_num(self.factors.trend, 1)} |",
            f"| 风险 | 20% | {_num(self.factors.risk, 1)} |",
            f"| 基本面 | 20% | {_num(self.factors.fundamental, 1)} |",
            "",
            "综合评分：",
            "",
            "```",
            "Score = 0.35 × 动量 + 0.25 × 趋势 + 0.20 × 风险 + 0.20 × 基本面",
            "```",
            "",
            f"综合评分为 {_num(self.conclusion.composite_score, 1)} / 100。",
            "",
            "## 3.4 未来收益预测",
            "",
            "**预测方法**",
            "",
            f"基于历史样本，按动量、波动、趋势等特征筛选与当前状态相近的历史窗口，统计这些窗口之后 {self.holding_days} 个交易日的收益分布。该方法输出的是历史条件下的收益区间估计，不是确定性预测。",
            "",
            "**统计结果**",
            "",
            "| 指标 | 结果 |",
            "|---|---:|",
            f"| 相似状态样本数 | {self.prediction.sample_count} 次 |",
            f"| {self.holding_days} 日平均收益 | {_pct(self.prediction.mean_return)} |",
            f"| 盈利概率 | {_pct(self.prediction.win_probability, 1)} |",
            f"| 最差 5% 分位 | {_pct(self.prediction.downside_5pct)} |",
            f"| 平均最大回撤 | {_pct(self.prediction.avg_max_drawdown)} |",
            "",
            f"相似状态样本数为 {self.prediction.sample_count} 次，{'样本量充足' if self.prediction.sample_sufficient else '样本量偏少'}；平均收益为 {_pct(self.prediction.mean_return)}，盈利概率为 {_pct(self.prediction.win_probability, 1)}。",
            "",
            "**预测结论**",
            "",
            "| 项目 | 结果 |",
            "|---|---|",
            f"| 预期收益区间 | {_pct(self.prediction.expected_low)} ~ {_pct(self.prediction.expected_high)} |",
            f"| 上涨概率 | {_pct(self.prediction.win_probability, 1)} |",
            f"| 风险等级 | {self.conclusion.risk_level.value} |",
            "",
            "## 3.5 风险分析",
            "",
            "| 风险类别 | 度量指标 | 当前水平 | 对持有期的影响 |",
            "|---|---:|---|---|",
            f"| 系统性风险 | 与沪深 300 近一年相关性 | {_num(self.risk.correlation_csi300)} | 大盘调整时跟随下跌的程度 |",
            f"| 波动风险 | 近 {self.holding_days} 日年化波动率 | {_pct(self.risk.annualized_vol_20d)} | 持有期内价格的震荡幅度 |",
            f"| 下行风险 | 最差 5% 分位 | {_pct(self.risk.downside_5pct)} | 最坏情景下的浮亏水平 |",
            f"| 流动性风险 | 近 {self.holding_days} 日日均成交额 | {_num(self.risk.avg_amount_20d / 1e8)} 亿元 | 进出场成本与停牌风险 |",
            "",
            f"该股近一年与沪深 300 相关性为 {_num(self.risk.correlation_csi300)}，beta 为 {_num(self.risk.beta_csi300)}。",
            "",
            "## 3.6 免责声明与合规说明",
            "",
            "1. 本报告基于公开历史数据与量化模型生成，仅用于研究分析，不构成投资建议。",
            "2. 历史统计不代表未来收益，实际结果可能受市场环境与突发事件影响。",
            "3. 报告完成后，后续市场走势不用于回溯调整任何结论。",
        ]
        return "\n".join(parts)
