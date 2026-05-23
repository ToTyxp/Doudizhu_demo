"""角色卡 —— 8 张内置角色，统一中立人设。

设计意图：用户想看"同一个 prompt 不同 LLM 打牌风格差异"，所以 persona 不灌输任何
性格特征，只告诉模型"你是 X，按你自己的判断玩"，让模型本身的脾气透出来。

API 路由两种：
- anthropic：Claude 系列，走 langchain-anthropic
- openai_compat：其他全部走 OpenAI 兼容协议（含 OpenAI 官方和 DashScope 中转的第三方）

DashScope 百炼平台托管了 Qwen / DeepSeek / GLM / Kimi / MiniMax / MiMo 等，统一一个
DASHSCOPE_API_KEY 全能用，model id 形如 `xiaomi/mimo-v2.5-pro`、`ZHIPU/GLM-5.1`。
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any


# ============================================================
# Character 数据结构
# ============================================================

@dataclass(frozen=True)
class Character:
    """角色卡 = LLM 模型 + 调用路由信息 + UI 元数据。"""
    id: str                         # 内部稳定 ID
    name: str                       # 显示名 / 代号
    avatar: str                     # emoji 头像
    tagline: str                    # 一句话标签

    api_kind: str                   # "anthropic" | "openai_compat"
    model_name: str                 # 真实的 model 字符串
    model_label: str                # 喂给 LLM 自我认知的"你是 X"标签

    api_key_env: str                # 哪个 env var 存 API key
    base_url_env: str = ""          # 哪个 env var 存 base_url（空表示不需要）
    default_base_url: str = ""      # env 没设时的 fallback

    extra_body: dict[str, Any] = field(default_factory=dict)  # 例如 {"enable_thinking": False}
    persona_prompt: str = ""        # 拼到 system prompt 末尾（自动生成）


# ============================================================
# 统一中立人设模板
# ============================================================

def _neutral_persona(model_label: str, name: str) -> str:
    return f"""【角色设定】
