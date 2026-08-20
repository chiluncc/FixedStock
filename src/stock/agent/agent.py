from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from openjiuwen.core.common.logging.log_config import configure_log_config

configure_log_config(
    {
        "backend": "default",
        "level": "ERROR",
        "log_path": "/tmp/jiuwen_logs",
        "output": ["console"],
        "interface_output": ["console"],
        "performance_output": ["console"],
    }
)

from openjiuwen.core.session.agent import create_agent_session
from openjiuwen.core.single_agent import AgentCard, ReActAgent, ReActAgentConfig
from openjiuwen.core.single_agent.rail.base import (
    AgentCallbackContext,
    AgentCallbackEvent,
)

from stock.agent.prompt import SYSTEM_PROMPT, build_user_prompt
from stock.agent.tool import get_tools
from stock.structures.config import Config
from stock.structures.report import StockReport
from stock.utils.file_handles import get_default_logger, keys_llm_load

MAX_LLM_ITERATIONS = 32
MAX_OUTER_ROUNDS = 3


class ReportAgent:
    def __init__(self, config: Config, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = get_default_logger(logger)
        self._llm_call_count = 0
        self._last_model_start = 0.0

    def __call__(self, report: StockReport) -> StockReport | None:
        if report.investment_summary is not None and report.investment_analysis is not None:
            self.logger.info("研报字段已齐全，直接返回: %s(%s)", report.name, report.code)
            return report
        try:
            return asyncio.run(self._run(report))
        except Exception as exc:
            self.logger.warning("研报生成失败: %s(%s): %s", report.name, report.code, exc, exc_info=True)
            return None

    async def _run(self, report: StockReport) -> StockReport | None:
        self.logger.info("开始生成研报: %s(%s)", report.name, report.code)
        self._llm_call_count = 0
        self._last_model_start = 0.0
        agent = await self._build_agent(report)
        session = create_agent_session(session_id=f"report_{report.code}", card=agent.card)
        user_prompt = build_user_prompt(
            name=report.name,
            code=report.code,
            sector=report.sector,
            report_date=report.report_date.strftime("%Y-%m-%d"),
            holding_days=report.holding_days,
        )

        for outer_index in range(MAX_OUTER_ROUNDS):
            round_start = time.monotonic()
            self.logger.info("外循环第 %d 轮开始", outer_index + 1)
            await self._invoke_once(agent, session, user_prompt)
            self.logger.info(
                "外循环第 %d 轮结束，耗时 %.2fs",
                outer_index + 1,
                time.monotonic() - round_start,
            )

            if report.investment_summary is not None and report.investment_analysis is not None:
                self.logger.info("研报生成完成: %s(%s)", report.name, report.code)
                return report

            missing = []
            if report.investment_summary is None:
                missing.append("投资观点摘要")
            if report.investment_analysis is None:
                missing.append("投资分析")
            self.logger.warning(
                "第 %d 轮后仍缺少: %s，将注入补充提示",
                outer_index + 1,
                "、".join(missing),
            )
            user_prompt = (
                f"你尚未完成以下内容：{'、'.join(missing)}。"
                "调用对应工具补齐内容"
            )

        self.logger.warning("经过 %d 轮仍未完成研报: %s(%s)", MAX_OUTER_ROUNDS, report.name, report.code)
        return None

    async def _build_agent(self, report: StockReport) -> ReActAgent:
        keys = keys_llm_load()
        api_key = keys["deepseek"]
        agent = ReActAgent(
            card=AgentCard(name="report_agent", description="个股量化投资研报撰写助手")
        )
        config = (
            ReActAgentConfig()
            .configure_model_client(
                provider="DeepSeek",
                api_key=api_key,
                api_base="https://api.deepseek.com",
                model_name="deepseek-v4-flash",
                verify_ssl=True,
            )
            .configure_prompt_template([{"role": "system", "content": SYSTEM_PROMPT}])
            .configure_max_iterations(MAX_LLM_ITERATIONS)
        )
        agent.configure(config)
        for tool in get_tools(self.config, report):
            agent.ability_manager.add_ability(tool.card, tool)
        await agent.register_callback(
            AgentCallbackEvent.BEFORE_MODEL_CALL,
            self._on_before_model_call,
        )
        await agent.register_callback(
            AgentCallbackEvent.AFTER_MODEL_CALL,
            self._on_after_model_call,
        )
        await agent.register_callback(
            AgentCallbackEvent.AFTER_TOOL_CALL,
            self._on_after_tool_call,
        )
        return agent

    async def _invoke_once(
        self,
        agent: ReActAgent,
        session: Any,
        user_prompt: str,
    ) -> None:
        result = await agent.invoke(user_prompt, session=session)
        if isinstance(result, dict):
            output = result.get("output", "")
            if output:
                self.logger.debug("LLM 最终答复: %s", output)

    async def _on_before_model_call(self, ctx: AgentCallbackContext) -> None:
        self._last_model_start = time.monotonic()

    async def _on_after_model_call(self, ctx: AgentCallbackContext) -> None:
        elapsed = time.monotonic() - self._last_model_start
        self._llm_call_count += 1
        response = getattr(getattr(ctx, "inputs", None), "response", None)
        tool_calls = getattr(response, "tool_calls", None) or []
        tool_summary = [
            f"{tc.name}({tc.arguments})"
            for tc in tool_calls
            if getattr(tc, "name", None)
        ]
        self.logger.debug(
            "LLM 第 %d 次调用完成，耗时 %.2fs，工具调用: %s",
            self._llm_call_count,
            elapsed,
            "、".join(tool_summary) if tool_summary else "无",
        )

    async def _on_after_tool_call(self, ctx: AgentCallbackContext) -> None:
        inputs = getattr(ctx, "inputs", None)
        tool_name = getattr(inputs, "tool_name", "")
        tool_args = getattr(inputs, "tool_args", None)
        if isinstance(tool_args, dict):
            tool_args = json.dumps(tool_args, ensure_ascii=False)
        self.logger.debug("工具调用完成: %s(%s)", tool_name, tool_args)
        tool_result = getattr(inputs, "tool_result", None)
        if getattr(tool_result, "error", False):
            self.logger.warning(
                "工具调用返回错误: %s: %s",
                tool_name,
                getattr(tool_result, "error_str", ""),
            )
