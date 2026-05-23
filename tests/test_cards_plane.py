"""测试飞机牌型：identify / can_beat / enumerate_legal_plays / describe_play

三种变体：
- PLANE：K 个连续三张，3K 张牌
- PLANE_WITH_SOLO：上面 + K 张单（rank 各异，可含 2 和王），4K 张牌
- PLANE_WITH_PAIRS：上面 + K 对（rank 各异、不含王），5K 张牌
"""

from server.cards import (
    BIG_JOKER,
    SMALL_JOKER,
    CardType,
    can_beat,
    describe_play,
    enumerate_legal_plays,
    identify,
    validate_play,
)


def cid(rank_idx: int, suit_offset: int = 0) -> int:
    return rank_idx * 4 + suit_offset


def triple(rank_idx: int) -> list[int]:
    """返回某 rank 的前 3 张（不同 suit）。"""
    return [cid(rank_idx, 0), cid(rank_idx, 1), cid(rank_idx, 2)]


# ================================================================
# identify：飞机不带翅膀
# ================================================================

def test_identify_plane_2_triples():
    # 333 444
    cards = triple(0) + triple(1)
    assert identify(cards) == (CardType.PLANE, 0, 6)


def test_identify_plane_3_triples():
    # 555 666 777
    cards = triple(2) + triple(3) + triple(4)
    assert identify(cards) == (CardType.PLANE, 2, 9)


def test_identify_plane_at_top_rank_A():
    # 飞机最高到 A：QQQ KKK AAA（rank 9,10,11）合法
    cards = triple(9) + triple(10) + triple(11)
    assert identify(cards) == (CardType.PLANE, 9, 9)


def test_plane_cannot_include_rank_2():
    # AAA 222 不算飞机（2 在 rank 12，超出 PLANE_MAX_RANK=11）
    cards = triple(11) + triple(12)
    assert identify(cards) is None


def test_plane_cannot_be_non_consecutive():
    # 333 555 不连续
    cards = triple(0) + triple(2)
    assert identify(cards) is None


# ================================================================
# identify：飞机带小翅膀
# ================================================================

def test_identify_plane_with_solo_wings():
    # 333 444 + 7 + 9
    cards = triple(0) + triple(1) + [cid(4, 0), cid(6, 0)]
    assert identify(cards) == (CardType.PLANE_WITH_SOLO, 0, 8)


def test_identify_plane_with_solo_includes_joker_wing():
    # 333 444 + 7 + 大王（翅膀可以是王）
    cards = triple(0) + triple(1) + [cid(4, 0), BIG_JOKER]
    assert identify(cards) == (CardType.PLANE_WITH_SOLO, 0, 8)


def test_identify_plane_with_solo_rejects_same_rank_wings():
    # 333 444 + 7 + 7（两张相同 rank 的"单"，实际是对子）
    cards = triple(0) + triple(1) + [cid(4, 0), cid(4, 1)]
    # counts = {0:3, 1:3, 4:2}, 长度 8，本应是 8=4K，K=2，但 wings 不是 K 个 distinct rank
    # 真实判定：识别成"飞机带小翅膀"需 wings 各异。此处 wings 是 1 个 rank、count=2，不匹配 4K 模式
    assert identify(cards) is None


def test_identify_plane_with_solo_3_triples():
    # 333 444 555 + 7 + 9 + J  → K=3
    cards = triple(0) + triple(1) + triple(2) + [cid(4, 0), cid(6, 0), cid(8, 0)]
    assert identify(cards) == (CardType.PLANE_WITH_SOLO, 0, 12)


# ================================================================
# identify：飞机带大翅膀
# ================================================================

def test_identify_plane_with_pair_wings():
    # 333 444 + 77 + 99
    cards = (
        triple(0) + triple(1)
        + [cid(4, 0), cid(4, 1)]   # 77
        + [cid(6, 0), cid(6, 1)]   # 99
    )
    assert identify(cards) == (CardType.PLANE_WITH_PAIRS, 0, 10)


