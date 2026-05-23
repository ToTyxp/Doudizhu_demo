"""测试 cards.py 的规则引擎：identify / can_beat / enumerate_legal_plays / describe_play。

约定：
- card_id = rank * 4 + suit_offset
- rank "3" 对应 card_id 0..3；rank "2" 对应 card_id 48..51
- SMALL_JOKER=52，BIG_JOKER=53
"""

from server.cards import (
    BIG_JOKER,
    ROCKET_RANK,
    SMALL_JOKER,
    CardType,
    can_beat,
    describe_play,
    enumerate_legal_plays,
    identify,
)


# ---- 工具：用 rank 索引 + 自动选一张 suit 来构造 card_id ----
def cid(rank_idx: int, suit_offset: int = 0) -> int:
    """rank_idx: 0..12（"3" 到 "2"）、suit_offset: 0..3"""
    return rank_idx * 4 + suit_offset


# ================================================================
# identify
# ================================================================

def test_identify_single():
    assert identify([cid(0)]) == (CardType.SINGLE, 0, 1)
    assert identify([cid(12, 3)]) == (CardType.SINGLE, 12, 1)
    assert identify([SMALL_JOKER]) == (CardType.SINGLE, 13, 1)
    assert identify([BIG_JOKER]) == (CardType.SINGLE, 14, 1)


def test_identify_pair():
    # 两张 5（rank 2）
    assert identify([cid(2, 0), cid(2, 1)]) == (CardType.PAIR, 2, 2)
    # 不同 rank 不是对子
    assert identify([cid(2, 0), cid(3, 0)]) is None


def test_identify_triple():
    assert identify([cid(5, 0), cid(5, 1), cid(5, 2)]) == (CardType.TRIPLE, 5, 3)


def test_identify_triple_one():
    # 三张 7 + 一张 K
    cards = [cid(4, 0), cid(4, 1), cid(4, 2), cid(10, 0)]
    assert identify(cards) == (CardType.TRIPLE_ONE, 4, 4)
    # 三张 7 + 一张大王（kicker 可以是王）
    cards = [cid(4, 0), cid(4, 1), cid(4, 2), BIG_JOKER]
    assert identify(cards) == (CardType.TRIPLE_ONE, 4, 4)


def test_identify_triple_pair():
    # 三张 8 + 一对 Q
    cards = [cid(5, 0), cid(5, 1), cid(5, 2), cid(9, 0), cid(9, 1)]
    assert identify(cards) == (CardType.TRIPLE_PAIR, 5, 5)


def test_identify_bomb():
    # 四个 7
    cards = [cid(4, 0), cid(4, 1), cid(4, 2), cid(4, 3)]
    assert identify(cards) == (CardType.BOMB, 4, 4)


def test_identify_rocket():
    assert identify([SMALL_JOKER, BIG_JOKER]) == (CardType.ROCKET, ROCKET_RANK, 2)
    assert identify([BIG_JOKER, SMALL_JOKER]) == (CardType.ROCKET, ROCKET_RANK, 2)


def test_identify_straight():
    assert identify([cid(i) for i in range(5)]) == (CardType.STRAIGHT, 0, 5)
    assert identify([cid(i) for i in range(7, 12)]) == (CardType.STRAIGHT, 7, 5)
    assert identify([cid(i) for i in range(0, 12)]) == (CardType.STRAIGHT, 0, 12)


def test_identify_straight_rejects_2_jokers_and_duplicates():
    assert identify([cid(i) for i in range(8, 13)]) is None
    assert identify([cid(7), cid(8), cid(9), cid(10), SMALL_JOKER]) is None
    assert identify([cid(0), cid(1), cid(2), cid(3)]) is None
    assert identify([cid(0), cid(1), cid(2), cid(3), cid(3, 1)]) is None


def test_identify_straight_pair():
    cards = [cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1), cid(2, 0), cid(2, 1)]
    assert identify(cards) == (CardType.STRAIGHT_PAIR, 0, 6)
    long_cards = []
    for rank in range(6, 12):
        long_cards.extend([cid(rank, 0), cid(rank, 1)])
    assert identify(long_cards) == (CardType.STRAIGHT_PAIR, 6, 12)


