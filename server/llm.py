"""LLM 调用层 —— 走 LangChain 统一调度 + 结构化输出。

特性：
- 按角色卡（character_id）路由到对应 LLM（anthropic / openai）
- 用 .with_structured_output() 直接吃 Pydantic schema，免去 JSON 抠取
- base_url 可选（走代理/中转），从 env 读取
- 任何错误（API / 校验 / 业务约束）都走 fallback：叫分=0、出牌=pass

注意：本模块只做 LLM 通信 + 输出 schema 校验。
"LLM 给的 cards 是否合法牌型 / 能不能压上家" 由 game.py 在 commit 阶段
用 cards.validate_play() 校验，本模块不重复做。
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from typing import Any

from pydantic import ValidationError

from .characters import Character, get_character
from .prompts import build_bid_prompt, build_play_prompt
from .schemas import LLMBidDecision, LLMPlayDecision, PlayerView


DEFAULT_TEMPERATURE = 0.3
# 总 output 上限：底层 thinking 已关闭；这里仍保持统一预算，避免某些模型 JSON 输出被截断。
DEFAULT_MAX_TOKENS = 6000


# ============================================================
# 模型构造（按 character_id 缓存）
# ============================================================

def _resolve_base_url(char: Character) -> str:
    """优先用 base_url_env 指向的环境变量；env 没设则用 default_base_url。"""
    if char.base_url_env:
        if val := os.environ.get(char.base_url_env):
            return val
    return char.default_base_url


@lru_cache(maxsize=16)
def _get_chat_model(character_id: str):
    """构造一个 LangChain ChatModel。结果缓存避免每次请求都重建。

    api_kind="anthropic" → ChatAnthropic
    api_kind="openai_compat" → ChatOpenAI（含 OpenAI 官方、DashScope 中转的所有第三方）
    """
    char = get_character(character_id)
    api_key = os.environ.get(char.api_key_env)
    if not api_key:
        raise KeyError(f"角色 {char.id} 需要环境变量 {char.api_key_env}，但未设置")

    if char.api_kind == "anthropic":
        from langchain_anthropic import ChatAnthropic
        kwargs: dict[str, Any] = {
            "model": char.model_name,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "api_key": api_key,
        }
        if base_url := _resolve_base_url(char):
            kwargs["base_url"] = base_url
        if char.extra_body:
            kwargs.update(char.extra_body)
        return ChatAnthropic(**kwargs)

    if char.api_kind == "openai_compat":
        from langchain_openai import ChatOpenAI
        kwargs = {
            "model": char.model_name,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens": DEFAULT_MAX_TOKENS,
            "api_key": api_key,
        }
        if base_url := _resolve_base_url(char):
            kwargs["base_url"] = base_url
        # OpenAI 官方 Chat Completions 用 reasoning_effort；DashScope 等兼容端点
        # 仍用 extra_body 传 enable_thinking 这类供应商私有参数。
        if char.extra_body:
            extra_body = dict(char.extra_body)
            if reasoning_effort := extra_body.pop("reasoning_effort", None):
                kwargs["reasoning_effort"] = reasoning_effort
            if extra_body:
                kwargs["extra_body"] = extra_body
        return ChatOpenAI(**kwargs)

    raise ValueError(f"未知 api_kind: {char.api_kind}")


def _structured_output(model, schema, char: Character):
    """让 model 输出指定 Pydantic schema。不同 SDK 用不同方式：
    - Anthropic：tool calling（with_structured_output 默认）
    - OpenAI 兼容：json_mode（DashScope 中转的第三方未必都支持 json_schema，json_mode 兼容性更广）
    """
    if char.api_kind == "anthropic":
        return model.with_structured_output(schema)
    return model.with_structured_output(schema, method="json_mode")


def _debug(label: str, payload: Any) -> None:
    """LLM_DEBUG=1 时把 prompt/response 打到 stderr。"""
    if os.environ.get("LLM_DEBUG") == "1":
        print(f"[llm/{label}] {payload}", file=sys.stderr)


# ============================================================
# 公开接口
# ============================================================

def ask_bid(view: PlayerView, character_id: str, output_language: str = "zh") -> LLMBidDecision:
    """让指定角色决定叫几分。任何失败都 fallback 到 0（不叫）。"""
    fallback_reason = "(fallback: LLM 失败)"
    try:
        character = get_character(character_id)
        system, user = build_bid_prompt(view, character, output_language)
        _debug("bid.system", system[:120] + "...")
        _debug("bid.user", user)

        model = _get_chat_model(character_id)
        structured = _structured_output(model, LLMBidDecision, character)
        result: LLMBidDecision = structured.invoke(
            [
                ("system", system),
                ("human", user),
            ]
        )
        _debug("bid.result", result.model_dump())

        # 业务约束：score 必须 > current_top_bid 或 = 0
        if result.score != 0 and result.score <= view.current_top_bid:
            return LLMBidDecision(
                score=0,
                reason=f"(fallback: LLM 想叫 {result.score} 但当前最高已 {view.current_top_bid})",
            )
        return result
    except (ValidationError, Exception) as e:
        _debug("bid.error", f"{type(e).__name__}: {e}")
        return LLMBidDecision(score=0, reason=f"(fallback: {type(e).__name__})")


def ask_play(view: PlayerView, character_id: str, output_language: str = "zh") -> LLMPlayDecision:
    """让指定角色决定出什么牌。

    返回的 cards 字段是 rank 字符串列表（如 ["5","5"]）；
    上层应再调用 cards.parse_ranks_to_cards 转换为 card_ids，并用 validate_play 校验。
    校验失败时上层负责走兜底：
      - 新轮（last_play=None）不能 pass → 兜底打最小单张
      - 否则 → pass
    """
    must_play = view.last_play_display is None
    fallback_action = "play" if must_play else "pass"

    try:
        character = get_character(character_id)
        system, user = build_play_prompt(view, character, output_language)
        _debug("play.system", system[:120] + "...")
        _debug("play.user", user)

        model = _get_chat_model(character_id)
        structured = _structured_output(model, LLMPlayDecision, character)
        result: LLMPlayDecision = structured.invoke(
            [
                ("system", system),
                ("human", user),
            ]
        )
        _debug("play.result", result.model_dump())

        # 业务约束：新轮不能 pass
        if must_play and result.action == "pass":
            return LLMPlayDecision(
                action="play",
                cards=[],
                reason="(fallback: 新轮不能 pass，等上层用规则兜底)",
                thought_process="新一轮必须出牌，模型选择了 pass，因此交给规则兜底出最小合法牌。",
            )

        # 地主输出 secret_message 也忽略掉（防止 LLM 越权）
        if view.my_role != "peasant":
            result.secret_message = None

        return result
    except (ValidationError, Exception) as e:
        _debug("play.error", f"{type(e).__name__}: {e}")
        return LLMPlayDecision(
            action=fallback_action,
            cards=[],
            reason=f"(fallback: {type(e).__name__})",
        )


def clear_model_cache() -> None:
    """清空 ChatModel 缓存。改 env 后调一次，否则新 base_url/key 不生效。"""
    _get_chat_model.cache_clear()
