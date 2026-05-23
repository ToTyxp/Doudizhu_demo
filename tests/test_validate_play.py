"""测试 validate_play —— 出牌合规性检查。

覆盖 5 个失败路径 + 多个成功路径，确保人类玩家和 AI 都用这一套验证。
"""

from server.cards import (
    BIG_JOKER,
    CardType,
    PlayValidation,
    SMALL_JOKER,
    parse_ranks_to_cards,
    validate_play,
)


def cid(rank_idx: int, suit_offset: int = 0) -> int:
    return rank_idx * 4 + suit_offset


# ================================================================
# 失败路径
# ================================================================

def test_empty_cards_rejected():
    hand = [cid(0), cid(0, 1)]
    r = validate_play([], hand, [])
    assert r.ok is False
    assert "空牌" in r.reason


def test_duplicate_card_id_rejected():
    """同一张物理牌不能算两次（哪怕牌型看起来像对子）。"""
    hand = [cid(0, 0), cid(0, 1)]
    r = validate_play([cid(0, 0), cid(0, 0)], hand, [])
    assert r.ok is False
    assert "重复" in r.reason


def test_card_not_in_hand_rejected():
    """玩家手里没有这张牌，不能凭空打出来。"""
    hand = [cid(0, 0), cid(0, 1)]
    # 玩家想打一对 5 但手里只有两个 3
    r = validate_play([cid(2, 0), cid(2, 1)], hand, [])
    assert r.ok is False
    assert "手里没有" in r.reason


def test_partial_in_hand_rejected():
    """有些在手里有些不在，整体也算非法。"""
    hand = [cid(0, 0), cid(0, 1)]
    # 一张 3 在手里，一张 5 不在
    r = validate_play([cid(0, 0), cid(2, 0)], hand, [])
    assert r.ok is False
    assert "手里没有" in r.reason


def test_illegal_card_type_rejected():
    """两张不同 rank 的单张拼在一起不是合法牌型。"""
    hand = [cid(0, 0), cid(1, 0)]
    r = validate_play([cid(0, 0), cid(1, 0)], hand, [])
    assert r.ok is False
    assert "合法牌型" in r.reason


def test_six_card_non_consecutive_singles_rejected():
    """6 张不连续散单不是合法牌型；连续 5+ 张会识别为顺子。"""
    hand = [cid(i) for i in [0, 1, 2, 3, 5, 6]]
    r = validate_play(hand, hand, [])
    assert r.ok is False
    assert "合法牌型" in r.reason


def test_cannot_beat_last_play_rejected():
    """同型但点数没人家大。"""
    hand = [cid(9, 0), cid(9, 1)]   # 对 Q
    last = [cid(10, 0), cid(10, 1)]  # 上家出对 K
    r = validate_play(hand, hand, last)
    assert r.ok is False
    assert "压不过" in r.reason
    assert r.info is not None  # 牌型本身合法，所以 info 仍带回


def test_cross_type_rejected():
    """跨型压不过，应该返回"压不过"而不是"非法牌型"。"""
    hand = [cid(5, 0), cid(5, 1), cid(5, 2)]  # 三张 8
    last = [cid(10, 0), cid(10, 1)]            # 对 K
    r = validate_play(hand, hand, last)
    assert r.ok is False
    assert "压不过" in r.reason


# ================================================================
# 成功路径
# ================================================================

def test_new_round_any_valid_play_ok():
    """起新轮（last_play=[]）任何合法牌型都通过。"""
    hand = [cid(0, 0), cid(0, 1), cid(5, 0)]
    # 单张 3
    r1 = validate_play([cid(0, 0)], hand, [])
    assert r1.ok is True
    assert r1.info == (CardType.SINGLE, 0, 1)
    # 对 3
    r2 = validate_play([cid(0, 0), cid(0, 1)], hand, [])
    assert r2.ok is True
    assert r2.info == (CardType.PAIR, 0, 2)


def test_higher_pair_beats_lower_pair():
    hand = [cid(10, 0), cid(10, 1)]
    last = [cid(9, 0), cid(9, 1)]  # 对 Q
    r = validate_play(hand, hand, last)
    assert r.ok is True
    assert r.info[0] == CardType.PAIR


def test_bomb_beats_pair():
    hand = [cid(0, 0), cid(0, 1), cid(0, 2), cid(0, 3)]  # 4 个 3
    last = [cid(12, 0), cid(12, 1)]                       # 对 2
    r = validate_play(hand, hand, last)
    assert r.ok is True
    assert r.info[0] == CardType.BOMB


def test_rocket_beats_bomb():
    hand = [SMALL_JOKER, BIG_JOKER]
    last = [cid(12, 0), cid(12, 1), cid(12, 2), cid(12, 3)]  # 炸 2
    r = validate_play(hand, hand, last)
    assert r.ok is True
    assert r.info[0] == CardType.ROCKET


def test_straight_and_straight_pair_validate_ok():
    straight = [cid(i) for i in range(5)]
    r = validate_play(straight, straight, [])
    assert r.ok is True
    assert r.info == (CardType.STRAIGHT, 0, 5)

    pair_chain = [cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1), cid(2, 0), cid(2, 1)]
    r = validate_play(pair_chain, pair_chain, [])
    assert r.ok is True
    assert r.info == (CardType.STRAIGHT_PAIR, 0, 6)


# ================================================================
# AI 路径：parse_ranks_to_cards + validate_play 组合
# ================================================================

def test_ai_flow_valid_play():
    """LLM 给 ["5","5"]，hand 里有 4 张 5，解析+验证全过。"""
    hand = [cid(2, i) for i in range(4)] + [cid(0, 0)]  # 4 张 5 + 1 张 3
    cards = parse_ranks_to_cards(["5", "5"], hand)
    assert cards is not None
    r = validate_play(cards, hand, [])
    assert r.ok is True
    assert r.info[0] == CardType.PAIR


def test_ai_flow_llm_hallucinated_cards():
    """LLM 出"5 5"但 hand 里没有 5，parse 返回 None（上层 fallback 到 pass）。"""
    hand = [cid(0, 0), cid(0, 1), cid(1, 0)]  # 只有 3 和 4
    cards = parse_ranks_to_cards(["5", "5"], hand)
    assert cards is None  # parse 阶段就拦下了


def test_ai_flow_invalid_combination():
    """LLM 出 ["5","7"]，parse 能解析（5 和 7 都在 hand），但 validate 应失败（牌型非法）。"""
    hand = [cid(2, 0), cid(4, 0), cid(4, 1)]  # 1 张 5 + 2 张 7
    cards = parse_ranks_to_cards(["5", "7"], hand)
    assert cards is not None
    r = validate_play(cards, hand, [])
    assert r.ok is False
    assert "合法牌型" in r.reason


def test_ai_flow_cant_beat_falls_through_to_reason():
    """AI 出对 Q 想压对 K，应该走"压不过"而不是"非法"。"""
    hand = [cid(9, i) for i in range(4)]
    last = [cid(10, 0), cid(10, 1)]
    cards = parse_ranks_to_cards(["Q", "Q"], hand)
    assert cards is not None
    r = validate_play(cards, hand, last)
    assert r.ok is False
    assert "压不过" in r.reason
