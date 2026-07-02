# -*- coding: utf-8 -*-
"""
@title 対戦相手モデル
@description 他家の仕掛け・リーチ・打牌傾向から手牌強度・危険度を推定するベイズ的モデル。
"""
from __future__ import annotations
from typing import List, Tuple, Optional

from game_state import GameState, Meld
from str_converter import tile_to_id, hand_to_counts, is_honor, is_terminal
from strategy_manager import ShantenCalculator

SANGEN = {31, 32, 33}


def estimate_opponent_state(state: GameState, opponent_seat: int) -> dict:
    melds = state.melds[opponent_seat]
    river = state.river[opponent_seat]
    open_meld_count = sum(1 for m in melds if m.is_open)
    is_reach = state.reach_states[opponent_seat].is_reach

    discards = {}
    for t in river:
        tid = tile_to_id(t)
        discards[tid] = discards.get(tid, 0) + 1

    meld_tiles = []
    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        meld_tiles.extend(tile_to_id(t) for t in mt)

    safe_suits = set()
    dangerous_suits = set()
    for tid in list(discards.keys()) + meld_tiles:
        if tid < 27:
            suit_idx = tid // 9
            cnt_in_river = discards.get(tid, 0)
            cnt_in_melds = sum(1 for mt in meld_tiles if mt == tid)
            if cnt_in_river + cnt_in_melds >= 3:
                safe_suits.add(suit_idx * 9 + (tid % 9))
            if cnt_in_river >= 2:
                dangerous_suits.add(suit_idx)

    yakuhai_count = 0
    dora_count = 0
    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        if mt and hasattr(m, 'is_open') and m.is_open:
            tid = tile_to_id(mt[0])
            if tid in SANGEN:
                yakuhai_count += 1

    est_han = 1
    est_han += yakuhai_count
    if is_reach:
        est_han += 1
    if open_meld_count >= 3:
        est_han += 1

    is_tenpai = is_reach or open_meld_count >= 3
    if not is_tenpai and open_meld_count == 2 and len(river) >= 8:
        is_tenpai = True

    is_riichi = is_reach

    return {
        'seat': opponent_seat,
        'is_riichi': is_riichi,
        'is_tenpai': is_tenpai,
        'open_meld_count': open_meld_count,
        'estimated_han': min(est_han, 5),
        'discards': discards,
        'melt_tiles': meld_tiles,
        'yakuhai_count': yakuhai_count,
    }


def get_opponent_threat_details(state: GameState) -> List[dict]:
    results = []
    for seat in range(4):
        if seat == state.my_seat:
            continue
        results.append(estimate_opponent_state(state, seat))
    return results


def is_suji_against(opponent_state: dict, tile_id: int, state: GameState) -> bool:
    if is_honor(tile_id):
        return False
    base = (tile_id // 9) * 9
    off = tile_id - base
    for delta in (-3, 3):
        t = off + delta
        if 0 <= t <= 8:
            tid = base + t
            if tid in opponent_state['discards']:
                return True
    return False


def opponent_tile_danger(tile_id: int, opponent_state: dict, state: GameState) -> float:
    if tile_id in opponent_state.get('discards', {}):
        return 0.0
    if is_suji_against(opponent_state, tile_id, state):
        return 0.3
    if opponent_state['is_riichi']:
        return 1.0
    if opponent_state['is_tenpai']:
        return 0.6
    return 0.1
