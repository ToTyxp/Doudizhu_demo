"""单局斗地主状态机。

Day 3 目标：先跑通一局基础玩法，三家都由前端手动操作，方便调试规则和路由。
AI 自动叫分/出牌会在 Day 4 接到同一套 bid/play/pass 方法上。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field
from threading import Lock
from typing import Literal

from .cards import (
    card_name,
    enumerate_legal_plays,
    describe_play,
    hand_to_display,
    parse_ranks_to_cards,
    shuffle_and_deal,
    sort_hand,
    validate_play,
)
from .characters import get_character
from .llm import ask_bid, ask_play
from .schemas import PlayerSummary, PlayerView, TrickPlay


Phase = Literal["bidding", "playing", "ended"]
Team = Literal["landlord", "peasants"]
AI_TIMEOUT_SECONDS = 15
_AI_EXECUTOR = ThreadPoolExecutor(max_workers=8)


@dataclass
class Player:
    id: int
    name: str
    hand: list[int]
    character_id: str = "human"
    role: Literal["landlord", "peasant", "undetermined"] = "undetermined"
    bid: int | None = None

    @property
    def is_human(self) -> bool:
        return self.character_id == "human"


@dataclass
class TrickAction:
    seq: int
    player_id: int
    action: Literal["bid", "play", "pass"]
    cards: list[int] = field(default_factory=list)
    bid_score: int | None = None
    reason: str = ""
    thought_process: str = ""
    opponents_assessment: str = ""
    mood: str | None = None
    taunt_received: str | None = None

    def to_api(self) -> dict:
        return {
            "player_id": self.player_id,
            "seq": self.seq,
            "action": self.action,
            "phase": "bidding" if self.action == "bid" else "playing",
            "bid_score": self.bid_score,
            "cards": [card_payload(c) for c in self.cards],
            "cards_display": describe_play(self.cards) if self.cards else "",
            "is_pass": self.action == "pass",
            "reason": self.reason,
            "thought_process": self.thought_process,
            "opponents_assessment": self.opponents_assessment,
            "mood": self.mood,
            "taunt_received": self.taunt_received,
        }


@dataclass
class TauntEvent:
    seq: int
    target_seat: int
    target_name: str
    message: str

    def to_api(self) -> dict:
        return {
            "seq": self.seq,
            "target_seat": self.target_seat,
            "target_name": self.target_name,
            "message": self.message,
        }


def card_payload(card: int) -> dict:
    return {"id": card, "label": card_name(card)}


class GameError(ValueError):
    """玩家操作不符合当前状态。"""


class Game:
    def __init__(
        self,
        seed: int | None = None,
        ai_characters: list[str] | None = None,
        output_language: str = "zh",
    ):
        self.seed = seed
        self.ai_characters = self._normalize_ai_characters(ai_characters)
        self.output_language = self._normalize_output_language(output_language)
        self.redeal_count = 0
        self._ai_step_lock = Lock()
        self._deal()

    @staticmethod
    def _normalize_ai_characters(ai_characters: list[str] | None) -> list[str]:
        chars = list(ai_characters or ["qwen", "deepseek"])
        if len(chars) != 2:
            raise GameError("必须选择 2 个 AI 角色")
        if any(not c or c == "human" for c in chars):
            raise GameError("AI 角色不能为空，也不能是 human")
        return chars

    @staticmethod
    def _normalize_output_language(output_language: str | None) -> Literal["zh", "en"]:
        return "en" if output_language == "en" else "zh"

    def set_output_language(self, output_language: str | None) -> None:
        self.output_language = self._normalize_output_language(output_language)

    def _deal(self) -> None:
        h0, h1, h2, bottom = shuffle_and_deal(
            seed=None if self.seed is None else self.seed + self.redeal_count
        )
        ai_names = [get_character(c).name for c in self.ai_characters]
        self.players = [
            Player(id=0, name="挑战者", hand=h0, character_id="human"),
            Player(id=1, name=ai_names[0], hand=h1, character_id=self.ai_characters[0]),
            Player(id=2, name=ai_names[1], hand=h2, character_id=self.ai_characters[1]),
        ]
        self.bottom = bottom
        self.phase: Phase = "bidding"
        self.current_player = 0
        self.bid_turns = 0
        self.current_top_bid = 0
        self.top_bidder: int | None = None
        self.landlord_id: int | None = None
        self.last_play: list[int] = []
        self.last_play_player_id: int | None = None
        self.consecutive_passes = 0
        self.current_trick: list[TrickAction] = []
        self.played_history: list[TrickAction] = []
        self.taunt_history: list[TauntEvent] = []
        self.event_seq = 0
        self.private_ai_notes: dict[int, list[str]] = {1: [], 2: []}
        self.pending_taunts: dict[int, str] = {}
        self.taunted_this_turn: set[int] = set()
        self.winning_team: Team | None = None
        self.winner_id: int | None = None
        self.message = "新局已发牌，请挑战者先叫分。"

    def bid(self, player_id: int, score: int) -> None:
        self._require_phase("bidding")
        self._require_current_player(player_id)
        if score not in (0, 1, 2, 3):
            raise GameError("叫分只能是 0、1、2、3")
        if score != 0 and score <= self.current_top_bid:
            raise GameError(f"当前最高叫分是 {self.current_top_bid}，只能叫更高或不叫")

        player = self.players[player_id]
        player.bid = score
        self.played_history.append(
            TrickAction(seq=self._next_seq(), player_id=player_id, action="bid", bid_score=score)
        )
        self.bid_turns += 1
        if score > self.current_top_bid:
            self.current_top_bid = score
            self.top_bidder = player_id
        self._reset_taunt_window(player_id)

        if score == 3 or self.bid_turns >= 3:
            self._finish_bidding()
            return

        self.current_player = self._next_player(player_id)
        self.message = f"{self._display_name(player_id)} 叫 {score} 分，轮到 {self._display_name(self.current_player)}。"

    def advance_ai(self) -> None:
        """如果当前轮到 AI，就执行一步 AI 动作。"""
        if self.phase == "ended":
            return
        player = self.players[self.current_player]
        if player.is_human:
            return
        if not self._ai_step_lock.acquire(blocking=False):
            return

        try:
            if self.phase == "bidding":
                taunt = self._consume_taunt(player.id)
                view = self.player_view(player.id, incoming_taunt=taunt)
                decision = self._ask_bid_with_timeout(view, player.character_id)
                self.bid(player.id, decision.score)
                self._annotate_last_ai_action(decision, taunt)
                self._remember_ai_note(
                    player.id,
                    f"叫分 {decision.score}: {decision.reason} {decision.opponents_assessment} {decision.mood or ''}",
                )
                self.message = (
                    f"{player.name} 叫 {decision.score} 分："
                    f"{decision.reason}"
                )
                return

            if self.phase == "playing":
                taunt = self._consume_taunt(player.id)
                view = self.player_view(player.id, incoming_taunt=taunt)
                decision = self._ask_play_with_timeout(view, player.character_id)
                reason = decision.reason
                assessment = decision.opponents_assessment

                if decision.action == "pass" and self.last_play:
                    self.pass_turn(player.id)
                    self._annotate_last_ai_action(decision, taunt)
                    self._remember_ai_note(player.id, f"过牌: {reason} {assessment} {decision.mood or ''}")
                    self.message = f"{player.name} 过牌：{reason}"
                    return

                parsed = parse_ranks_to_cards(decision.cards, player.hand)
                if parsed is not None:
                    validation = validate_play(parsed, player.hand, self.last_play)
                    if validation.ok:
                        self.play(player.id, parsed)
                        self._annotate_last_ai_action(decision, taunt)
                        self._remember_ai_note(
                            player.id,
                            f"出牌 {describe_play(parsed)}: {reason} {assessment} {decision.mood or ''}",
                        )
                        return

                # 兜底：新轮必须出最小单张；压牌失败时 pass。
                if not self.last_play:
                    fallback = [sort_hand(player.hand)[0]]
                    self.play(player.id, fallback)
                    self._annotate_last_ai_action(decision, taunt)
                    self.played_history[-1].reason = f"{reason}；fallback: 起新轮打最小单张"
                    self._remember_ai_note(
                        player.id,
                        f"fallback 出牌 {describe_play(fallback)}: {reason}",
                    )
                    return

                self.pass_turn(player.id)
                self._annotate_last_ai_action(decision, taunt)
                self.played_history[-1].reason = f"{reason}；fallback: 非法/压不过，改为 pass"
                self._remember_ai_note(player.id, f"fallback 过牌: {reason}")
        finally:
            self._ai_step_lock.release()

    def taunt(self, target_seat: int, message: str) -> None:
        if self.phase == "ended":
            raise GameError("游戏已结束，不能继续嘴炮")
        if target_seat not in (1, 2) or self.players[target_seat].is_human:
            raise GameError("嘴炮目标必须是 AI")
        compact = " ".join(message.split())
        if not compact:
            raise GameError("嘴炮内容不能为空")
        if target_seat in self.taunted_this_turn or target_seat in self.pending_taunts:
            raise GameError("该 AI 本回合已被嘴炮过")
        self.pending_taunts[target_seat] = compact[:300]
        self.taunted_this_turn.add(target_seat)
        self.taunt_history.append(
            TauntEvent(
                seq=self._next_seq(),
                target_seat=target_seat,
                target_name=self.players[target_seat].name,
                message=compact[:300],
            )
        )
        self.message = f"你对 {self.players[target_seat].name} 放了句狠话。"

    def _ask_bid_with_timeout(self, view: PlayerView, character_id: str):
        future = _AI_EXECUTOR.submit(ask_bid, view, character_id, self.output_language)
        try:
            return future.result(timeout=AI_TIMEOUT_SECONDS)
        except TimeoutError:
            from .schemas import LLMBidDecision

            reason = "Thinking took too long, so I will pass the bid." if self.output_language == "en" else "想太久了，先不叫。"
            return LLMBidDecision(score=0, reason=reason)

    def _ask_play_with_timeout(self, view: PlayerView, character_id: str):
        future = _AI_EXECUTOR.submit(ask_play, view, character_id, self.output_language)
        try:
            return future.result(timeout=AI_TIMEOUT_SECONDS)
        except TimeoutError:
            from .schemas import LLMPlayDecision

            if view.last_play_display is None:
                reason = "Thinking took too long, so I will play the smallest single." if self.output_language == "en" else "想太久了，先打最小单张。"
                thought = (
                    "Time is up. I need to start the trick, so I will use the smallest single to keep the game moving."
                    if self.output_language == "en"
                    else "时间到，先用最小单张把牌权交出去，避免卡住游戏。"
                )
                return LLMPlayDecision(
                    action="play",
                    cards=[],
                    reason=reason,
                    thought_process=thought,
                )
            reason = "Thinking took too long, so I will pass." if self.output_language == "en" else "想太久了，先过。"
            thought = (
                "Time is up. I need to beat the previous play, so passing keeps the game moving."
                if self.output_language == "en"
                else "时间到，当前要压牌，直接过牌让流程继续。"
            )
            return LLMPlayDecision(
                action="pass",
                reason=reason,
                thought_process=thought,
            )

    def _finish_bidding(self) -> None:
        if self.top_bidder is None:
            self.redeal_count += 1
            self._deal()
            self.message = "三家都不叫，已重新发牌。"
            return

        self.landlord_id = self.top_bidder
        for p in self.players:
            p.role = "landlord" if p.id == self.landlord_id else "peasant"
        landlord = self.players[self.landlord_id]
        landlord.hand = sort_hand(landlord.hand + self.bottom)

        self.phase = "playing"
        self.current_player = self.landlord_id
        self.message = f"{self._display_name(self.landlord_id)} 成为地主并拿到底牌，地主先出。"

    def play(self, player_id: int, cards: list[int]) -> None:
        self._require_phase("playing")
        self._require_current_player(player_id)

        player = self.players[player_id]
        validation = validate_play(cards, player.hand, self.last_play)
        if not validation.ok:
            raise GameError(validation.reason)

        card_set = set(cards)
        player.hand = [c for c in player.hand if c not in card_set]
        action = TrickAction(
            seq=self._next_seq(),
            player_id=player_id,
            action="play",
            cards=sort_hand(cards),
        )
        self.current_trick.append(action)
        self.played_history.append(action)
        self.last_play = sort_hand(cards)
        self.last_play_player_id = player_id
        self.consecutive_passes = 0
        self._reset_taunt_window(player_id)

        if not player.hand:
            self._finish_game(player_id)
            return

        self.current_player = self._next_player(player_id)
        self.message = f"{self._display_name(player_id)} 出了 {describe_play(cards)}，轮到 {self._display_name(self.current_player)}。"

    def pass_turn(self, player_id: int) -> None:
        self._require_phase("playing")
        self._require_current_player(player_id)
        if not self.last_play:
            raise GameError("新一轮必须出牌，不能过牌")
        if player_id == self.last_play_player_id:
            raise GameError("上一手出牌人不能主动过自己的牌")

        action = TrickAction(seq=self._next_seq(), player_id=player_id, action="pass")
        self.current_trick.append(action)
        self.played_history.append(action)
        self.consecutive_passes += 1
        self._reset_taunt_window(player_id)

        if self.consecutive_passes >= 2:
            assert self.last_play_player_id is not None
            starter = self.last_play_player_id
            self.last_play = []
            self.last_play_player_id = None
            self.consecutive_passes = 0
            self.current_trick = []
            self.current_player = starter
            self.message = f"其余两家都过牌，{self._display_name(starter)} 重新起牌。"
            return

        self.current_player = self._next_player(player_id)
        self.message = f"{self._display_name(player_id)} 过牌，轮到 {self._display_name(self.current_player)}。"

    def _finish_game(self, winner_id: int) -> None:
        self.phase = "ended"
        self.winner_id = winner_id
        winner = self.players[winner_id]
        self.winning_team = "landlord" if winner.role == "landlord" else "peasants"
        self.current_player = winner_id
        self.message = f"{self._display_name(winner_id)} 出完手牌，{self._team_zh(self.winning_team)}获胜。"

    def to_api(self) -> dict:
        return {
            "phase": self.phase,
            "message": self.message,
            "current_player": self.current_player,
            "current_player_is_human": self.players[self.current_player].is_human,
            "current_top_bid": self.current_top_bid,
            "landlord_id": self.landlord_id,
            "winner_id": self.winner_id,
            "winning_team": self.winning_team,
            "bottom": [card_payload(c) for c in self.bottom],
            "bottom_display": hand_to_display(self.bottom, with_suit=True),
            "last_play": [card_payload(c) for c in self.last_play],
            "last_play_display": describe_play(self.last_play) if self.last_play else "",
            "last_play_player_id": self.last_play_player_id,
            "consecutive_passes": self.consecutive_passes,
            "current_trick": [a.to_api() for a in self.current_trick],
            "played_history": [a.to_api() for a in self.played_history],
            "taunt_history": [t.to_api() for t in self.taunt_history],
            "pending_taunt_targets": sorted(self.pending_taunts.keys()),
            "taunted_this_turn": sorted(self.taunted_this_turn),
            "ai_characters": list(self.ai_characters),
            "players": [self._player_to_api(p) for p in self.players],
        }

    def _player_to_api(self, player: Player) -> dict:
        return {
            "id": player.id,
            "name": player.name,
            "character_id": player.character_id,
            "is_human": player.is_human,
            "role": player.role,
            "bid": player.bid,
            "hand_count": len(player.hand),
            "hand": [card_payload(c) for c in player.hand],
            "hand_display": hand_to_display(player.hand, with_suit=True),
            "is_landlord": player.role == "landlord",
            "is_current": self.phase != "ended" and player.id == self.current_player,
        }

    def player_view(self, player_id: int, incoming_taunt: str | None = None) -> PlayerView:
        player = self.players[player_id]
        return PlayerView(
            phase=self.phase,  # type: ignore[arg-type]
            my_id=player.id,
            my_name=player.name,
            my_role=player.role,
            my_hand_display=hand_to_display(player.hand),
            my_hand_count=len(player.hand),
            others=[
                PlayerSummary(
                    id=p.id,
                    name=p.name,
                    role=p.role,
                    hand_count=len(p.hand),
                )
                for p in self.players
                if p.id != player.id
            ],
            bottom_display=hand_to_display(self.bottom) if self.phase == "playing" else None,
            played_history_display=self._played_history_display(),
            private_notes_display=self._private_notes_display(player_id),
            incoming_taunt=incoming_taunt,
            current_trick=[
                TrickPlay(
                    player_id=a.player_id,
                    cards_display=describe_play(a.cards) if a.cards else "",
                    is_pass=a.action == "pass",
                )
                for a in self.current_trick
            ],
            last_play_display=describe_play(self.last_play) if self.last_play else None,
            last_play_player_id=self.last_play_player_id,
            legal_play_hints=[
                describe_play(cards)
                for cards in enumerate_legal_plays(player.hand, self.last_play)[:40]
            ],
            current_top_bid=self.current_top_bid,
        )

    def _played_history_display(self) -> str:
        groups = [
            describe_play(a.cards)
            for a in self.played_history
            if a.action == "play" and a.cards
        ]
        return " ; ".join(groups)

    def _remember_ai_note(self, player_id: int, note: str) -> None:
        if player_id not in self.private_ai_notes:
            return
        compact = " ".join(note.split())
        if compact:
            self.private_ai_notes[player_id].append(compact[:180])
            self.private_ai_notes[player_id] = self.private_ai_notes[player_id][-8:]

    def _private_notes_display(self, player_id: int) -> str:
        notes = self.private_ai_notes.get(player_id, [])
        if not notes:
            return ""
        return "\n".join(f"  - {note}" for note in notes)

    def _next_seq(self) -> int:
        self.event_seq += 1
        return self.event_seq

    def _consume_taunt(self, player_id: int) -> str | None:
        return self.pending_taunts.pop(player_id, None)

    def _reset_taunt_window(self, player_id: int) -> None:
        self.taunted_this_turn.discard(player_id)

    def _annotate_last_ai_action(self, decision, taunt: str | None) -> None:
        if not self.played_history:
            return
        action = self.played_history[-1]
        action.reason = getattr(decision, "reason", "") or ""
        action.thought_process = getattr(decision, "thought_process", "") or ""
        action.opponents_assessment = getattr(decision, "opponents_assessment", "") or ""
        action.mood = getattr(decision, "mood", None)
        action.taunt_received = taunt

    def _require_phase(self, phase: Phase) -> None:
        if self.phase != phase:
            raise GameError(f"当前阶段是 {self.phase}，不能执行该操作")

    def _require_current_player(self, player_id: int) -> None:
        if player_id not in (0, 1, 2):
            raise GameError("player_id 必须是 0、1、2")
        if player_id != self.current_player:
            raise GameError(f"现在轮到玩家 {self.current_player}，不是玩家 {player_id}")

    def _display_name(self, player_id: int | None) -> str:
        if player_id is None:
            return "-"
        return self.players[player_id].name

    @staticmethod
    def _next_player(player_id: int) -> int:
        return (player_id + 1) % 3

    @staticmethod
    def _team_zh(team: Team) -> str:
        return "地主" if team == "landlord" else "农民"
