"""LLM 输入/输出的 Pydantic 模型，以及给 LLM 的"玩家视角"数据结构。

设计原则：
- View 是单个玩家能合法看到的所有信息；这是我们把游戏状态投影出来喂给 LLM 的中间层。
- LLMBidDecision / LLMPlayDecision 是从 LLM 拿回来 JSON 后 parse 得到的结构。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# ---------------- 玩家视角（喂给 prompt） ----------------

class PlayerSummary(BaseModel):
    """其他玩家的公开信息（不含手牌）。"""
    id: int
    name: str
    role: Literal["landlord", "peasant", "undetermined"]
    hand_count: int


class TrickPlay(BaseModel):
    """当前 trick 里一次出牌动作。"""
    player_id: int
    cards_display: str   # "5 5"，已格式化成 rank 字符串
    is_pass: bool


class PlayerView(BaseModel):
    """喂给某一个 AI 玩家的视角。整套数据只反映这个玩家能合法看到的。"""
    phase: Literal["bidding", "playing"]

    # 自己的信息
    my_id: int
    my_name: str
    my_role: Literal["landlord", "peasant", "undetermined"]
    my_hand_display: str          # "3 3 4 5 5 7 J J Q K A 2 小王 大王"
    my_hand_count: int

    # 公开信息
    others: list[PlayerSummary]   # 其他两个玩家的摘要
    bottom_display: str | None    # "K 7 4"，叫分前是 None，叫分后公开
    played_history_display: str   # 整局至今所有出过的牌，"3 4 5 ; J J ; ..." 用分号分组
    private_notes_display: str = "" # 仅当前 AI 自己过去的 reason/assessment，不含其他 AI 的思考
    incoming_taunt: str | None = None # 玩家刚刚对这个 AI 说的话；只注入一次并在决策时消费

    # 仅 playing 阶段：
    current_trick: list[TrickPlay] = Field(default_factory=list)
    last_play_display: str | None = None     # 当前要压过的最后一手，None 表示自己起新轮
    last_play_player_id: int | None = None
    legal_play_hints: list[str] = Field(default_factory=list)   # ["对 J", "对 Q", "炸弹 3"] 之类

    # 仅 bidding 阶段：
    current_top_bid: int = 0      # 当前最高叫分（0/1/2/3），自己只能叫更高或不叫

    # 暗黑机制：
    incoming_secret: str | None = None       # 队友刚发的暗号（仅农民收到）
    intercepted_secret: str | None = None    # 偷听到的对家暗号（仅地主、且 30% 概率）


# ---------------- LLM 响应模型 ----------------

class LLMBidDecision(BaseModel):
    """叫分阶段 LLM 返回。score 必须 > current_top_bid 或 = 0（不叫）。"""
    score: Literal[0, 1, 2, 3]
    reason: str = ""
    opponents_assessment: str = ""    # 基于手牌对其他玩家的初判（局末回放展示用）
    mood: str | None = None            # 短情绪标签，用于嘴炮反馈 / 局末复盘


class LLMPlayDecision(BaseModel):
    """出牌阶段 LLM 返回。"""
    action: Literal["play", "pass"]
    cards: list[str] = Field(default_factory=list)   # 仅 action=play 时有意义，例如 ["5","5"]
    reason: str = ""
    thought_process: str = ""         # 给前端展示的简短思考过程；不是模型内部 chain-of-thought
    opponents_assessment: str = ""    # 对队友 / 对手牌技与剩余牌的当前评价（局末回放展示用）
    mood: str | None = None            # 短情绪标签，用于嘴炮反馈 / 局末复盘
    secret_message: str | None = None    # 农民可填：给队友的暗号（地主/玩家=地主时由后端忽略）


class TauntRequest(BaseModel):
    """玩家对某个 AI 的自然语言嘴炮。"""
    target_seat: int = Field(ge=0, le=2)
    message: str = Field(min_length=1, max_length=300)


# ---------------- 角色 / 比赛系统 ----------------

class CharacterInfo(BaseModel):
    """暴露给前端的角色卡信息（不含 persona_prompt 等敏感设定）。"""
    id: str
    name: str
    avatar: str
    tagline: str
    model_provider: str
    model_name: str
    available: bool
    required_env: str


class PlayLogEntry(BaseModel):
    """记录一次叫分 / 出牌 / 过牌，给"局末聊天记录"回放用。

    人类玩家的条目通常只有 cards_display；reason / opponents_assessment / secret_message
    都是 LLM 玩家才有。
    """
    player_id: int
    player_name: str                    # "You" / 角色 name
    character_id: str                   # "human" 或 character.id
    phase: Literal["bidding", "playing"]
    turn_index: int                     # 出牌阶段第几手；叫分阶段固定为 0

    action_type: Literal["bid", "play", "pass"]
    bid_score: int | None = None         # 仅 action_type="bid"
    cards_display: str = ""              # "对 K" / "三带一 (5 带 J)" / "" (pass)

    reason: str = ""                     # LLM 给的简短解释
    opponents_assessment: str = ""       # LLM 给的对手牌技 / 剩余牌评价
    secret_message: str | None = None    # 发出去的暗号（农民才有）
    overheard_secret: str | None = None  # 偷听到的暗号（地主才有）


class GameResult(BaseModel):
    """单局结算。"""
    game_index: int                     # 第几局（1..5）
    landlord_player_id: int
    winning_team: Literal["landlord", "peasants"]
    player_won: bool                    # 玩家所在那队是否赢
    final_hands_display: dict[int, str] # player_id -> 局末手牌（已出完则空字符串）
    play_log: list[PlayLogEntry] = Field(default_factory=list)   # 整局的聊天/出牌历史


class MatchState(BaseModel):
    """5 局 3 胜整场状态。"""
    # 三个座位的角色 ID："human" 表示玩家自己；其他两个是 character.id
    characters: dict[int, str]
    games_played: int = 0
    player_wins: int = 0
    ai_wins: int = 0
    dark_points: int = 100              # 玩家暗黑分（跨整场固定 100 起步）
    history: list[GameResult] = Field(default_factory=list)
    finished: bool = False
