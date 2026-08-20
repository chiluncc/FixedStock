from __future__ import annotations

import re

from openjiuwen.core.foundation.tool import tool

from stock.structures.config import Config
from stock.structures.report import StockReport
from stock.utils.tools.sql import sql_query


VIEWS = (
    "v_stock_basic",
    "v_trade_calendar",
    "v_daily_bar",
    "v_financial_report",
    "v_valuation_daily",
    "v_index_bar",
)
SCHEMA_SQL = f"""
SELECT m.name AS view_name, p.name AS column_name, p.type AS column_type
FROM sqlite_master m
JOIN pragma_table_info(m.name) p
WHERE m.type = 'view' AND m.name IN ({", ".join(f"'{v}'" for v in VIEWS)})
ORDER BY m.name, p.cid
"""


def _validate_summary(txt: str) -> str | None:
    for line in txt.splitlines():
        if re.match(r"^#+\s+", line):
            return "摘要中不允许出现 Markdown 标题，请去掉所有以 # 开头的行后重新提交"
    return None


def _analysis_titles() -> list[str]:
    return [
        "投资要点",
        "盈利预测与投资建议",
        "风险提示",
    ]


def _validate_analysis(txt: str) -> str | None:
    for line in txt.splitlines():
        if re.match(r"^#+\s+", line):
            return "投资分析中不允许出现 Markdown 标题，请使用加粗小标题格式重写"

    expected = _analysis_titles()
    blocks: list[tuple[str, list[str]]] = []
    current_title: str | None = None
    current_body: list[str] = []
    for raw_line in txt.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = re.match(r"^\*\*(.+?)\*\*\s*$", line)
        if match:
            if current_title is not None:
                blocks.append((current_title, current_body))
            current_title = match.group(1).strip().rstrip("：:")
            current_body = []
        else:
            if current_title is None:
                return "投资分析中每个段落必须以 `**标题**` 开头，请按格式重写"
            current_body.append(line)
    if current_title is not None:
        blocks.append((current_title, current_body))

    if not blocks:
        return "投资分析内容为空，请按格式重新提交"

    seen: set[str] = set()
    for title, body in blocks:
        if title not in expected:
            return f"投资分析中存在未知段落标题：**{title}**，请只使用规定标题"
        if title in seen:
            return f"投资分析中段落标题重复：**{title}**"
        if not body:
            return f"投资分析段落 `**{title}**` 缺少正文"
        seen.add(title)
        for body_line in body:
            if re.match(r"^\*\*.+?\*\*\s*$", body_line.strip()):
                return "投资分析正文中不允许出现独立加粗标题"

    missing = [title for title in expected if title not in seen]
    if missing:
        return f"投资分析缺少以下段落：{'、'.join(f'**{t}**' for t in missing)}，请补充后重新提交"
    return None


def get_tools(config: Config, report: StockReport) -> list:
    db_path = config.local_data_dir / "market.db"

    @tool
    def write_summary(txt: str) -> str:
        """
        编写投资研报摘要。

        Args:
            txt: 投资研报摘要正文。
        """
        error = _validate_summary(txt)
        if error is not None:
            return f"摘要未保存：{error}"
        report.investment_summary = txt
        return "投资研报摘要已保存"

    @tool
    def write_analysis(txt: str) -> str:
        """
        编写投资研报分析。

        Args:
            txt: 投资研报分析正文。
        """
        error = _validate_analysis(txt)
        if error is not None:
            return f"分析未保存：{error}"
        report.investment_analysis = txt
        return "投资研报分析已保存"

    @tool
    def view_autobuild_report() -> str:
        """
        查看当前自动生成的研报全文。
        """
        return report.as_md()

    @tool
    def sql_schema_show() -> str:
        """
        查看数据库视图结构，包括列名与类型。
        """
        result = sql_query(db_path, SCHEMA_SQL, limit=None)
        return result.error_str if result.error else result.result

    @tool
    def sql_query_execute(sql: str) -> str:
        """
        执行只读 SQL 查询并返回结果，
        结果若超过32行将被截断

        Args:
            sql: 只读 SQL 查询语句。
        """
        result = sql_query(db_path, sql, limit=32)
        return result.error_str if result.error else result.result

    return [write_summary, write_analysis, view_autobuild_report, sql_schema_show, sql_query_execute]