def test_identify_plane_with_pair_wings_rejects_joker_pair():
    # 飞机带大翅膀的对子不能是王（王本身就单张，不可能 count=2，但定义上也禁止）
    # 这个 case 实际不可能构造（王只能一张），所以只验证逻辑边界
    cards = triple(0) + triple(1) + [SMALL_JOKER, BIG_JOKER, cid(6, 0), cid(6, 1)]
    # counts = {0:3, 1:3, 13:1, 14:1, 6:2}, 长度 10 = 5K (K=2)
    # 但 wings 是 3 个 rank（13、14、6），不是 K=2 个，所以走不到大翅膀分支
    assert identify(cards) is None


# ================================================================
# can_beat：飞机比较
# ================================================================

def test_can_beat_plane_higher_main_rank():
    # 444 555（main=1）压 333 444（main=0）
    play = triple(1) + triple(2)
    last = triple(0) + triple(1)
    # 注：玩家A 出 333 444 后这些牌从牌局消失，玩家B 出 444 555 用的是自己手里的牌
    # can_beat 只检查类型/长度/main_rank，不管牌物理是否冲突
    assert can_beat(play, last) is True


def test_can_beat_plane_same_main_rank_false():
    play = triple(0) + triple(1)
    last = triple(0) + triple(1)
    assert can_beat(play, last) is False


def test_can_beat_plane_different_K_false():
    # K=3 飞机 vs K=2 飞机：长度不同，互相压不过
    plane_K3 = triple(0) + triple(1) + triple(2)
    plane_K2 = triple(5) + triple(6)
    assert can_beat(plane_K3, plane_K2) is False
    assert can_beat(plane_K2, plane_K3) is False


def test_can_beat_plane_vs_plane_with_solo_false():
    """不同飞机变体不能互相压（同 K 但变体不同）。"""
    no_wings = triple(0) + triple(1)
    with_solo = triple(0) + triple(1) + [cid(4, 0), cid(6, 0)]
    assert can_beat(no_wings, with_solo) is False
    assert can_beat(with_solo, no_wings) is False


def test_can_beat_bomb_beats_plane():
    bomb = [cid(0, 0), cid(0, 1), cid(0, 2), cid(0, 3)]
    plane = triple(5) + triple(6)
    assert can_beat(bomb, plane) is True
    assert can_beat(plane, bomb) is False


def test_can_beat_rocket_beats_plane():
    rocket = [SMALL_JOKER, BIG_JOKER]
    plane = triple(5) + triple(6)
    assert can_beat(rocket, plane) is True
    assert can_beat(plane, rocket) is False


def test_can_beat_plane_with_solo_higher():
    play = triple(2) + triple(3) + [cid(0, 0), cid(8, 0)]  # 555 666 + 3 + J
    last = triple(0) + triple(1) + [cid(5, 0), cid(7, 0)]  # 333 444 + 8 + 10
    assert can_beat(play, last) is True


def test_can_beat_plane_with_pairs_higher():
    play = (
        triple(2) + triple(3)
        + [cid(8, 0), cid(8, 1)]  # JJ
        + [cid(10, 0), cid(10, 1)]  # KK
    )
    last = (
        triple(0) + triple(1)
        + [cid(5, 0), cid(5, 1)]
        + [cid(9, 0), cid(9, 1)]
    )
    assert can_beat(play, last) is True


# ================================================================
# enumerate_legal_plays：飞机被枚举出来
# ================================================================

def test_enumerate_includes_plane_no_wings():
    # 手牌：333 444 555 + 一些杂牌
    hand = triple(0) + triple(1) + triple(2) + [cid(8, 0), cid(10, 0)]
    plays = enumerate_legal_plays(hand, [])

    plane_no_wings = [p for p in plays if identify(p) and identify(p)[0] == CardType.PLANE]
    # 应该包含 K=2 飞机（333 444 / 444 555）和 K=3 飞机（333 444 555）
    assert len(plane_no_wings) >= 3


