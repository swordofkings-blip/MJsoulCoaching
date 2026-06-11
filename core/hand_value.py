# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple

from str_converter import hand_to_counts, is_honor, is_terminal, is_red_five, tile_to_id, id_to_tile

SANGEN = {31, 32, 33}


def _all_ids(hand: List[str], melds: List) -> List[int]:
    ids = [tile_to_id(t) for t in hand]
    for m in melds:
        mt = getattr(m, 'tiles', [])
        ids.extend(tile_to_id(t) for t in mt)
    return ids


def _suit_dist(ids: List[int]) -> Tuple[set, bool]:
    suits = set()
    has_hon = False
    for tid in ids:
        if tid < 9:
            suits.add('m')
        elif tid < 18:
            suits.add('p')
        elif tid < 27:
            suits.add('s')
        else:
            has_hon = True
    return suits, has_hon


def estimate_han_advanced(hand: List[str], melds: List, doras: List[str],
                          is_open: bool, has_reach: bool, is_ippatsu: bool,
                          is_tsumo: bool, seat: int = 0, chang: int = 0, ju: int = 0) -> int:
    han = 0
    counts = hand_to_counts(hand)
    all_ids = _all_ids(hand, melds)
    suits, has_hon = _suit_dist(all_ids)

    if has_reach:
        han += 1
    if is_ippatsu:
        han += 1
    if is_tsumo and not is_open:
        han += 1

    han += sum(1 for tid in all_ids if is_red_five(id_to_tile(tid)))

    from str_converter import dora_indicator_to_dora
    actual_doras = [dora_indicator_to_dora(d) for d in doras]
    for d in actual_doras:
        did = tile_to_id(d)
        han += sum(1 for tid in all_ids if tid == did)

    has_term = any(is_terminal(tid) for tid in all_ids)
    has_honor = any(is_honor(tid) for tid in all_ids)
    all_2to8 = not has_term and not has_honor

    if all_2to8:
        han += 1

    n_suits = len(suits)
    if n_suits == 1 and not has_hon:
        han += 6 if not is_open else 5
    elif n_suits == 1 and has_hon:
        han += 3 if not is_open else 2
    elif n_suits == 2 and has_hon and not is_open:
        honitsu_check = any(tid >= 27 for tid in all_ids)
        one_suit = len({tid // 9 for tid in all_ids if tid < 27}) == 1
        if honitsu_check and one_suit:
            han += 3 if not is_open else 2

    yakuhai_ids = {31, 32, 33}
    sw = {0: 27, 1: 28, 2: 29, 3: 30}.get(seat)
    rw = {0: 27, 1: 28, 2: 29, 3: 30}.get(chang % 4)
    if sw is not None:
        yakuhai_ids.add(sw)
    if rw is not None:
        yakuhai_ids.add(rw)
    for yid in yakuhai_ids:
        mc = 0
        for m in melds:
            mt = getattr(m, 'tiles', [])
            if mt and tile_to_id(mt[0]) == yid and getattr(m, 'is_open', True):
                mc += 1
        if counts[yid] >= 3 or mc >= 1:
            if han < 13:
                han += 1

    open_meld_count = sum(1 for m in melds if getattr(m, 'is_open', True))
    if not is_open:
        pairs = sum(1 for c in counts if c >= 2)
        if pairs >= 6:
            han += 2

    # yaku_detector補完（二重計上防止のため既存計上役を除外）
    _already_counted = {'yakuhai', 'honitsu', 'chinitsu', 'tanyao', 'chiitoitsu', 'dora'}
    try:
        from yaku_detector import analyze_all
        yi = analyze_all(hand, melds, seat=seat, chang=chang, ju=ju)
        partial_total = 0
        for name, y in yi.items():
            if name in _already_counted:
                continue
            if y.is_complete:
                add = y.open_han if is_open else y.closed_han
                if han < 13 and add > 0:
                    han += add
            elif y.progress > 0.4 and han < 13 and partial_total < 3:
                add = max(1, int((y.open_han if is_open else y.closed_han) * y.progress))
                if add > 0:
                    partial_total += min(add, 3 - partial_total)
                    han += min(add, 3 - partial_total)
    except Exception:
        pass

    return han


def estimate_win_score(han: int, fu: int, is_dealer: bool) -> int:
    if han >= 5:
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
    table = {(20,1):1000,(20,1):1000,(25,1):1600,(30,1):1000,(40,1):1300,(50,1):1600,
             (20,2):2000,(25,2):3200,(30,2):2000,(40,2):2600,(50,2):3200,
             (20,3):3900,(25,3):6400,(30,3):3900,(40,3):5200,(50,3):6400,
             (25,4):12000,(30,4):7700,(40,4):10400}
    key = (fu, han)
    if key in table:
        base = table[key]
        if is_dealer:
            base = int(base * 1.5)
        return base
    base = fu * 4 * (2 ** (han + 2))
    base = ((base + 99) // 100) * 100
    if is_dealer:
        base = int(base * 1.5)
    return base


def estimate_hand_value(hand: List[str], melds: List, doras: List[str],
                        is_open: bool, has_reach: bool, is_ippatsu: bool,
                        is_tsumo: bool, is_dealer: bool,
                        seat: int = 0, chang: int = 0, ju: int = 0) -> int:
    han = estimate_han_advanced(hand, melds, doras, is_open, has_reach, is_ippatsu, is_tsumo,
                                seat=seat, chang=chang, ju=ju)
    return estimate_win_score(han, 30, is_dealer)
