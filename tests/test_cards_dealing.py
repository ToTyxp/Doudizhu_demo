"""测试 cards.py 里"发牌 + 牌面表示"这部分。

牌型识别/比较/枚举（identify / can_beat / enumerate_legal_plays / describe_play）的测试
由 yxp 自己实现规则引擎时再补。
"""

from collections import Counter

from server.cards import (
    BIG_JOKER,
    RANK_BIG_JOKER,
    RANK_SMALL_JOKER,
    SMALL_JOKER,
    card_name,
    card_rank,
    card_suit,
    hand_to_display,
    make_deck,
    parse_ranks_to_cards,
    shuffle_and_deal,
    sort_hand,
)


# ---------------- 常量 / 单牌 ----------------

def test_card_rank_jokers():
    assert card_rank(SMALL_JOKER) == RANK_SMALL_JOKER == 13
    assert card_rank(BIG_JOKER) == RANK_BIG_JOKER == 14


def test_card_rank_normal_cards():
    # card 0..3 是四张 3；card 4..7 是四张 4
    for c in range(4):
        assert card_rank(c) == 0  # rank "3"
    for c in range(4, 8):
        assert card_rank(c) == 1  # rank "4"
    # card 48..51 是四张 "2"（最大的普通牌）
    for c in range(48, 52):
        assert card_rank(c) == 12  # rank "2"


def test_card_suit():
    assert card_suit(0) == 0  # ♠3
    assert card_suit(1) == 1  # ♥3
    assert card_suit(2) == 2  # ♣3
    assert card_suit(3) == 3  # ♦3
    assert card_suit(SMALL_JOKER) == -1
    assert card_suit(BIG_JOKER) == -1


def test_card_name():
    assert card_name(0) == "♠3"
    assert card_name(1) == "♥3"
    assert card_name(48) == "♠2"
    assert card_name(SMALL_JOKER) == "小王"
    assert card_name(BIG_JOKER) == "大王"


def test_invalid_card_raises():
    import pytest

    with pytest.raises(ValueError):
        card_rank(54)
    with pytest.raises(ValueError):
        card_rank(-1)


# ---------------- 排序 ----------------

def test_sort_hand_basic():
    # 无序：大王、♣4、♠3、小王、♥2
    unsorted = [BIG_JOKER, 6, 0, SMALL_JOKER, 49]
    s = sort_hand(unsorted)
    # 排序后：♠3 (0), ♣4 (6), ♥2 (49), 小王 (52), 大王 (53)
    assert s == [0, 6, 49, SMALL_JOKER, BIG_JOKER]


def test_sort_hand_same_rank():
    # 4 张 5：card 8..11
    hand = [11, 8, 10, 9]
    s = sort_hand(hand)
    # 同 rank 内按 suit 升序
    assert s == [8, 9, 10, 11]


# ---------------- 发牌 ----------------

def test_make_deck():
    deck = make_deck()
    assert len(deck) == 54
    assert set(deck) == set(range(54))


def test_deal_split_sizes():
    h0, h1, h2, bottom = shuffle_and_deal(seed=42)
    assert len(h0) == 17
    assert len(h1) == 17
    assert len(h2) == 17
    assert len(bottom) == 3


def test_deal_covers_all_cards_no_dupes():
    h0, h1, h2, bottom = shuffle_and_deal(seed=42)
    all_cards = h0 + h1 + h2 + bottom
    assert len(all_cards) == 54
    assert set(all_cards) == set(range(54))   # 不重不漏


def test_deal_deterministic_with_seed():
    """同 seed 发牌必须完全一致——单测复现刚需。"""
    a = shuffle_and_deal(seed=123)
    b = shuffle_and_deal(seed=123)
    assert a == b


def test_deal_random_without_seed():
    """不给 seed 时连续两次发牌应该不一样（极小概率撞同）。"""
    a = shuffle_and_deal()
    b = shuffle_and_deal()
    assert a != b


def test_deal_hands_are_sorted():
    h0, h1, h2, bottom = shuffle_and_deal(seed=42)
    for hand in (h0, h1, h2, bottom):
        sorted_hand = sort_hand(list(hand))
        assert hand == sorted_hand


