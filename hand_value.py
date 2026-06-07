# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List

from str_converter import (
    HONOR_IDS, TERMINAL_IDS,
    hand_to_counts, is_honor, is_terminal, is_red_five, tile_to_id,
)

SANGEN = {31, 32, 33}


def estimate_han_advanced(hand: List[str], melds: List, doras: List[str],
                          is_open: bool, has_reach: bool, is_ippatsu: bool,
                          is_tsumo: bool) -> int:
    han = 0
    counts = hand_to_counts(hand)
    total_counts = list(counts)
    meld_tiles = []
    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        meld_tiles.extend(mt)
        for t in mt:
            tid = tile_to_id(t)
            total_counts[tid] += 3 if hasattr(m, 'type') and m.type == 3 else 0

    all_tiles = list(hand)
    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        all_tiles.extend(mt)

    if has_reach:
        han += 1
    if is_ippatsu:
        han += 1
    if is_tsumo and not is_open:
        han += 1

    has_aka = any(is_red_five(t) for t in all_tiles)
    if has_aka:
        aka_count = sum(1 for t in all_tiles if is_red_five(t))
        han += aka_count

    for d in doras:
        did = tile_to_id(d)
        in_hand = sum(1 for t in hand if tile_to_id(t) == did)
        in_melds = 0
        for m in melds:
            mt = m.tiles if hasattr(m, 'tiles') else []
            in_melds += sum(1 for t in mt if tile_to_id(t) == did)
        han += in_hand + in_melds

    has_term = any(is_terminal(tile_to_id(t)) for t in all_tiles)
    has_hon = any(is_honor(tile_to_id(t)) for t in all_tiles)

    if not is_open:
        if not has_term and not has_hon:
            han += 1

    suits_used = set()
    for t in all_tiles:
        tid = tile_to_id(t)
        if tid < 9:
            suits_used.add('m')
        elif tid < 18:
            suits_used.add('p')
        elif tid < 27:
            suits_used.add('s')
        else:
            suits_used.add('z')

    if not is_open:
        if len(suits_used) == 1 and 'z' not in suits_used:
            han += 6
        elif len(suits_used) == 2 and 'z' in suits_used and len(suits_used - {'z'}) == 1:
            han += 3
        elif len(suits_used) == 1 and 'z' in suits_used:
            han += 3

    for m in melds:
        mt = m.tiles if hasattr(m, 'tiles') else []
        if len(mt) >= 3 and hasattr(m, 'is_open') and not m.is_open:
            tid = tile_to_id(mt[0])
            if is_terminal(tid) or is_honor(tid):
                han += 8

    for i in SANGEN:
        c = counts[i]
        m_count = 0
        for m in melds:
            mt = m.tiles if hasattr(m, 'tiles') else []
            if mt and tile_to_id(mt[0]) == i and hasattr(m, 'is_open'):
                m_count += 1
        if c >= 3 or m_count >= 1:
            han += 1

    se_total = 0
    for suit in range(3):
        base = suit * 9
        seqs = 0
        for start in range(7):
            if (counts[base + start] >= 1 and counts[base + start + 1] >= 1
                    and counts[base + start + 2] >= 1):
                seqs += 1
        if seqs >= 3:
            se_total += 2

    if not is_open:
        all_koutsu = True
        for i in range(34):
            if counts[i] not in (0, 2, 3, 4):
                all_koutsu = False
                break
        pairs = sum(1 for c in counts if c >= 2)
        if all_koutsu and pairs == 7:
            han += 2

    return han


def estimate_win_score(han: int, is_dealer: bool) -> int:
    if han >= 13:
        base = 32000
    elif han >= 11:
        base = 24000
    elif han >= 8:
        base = 16000
    elif han >= 6:
        base = 12000
    elif han == 5:
        base = 8000
    elif han == 4:
        base = 2000
    elif han == 3:
        base = 1000
    elif han == 2:
        base = 500
    else:
        base = 300
    if is_dealer:
        base = int(base * 1.5)
    return base
