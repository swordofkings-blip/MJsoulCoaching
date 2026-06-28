# -*- coding: utf-8 -*-
"""
@title ver.2 戦略モード判定
@description Fuzzy 推論を完全廃止。カウントと if-else で純粋に判定。
              7 つのモード: URGENT_ATTACK, ATTACK, BALANCED, DEFEND, FOLD, CHIITOITSU, YAKUMAN, KOKUSHI
"""
from __future__ import annotations
from enum import Enum
from typing import Optional

from core.shanten_v2 import ShantenCalculatorV2
from core.chiitoitsu_v2 import chiitoitsu_mode_applicable
from core.yakuman_v2 import get_active_yakuman


class Mode(Enum):
    URGENT_ATTACK = "URGENT_ATTACK"  # 終盤 4 位
    ATTACK = "ATTACK"               # 攻撃モード
    BALANCED = "BALANCED"            # バランス
    DEFEND = "DEFEND"                # 防御
    FOLD = "FOLD"                    # オリ
    CHIITOITSU = "CHIITOITSU"        # 七対子
    YAKUMAN = "YAKUMAN"              # 役満 (国士以外)
    KOKUSHI = "KOKUSHI"              # 国士無双


def get_mode(state, current_turn: int, is_last_round: bool) -> Mode:
    """
    @title 戦略モード判定
    @description 優先順位:
                1. 国士無双進行中 → KOKUSHI
                2. 役満進行中 → YAKUMAN
                3. 終盤 4 位 → URGENT_ATTACK
                4. 七対子モード条件 → CHIITOITSU
                5. 2 リーチ + テンパイ未満 → FOLD
                6. 1 リーチ + テンパイ未満 → DEFEND
                7. テンパイ + 1 向聴 → ATTACK
                8. その他 → BALANCED
    """
    my_counts = state.my_hand_counts()
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count == 0:
        shanten = ShantenCalculatorV2.calculate_closed_effective(my_counts)
    else:
        shanten = ShantenCalculatorV2.calculate_open(my_counts, open_meld_count)

    rank = _my_score_rank(state)
    is_tenpai = shanten <= 0
    n_reach = sum(
        1 for s in range(4)
        if s != state.my_seat and state.reach_states[s].is_reach
    )

    # 1. 国士無双
    yakuman = get_active_yakuman(state)
    if yakuman == 'kokushi':
        return Mode.KOKUSHI

    # 2. 役満
    if yakuman is not None and yakuman != 'kokushi':
        return Mode.YAKUMAN

    # 3. 終盤 4 位
    if is_last_round and rank == 3:
        return Mode.URGENT_ATTACK

    # 4. 七対子
    if chiitoitsu_mode_applicable(state, current_turn):
        return Mode.CHIITOITSU

    # 5. 2 リーチ + テンパイ未満
    if n_reach >= 2 and not is_tenpai:
        return Mode.FOLD

    # 6. 1 リーチ + テンパイ未満
    if n_reach >= 1 and not is_tenpai:
        return Mode.DEFEND

    # 7. テンパイ or 1 向聴
    if shanten <= 1:
        return Mode.ATTACK

    # 8. その他
    return Mode.BALANCED


def _my_score_rank(state) -> int:
    """
    @title 自分の順位 (0=トップ, 3=ラス)
    """
    my_score = state.scores[state.my_seat]
    sorted_scores = sorted(state.scores, reverse=True)
    return sorted_scores.index(my_score)
