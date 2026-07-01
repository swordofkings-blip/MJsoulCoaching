# -*- coding: utf-8 -*-
"""
@title v2 9 次元入力評価
@description 戦略モード判定に必要な 9 次元入力ベクトルを計算:
              A_speed: 手の早さ (0-1, 高=速い)
              A_value: 手の打点 (0-1, 高=強打)
              B[3]:   三人別 放銃リスク (0-1, 高=危険)
              C:      順位圧 (0-1, 高=焦り)
              D[5]:   手牌特性ベクトル
                d_pair: 対子率, d_honor: 字牌率, d_color: 1色偏り,
                d_yaochu: ヤオ九率, d_ukeire: 受け入れ広さ
"""
from __future__ import annotations
from typing import Tuple, List


def _get_left(state) -> int:
    return getattr(state, 'left_tile_count', 70) or 70


def compute_speed(state) -> float:
    """A_speed: 手の早さ (0-1, テンパイ=1.0)"""
    from core.shanten_v2 import ShantenCalculatorV2
    from core.str_converter import hand_to_counts
    hand = getattr(state, 'my_hand', []) or []
    if not hand:
        return 0.0
    counts = hand_to_counts(hand)
    open_cnt = sum(1 for m in getattr(state, 'my_melds', []) or [] if getattr(m, 'is_open', False))
    if open_cnt == 0:
        sh = ShantenCalculatorV2.calculate_closed_effective(counts)
    else:
        sh = ShantenCalculatorV2.calculate_open(counts, open_cnt)
    if sh <= 0:
        return 1.0
    if sh == 1:
        # 受け入れ広さで補正
        visible = state.all_visible_counts() if hasattr(state, 'all_visible_counts') else [0]*34
        ukeire = 0
        for tid in range(34):
            if counts[tid] >= 4 or visible[tid] >= 4:
                continue
            test = list(counts); test[tid] += 1
            if open_cnt == 0:
                ns = ShantenCalculatorV2.calculate_closed_effective(test)
            else:
                ns = ShantenCalculatorV2.calculate_open(test, open_cnt)
            if ns == 0:
                ukeire += 4 - visible[tid]
        return min(0.7, 0.4 + ukeire * 0.02)
    return max(0.1, 0.5 - sh * 0.15)


def compute_value(state) -> float:
    """A_value: 手の打点 (0-1, 満貫以上=1.0)"""
    from core.riichi_v2 import estimate_han_count
    hand = getattr(state, 'my_hand', []) or []
    if not hand:
        return 0.0
    han = estimate_han_count(state)
    if han >= 4: return 1.0
    if han >= 3: return 0.7
    if han >= 2: return 0.5
    if han >= 1: return 0.3
    return 0.1


def compute_opp_risks(state) -> List[float]:
    """B[3]: 三人別の放銃リスク (0-1)"""
    risks = []
    reach = getattr(state, 'reach_states', [None]*4)
    melds = getattr(state, 'melds', [[]]*4)
    rivers = getattr(state, 'river', [[]]*4)
    my_seat = getattr(state, 'my_seat', 0)
    for s in range(4):
        if s == my_seat:
            continue
        risk = 0.1
        # リーチ: +0.6
        if s < len(reach) and reach[s] is not None and reach[s].is_reach:
            risk += 0.6
        # 2副露以上: +0.3
        if s < len(melds) and len(melds[s]) >= 2:
            risk += 0.3
        # ツモ切り率高: +0.15
        if s < len(rivers) and len(rivers[s]) >= 3:
            consec = 0
            for i in range(1, len(rivers[s])):
                try:
                    from core.str_converter import tile_to_id
                    if tile_to_id(rivers[s][i]) == tile_to_id(rivers[s][i-1]):
                        consec += 1
                except:
                    pass
            if consec / max(len(rivers[s]), 1) > 0.5:
                risk += 0.15
        risks.append(min(1.0, risk))
    return risks


def compute_pressure(state) -> float:
    """C: 順位圧 (0-1, 高=焦り)"""
    if not hasattr(state, 'scores') or not state.scores:
        return 0.5
    my_score = state.scores[getattr(state, 'my_seat', 0)]
    sorted_scores = sorted(state.scores, reverse=True)
    rank = sorted_scores.index(my_score)
    gap_to_third = sorted_scores[2] - my_score if rank == 3 else 0
    base = 0.0
    if rank == 3: base = min(1.0, 0.4 + gap_to_third / 20000)  # 4位
    elif rank == 2: base = 0.3
    elif rank == 1: base = 0.15
    else: base = 0.0
    # 進行度
    total = 4  # tonpu
    try:
        current = (getattr(state, 'chang', 0) or 0) * 4 + (getattr(state, 'ju', 0) or 0) + 1
    except:
        current = 1
    progress = min(1.0, current / max(total, 1))
    return min(1.0, base * (0.5 + progress * 0.5))


def compute_hand_profile(state) -> List[float]:
    """D[5]: 手牌特性ベクトル
    [d_pair, d_honor, d_color, d_yaochu, d_ukeire]
    """
    from core.str_converter import tile_to_id
    hand = getattr(state, 'my_hand', []) or []
    if not hand or len(hand) < 13:
        return [0.0]*5
    ids = [tile_to_id(t) for t in hand if t]
    n = len(ids) if ids else 1
    # d_pair
    from core.str_converter import hand_to_counts
    counts = hand_to_counts(hand)
    pairs = sum(1 for c in counts if c >= 2)
    d_pair = min(1.0, pairs / 7.0)
    d_honor = sum(1 for t in ids if t >= 27) / n
    # d_color
    man = sum(1 for t in ids if 0 <= t < 9)
    pin = sum(1 for t in ids if 9 <= t < 18)
    sou = sum(1 for t in ids if 18 <= t < 27)
    max_suit = max(man, pin, sou) / max(n, 1)
    d_color = min(1.0, max_suit * 1.5)
    # d_yaochu
    yao9_set = {0, 8, 9, 17, 18, 26} | set(range(27, 34))
    yao9 = sum(1 for t in ids if t in yao9_set) / n
    d_yaochu = min(1.0, yao9 * 2.0)
    # d_ukeire (簡易)
    visible = state.all_visible_counts() if hasattr(state, 'all_visible_counts') else [0]*34
    ukeire = sum(max(0, 4 - visible[tid]) for tid in range(34) if counts[tid] > 0)
    d_ukeire = min(1.0, ukeire / 50.0)
    return [d_pair, d_honor, d_color, d_yaochu, d_ukeire]


def compute_full_5d(state) -> dict:
    """5D セット (A_speed, A_value, B_risk, C_press, D_profile)"""
    B = compute_opp_risks(state)
    return {
        'speed': compute_speed(state),
        'value': compute_value(state),
        'b_risk_max': max(B) if B else 0.5,
        'b_risk_all': B,
        'pressure': compute_pressure(state),
        'profile': compute_hand_profile(state),
    }