def test_identify_straight_pair_rejects_invalid_patterns():
    # 只有两对不是连对
    assert identify([cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1)]) is None
    # 不能包含 2
    cards = [cid(10, 0), cid(10, 1), cid(11, 0), cid(11, 1), cid(12, 0), cid(12, 1)]
    assert identify(cards) is None
    # 三对但不连续
    cards = [cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1), cid(3, 0), cid(3, 1)]
    assert identify(cards) is None
    # 连续 rank 但其中一组不是对子
    cards = [cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1), cid(2, 0), cid(2, 1), cid(2, 2)]
    assert identify(cards) is None


def test_identify_invalid():
    assert identify([]) is None
    # 4 张但不是炸/三带一
    assert identify([cid(0), cid(0), cid(1), cid(1)]) is None  # 两对
    # 5 张但不是三带二
    assert identify([cid(0), cid(0), cid(0), cid(1), cid(2)]) is None  # 三 + 两个不同单张
    # 三 + 两张王不是三带二（王不能成对）
    assert identify(
        [cid(4, 0), cid(4, 1), cid(4, 2), SMALL_JOKER, BIG_JOKER]
    ) is None


# ================================================================
# can_beat
# ================================================================

def test_can_beat_new_round():
    # last_play=[] 任何合法 play 都能出
    assert can_beat([cid(0)], []) is True
    assert can_beat([cid(0), cid(0, 1)], []) is True
    # 非法 play 永远 False
    assert can_beat([cid(0), cid(1)], []) is False


def test_can_beat_single_compare():
    # 4 比 3 大
    assert can_beat([cid(1)], [cid(0)]) is True
    # 3 比 4 小
    assert can_beat([cid(0)], [cid(1)]) is False
    # 同 rank 不能压
    assert can_beat([cid(0, 1)], [cid(0, 0)]) is False
    # 大王压所有单张
    assert can_beat([BIG_JOKER], [cid(12)]) is True
    # 单张 2 压不过大王
    assert can_beat([cid(12)], [BIG_JOKER]) is False


def test_can_beat_pair():
    # 对 K 压对 Q
    assert can_beat([cid(10, 0), cid(10, 1)], [cid(9, 0), cid(9, 1)]) is True
    # 反之不行
    assert can_beat([cid(9, 0), cid(9, 1)], [cid(10, 0), cid(10, 1)]) is False
    # 对子压不了单张（跨型）
    assert can_beat([cid(10, 0), cid(10, 1)], [BIG_JOKER]) is False


def test_can_beat_bomb_over_non_bomb():
    # 炸弹压对子
    bomb = [cid(0, 0), cid(0, 1), cid(0, 2), cid(0, 3)]
    pair = [cid(12, 0), cid(12, 1)]
    assert can_beat(bomb, pair) is True
    # 反之不行
    assert can_beat(pair, bomb) is False
    # 炸弹压三带一
    triple_one = [cid(5, 0), cid(5, 1), cid(5, 2), cid(8, 0)]
    assert can_beat(bomb, triple_one) is True


def test_can_beat_bomb_vs_bomb():
    bomb_lo = [cid(0, 0), cid(0, 1), cid(0, 2), cid(0, 3)]  # 4 个 3
    bomb_hi = [cid(12, 0), cid(12, 1), cid(12, 2), cid(12, 3)]  # 4 个 2
    assert can_beat(bomb_hi, bomb_lo) is True
    assert can_beat(bomb_lo, bomb_hi) is False


def test_can_beat_rocket():
    rocket = [SMALL_JOKER, BIG_JOKER]
    bomb = [cid(12, 0), cid(12, 1), cid(12, 2), cid(12, 3)]
    # 王炸压一切
    assert can_beat(rocket, bomb) is True
    assert can_beat(rocket, [cid(0)]) is True
    # 任何牌都压不过王炸
    assert can_beat(bomb, rocket) is False
    assert can_beat([cid(12)], rocket) is False


def test_can_beat_cross_type_fails():
    # 三张压不了对子（不同型）
    triple = [cid(5, 0), cid(5, 1), cid(5, 2)]
    pair = [cid(0, 0), cid(0, 1)]
    assert can_beat(triple, pair) is False
    assert can_beat(pair, triple) is False
    # 三带一压不了三带二
    t1 = [cid(5, 0), cid(5, 1), cid(5, 2), cid(8, 0)]
    t2 = [cid(0, 0), cid(0, 1), cid(0, 2), cid(1, 0), cid(1, 1)]
    assert can_beat(t1, t2) is False


