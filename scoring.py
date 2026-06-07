# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple, Optional

from str_converter import (
    HONOR_IDS, TERMINAL_IDS,
    hand_to_counts, is_honor, is_terminal, is_red_five, tile_to_id, id_to_tile,
)

SCORE_TABLE = [
    (0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0),
    (0, 0, 0, 0, 0, 0),
]

def calculate_fu(hand: List[str], melds: List, win_tile: str, is_tsumo: bool,
                 is_open: bool, is_dealer: bool, wait_type: str = 'ryanmen') -> int:
    counts = hand_to_counts(hand)
    win_id = tile_to_id(win_tile)

    base = 20
    if not is_open:
        if wait_type == 'ron':
            base = 30 if not is_tsumo else 20
        else:
            base = 20

    fu = base
    if is_tsumo:
        fu += 2

    if 'ron' in wait_type and not is_open:
        pass

    has_fu_extra = False
    for i in range(34):
        if counts[i] >= 3:
            c = counts[i]
            is_yaochu = is_terminal(i) or is_honor(i)
            if c == 3:
                fu += 8 if is_yaochu else 4
            elif c == 4:
                fu += 16 if is_yaochu else 8
            has_fu_extra = True

    for m in melds:
        if hasattr(m, 'type'):
            tiles = m.tiles if hasattr(m, 'tiles') else []
            if len(tiles) >= 3:
                t_id = tile_to_id(tiles[0])
                is_yaochu = is_terminal(t_id) or is_honor(t_id)
                if m.type == 3:
                    fu += 32 if is_yaochu else 16
                elif m.type == 2:
                    fu += 16 if is_yaochu else 8
                elif len(tiles) == 4 and m.type == 1:
                    fu += 8 if is_yaochu else 4

    for i in range(27, 34):
        if counts[i] >= 2:
            if i in (27, 28, 29, 30):
                fu += 2
            break

    if wait_type in ('kanchan', 'penchan', 'tanki'):
        fu += 2

    if not is_open:
        if fu == 20 and wait_type == 'ryanmen' and not has_fu_extra and not is_tsumo:
            fu = 30

    return ((fu + 9) // 10) * 10


def estimate_han(hand: List[str], melds: List, doras: List[str],
                 is_open: bool, is_tsumo: bool, has_reach: bool,
                 is_ippatsu: bool) -> int:
    han = 0
    counts = hand_to_counts(hand)

    if has_reach:
        han += 1
    if is_ippatsu:
        han += 1
    if is_tsumo and not is_open:
        han += 1

    yakuhai_wind = {27: 'ton', 28: 'nan', 29: 'shaa', 30: 'pei'}
    for i in range(27, 34):
        c = counts[i]
        m_count = sum(1 for m in melds if m.is_open and hasattr(m, 'tiles') and len(m.tiles) >= 3 and tile_to_id(m.tiles[0]) == i)
        total = (c // 3) + m_count
        if total >= 1:
            if i in (31, 32, 33):
                han += total
            elif i == 27:
                han += total

    if not is_open:
        all_terminals = all(
            is_terminal(tile_to_id(t)) or is_honor(tile_to_id(t))
            for t in hand
        )
        if all_terminals:
            pass

    has_honor = any(is_honor(tile_to_id(t)) for t in hand)
    has_terminal = any(is_terminal(tile_to_id(t)) for t in hand)
    if not is_open and not has_honor and not has_terminal:
        if len(hand) % 3 == 2:
            han += 1

    for t in hand:
        tid = tile_to_id(t)
        for d in doras:
            if tid == tile_to_id(d):
                han += 1
        if is_red_five(t):
            han += 1

    return han


def calculate_score(han: int, fu: int, is_dealer: bool, is_tsumo: bool,
                    honba: int = 0, riichi_sticks: int = 0) -> dict:
    if han >= 5:
        if han >= 13:
            base = 8000
        elif han >= 11:
            base = 6000
        elif han >= 8:
            base = 4000
        elif han >= 6:
            base = 3000
        else:
            base = 2000
    else:
        base = fu * (2 ** (2 + han))
        base = ((base + 99) // 100) * 100

    if is_dealer:
        if is_tsumo:
            each = ((base * 2 + 99) // 100) * 100
            return {
                'total': each * 3 + honba * 300 + riichi_sticks * 1000,
                'from_each_non_dealer': each,
                'honba': honba * 300,
                'riichi_sticks': riichi_sticks * 1000,
            }
        else:
            pay = ((base * 6 + 99) // 100) * 100
            return {
                'total': pay + honba * 300 + riichi_sticks * 1000,
                'from_discarder': pay,
                'honba': honba * 300,
                'riichi_sticks': riichi_sticks * 1000,
            }
    else:
        if is_tsumo:
            dealer = ((base * 2 + 99) // 100) * 100
            non_dealer = ((base + 99) // 100) * 100
            return {
                'total': dealer + non_dealer * 2 + honba * 300 + riichi_sticks * 1000,
                'from_dealer': dealer,
                'from_each_non_dealer': non_dealer,
                'honba': honba * 300,
                'riichi_sticks': riichi_sticks * 1000,
            }
        else:
            pay = ((base * 4 + 99) // 100) * 100
            return {
                'total': pay + honba * 300 + riichi_sticks * 1000,
                'from_discarder': pay,
                'honba': honba * 300,
                'riichi_sticks': riichi_sticks * 1000,
            }


def calculate_tenpai_payments(tenpai_seats: List[int]) -> List[int]:
    n_tenpai = len(tenpai_seats)
    n_noten = 4 - n_tenpai
    if n_noten == 0:
        return [0, 0, 0, 0]

    total = 3000
    payments = [0, 0, 0, 0]
    for s in range(4):
        if s in tenpai_seats:
            payments[s] = total // n_tenpai
        else:
            payments[s] = -(total // n_noten)
    return payments
