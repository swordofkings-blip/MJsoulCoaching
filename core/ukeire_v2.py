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

    修正: 従来は「ツモる牌の両隣が手牌にあるか」という誤った基準だった。
    正しくは「tile_id を一枚加えた後、テンパイしてどの牌で待つか」を判定する。

    判定方法: tile_id を加えた後の手牌で各牌を 1 枚ずつ加えてアガリ形になるものを探す。
              その待ちの形が良形 (両面・三面張・双碰) なら True。
    """
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    is_closed = (open_meld_count == 0)

    if is_honor(tile_id):
        # 字牌: 単騎 or 双碰しか作れない (愚形扱い)
        # ただし双碰は面前なら良形扱い
        if not is_closed:
            return False
        # 双碰: 同じ字牌が手牌に 2 枚ある → 双碰待ちができる
        my_count = hand_counts[tile_id]
        return my_count == 2  # 1 枚持ちなら単騎 (愚形), 2 枚なら双碰 (良形)

    # 数牌: tile_id を加えた後のテンパイで、待ちの形を判定
    test = list(hand_counts)
    test[tile_id] = min(4, test[tile_id] + 1)
    base = (tile_id // 9) * 9
    off = tile_id - base

    # 周辺牌が 1 つでも手牌にあるか
    if off == 0 or off == 8:
        return False  # 端牌 → 単騎 or ペンチャン

    has_l = off > 0 and test[base + off - 1] >= 1
    has_r = off < 8 and test[base + off + 1] >= 1

    if has_l and has_r:
        return True  # 両面 (両端が手牌にある)
    if has_l or has_r:
        return False  # カンチャン or ペンチャン (愚形)
    return False  # 単騎扱い (待ちがない)


def _is_good_tenpai_wait(state, hand_counts, wait_tile_id: int) -> bool:
    """
    @title テンパイ後の待ちが「良形」かどうか
    @description 両面待ちなら True
                双碰待ちも True (面前なら良形扱い)
                カンチャン・ペンチャン・単騎なら False
    """
    if is_honor(wait_tile_id):
        # 双碰: 同じ字牌が手牌に 2 枚あるなら双碰待ち (面前のみ良形)
        my_count = hand_counts[wait_tile_id]
        open_meld_count = sum(1 for m in state.my_melds if m.is_open)
        if open_meld_count == 0 and my_count == 2:
            return True
        return False  # 単騎

    base = (wait_tile_id // 9) * 9
    off = wait_tile_id - base

    if off == 0 or off == 8:
        return False  # 端牌 → ペンチャン・単騎

    if off > 0 and off < 8:
        has_l = hand_counts[base + off - 1] >= 1
        has_r = hand_counts[base + off + 1] >= 1
        if has_l and has_r:
            return True
        if has_l or has_r:
            return False

    return False
