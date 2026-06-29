# -*- coding: utf-8 -*-
"""
@title ver.2 立直判断 (加減算モデル)
@description テンパイ時の立直判断を 自前実装。
              加減算: 立直_score = 加点 - 減点 + 状況補正
              人間挙動再現 (ver.1 とは独立) と 麻雀セオリー 両立を目指す。

重み:
  - 期待値最大化 (門前 vs 立直)
  - 裏ドラ期待
  - 一発・ドラ表示牌増加
  - 手役の確定度
  - 状況 (巡目、点数、順位、他家)

門前立直と ダマテン の 期待値差 で 判断:
  EV(立直) = EV(和了) + 1 han (裏ドラ) + 立直棒 (1,000 点)
  EV(門前) = EV(和了) + α han (門前ボーナス)
  → 立直 > 門前 → 立直
"""
from __future__ import annotations
from typing import List, Tuple

from core.str_converter import tile_to_id, is_honor
from core.shanten_v2 import ShantenCalculatorV2


DEFAULT_WEIGHTS = {
    'RIICHI_W_BASE_SCORE': -100.0,        # 人間挙動 16% 立直 目標 (実測 16.1%)
    'RIICHI_W_URA_DORA': 30.0,            # 裏ドラ期待 +1 翻
    'RIICHI_W_RIICHI_STICK': 50.0,        # 立直棒 +1,000 点 (損評価 弱め)
    'RIICHI_W_DORA_TURN': 50.0,           # 巡目浅い + ドラ表示牌増加 期待
    'RIICHI_W_HAND_QUALITY': 80.0,        # 手役の確定度 (高いほど立直)
    'RIICHI_W_CLOSED_BONUS': 60.0,        # 門前ボーナス
    'RIICHI_W_HIGH_HAN': 100.0,           # 高翻数 (満貫以上) は立直積極
    'RIICHI_W_OPEN_PONTAI': -80.0,        # 副露後テンパイは立直不可
    # 状況
    'RIICHI_W_EARLY_TURN': -100.0,        # 序盤 (1-5 巡) は立直慎重
    'RIICHI_W_LATE_TURN': 80.0,           # 終盤 (14+ 巡) は立直積極
    'RIICHI_W_TOP_PLACE': -100.0,         # トップ目 = 流して逃げ切り
    'RIICHI_W_LAST_PLACE': 120.0,         # ラス目 = 攻め必要
    'RIICHI_W_OPP_REACH': -80.0,          # 他家リーチ = 慎重
    'RIICHI_W_ALL_EARLY': -50.0,          # 全家早 = ダマ有利
    'RIICHI_W_TENPAI_SELF': 30.0,         # 既にテンパイ情報あり = 立直
    'RIICHI_W_AGARI_LOW_HAN': 0.0,        # 役なし 0 翻 のみ score_riichi で 適用
}


def get_weights(params: dict) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    if params:
        for k in w:
            v = params.get(k)
            if v is not None:
                w[k] = float(v)
    return w


def estimate_han_count(state) -> int:
    """
    @title 翻数の概算 (簡略)
    @description 手役の確定度を ドラ枚数 + 役牌 + 赤ドラ などで 概算
    """
    from core.str_converter import hand_to_counts
    counts = hand_to_counts(state.my_hand)
    han = 0
    # ドラ (各ドラ表示牌ごとに手牌内の枚数)
    if state.doras:
        for d in state.doras:
            try:
                tid = tile_to_id(d)
                han += counts[tid]
            except Exception:
                continue
    # 赤ドラ (0m, 0p, 0s)
    han += sum(1 for t in state.my_hand if t in ('0m', '0p', '0s'))
    # 役牌 (三元牌、自風、場風) 暗刻
    SANGEN = {31, 32, 33}
    seat_wind = 27 + ((state.my_seat - state.ju) % 4)
    round_wind = 27 + (state.chang % 4)
    for t in set(state.my_hand):
        try:
            tid = tile_to_id(t)
        except Exception:
            continue
        if tid in SANGEN or tid in (seat_wind, round_wind):
            if counts[tid] >= 3:
                han += 1
    return han