def test_can_beat_straight_and_straight_pair():
    straight_lo = [cid(i) for i in range(5)]
    straight_hi = [cid(i) for i in range(1, 6)]
    straight_long = [cid(i) for i in range(6)]
    assert can_beat(straight_hi, straight_lo) is True
    assert can_beat(straight_lo, straight_hi) is False
    assert can_beat(straight_long, straight_lo) is False

    pair_lo = [cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1), cid(2, 0), cid(2, 1)]
    pair_hi = [cid(1, 0), cid(1, 1), cid(2, 0), cid(2, 1), cid(3, 0), cid(3, 1)]
    pair_long = pair_lo + [cid(3, 0), cid(3, 1)]
    assert can_beat(pair_hi, pair_lo) is True
    assert can_beat(pair_lo, pair_hi) is False
    assert can_beat(pair_long, pair_lo) is False
    assert can_beat(straight_hi, pair_lo) is False


# ================================================================
# enumerate_legal_plays
# ================================================================

def test_enumerate_empty_hand():
    assert enumerate_legal_plays([], []) == []
    assert enumerate_legal_plays([], [cid(0)]) == []


def test_enumerate_new_round_lists_all_basic_plays():
    # 手牌：3 3 5 5 5 K
    hand = [cid(0, 0), cid(0, 1), cid(2, 0), cid(2, 1), cid(2, 2), cid(10, 0)]
    plays = enumerate_legal_plays(hand, [])

    # 应该包含：3 个单张代表（rank 0/2/10）+ 2 个对子（3 3、5 5）+ 1 个三张（5）
    # + 三带一组合（5 5 5 带 3 或 K）+ 三带二（5 5 5 带 3 3）
    types_seen = set()
    for p in plays:
        info = identify(p)
        if info:
            types_seen.add(info[0])
    assert CardType.SINGLE in types_seen
    assert CardType.PAIR in types_seen
    assert CardType.TRIPLE in types_seen
    assert CardType.TRIPLE_ONE in types_seen
    assert CardType.TRIPLE_PAIR in types_seen


def test_enumerate_filters_by_last_play():
    # 手牌：5 5 5 K K，last_play 是对 Q
    hand = [cid(2, 0), cid(2, 1), cid(2, 2), cid(10, 0), cid(10, 1)]
    last = [cid(9, 0), cid(9, 1)]  # 对 Q

    plays = enumerate_legal_plays(hand, last)
    # 所有返回的都应能压过对 Q（同型且更大、或炸弹、或王炸）
    for p in plays:
        assert can_beat(p, last), f"{describe_play(p)} 不能压 对 Q"
    # 应该包含对 K（同型更大）
    assert any(identify(p) == (CardType.PAIR, 10, 2) for p in plays)


def test_enumerate_bombs_appear_when_present():
    # 手牌有炸弹和别的，last_play 是对子
    hand = [
        cid(2, 0), cid(2, 1), cid(2, 2), cid(2, 3),  # 4 个 5（炸）
        cid(9, 0), cid(9, 1),                          # 对 Q
    ]
    last = [cid(10, 0), cid(10, 1)]  # 对 K（比 Q 大）
    plays = enumerate_legal_plays(hand, last)
    # 对 Q 压不过对 K，但炸弹能。结果里应该只有炸弹
    bomb_plays = [p for p in plays if identify(p)[0] == CardType.BOMB]
    assert len(bomb_plays) >= 1


def test_enumerate_rocket_beats_bomb():
    # 手牌有王炸 + 别的，last_play 是炸弹
    hand = [
        SMALL_JOKER, BIG_JOKER,
        cid(0, 0), cid(0, 1), cid(0, 2),
    ]
    last = [cid(5, 0), cid(5, 1), cid(5, 2), cid(5, 3)]  # 炸弹 8
    plays = enumerate_legal_plays(hand, last)
    # 只有王炸能压
    assert any(identify(p)[0] == CardType.ROCKET for p in plays)
    # 其它都不该出现
    for p in plays:
        assert identify(p)[0] == CardType.ROCKET