def test_enumerate_includes_plane_with_solo():
    # 333 444 + 一些单牌作为翅膀
    hand = triple(0) + triple(1) + [cid(4, 0), cid(6, 0), cid(8, 0), cid(10, 0)]
    plays = enumerate_legal_plays(hand, [])
    plane_solo = [p for p in plays if identify(p) and identify(p)[0] == CardType.PLANE_WITH_SOLO]
    assert len(plane_solo) >= 1


def test_enumerate_includes_plane_with_pairs():
    # 333 444 + 两对翅膀
    hand = triple(0) + triple(1) + [cid(5, 0), cid(5, 1), cid(7, 0), cid(7, 1)]
    plays = enumerate_legal_plays(hand, [])
    plane_pairs = [p for p in plays if identify(p) and identify(p)[0] == CardType.PLANE_WITH_PAIRS]
    assert len(plane_pairs) >= 1


def test_enumerate_filters_lower_plane():
    # 手里有 333 444 + 555 666，last_play 是 444 555（main=1）
    hand = triple(0) + triple(1) + triple(2) + triple(3)
    last = triple(1) + triple(2)  # 444 555

    plays = enumerate_legal_plays(hand, last)
    plane_plays = [p for p in plays if identify(p) and identify(p)[0] == CardType.PLANE]
    # 至少包含 555 666（main=2，能压）
    assert any(identify(p) == (CardType.PLANE, 2, 6) for p in plane_plays)
    # 不应包含 333 444（main=0，压不过）
    assert not any(identify(p) == (CardType.PLANE, 0, 6) for p in plane_plays)


def test_enumerate_no_plane_when_no_consecutive_triples():
    # 333 555 666（中间断了）+ 杂牌
    hand = triple(0) + triple(2) + triple(3) + [cid(8, 0)]
    plays = enumerate_legal_plays(hand, [])
    # 555 666 是连续的两个三张，会被识别为飞机
    plane_plays = [p for p in plays if identify(p) and identify(p)[0] == CardType.PLANE]
    assert any(identify(p) == (CardType.PLANE, 2, 6) for p in plane_plays)
    # 但 333 + 555 / 555 + 666 666 这种不连续的不会


# ================================================================
# describe_play：飞机描述
# ================================================================

def test_describe_plane_no_wings():
    cards = triple(0) + triple(1)  # 333 444
    assert describe_play(cards) == "飞机 (3-4)"


def test_describe_plane_3_triples():
    cards = triple(2) + triple(3) + triple(4)  # 555 666 777
    assert describe_play(cards) == "飞机 (5-7)"


def test_describe_plane_with_solo():
    cards = triple(0) + triple(1) + [cid(4, 0), cid(6, 0)]
    assert describe_play(cards) == "飞机带小翅膀 (3-4)"


def test_describe_plane_with_pairs():
    cards = (
        triple(0) + triple(1)
        + [cid(4, 0), cid(4, 1)]
        + [cid(6, 0), cid(6, 1)]
    )
    assert describe_play(cards) == "飞机带大翅膀 (3-4)"


# ================================================================
# validate_play：飞机走 validate_play 也要通过
# ================================================================

def test_validate_play_plane_ok():
    hand = triple(0) + triple(1) + [cid(8, 0)]
    cards = triple(0) + triple(1)
    r = validate_play(cards, hand, [])
    assert r.ok is True
    assert r.info[0] == CardType.PLANE


def test_validate_play_plane_cant_beat_higher_plane():
    hand = triple(0) + triple(1)
    last = triple(5) + triple(6)  # 888 999（main=5）
    cards = triple(0) + triple(1)  # 333 444（main=0）
    r = validate_play(cards, hand, last)
    assert r.ok is False
    assert "压不过" in r.reason