def is_tenpai_closed(state) -> bool:
    """
    @title 門前でテンパイしているか
    @description 0 待ち (= テンパイ) で 副露なし なら True
    """
    from core.str_converter import hand_to_counts
    if sum(1 for m in state.my_melds if m.is_open) > 0:
        return False
    counts = hand_to_counts(state.my_hand)
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count == 0:
        sh = ShantenCalculatorV2.calculate_closed_effective(counts)
    else:
        sh = ShantenCalculatorV2.calculate_open(counts, open_meld_count)
    return sh <= 0


def already_reach(state) -> bool:
    """@title 既に立直しているか (自分 + 他家)"""
    for s in range(4):
        rs = state.reach_states[s] if s < len(state.reach_states) else None
        if rs is not None and rs.is_reach:
            return True
    return False


def score_riichi(state, params: dict) -> Tuple[float, str]:
    """
    @title 立直スコア計算
    @returns (score, reason)
    """
    w = get_weights(params)

    # 門前テンパイ のみ立直可能
    if not is_tenpai_closed(state):
        return -9999.0, "副露後 or 1 向聴以上 (立直不可)"
    # 既に立直済み
    if already_reach(state):
        return -9999.0, "既にリーチ宣言済み"

    score = w['RIICHI_W_BASE_SCORE']
    reasons = []

    # 加点
    han = estimate_han_count(state)
    if han >= 1:
        score += w['RIICHI_W_HAND_QUALITY'] * 0.5
        reasons.append(f"手役確定 (推定 {han} 翻)")
    if han >= 4:
        # 満貫以上 = 立直積極
        score += w['RIICHI_W_HIGH_HAN']
        reasons.append(f"高打点 (満貫+)")
    if han < 2 and han == 0:
        # 役 なし 0 翻 → 立直慎重
        score += w['RIICHI_W_AGARI_LOW_HAN']
        reasons.append(f"役なし 0 翻")
    elif han == 1:
        # 1 翻 確定 (ドラ 等) → やや 積極
        score -= 30  # 微減点
        reasons.append(f"1 翻 確定")

    # 門前ボーナス
    score += w['RIICHI_W_CLOSED_BONUS']

    # 状況
    turn = (state.tsumo_count - 1) // 4 + 1
    if turn <= 5:
        score += w['RIICHI_W_EARLY_TURN']
        reasons.append(f"序盤 {turn} 巡")
    elif turn >= 14:
        score += w['RIICHI_W_LATE_TURN']
        reasons.append(f"終盤 {turn} 巡")

    # 順位
    if hasattr(state, 'scores') and state.scores:
        my_score = state.scores[state.my_seat]
        sorted_scores = sorted(state.scores, reverse=True)
        my_rank = sorted_scores.index(my_score)
        if my_rank == 0:
            score += w['RIICHI_W_TOP_PLACE']
            reasons.append("トップ目")
        elif my_rank == 3:
            score += w['RIICHI_W_LAST_PLACE']
            reasons.append("ラス目")

    # 他家リーチ
    opp_reach_count = sum(1 for s in range(4)
                            if s != state.my_seat
                            and state.reach_states[s] is not None
                            and state.reach_states[s].is_reach)
    if opp_reach_count >= 1:
        score += w['RIICHI_W_OPP_REACH']
        reasons.append(f"他家リーチ {opp_reach_count} 人")

    # 全家早 (全員テンパイ)
    # 簡略: skip

    reason = ", ".join(reasons) if reasons else "加点なし"
    return score, f"score={score:.0f} ({reason})"


def should_riichi(state, params: dict = None) -> bool:
    """
    @title 立直すべきか (ver.2 加減算モデル)
    """
    if params is None:
        params = {}
    score, _ = score_riichi(state, params)
    threshold = get_weights(params).get('RIICHI_THRESHOLD', 0.0)
    return score > threshold


def should_kan(state, call_type: int, tiles: List[str], from_seat: int, params: dict = None) -> bool:
    """
    @title カンすべきか (ver.2 加減算モデル)
    @description 暗槓 / 大明槓 / 加槓 を 統合判定
    """
    # 簡易: 鳴き判断 (meld_v2) に委譲
    from core.meld_v2 import should_call_meld
    if params is None:
        params = {}
    decision, _reason = should_call_meld(state, call_type, tiles, from_seat, params)
    return bool(decision)
