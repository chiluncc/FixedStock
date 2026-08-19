from __future__ import annotations

from openjiuwen.core.foundation.tool import tool

from stock.structures.report import StockReport
from stock.structures.config import Config


def get_tools(config: Config, report: StockReport) -> list:

    @tool
    def write_summary(txt: str) -> str:
        """
        """
        pass


    @tool
    def write_analysis(txt: str) -> str:
        """
        """
        pass


    @tool
    def view_autobuild_report() -> str:
        """
        """
        pass


    @tool
    def sql_schema_show() -> str:
        """
        """
        pass


    @tool
    def sql_query_execute(sql: str) -> str:
        """
        """
        pass

    return [write_summary, write_analysis, view_autobuild_report, sql_schema_show, sql_query_execute]