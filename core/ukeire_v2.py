# -*- coding: utf-8 -*-
"""
@title ver.2 受け入れ計算
@description 打牌後の受け入れ枚数を「良形」「愚形」に分解する。
              - 良形: 両面・三面張になる受け入れ
              - 愚形: カンチャン・ペンチャン・単騎・双碰になる受け入れ
@returns (good_ukeire, bad_ukeire) のタプル
"""
from __future__ import annotations
from typing import Tuple

from core.shanten_v2 import ShantenCalculatorV2
from str_converter import tile_to_id, is_honor


def count_good_bad_ukeire(state, tile: str) -> Tuple[int, int]:
    """
    @title 良形/愚形に分解した受け入れカウント
    @description tile を切った後の手牌の受け入れ枚数を、
                良形 (両面・三面張) と愚形 (カンチャン・ペンチャン・単騎・双碰) に分けて返す。

    @returns (good_count, bad_count) のタプル
             good_count: 良形受入の山残り枚数
             bad_count: 愚形受入の山残り枚数
    """
    hand_counts = list(state.my_hand_counts())
    discard_id = tile_to_id(tile)

    if 0 <= discard_id < 34:
        hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count == 0:
        current_shanten = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
    else:
        current_shanten = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

    visible = state.all_visible_counts()
    good = 0
    bad = 0

    for tid in range(34):
        if hand_counts[tid] >= 4:
            continue
        test = list(hand_counts)
        test[tid] += 1
        if open_meld_count == 0:
            next_shanten = ShantenCalculatorV2.calculate_closed_effective(test)
        else:
            next_shanten = ShantenCalculatorV2.calculate_open(test, open_meld_count)

        if next_shanten >= current_shanten:
            continue  # シャンテン数が進まないので受け入れではない

        remaining = 4 - visible[tid]
        if remaining <= 0:
            continue

        if _is_good_wait(state, hand_counts, tid):
            good += remaining
        else:
            bad += remaining

    return (good, bad)


def count_ukeire_by_tenpai(state, tile: str) -> Tuple[int, int]:
    """
    @title テンパイ時の待ち種類を良形/愚形に分類
    @description tile を切った後にテンパイ (shanten=0) する場合、
                待ち牌の種類を「良形」「愚形」に分類する。
                テンパイじゃない場合は (0, 0) を返す。

    @returns (good, bad)
    """
    hand_counts = list(state.my_hand_counts())
    discard_id = tile_to_id(tile)
    if 0 <= discard_id < 34:
        hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count == 0:
        shanten_after = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
    else:
        shanten_after = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

    if shanten_after != 0:
        return (0, 0)

    visible = state.all_visible_counts()
    good = 0
    bad = 0
    for tid in range(34):
        if hand_counts[tid] >= 4:
            continue
        test = list(hand_counts)
        test[tid] += 1
        if open_meld_count == 0:
            next_shanten = ShantenCalculatorV2.calculate_closed_effective(test)
        else:
            next_shanten = ShantenCalculatorV2.calculate_open(test, open_meld_count)
        if next_shanten >= 0:
            continue
        remaining = 4 - visible[tid]
        if remaining <= 0:
            continue
        if _is_good_tenpai_wait(state, hand_counts, tid):
            good += remaining
        else:
            bad += remaining

    return (good, bad)


def _is_good_wait(state, hand_counts, tile_id: int) -> bool:
    """
    @title 受け入れ牌が「良形」を生むか
    @description 1 シャンテン以下で、テンパイ後に両面/三面張/双碰待ちになる牌かどうか
    """
    if is_honor(tile_id):
        return False  # 字牌は単騎/双碰のみ (愚形扱い)

    base = (tile_id // 9) * 9
    off = tile_id - base

    if off == 0 or off == 8:
        return False  # 端牌 → 単騎扱い

    # 両面: 隣接 1 つ先の牌が手牌にある
    has_l = off > 0 and hand_counts[base + off - 1] >= 1
    has_r = off < 8 and hand_counts[base + off + 1] >= 1
    if has_l and has_r:
        return True  # 両面 (の両端に手牌がある)

    # カンチャン: 両隣 (off±1) のどちらかが手牌にある
    if (off >= 1 and hand_counts[base + off - 1] >= 1) or \
       (off <= 7 and hand_counts[base + off + 1] >= 1):
        return False  # カンチャン (愚形)

    return False


def _is_good_tenpai_wait(state, hand_counts, wait_tile_id: int) -> bool:
    """
    @title テンパイ後の待ちが「良形」かどうか
    @description 両面待ちなら True
                双碰待ちも True (面前なら良形扱い)
                カンチャン・ペンチャン・単騎なら False
    """
    if is_honor(wait_tile_id):
        return False  # 字牌は単騎/双碰のみ (愚形扱い)

    base = (wait_tile_id // 9) * 9
    off = wait_tile_id - base

    if off == 0 or off == 8:
        return False  # 端牌 → ペンチャン・単騎

    # 両面: 隣接両側に手牌がある
    if off > 0 and off < 8:
        has_l = hand_counts[base + off - 1] >= 1
        has_r = hand_counts[base + off + 1] >= 1
        if has_l and has_r:
            return True
        # カンチャン待ち (片側のみ): 愚形
        if has_l or has_r:
            return False

    return False
