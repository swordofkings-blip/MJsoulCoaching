# -*- coding: utf-8 -*-
"""
@title ver.2 1 シャンテン期待値 DFS
@description ver.1 の _run_1shanten_dfs を移植。
              切った後の 1 シャンテン手牌から、テンパイ時に
              「良形待ち + 高打点」になる確率を期待値で返す。

@returns float (高いほど良い)
"""
from __future__ import annotations
from typing import List

from core.shanten_v2 import ShantenCalculatorV2
from str_converter import tile_to_id, id_to_tile, is_honor


def run_1shanten_dfs(state, discard_tile: str) -> float:
    """
    @title 1 シャンテン時の DFS 期待値
    @description discard_tile を切った後の手牌について、
                テンパイ (shanten=0) する全ての牌を引いた場合の
                期待値 (良形待ち確率 × 飜数) を返す。

                ver.1 と同じ実装方針:
                - 良形待ちなら 1.5 倍 (両面・三面張)
                - 愚形待ちなら 1.0 倍 (カンチャン・ペンチャン)
                - 0 飜なら和了不可なのでスキップ
                - 各牌の残り枚数を山から計算

    @returns float (0.0 〜 100+)
    """
    hand_counts = list(state.my_hand_counts())
    discard_id = tile_to_id(discard_tile)
    if 0 <= discard_id < 34:
        hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    is_closed = (open_meld_count == 0)
    visible = state.all_visible_counts()

    if is_closed:
        shanten_after = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
    else:
        shanten_after = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

    if shanten_after > 1:
        return 0.0  # 1 シャンテン未満のときは DFS しない

    from hand_value import estimate_han_advanced
    seat_idx = (state.my_seat - state.ju) % 4

    if shanten_after == 0:
        # 既にテンパイ
        return _dfs_tenpai_ev(state, hand_counts, is_closed, open_meld_count, visible, seat_idx)
    else:
        # 1 シャンテン維持
        return _dfs_1shanten_ev(state, hand_counts, is_closed, open_meld_count, visible, seat_idx)


def _dfs_tenpai_ev(state, hand_counts, is_closed, open_meld_count, visible, seat_idx) -> float:
    """@title テンパイ時の DFS 期待値"""
    from hand_value import estimate_han_advanced
    total_ev = 0.0
    for tile_id in range(34):
        if hand_counts[tile_id] >= 4:
            continue
        test = list(hand_counts)
        test[tile_id] += 1
        if is_closed:
            ns = ShantenCalculatorV2.calculate_closed_effective(test)
        else:
            ns = ShantenCalculatorV2.calculate_open(test, open_meld_count)
        if ns < 0:
            remaining = 4 - visible[tile_id]
            if remaining <= 0:
                continue
            temp_hand = []
            for i in range(34):
                temp_hand.extend([id_to_tile(i)] * test[i])
            han = estimate_han_advanced(
                temp_hand, state.my_melds, state.doras,
                is_open=not is_closed, has_reach=is_closed, is_ippatsu=False,
                is_tsumo=True, seat=seat_idx, chang=state.chang, ju=state.ju
            )
            if not is_closed and han == 0:
                continue
            is_ryanmen = _is_ryanmen_wait(state, hand_counts, tile_id)
            mult = 1.5 if is_ryanmen else 1.0
            total_ev += remaining * max(1, han) * mult
    return total_ev


def _dfs_1shanten_ev(state, hand_counts, is_closed, open_meld_count, visible, seat_idx) -> float:
    """@title 1 シャンテン時の DFS 期待値"""
    from hand_value import estimate_han_advanced
    total_ev = 0.0
    for draw_id in range(34):
        if hand_counts[draw_id] >= 4:
            continue
        test = list(hand_counts)
        test[draw_id] += 1
        if is_closed:
            ns = ShantenCalculatorV2.calculate_closed_effective(test)
        else:
            ns = ShantenCalculatorV2.calculate_open(test, open_meld_count)
        if ns == 0:
            # テンパイになるツモ
            remaining = 4 - visible[draw_id]
            if remaining <= 0:
                continue
            best_temp_ev = 0.0
            for disc_id2 in range(34):
                if test[disc_id2] <= 0:
                    continue
                counts_tenpai = list(test)
                counts_tenpai[disc_id2] -= 1
                temp_ev = 0.0
                for wait_id in range(34):
                    if counts_tenpai[wait_id] >= 4:
                        continue
                    counts_agari = list(counts_tenpai)
                    counts_agari[wait_id] += 1
                    if is_closed:
                        ns2 = ShantenCalculatorV2.calculate_closed_effective(counts_agari)
                    else:
                        ns2 = ShantenCalculatorV2.calculate_open(counts_agari, open_meld_count)
                    if ns2 < 0:
                        rem_wait = 4 - visible[wait_id]
                        if rem_wait <= 0:
                            continue
                        hand_agari = []
                        for i in range(34):
                            hand_agari.extend([id_to_tile(i)] * counts_agari[i])
                        han = estimate_han_advanced(
                            hand_agari, state.my_melds, state.doras,
                            is_open=not is_closed, has_reach=is_closed, is_ippatsu=False,
                            is_tsumo=True, seat=seat_idx, chang=state.chang, ju=state.ju
                        )
                        if not is_closed and han == 0:
                            continue
                        is_ryanmen = _is_ryanmen_wait(state, counts_tenpai, wait_id)
                        mult = 1.5 if is_ryanmen else 1.0
                        temp_ev += rem_wait * max(1, han) * mult
                if temp_ev > best_temp_ev:
                    best_temp_ev = temp_ev
            total_ev += remaining * best_temp_ev * 0.02
    return total_ev


def _is_ryanmen_wait(state, hand_counts, wait_id: int) -> bool:
    """@title 両面待ちかどうか"""
    if is_honor(wait_id):
        return False
    base = (wait_id // 9) * 9
    off = wait_id - base
    if off == 0 or off == 8:
        return False
    has_l = off > 0 and hand_counts[base + off - 1] >= 1
    has_r = off < 8 and hand_counts[base + off + 1] >= 1
    return has_l and has_r