def _avg_pairs_per_hand(cluster_strength: float, n_trials: int = 200) -> float:
    """统计某 cluster_strength 下，每手平均有多少个"≥2 同 rank"的组。"""
    from server.cards import card_rank as _cr
    total = 0
    for i in range(n_trials):
        h0, h1, h2, _ = shuffle_and_deal(seed=10_000 + i, cluster_strength=cluster_strength)
        for h in (h0, h1, h2):
            counts = Counter(_cr(c) for c in h)
            total += sum(1 for v in counts.values() if v >= 2)
    return total / (n_trials * 3)


def test_cluster_strength_increases_pairs():
    """轻偏置（0.5）的平均对子数应该明显多于纯随机（0.0）。

    这个测试同时验证：
      a) cluster_strength=0 退化为纯随机
      b) cluster_strength=0.5 确实产生可感知的偏置
    """
    pure_random = _avg_pairs_per_hand(0.0)
    biased = _avg_pairs_per_hand(0.5)
    # 200 局 × 3 手 = 600 个样本，差异应该稳定
    assert biased > pure_random, (
        f"轻偏置没起作用：纯随机 avg pairs = {pure_random:.2f}, "
        f"偏置 avg pairs = {biased:.2f}"
    )
    # 不要偏太狠（避免一不小心调成强偏置）
    assert biased < pure_random + 3, (
        f"偏置过强：{biased:.2f} vs {pure_random:.2f}（差值 > 3）"
    )


# ---------------- 展示格式 ----------------

def test_hand_to_display_rank_only():
    # 构造一个手牌：♠3, ♥3, ♣4, ♦5, 小王, 大王
    hand = [0, 1, 6, 9, SMALL_JOKER, BIG_JOKER]
    s = hand_to_display(hand, with_suit=False)
    # 期望：rank 升序，王在最后
    assert s == "3 3 4 5 小王 大王"


def test_hand_to_display_with_suit():
    # 0=♠3, 1=♥3, 6=♣4, 9=♥5（5 在 rank idx 2，5*4=8 是 ♠5；9 = ♥5）
    hand = [0, 1, 6, 9, SMALL_JOKER, BIG_JOKER]
    s = hand_to_display(hand, with_suit=True)
    assert s == "♠3 ♥3 ♣4 ♥5 小王 大王"


def test_hand_to_display_10():
    # ♠10 = card 28（10 是第 7 个 rank，idx 7，所以 7*4 = 28..31）
    s = hand_to_display([28], with_suit=False)
    assert s == "10"


# ---------------- parse_ranks_to_cards ----------------

def test_parse_simple_pair():
    # hand 有 4 张 5（card 8..11）
    hand = [8, 9, 10, 11, 20, 21]
    cards = parse_ranks_to_cards(["5", "5"], hand)
    assert cards is not None
    assert len(cards) == 2
    assert all(card_rank(c) == 2 for c in cards)  # rank "5" 是 idx 2


def test_parse_triple_one_kicker():
    # 三张 7 + 一张 K
    # 7 → rank 4 → cards 16..19
    # K → rank 10 → cards 40..43
    hand = [16, 17, 18, 40, 41]
    cards = parse_ranks_to_cards(["7", "7", "7", "K"], hand)
    assert cards is not None
    assert len(cards) == 4
    ranks_got = Counter(card_rank(c) for c in cards)
    assert ranks_got == {4: 3, 10: 1}  # 三张 7 + 一张 K


def test_parse_jokers():
    hand = [0, SMALL_JOKER, BIG_JOKER]
    cards = parse_ranks_to_cards(["小王", "大王"], hand)
    assert cards == [SMALL_JOKER, BIG_JOKER] or cards == [BIG_JOKER, SMALL_JOKER]
    # 实际我们 pop 顺序固定，所以应该是 [小王, 大王] 顺序
    assert cards == [SMALL_JOKER, BIG_JOKER]


def test_parse_not_enough_cards_returns_none():
    # hand 只有 2 张 5，LLM 想要 3 张 → None
    hand = [8, 9, 20]
    assert parse_ranks_to_cards(["5", "5", "5"], hand) is None


def test_parse_invalid_rank_string_returns_none():
    hand = [0, 1, 2]
    # "11" 不是合法 rank
    assert parse_ranks_to_cards(["11"], hand) is None
    # "joker" 英文不在映射里
    assert parse_ranks_to_cards(["joker"], hand) is None


def test_parse_empty_ranks_returns_empty_list():
    hand = [0, 1, 2]
    assert parse_ranks_to_cards([], hand) == []
