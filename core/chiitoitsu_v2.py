# -*- coding: utf-8 -*-
"""
@title ver.2 七対子モード
@description 4 対子 + 両面少 / 5 シャンテン以下で七対子有利 / 中盤 5-6 巡以降の条件
              を満たすとき七対子モードに切替。
              特殊タプルで評価。
"""
from __future__ import annotations
from typing import Tuple

from core.shanten_v2 import ShantenCalculatorV2
from str_converter import tile_to_id, is_honor


def chiitoitsu_mode_applicable(state, current_turn: int) -> bool:
    """
    @title 七対子モード発動条件
    @description 2 条件並列 (OR) で発動:
                1. 対子 4 個以上 + 両面ターツ 2 個以下 + 巡目 4-7
                2. 面子手 5 シャンテン以下で七対子側がシャンテン数的に有利
                3. 中盤 (5-6 巡) 以降で 4 対子 + リャンメンターツ少
    """
    hand_counts = state.my_hand_counts()
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count > 0:
        return False  # 副露済なら七対子不可

    pairs = sum(1 for c in hand_counts if c >= 2)
    ryanmen_count = _count_ryanmen_taatsu(hand_counts)
    chiitoi_shanten = ShantenCalculatorV2._chiitoitsu_shanten(hand_counts)
    std_shanten = ShantenCalculatorV2.calculate_closed_effective(hand_counts)

    # 条件 1: 4 対子以上 + 両面少 + 巡目 4-7 (デフォルト)
    if pairs >= 4 and ryanmen_count <= 2 and 4 <= current_turn <= 7:
        return True

    # 条件 2: 面子手 5 シャンテン vs 七対子側有利
    if std_shanten >= 5 and chiitoi_shanten < std_shanten:
        return True

    # 条件 3: 中盤以降 + 4 対子 + リャンメン少
    if current_turn >= 5 and pairs >= 4 and ryanmen_count <= 1:
        return True

    return False


def chiitoitsu_tuple(state, tile: str) -> Tuple:
    """
    @title 七対子モードのタプル
    @returns (shanten, -ukeire, -pair_quality, tactical_rank, dora_loss)
    """
    hand_counts = list(state.my_hand_counts())
    discard_id = tile_to_id(tile)
    if 0 <= discard_id < 34:
        hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

    chiitoi_shanten = ShantenCalculatorV2._chiitoitsu_shanten(hand_counts)
    # 受け入れ: 対子候補の種類数 (字牌対子は質が高い)
    visible = state.all_visible_counts()
    my_counts = state.my_hand_counts()
    good_ukeire = 0
    bad_ukeire = 0
    for tid in range(34):
        if hand_counts[tid] >= 4:
            continue
        test = list(hand_counts)
        test[tid] += 1
        ns = ShantenCalculatorV2._chiitoitsu_shanten(test)
        if ns < chiitoi_shanten:
            remaining = 4 - visible[tid]
            if remaining > 0:
                if _is_high_quality_pair(state, tid):
                    good_ukeire += remaining
                else:
                    bad_ukeire += remaining
    ukeire = good_ukeire + bad_ukeire  # 合計
    pair_quality = _tile_pair_quality(state, discard_id)
    dora_loss = _dora_loss(state, discard_id)
    from core.tactical_rank_v2 import tactical_discard_rank
    rank = tactical_discard_rank(state, tile)
    return (chiitoi_shanten, -ukeire, -pair_quality, rank, dora_loss)


def _count_ryanmen_taatsu(hand_counts) -> int:
    """@title 両面ターツ数 (数牌で隣接ペアがある組)"""
    count = 0
    for base in (0, 9, 18):
        for i in range(8):
            if hand_counts[base + i] >= 1 and hand_counts[base + i + 1] >= 1:
                count += 1
    return count


def _is_high_quality_pair(state, tid: int) -> bool:
    """@title 役牌・ドラ・三元牌 かどうか"""
    if 27 <= tid <= 33:
        return True  # 字牌
    for d in state.doras:
        try:
            if tile_to_id(d) == tid:
                return True
        except Exception:
            pass
    return False


def _tile_pair_quality(state, tid: int) -> int:
    """@title 牌の対子としての質 (高いほど残したい)"""
    quality = 0
    if is_honor(tid):
        quality += 3
    for d in state.doras:
        try:
            if tile_to_id(d) == tid:
                quality += 5
        except Exception:
            pass
    return quality


def _dora_loss(state, tid: int) -> int:
    """@title ドラ表示牌を捨てる際の損失"""
    loss = 0
    for d in state.doras:
        try:
            if tile_to_id(d) == tid:
                loss += 1
        except Exception:
            pass
    return loss