你是 {model_label} 模型，在这局斗地主里玩家给你的代号是"{name}"。
请按你的真实判断打牌——不需要扮演任何特定性格。
在 reason 字段里简短诚实地说出你的思路，让玩家看清你的决策逻辑。
你的目标：当地主时单干胜两个农民；当农民时配合队友打败地主。
"""


def _make(
    id: str,
    name: str,
    avatar: str,
    tagline: str,
    api_kind: str,
    model_name: str,
    model_label: str,
    api_key_env: str,
    base_url_env: str = "",
    default_base_url: str = "",
    extra_body: dict[str, Any] | None = None,
) -> Character:
    """构造一张角色卡 + 自动注入中立 persona。"""
    return Character(
        id=id,
        name=name,
        avatar=avatar,
        tagline=tagline,
        api_kind=api_kind,
        model_name=model_name,
        model_label=model_label,
        api_key_env=api_key_env,
        base_url_env=base_url_env,
        default_base_url=default_base_url,
        extra_body=extra_body or {},
        persona_prompt=_neutral_persona(model_label, name),
    )


# ============================================================
# 内置角色（8 张）
# ============================================================
# DashScope 兼容端点（北京区）；第三方模型全部通过这个 base_url 调
_DASHSCOPE_BASE = "https://dashscope.aliyuncs.com/compatible-mode/v1"

# thinking/reasoning 统一关闭：游戏里保留可展示的 thought_process 字段，
# 但底层 API 不开模型私有的长思考模式。
_DASHSCOPE_THINKING_OFF = {"enable_thinking": False}
_ANTHROPIC_THINKING_OFF = {"thinking": {"type": "disabled"}}
_OPENAI_REASONING_OFF = {"reasoning_effort": "none"}


CHARACTERS: list[Character] = [
    # ---- Anthropic：Claude Opus 4.7 ----
    _make(
        id="claude",
        name="Claude Opus 4.7",
        avatar="🧠",
        tagline="Anthropic 旗舰",
        api_kind="anthropic",
        model_name="claude-opus-4-7",
        model_label="Claude Opus 4.7（Anthropic）",
        api_key_env="ANTHROPIC_API_KEY",
        base_url_env="ANTHROPIC_BASE_URL",
        extra_body=_ANTHROPIC_THINKING_OFF,
    ),

    # ---- OpenAI：GPT-5.5 ----
    _make(
        id="gpt",
        name="GPT-5.5",
        avatar="🤖",
        tagline="OpenAI 旗舰",
        api_kind="openai_compat",
        model_name="gpt-5.5-2026-04-23",
        model_label="GPT-5.5（OpenAI）",
        api_key_env="OPENAI_API_KEY",
        base_url_env="OPENAI_BASE_URL",
        extra_body=_OPENAI_REASONING_OFF,
    ),

    # ---- 阿里通义：Qwen3.6-Plus（深度思考模型）----
    _make(
        id="qwen",
        name="Qwen3.6-Plus",
        avatar="🐫",
        tagline="阿里通义旗舰",
        api_kind="openai_compat",
        model_name="qwen3.6-plus",
        model_label="Qwen3.6-Plus（阿里通义）",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        default_base_url=_DASHSCOPE_BASE,
        extra_body=_DASHSCOPE_THINKING_OFF,
    ),

    # ---- DeepSeek V4 Pro（百炼托管）----
    _make(
        id="deepseek",
        name="DeepSeek V4 Pro",
        avatar="🐳",
        tagline="DeepSeek 推理",
        api_kind="openai_compat",
        model_name="deepseek-v4-pro",
        model_label="DeepSeek V4 Pro",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        default_base_url=_DASHSCOPE_BASE,
        extra_body=_DASHSCOPE_THINKING_OFF,
    ),

    # ---- 智谱 GLM-5.1（百炼托管）----
    _make(
        id="glm",
        name="GLM-5.1",
        avatar="🪞",
        tagline="智谱清言",
        api_kind="openai_compat",
        model_name="ZHIPU/GLM-5.1",
        model_label="GLM-5.1（智谱清言）",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        default_base_url=_DASHSCOPE_BASE,
        extra_body=_DASHSCOPE_THINKING_OFF,
    ),

    # ---- 月之暗面 Kimi K2.6（百炼托管）----
    _make(
        id="kimi",
        name="Kimi K2.6",
        avatar="🌙",
        tagline="月之暗面",
        api_kind="openai_compat",
        model_name="kimi/kimi-k2.6",
        model_label="Kimi K2.6（月之暗面）",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        default_base_url=_DASHSCOPE_BASE,
        extra_body=_DASHSCOPE_THINKING_OFF,
    ),

    # ---- MiniMax M2.7（百炼托管，无思考模式）----
    _make(
        id="minimax",
        name="MiniMax M2.7",
        avatar="🐠",
        tagline="MiniMax",
        api_kind="openai_compat",
        model_name="MiniMax/MiniMax-M2.7",
        model_label="MiniMax M2.7",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        default_base_url=_DASHSCOPE_BASE,
    ),

    # ---- 小米 MiMo V2.5 Pro（百炼托管）----
    _make(
        id="mimo",
        name="MiMo V2.5 Pro",
        avatar="📱",
        tagline="小米 MiMo",
        api_kind="openai_compat",
        model_name="xiaomi/mimo-v2.5-pro",
        model_label="MiMo V2.5 Pro（小米）",
        api_key_env="DASHSCOPE_API_KEY",
        base_url_env="DASHSCOPE_BASE_URL",
        default_base_url=_DASHSCOPE_BASE,
        extra_body=_DASHSCOPE_THINKING_OFF,
    ),
]


_BY_ID: dict[str, Character] = {c.id: c for c in CHARACTERS}


def get_character(character_id: str) -> Character:
    """按 id 查角色。找不到抛 KeyError。"""
    if character_id not in _BY_ID:
        raise KeyError(f"未知角色: {character_id}")
    return _BY_ID[character_id]


def list_characters() -> list[Character]:
    """所有内置角色（含不可用）。"""
    return list(CHARACTERS)


def is_available(character: Character) -> bool:
    """对应 API key 是否已配置。"""
    return bool(os.environ.get(character.api_key_env))


def list_for_api() -> list[dict]:
    """给 /api/characters 接口的 JSON 友好列表，不暴露 persona / 内部字段。"""
    return [
        {
            "id": c.id,
            "name": c.name,
            "avatar": c.avatar,
            "tagline": c.tagline,
            "model_label": c.model_label,
            "available": is_available(c),
            "required_env": c.api_key_env,
        }
        for c in CHARACTERS
    ]
