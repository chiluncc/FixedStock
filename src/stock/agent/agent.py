from __future__ import annotations

import asyncio
import logging
import random
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

MAX_LLM_ITERATIONS = 64
MAX_OUTER_ROUNDS = 3
LLM_RETRY_DELAYS = (2.0, 4.0, 8.0, 8.0, 8.0)


class ReportAgent:
    def __init__(self, config: Config, logger: logging.Logger | None = None) -> None:
        self.config = config
        self.logger = get_default_logger(logger)
        self._llm_call_count = 0

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
            AgentCallbackEvent.AFTER_MODEL_CALL,
            self._on_after_model_call,
        )
        return agent

    async def _invoke_once(
        self,
        agent: ReActAgent,
        session: Any,
        user_prompt: str,
    ) -> None:
        result = None
        retries = len(LLM_RETRY_DELAYS)
        for attempt in range(retries + 1):
            try:
                result = await agent.invoke(user_prompt, session=session)
                break
            except Exception as exc:
                if attempt >= retries:
                    raise
                delay = LLM_RETRY_DELAYS[attempt]
                wait = 2.0 + random.uniform(0.0, max(0.0, delay - 2.0))
                self.logger.warning(
                    "模型调用失败，%.1fs 后重试（第 %d/%d 次）: %s",
                    wait,
                    attempt + 1,
                    retries,
                    exc,
                )
                await asyncio.sleep(wait)
        if isinstance(result, dict):
            output = result.get("output", "")
            if output:
                self.logger.debug("LLM 最终答复: %s", output)

    async def _on_after_model_call(self, ctx: AgentCallbackContext) -> None:
        self._llm_call_count += 1
        response = getattr(getattr(ctx, "inputs", None), "response", None)
        reasoning = getattr(response, "reasoning_content", None)
        if reasoning:
            content = str(reasoning).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
            self.logger.debug(
                "第 %d 轮 [LLM]: %s",
                self._llm_call_count,
                content,
            )
        tool_calls = getattr(response, "tool_calls", None) or []
        tool_names = [
            getattr(tc, "name", "")
            for tc in tool_calls
            if getattr(tc, "name", None)
        ]
        if tool_names:
            self.logger.debug(
                "第 %d 轮 [Tool]: %s",
                self._llm_call_count,
                "; ".join(tool_names),
            )