def test_enumerate_nothing_beats_rocket():
    # 即使手里有炸弹，也压不过王炸
    hand = [cid(0, 0), cid(0, 1), cid(0, 2), cid(0, 3)]  # 炸弹 3
    last = [SMALL_JOKER, BIG_JOKER]
    assert enumerate_legal_plays(hand, last) == []


def test_enumerate_no_duplicate_rank_patterns():
    """同 rank pattern 不该重复出现（每个独立 pattern 一个代表）。"""
    # 手牌有 4 张 5 + 1 张 6
    hand = [cid(2, 0), cid(2, 1), cid(2, 2), cid(2, 3), cid(3, 0)]
    plays = enumerate_legal_plays(hand, [])
    # 单张 5 应该只出现 1 次（不应每个 suit 各一次）
    single_5_plays = [p for p in plays if identify(p) == (CardType.SINGLE, 2, 1)]
    assert len(single_5_plays) == 1


def test_enumerate_includes_straights():
    hand = [cid(i) for i in range(7)] + [cid(12), SMALL_JOKER]
    plays = enumerate_legal_plays(hand, [])
    straights = [p for p in plays if identify(p) and identify(p)[0] == CardType.STRAIGHT]
    assert any(identify(p) == (CardType.STRAIGHT, 0, 5) for p in straights)
    assert any(identify(p) == (CardType.STRAIGHT, 1, 5) for p in straights)
    assert not any(cid(12) in p or SMALL_JOKER in p for p in straights)


def test_enumerate_includes_straight_pairs_and_filters():
    hand = []
    for rank in range(5):
        hand.extend([cid(rank, 0), cid(rank, 1)])
    last = [cid(0, 2), cid(0, 3), cid(1, 2), cid(1, 3), cid(2, 2), cid(2, 3)]
    plays = enumerate_legal_plays(hand, last)
    straight_pairs = [
        p for p in plays
        if identify(p) and identify(p)[0] == CardType.STRAIGHT_PAIR
    ]
    assert any(identify(p) == (CardType.STRAIGHT_PAIR, 1, 6) for p in straight_pairs)
    assert not any(identify(p) == (CardType.STRAIGHT_PAIR, 0, 6) for p in straight_pairs)


# ================================================================
# describe_play
# ================================================================

def test_describe_basic_types():
    assert describe_play([cid(0)]) == "单 3"
    assert describe_play([cid(12, 0)]) == "单 2"
    assert describe_play([BIG_JOKER]) == "单 大王"
    assert describe_play([cid(2, 0), cid(2, 1)]) == "对 5"
    assert describe_play([cid(5, 0), cid(5, 1), cid(5, 2)]) == "三张 8"


def test_describe_bomb_and_rocket():
    bomb = [cid(0, 0), cid(0, 1), cid(0, 2), cid(0, 3)]
    assert describe_play(bomb) == "炸弹 3"
    assert describe_play([SMALL_JOKER, BIG_JOKER]) == "王炸"


def test_describe_triple_with_kicker():
    # 三张 5 + 一张 K
    t1 = [cid(2, 0), cid(2, 1), cid(2, 2), cid(10, 0)]
    assert describe_play(t1) == "三带一 (5 带 K)"
    # 三张 8 + 一对 J
    t2 = [cid(5, 0), cid(5, 1), cid(5, 2), cid(8, 0), cid(8, 1)]
    assert describe_play(t2) == "三带二 (8 带 J)"
    # 三张 7 + 大王（kicker 是王）
    t3 = [cid(4, 0), cid(4, 1), cid(4, 2), BIG_JOKER]
    assert describe_play(t3) == "三带一 (7 带 大王)"


def test_describe_straight_and_straight_pair():
    assert describe_play([cid(i) for i in range(5)]) == "顺子 (3-7)"
    cards = [cid(0, 0), cid(0, 1), cid(1, 0), cid(1, 1), cid(2, 0), cid(2, 1)]
    assert describe_play(cards) == "连对 (3-5)"


def test_describe_invalid():
    assert describe_play([]) == "(非法牌型)"
    # 两个不同 rank 单张
    assert describe_play([cid(0), cid(1)]) == "(非法牌型)"
