# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple

from str_converter import (
    HONOR_IDS, TERMINAL_IDS,
    hand_to_counts, is_honor, is_terminal, is_red_five, tile_to_id,
)

SANGEN = {31, 32, 33}

SUIT_COLORS = {'m': 0, 'p': 1, 's': 2}

_1_3_HAN_SCORE = {
    (20, 1, False): 1000, (20, 1, True): 1500,
    (20, 2, False): 2000, (20, 2, True): 3000,
    (20, 3, False): 3900, (20, 3, True): 5800,
    (25, 1, False): 1600, (25, 1, True): 2400,
    (25, 2, False): 3200, (25, 2, True): 4800,
    (25, 3, False): 6400, (25, 3, True): 9600,
    (30, 1, False): 1000, (30, 1, True): 1500,
    (30, 2, False): 2000, (30, 2, True): 2900,
    (30, 3, False): 3900, (30, 3, True): 5800,
    (40, 1, False): 1300, (40, 1, True): 2000,
    (40, 2, False): 2600, (40, 2, True): 3900,
    (40, 3, False): 5200, (40, 3, True): 7700,
    (50, 1, False): 1600, (50, 1, True): 2400,
    (50, 2, False): 3200, (50, 2, True): 4800,
    (50, 3, False): 6400, (50, 3, True): 9600,
    (60, 1, False): 2000, (60, 1, True): 2900,
    (60, 2, False): 3900, (60, 2, True): 5800,
    (60, 3, False): 7700, (60, 3, True): 11600,
    (70, 1, False): 2300, (70, 1, True): 3400,
    (70, 2, False): 4500, (70, 2, True): 6800,
    (70, 3, False): 9000, (70, 3, True): 13600,
}


def _all_tile_ids(hand: List[str], melds: List) -> List[int]:
    result = [tile_to_id(t) for t in hand]
    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        result.extend(tile_to_id(t) for t in mt)
    return result


def _has_only_2to8(tiles: List[int]) -> bool:
    for tid in tiles:
        if is_honor(tid):
            return False
        if tid % 9 in (0, 8):
            return False
    return True


def _suits_used(tiles: List[int]) -> Tuple[set, bool]:
    suits = set()
    has_hon = False
    for tid in tiles:
        if tid < 9:
            suits.add('m')
        elif tid < 18:
            suits.add('p')
        elif tid < 27:
            suits.add('s')
        else:
            has_hon = True
    return suits, has_hon


def estimate_fu(hand: List[str], melds: List, win_tile: str = None) -> int:
    counts = hand_to_counts(hand)
    fu = 20
    for i in range(34):
        if counts[i] >= 3:
            yaochu = is_terminal(i) or is_honor(i)
            fu += (8 if yaochu else 4)
    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        if len(mt) >= 3:
            tid = tile_to_id(mt[0])
            yaochu = is_terminal(tid) or is_honor(tid)
            if hasattr(m, 'type'):
                if m.type == 3:
                    fu += (32 if yaochu else 16)
                elif m.type == 2:
                    fu += (16 if yaochu else 8)
                elif hasattr(m, 'is_open') and not m.is_open:
                    fu += (8 if yaochu else 4)
    for i in range(27, 34):
        if counts[i] >= 2:
            if i in SANGEN or i <= 30:
                fu += 2
            break
    fu = min(fu, 110)
    return ((fu + 9) // 10) * 10


def estimate_han_advanced(hand: List[str], melds: List, doras: List[str],
                          is_open: bool, has_reach: bool, is_ippatsu: bool,
                          is_tsumo: bool) -> int:
    han = 0
    counts = hand_to_counts(hand)
    all_ids = _all_tile_ids(hand, melds)

    if has_reach:
        han += 1
    if is_ippatsu:
        han += 1
    if is_tsumo and not is_open:
        han += 1

    aka_count = sum(1 for tid in all_ids if is_red_five(id_to_tile(tid)))
    han += aka_count

    for d in doras:
        did = tile_to_id(d)
        han += sum(1 for tid in all_ids if tid == did)

    if not _has_only_2to8(all_ids):
        pass
    elif not is_open:
        han += 1

    suits, has_hon = _suits_used(all_ids)

    if not is_open:
        if len(suits) == 1 and not has_hon:
            han += 6
        elif len(suits) == 1 and has_hon:
            han += 3

    for i in SANGEN:
        c = counts[i]
        mc = 0
        for m in melds:
            mt = m.tiles if hasattr(m, 'tiles') else []
            if mt and tile_to_id(mt[0]) == i and (not hasattr(m, 'is_open') or m.is_open):
                mc += 1
        if c >= 3 or mc >= 1:
            han += 1

    if len(hand) >= 13 and not is_open:
        pairs = sum(1 for c in counts if c >= 2)
        if pairs >= 6:
            han += 2

    if not is_open and has_ryanmen_wait(hand):
        if han == 0 and not is_open:
            pass

    return han


def estimate_win_score(han: int, fu: int, is_dealer: bool) -> int:
    if han >= 5:
        return _mangan_score(han, is_dealer)

    key = (fu, han, is_dealer)
    if key in _1_3_HAN_SCORE:
        return _1_3_HAN_SCORE[key]

    base = fu * 4 * (2 ** (han + 2))
    base = ((base + 99) // 100) * 100
    if is_dealer:
        base = int(base * 1.5)
    return base


def _mangan_score(han: int, is_dealer: bool) -> int:
    if han >= 13:
        base = 32000
    elif han >= 11:
        base = 24000
    elif han >= 8:
        base = 16000
    elif han >= 6:
        base = 12000
    else:
        base = 8000
    if is_dealer:
        base = int(base * 1.5)
    return base


def estimate_hand_value(hand: List[str], melds: List, doras: List[str],
                        is_open: bool, has_reach: bool, is_ippatsu: bool,
                        is_tsumo: bool, is_dealer: bool) -> int:
    han = estimate_han_advanced(hand, melds, doras, is_open, has_reach, is_ippatsu, is_tsumo)
    fu = estimate_fu(hand, melds)
    return estimate_win_score(han, fu, is_dealer)


has_ryanmen_wait = lambda h: True


from str_converter import id_to_tile
