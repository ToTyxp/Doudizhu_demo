"""牌型规则引擎。

设计约定（先把"牌"的内部表示锁死，避免后面乱）：
----------------------------------------------------
- 一张牌用整数 0..53 表示，方便排序/哈希/前后端 JSON 传输。
- 切分规则：
    * 0..51  普通牌：rank = idx // 4，suit = idx % 4
              rank 范围 0..12，对应 ["3","4","5","6","7","8","9","10","J","Q","K","A","2"]
              suit 范围 0..3，对应 ["♠","♥","♣","♦"]，斗地主里只用来区分四张同点数，不影响大小
    * 52     小王（Black Joker）
    * 53     大王（Red Joker）
- 比较"大小"用 RANK_ORDER（见下），普通牌按 rank 索引，小王=13，大王=14。
- 牌型用枚举 CardType 表示；同型牌比较只看 main_rank；炸弹/王炸跨型碾压。
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from typing import Optional


# ---------------- 常量 ----------------

RANK_NAMES = ["3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A", "2"]
SUIT_NAMES = ["♠", "♥", "♣", "♦"]
SMALL_JOKER = 52
BIG_JOKER = 53

# 王在比较时的 rank：放在 12（"2"）之后
RANK_SMALL_JOKER = 13
RANK_BIG_JOKER = 14

# 王炸的 main_rank 用一个 sentinel，保证它压一切牌
ROCKET_RANK = 100

# rank 字符串 ↔ rank 整数 双向映射（给 parse_ranks_to_cards / describe_play 用）
RANK_STR_TO_INT: dict[str, int] = {name: idx for idx, name in enumerate(RANK_NAMES)}
RANK_STR_TO_INT["小王"] = RANK_SMALL_JOKER
RANK_STR_TO_INT["大王"] = RANK_BIG_JOKER

RANK_INT_TO_STR: dict[int, str] = {v: k for k, v in RANK_STR_TO_INT.items()}


class CardType(Enum):
    SINGLE = "single"                # 单张
    PAIR = "pair"                    # 对子
    TRIPLE = "triple"                # 三张（不带）
    TRIPLE_ONE = "triple_one"        # 三带一（带 1 张单）
    TRIPLE_PAIR = "triple_pair"      # 三带二（带 1 对）
    BOMB = "bomb"                    # 炸弹（四张同点）
    ROCKET = "rocket"                # 王炸（双王）
    PLANE = "plane"                  # 飞机不带翅膀（K 个连续三张，K≥2）
    PLANE_WITH_SOLO = "plane_solo"   # 飞机带小翅膀（+ K 张单，rank 各异）
    PLANE_WITH_PAIRS = "plane_pairs" # 飞机带大翅膀（+ K 对，rank 各异且不为王）
    STRAIGHT = "straight"            # 顺子（5+ 连续单张，3-A，不含 2/王）
    STRAIGHT_PAIR = "straight_pair"  # 连对（3+ 连续对子，3-A，不含 2/王）


# 飞机的三张部分允许的最高 rank：A（rank 11），不允许 2/王
PLANE_MAX_RANK = 11
CHAIN_MAX_RANK = 11


# ---------------- 牌面工具 ----------------

def card_rank(card: int) -> int:
    """返回这张牌的"比较等级"。0..12 = 3..2，13 = 小王，14 = 大王。"""
    if card == SMALL_JOKER:
        return RANK_SMALL_JOKER
    if card == BIG_JOKER:
        return RANK_BIG_JOKER
    if 0 <= card < 52:
        return card // 4
    raise ValueError(f"非法牌 id: {card}")


def card_suit(card: int) -> int:
    """返回普通牌的花色索引 0..3；王没有花色，返回 -1。"""
    if card in (SMALL_JOKER, BIG_JOKER):
        return -1
    if 0 <= card < 52:
        return card % 4
    raise ValueError(f"非法牌 id: {card}")


def card_name(card: int) -> str:
    """返回带花色的牌面字符串，例如 "♠3" / "大王"。"""
    if card == SMALL_JOKER:
        return "小王"
    if card == BIG_JOKER:
        return "大王"
    return f"{SUIT_NAMES[card_suit(card)]}{RANK_NAMES[card_rank(card)]}"


def sort_hand(hand: list[int]) -> list[int]:
    """按 rank 升序、同 rank 内按 suit（花色）排序，返回新列表。

    王（rank=13/14）排在最后；suit==-1 自动排在普通牌前面是无所谓的（只有王 rank 相同）。
    """
    return sorted(hand, key=lambda c: (card_rank(c), card_suit(c)))


# ---------------- 发牌 ----------------

def make_deck() -> list[int]:
    """返回 54 张牌（0..53）的有序列表。"""
    return list(range(54))


def _cluster_pass(deck: list[int], rng: random.Random, strength: float) -> None:
    """In-place 聚类 pass：让同 rank 的牌更倾向于在 deck 里相邻。

    走 0..n-2，每个位置 i 以 `strength` 概率向后找一张和 deck[i] 同 rank 的牌、
    把它换到 i+1 位置。块状切发后，同 rank 的牌更容易落到同一玩家手里
    （对子/三张/炸弹的出现概率上升），但高/低牌的玩家分布保持随机。
    """
    n = len(deck)
    for i in range(n - 1):
        if rng.random() >= strength:
            continue
        target_rank = card_rank(deck[i])
        for j in range(i + 2, n):
            if card_rank(deck[j]) == target_rank:
                deck[i + 1], deck[j] = deck[j], deck[i + 1]
                break


def shuffle_and_deal(
    seed: Optional[int] = None,
    cluster_strength: float = 0.3,
) -> tuple[list[int], list[int], list[int], list[int]]:
    """伪随机洗牌 + 发牌。返回 (玩家0, 玩家1, 玩家2, 底牌)。

    每个玩家 17 张；底牌 3 张；总和 = 54。
    流程：
        1. 纯随机洗一次
        2. 聚类 pass：让同 rank 的牌更可能相邻（cluster_strength 控制强度）
        3. 块状切分发牌（相邻位置 → 同玩家）

    参数：
        seed: 复现用；正式发牌传 None
        cluster_strength:
            0.0 = 纯随机（对子 4.8 / 三张 1.2 / 炸弹 0.10）
            0.3 = 默认轻偏置（对子 5.1 / 三张 1.8 / 炸弹 0.41）⭐
            0.5 = 中偏置（炸弹 0.87，几乎每局一个）
            1.0 = 强偏置（每局多个炸弹）
        以上数据基于 200 局采样。

    手牌返回前已排序。
    """
    deck = make_deck()
    rng = random.Random(seed)
    rng.shuffle(deck)
    if cluster_strength > 0:
        _cluster_pass(deck, rng, cluster_strength)
    hand0 = sort_hand(deck[0:17])
    hand1 = sort_hand(deck[17:34])
    hand2 = sort_hand(deck[34:51])
    bottom = sort_hand(deck[51:54])
    return hand0, hand1, hand2, bottom


# ---------------- 牌型识别 ----------------

def identify(cards: list[int]) -> Optional[tuple[CardType, int, int]]:
    """识别一组牌的牌型。

    返回 (CardType, main_rank, length)：
      - main_rank：用于同型比较的核心点数
            * 单/对/三/三带一/三带二/炸：用主牌的 rank
            * 王炸：固定 ROCKET_RANK=100 保证最大
      - length：这一手的总张数
    不合法的牌型返回 None。
    """
    if not cards:
        return None

    counts = Counter(card_rank(c) for c in cards)
    length = len(cards)

    # 王炸：恰好小王 + 大王
    if length == 2 and counts.get(RANK_SMALL_JOKER) == 1 and counts.get(RANK_BIG_JOKER) == 1:
        return CardType.ROCKET, ROCKET_RANK, 2

    # 按计数排序（降序），取前几位的 (rank, count) 组合做模式匹配
    items = sorted(counts.items(), key=lambda kv: -kv[1])

    if length == 1:
        # 单张
        return CardType.SINGLE, items[0][0], 1

    if length == 2 and items[0][1] == 2:
        # 对子（同 rank 2 张；普通牌——王不可能进这一支，因为单王只能 count=1）
        return CardType.PAIR, items[0][0], 2

    if length == 3 and items[0][1] == 3:
        # 三张
        return CardType.TRIPLE, items[0][0], 3

    if length == 4:
        if items[0][1] == 4:
            # 炸弹
            return CardType.BOMB, items[0][0], 4
        if items[0][1] == 3 and items[1][1] == 1:
            # 三带一
            return CardType.TRIPLE_ONE, items[0][0], 4

    if length == 5 and items[0][1] == 3 and items[1][1] == 2:
        # 三带二（注意：带的"对"不能是王——王没有第二张）
        # items[1][0] 是带的对子 rank；若是 13 或 14 不可能（count=2 不可能），所以这里安全
        return CardType.TRIPLE_PAIR, items[0][0], 5

    straight = _identify_straight(counts, length)
    if straight is not None:
        return straight

    straight_pair = _identify_straight_pair(counts, length)
    if straight_pair is not None:
        return straight_pair

    # 飞机三个变体：先看是否有 ≥2 个连续 triple
    plane = _identify_plane(counts, length)
    if plane is not None:
        return plane

    return None


def _is_consecutive(ranks: list[int]) -> bool:
    return bool(ranks) and ranks == list(range(ranks[0], ranks[0] + len(ranks)))


def _identify_straight(
    counts: Counter[int],
    length: int,
) -> Optional[tuple[CardType, int, int]]:
    """识别顺子：5+ 连续单张，最高到 A，不含 2/王。"""
    if length < 5:
        return None
    if any(c != 1 for c in counts.values()):
        return None
    ranks = sorted(counts)
    if ranks[-1] > CHAIN_MAX_RANK:
        return None
    if not _is_consecutive(ranks):
        return None
    return CardType.STRAIGHT, ranks[0], length


def _identify_straight_pair(
    counts: Counter[int],
    length: int,
) -> Optional[tuple[CardType, int, int]]:
    """识别连对：3+ 连续对子，最高到 A，不含 2/王。"""
    if length < 6 or length % 2 != 0:
        return None
    pair_count = length // 2
    if pair_count < 3:
        return None
    if any(c != 2 for c in counts.values()):
        return None
    ranks = sorted(counts)
    if ranks[-1] > CHAIN_MAX_RANK:
        return None
    if not _is_consecutive(ranks):
        return None
    return CardType.STRAIGHT_PAIR, ranks[0], length


def _identify_plane(
    counts: Counter[int],
    length: int,
) -> Optional[tuple[CardType, int, int]]:
    """识别飞机（三个变体）。返回 (CardType, main_rank, length) 或 None。

    main_rank = 飞机三张部分最小的那个 rank（如 333 444 → 0）。
    比较时同型同长比 main_rank。
    """
    # 飞机的"三张部分" rank 必须 0..PLANE_MAX_RANK（不含 2 和王）
    triple_ranks = sorted(r for r, c in counts.items() if c == 3 and 0 <= r <= PLANE_MAX_RANK)
    if len(triple_ranks) < 2:
        return None

    # 三张部分必须连续；如果不是连续的整段，可能玩家在多个独立 triple 上拼凑
    # 这里要求恰好用上所有 triple_ranks 且它们连续
    K = len(triple_ranks)
    if triple_ranks != list(range(triple_ranks[0], triple_ranks[0] + K)):
        return None  # 三张不连续

    main_rank = triple_ranks[0]
    triple_rank_set = set(triple_ranks)
    wing_ranks = {r: c for r, c in counts.items() if r not in triple_rank_set}

    # 飞机不带翅膀：length == 3K，没有别的牌
    if length == 3 * K and not wing_ranks:
        return CardType.PLANE, main_rank, length

    # 飞机带小翅膀：length == 4K，K 张单牌（rank 互不相同；可含 2 和王）
    if length == 4 * K and len(wing_ranks) == K and all(c == 1 for c in wing_ranks.values()):
        return CardType.PLANE_WITH_SOLO, main_rank, length

    # 飞机带大翅膀：length == 5K，K 对（rank 互不相同；不可含王）
    if length == 5 * K and len(wing_ranks) == K and all(c == 2 for c in wing_ranks.values()):
        # 翅膀对里不能有王（王无法成对，count=2 不可能出现，这里只是双保险）
        if not any(r in (RANK_SMALL_JOKER, RANK_BIG_JOKER) for r in wing_ranks):
            return CardType.PLANE_WITH_PAIRS, main_rank, length

    return None


def can_beat(play: list[int], last_play: list[int]) -> bool:
    """play 能否压过 last_play。

    last_play 为空（[]）表示自己起新轮——任何合法牌型都能出。
    """
    play_info = identify(play)
    if play_info is None:
        return False  # play 本身不合法

    if not last_play:
        return True  # 起新轮，合法即可

    last_info = identify(last_play)
    if last_info is None:
        # last_play 不合法，不应该发生；保守返回 True（允许压过）
        return True

    play_type, play_rank, _ = play_info
    last_type, last_rank, _ = last_info

    # 王炸压一切
    if play_type == CardType.ROCKET:
        return True
    # 任何牌都压不过王炸
    if last_type == CardType.ROCKET:
        return False

    # 炸弹压一切非炸弹
    if play_type == CardType.BOMB and last_type != CardType.BOMB:
        return True
    # 非炸弹压不过炸弹
    if play_type != CardType.BOMB and last_type == CardType.BOMB:
        return False

    # 走到这里：要么都是炸弹、要么都是非炸弹。需要同型同长才能比
    if play_type != last_type or len(play) != len(last_play):
        return False
    return play_rank > last_rank


# ---------------- 可选：合法出牌枚举（给 LLM 当 hint） ----------------

def _consecutive_runs(sorted_ranks: list[int]) -> list[tuple[int, int]]:
    """从已排序 rank 列表里找出所有"极大连续段"。

    返回 [(start, length)]，length≥1。例：
      [0,1,2,5,6,9] → [(0,3), (5,2), (9,1)]
    """
    runs: list[tuple[int, int]] = []
    if not sorted_ranks:
        return runs
    start = sorted_ranks[0]
    length = 1
    for r in sorted_ranks[1:]:
        if r == start + length:
            length += 1
        else:
            runs.append((start, length))
            start = r
            length = 1
    runs.append((start, length))
    return runs


def enumerate_legal_plays(hand: list[int], last_play: list[int]) -> list[list[int]]:
    """枚举手牌中所有"独立 rank pattern"的合法出牌（已能压过 last_play 的）。

    返回 list[list[int]]：每个子列表是一手合法的牌（具体的 card_id）。
    同 rank pattern 只返回一个代表（避免 LLM hint 列表爆炸）。

    起新轮（last_play=[]）时列出所有可出的牌型。
    需要压牌时只列能压过 last_play 的牌型。
    """
    # 按 rank 分组，记录每张的 card_id
    by_rank: dict[int, list[int]] = {}
    for c in hand:
        by_rank.setdefault(card_rank(c), []).append(c)

    candidates: list[list[int]] = []

    # 单张：每个 rank 取代表 1 张
    for r, cs in by_rank.items():
        candidates.append(cs[:1])

    # 对子：rank 至少 2 张，且不是王（王不可能 count≥2）
    for r, cs in by_rank.items():
        if len(cs) >= 2 and r not in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
            candidates.append(cs[:2])

    # 三张
    triple_ranks = [r for r, cs in by_rank.items() if len(cs) >= 3]
    for r in triple_ranks:
        candidates.append(by_rank[r][:3])

    # 三带一：三张 + 任意非同 rank 的单张（kicker 可以是王）
    for r in triple_ranks:
        for k_r, k_cs in by_rank.items():
            if k_r == r:
                continue
            candidates.append(by_rank[r][:3] + k_cs[:1])

    # 三带二：三张 + 任意非同 rank 的对子（kicker 不可以是王）
    for r in triple_ranks:
        for k_r, k_cs in by_rank.items():
            if k_r == r:
                continue
            if k_r in (RANK_SMALL_JOKER, RANK_BIG_JOKER):
                continue
            if len(k_cs) >= 2:
                candidates.append(by_rank[r][:3] + k_cs[:2])

    # 顺子：5+ 连续单张，3-A，不含 2/王
    straight_eligible = sorted(
        r for r, cs in by_rank.items()
        if len(cs) >= 1 and 0 <= r <= CHAIN_MAX_RANK
    )
    for run_start, run_len in _consecutive_runs(straight_eligible):
        if run_len < 5:
            continue
        for K in range(5, run_len + 1):
            for sub_start in range(run_start, run_start + run_len - K + 1):
                chain_ranks = list(range(sub_start, sub_start + K))
                candidates.append([by_rank[r][0] for r in chain_ranks])

    # 连对：3+ 连续对子，3-A，不含 2/王
    straight_pair_eligible = sorted(
        r for r, cs in by_rank.items()
        if len(cs) >= 2 and 0 <= r <= CHAIN_MAX_RANK
    )
    for run_start, run_len in _consecutive_runs(straight_pair_eligible):
        if run_len < 3:
            continue
        for K in range(3, run_len + 1):
            for sub_start in range(run_start, run_start + run_len - K + 1):
                chain_ranks = list(range(sub_start, sub_start + K))
                cards: list[int] = []
                for r in chain_ranks:
                    cards.extend(by_rank[r][:2])
                candidates.append(cards)

    # 飞机：找出 [0..PLANE_MAX_RANK] 范围内 ≥3 张的连续段
    plane_eligible = sorted(
        r for r, cs in by_rank.items()
        if len(cs) >= 3 and 0 <= r <= PLANE_MAX_RANK
    )
    for run_start, run_len in _consecutive_runs(plane_eligible):
        if run_len < 2:
            continue
        # 对每个 K（2..run_len）和每个起点子段都枚举一遍
        for K in range(2, run_len + 1):
            for sub_start in range(run_start, run_start + run_len - K + 1):
                chain_ranks = list(range(sub_start, sub_start + K))
                triple_cards: list[int] = []
                for r in chain_ranks:
                    triple_cards.extend(by_rank[r][:3])

                # 1) 飞机不带翅膀
                candidates.append(list(triple_cards))

                # 2) 飞机带小翅膀：K 个非 chain 的 rank、每个取 1 张
                #    选 rank 升序前 K 个（确定性代表；LLM 可自行换更高/低）
                wing_solo_pool = sorted(
                    r for r in by_rank
                    if r not in chain_ranks and len(by_rank[r]) >= 1
                )
                if len(wing_solo_pool) >= K:
                    wings = [by_rank[r][0] for r in wing_solo_pool[:K]]
                    candidates.append(triple_cards + wings)

                # 3) 飞机带大翅膀：K 个非 chain 非王、每个取 2 张
                wing_pairs_pool = sorted(
                    r for r in by_rank
                    if r not in chain_ranks
                    and r not in (RANK_SMALL_JOKER, RANK_BIG_JOKER)
                    and len(by_rank[r]) >= 2
                )
                if len(wing_pairs_pool) >= K:
                    wings = []
                    for r in wing_pairs_pool[:K]:
                        wings.extend(by_rank[r][:2])
                    candidates.append(triple_cards + wings)

    # 炸弹
    for r, cs in by_rank.items():
        if len(cs) == 4:
            candidates.append(cs[:4])

    # 王炸
    if RANK_SMALL_JOKER in by_rank and RANK_BIG_JOKER in by_rank:
        candidates.append([by_rank[RANK_SMALL_JOKER][0], by_rank[RANK_BIG_JOKER][0]])

    # 过滤：只留能压过 last_play 的（can_beat 已处理新轮逻辑）
    return [c for c in candidates if can_beat(c, last_play)]


def describe_play(cards: list[int]) -> str:
    """把一手牌格式化成给 LLM/UI 看的简短描述。

    例子：
      [3♠, 3♥]              → "对 3"
      [7♠, 7♥, 7♣, 7♦]      → "炸弹 7"
      [52, 53]              → "王炸"
      [8♠, 8♥, 8♣, K♠]      → "三带一 (8 带 K)"
      [9♠, 9♥, 9♣, J♠, J♥]  → "三带二 (9 带 J)"
    """
    info = identify(cards)
    if info is None:
        return "(非法牌型)"

    ctype, main_rank, length = info

    if ctype == CardType.ROCKET:
        return "王炸"

    main_str = RANK_INT_TO_STR[main_rank]

    if ctype == CardType.SINGLE:
        return f"单 {main_str}"
    if ctype == CardType.PAIR:
        return f"对 {main_str}"
    if ctype == CardType.TRIPLE:
        return f"三张 {main_str}"
    if ctype == CardType.BOMB:
        return f"炸弹 {main_str}"
    if ctype == CardType.STRAIGHT:
        end_str = RANK_INT_TO_STR[main_rank + length - 1]
        return f"顺子 ({main_str}-{end_str})"
    if ctype == CardType.STRAIGHT_PAIR:
        pair_count = length // 2
        end_str = RANK_INT_TO_STR[main_rank + pair_count - 1]
        return f"连对 ({main_str}-{end_str})"

    # 飞机三个变体：标注"从 X 到 Y"的连续段
    if ctype in (CardType.PLANE, CardType.PLANE_WITH_SOLO, CardType.PLANE_WITH_PAIRS):
        per_triple = {
            CardType.PLANE: 3,
            CardType.PLANE_WITH_SOLO: 4,
            CardType.PLANE_WITH_PAIRS: 5,
        }[ctype]
        K = length // per_triple
        end_str = RANK_INT_TO_STR[main_rank + K - 1]
        suffix = {
            CardType.PLANE: "飞机",
            CardType.PLANE_WITH_SOLO: "飞机带小翅膀",
            CardType.PLANE_WITH_PAIRS: "飞机带大翅膀",
        }[ctype]
        return f"{suffix} ({main_str}-{end_str})"

    # 三带一 / 三带二 需要把"带的"那部分点数也写出来
    counts = Counter(card_rank(c) for c in cards)
    kicker_rank = next(r for r, c in counts.items() if r != main_rank)
    kicker_str = RANK_INT_TO_STR[kicker_rank]

    if ctype == CardType.TRIPLE_ONE:
        return f"三带一 ({main_str} 带 {kicker_str})"
    if ctype == CardType.TRIPLE_PAIR:
        return f"三带二 ({main_str} 带 {kicker_str})"

    return "(未识别)"


def hand_to_display(hand: list[int], with_suit: bool = False) -> str:
    """把手牌格式化成空格分隔的字符串。

    with_suit=False（默认，给 LLM 用）：
      "3 3 4 5 5 7 J J Q K A 2 小王 大王"
      只输出 rank、空格分隔、升序

    with_suit=True（给前端 UI 用）：
      "♠3 ♥3 ♣4 ♦5 ♠5 ... 小王 大王"
      带花色，王不带花色（直接写"小王"/"大王"）。
    """
    sorted_hand = sort_hand(hand)
    if with_suit:
        return " ".join(card_name(c) for c in sorted_hand)
    return " ".join(RANK_INT_TO_STR[card_rank(c)] for c in sorted_hand)


def parse_ranks_to_cards(ranks: list[str], hand: list[int]) -> list[int] | None:
    """LLM 输出的 cards rank 字符串列表 → 玩家手牌里挑出对应的整数 IDs。

    例：LLM 给 ["5", "5"]，hand 里有 4 张 5（不同 suit），随便挑两张返回。
    如果 hand 里凑不齐对应数量（LLM 撒谎了），返回 None。

    rank 字符串约定：
      "3".."10", "J", "Q", "K", "A", "2", "小王", "大王"

    实现策略：按 rank 分组 hand，对每个 rank 需求量从该组里弹出指定数量。
    返回顺序：按 ranks 输入顺序拼接（保留输入次序方便后续 identify 调试）。
    """
    # 字符串 → rank int；遇到未知字符串返回 None
    try:
        wanted: list[int] = [RANK_STR_TO_INT[r] for r in ranks]
    except KeyError:
        return None

    # 按 rank 把 hand 索引分组（注意是索引不是 card_id，避免重复 card 时混淆）
    by_rank: dict[int, list[int]] = {}
    for card in hand:
        by_rank.setdefault(card_rank(card), []).append(card)

    result: list[int] = []
    # 复制一份避免破坏原 by_rank
    pool = {r: list(cs) for r, cs in by_rank.items()}
    for r in wanted:
        if r not in pool or not pool[r]:
            return None
        result.append(pool[r].pop())
    return result


# ---------------- 统一出牌合规检查 ----------------

@dataclass
class PlayValidation:
    """出牌合规检查结果。

    ok=True 时 info 是 identify 的返回值；ok=False 时 reason 是中文错误信息。
    """
    ok: bool
    reason: str = ""
    info: Optional[tuple[CardType, int, int]] = None


def validate_play(
    cards: list[int],
    hand: list[int],
    last_play: list[int],
) -> PlayValidation:
    """统一的出牌合规检查 —— 人类玩家和 AI 都走这一套。

    按顺序检查（短路）：
      1. cards 非空（要 pass 走 /api/pass 单独接口、不走这里）
      2. cards 内部 card_id 不重复
      3. cards 全部在 hand 里
      4. cards 构成合法牌型（identify 返回非 None）
      5. cards 能压过 last_play（last_play=[] 时跳过此项，由 can_beat 内部处理）

    用法：
      - 人类玩家：UI POST /api/play 直接传 card_ids → validate_play → 失败回 400+reason
      - AI 玩家：parse_ranks_to_cards(llm_ranks, hand) → 得到 card_ids → validate_play
                失败则 fallback 到 pass（or 起新轮兜底打最小单张）
    """
    if not cards:
        return PlayValidation(False, reason="不能出空牌（要过牌请走 pass 接口）")

    # 重复 card_id 检查（同一张物理牌不能算两次）
    if len(set(cards)) != len(cards):
        return PlayValidation(False, reason="出牌列表里有重复的 card_id")

    # 牌都在手里（防止玩家凭空打牌或 AI 编造了不在手里的牌）
    hand_set = set(hand)
    missing = [c for c in cards if c not in hand_set]
    if missing:
        missing_names = ", ".join(card_name(c) for c in missing if 0 <= c < 54)
        return PlayValidation(False, reason=f"手里没有这些牌: [{missing_names}]")

    # 牌型合法
    info = identify(cards)
    if info is None:
        played_names = ", ".join(card_name(c) for c in cards)
        return PlayValidation(False, reason=f"不是合法牌型: [{played_names}]")

    # 能压上家
    if not can_beat(cards, last_play):
        # can_beat 在 last_play=[] 时永远 True，所以这里 last_play 一定非空
        return PlayValidation(
            False,
            reason=f"压不过上家的 {describe_play(last_play)}",
            info=info,
        )

    return PlayValidation(True, info=info)
