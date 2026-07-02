# -*- coding: utf-8 -*-
"""
@title 符計算・点数計算
@description 麻雀の符計算ロジックと翻数に基づく点数計算（子・親）を行う。
"""
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


YAKU_DISPLAY: dict = {
    'daburi': 'ダブル立直', 'tanyao': 'タンヤオ', 'yakuhai': '役牌',
    'pinfu': '平和', 'iipeikou': '一盃口', 'chiitoitsu': '七対子',
    'sanshoku': '三色同順', 'ittsuu': '一気通貫', 'honitsu': '混一色',
    'chinitsu': '清一色', 'toitoi': '対々和', 'sanshoku_doukou': '三色同刻',
    'chanta': '混全帯么', 'junchan': '純全帯么', 'honroutou': '混老頭',
    'shousangen': '小三元', 'ryanpeikou': '二盃口', 'sanankou': '三暗刻',
    'sankantsu': '三槓子',
}


def estimate_han(hand: List[str], melds: List, doras: List[str],
                 is_open: bool, is_tsumo: bool, has_reach: bool,
                 is_ippatsu: bool, seat: int = 0, chang: int = 0, ju: int = 0,
                 win_tile: Optional[str] = None,
                 tsumo_turn: int = 0) -> Tuple[int, List[str]]:
    from str_converter import is_red_five, tile_to_id, dora_indicator_to_dora
    actual_doras = [dora_indicator_to_dora(d) for d in doras]

    han = 0
    yaku_list: List[str] = []
    all_ids = [tile_to_id(t) for t in hand]
    for m in melds:
        all_ids.extend(tile_to_id(t) for t in getattr(m, 'tiles', []))

    if has_reach:
        han += 1
        yaku_list.append('立直')
    if is_ippatsu:
        han += 1
        yaku_list.append('一発')
    if is_tsumo and not is_open:
        han += 1
        yaku_list.append('門前清自摸和')

    for t in all_ids:
        tid = t
        for d in actual_doras:
            if tid == tile_to_id(d):
                han += 1
                yaku_list.append('ドラ')
        if is_red_five(id_to_tile(t)):
            han += 1
            yaku_list.append('赤ドラ')

    from yaku_detector import analyze_all
    yaku_infos = analyze_all(hand, melds, seat=seat, chang=chang, ju=ju,
                              win_tile=win_tile, tsumo_turn=tsumo_turn)
    for yi in yaku_infos.values():
        if yi.is_complete:
            h = yi.open_han if is_open else yi.closed_han
            if h > 0:
                han += h
                display = YAKU_DISPLAY.get(yi.name, yi.name)
                yaku_list.append(display)

    return han, yaku_list


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
        if base >= 2000:
            base = 2000

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
    if n_tenpai == 0 or n_noten == 0:
        return [0, 0, 0, 0]

    total = 3000
    payments = [0, 0, 0, 0]
    for s in range(4):
        if s in tenpai_seats:
            payments[s] = total // n_tenpai
        else:
            payments[s] = -(total // n_noten)
    return payments
