# -*- coding: utf-8 -*-
"""
@title ver.2 立直判断 (ルールベース + EV フォールバック)
@description テンパイ時の立直判断を 明示的ルールベースで実施。
優先順位: 1.禁止 2.立直推奨 3.ダマ推奨 4.EV比較
"""
from __future__ import annotations
from typing import List, Tuple, Optional

from core.str_converter import tile_to_id, is_honor, hand_to_counts
from core.shanten_v2 import ShantenCalculatorV2


def _is_ryanmen_wait(hand_counts, wait_id: int) -> bool:
    """@title 待ち牌 wait_id が 両面待ち (Ryanmen) かどうか
    3 patterns:
      1. wait fills LEFT: hand has wait+1 AND wait+2
      2. wait fills MIDDLE: hand has wait-1 AND wait+1
      3. wait fills RIGHT: hand has wait-2 AND wait-1
    """
    if is_honor(wait_id):
        return False
    base = (wait_id // 9) * 9
    off = wait_id - base
    if off == 0 or off == 8:
        return False
    check_left = off <= 6 and hand_counts[base + off + 1] >= 1 and hand_counts[base + off + 2] >= 1
    check_mid = (off > 0 and off < 8 and hand_counts[base + off - 1] >= 1 and hand_counts[base + off + 1] >= 1)
    check_right = off >= 2 and hand_counts[base + off - 2] >= 1 and hand_counts[base + off - 1] >= 1
    return check_left or check_mid or check_right


def _classify_wait_type(hand_counts) -> dict:
    win_tiles = []
    ryanmen = False
    kanchan = False
    penchan = False
    tanki = False
    for tile_id in range(34):
        if hand_counts[tile_id] >= 4:
            continue
        test = list(hand_counts)
        test[tile_id] += 1
        sh = ShantenCalculatorV2.calculate_closed_effective(test)
        if sh < 0:
            win_tiles.append(tile_id)
            if _is_ryanmen_wait(hand_counts, tile_id):
                ryanmen = True
            elif is_honor(tile_id):
                tanki = True
            else:
                base = (tile_id // 9) * 9
                off = tile_id - base
                if off == 0 or off == 8:
                    penchan = True
                else:
                    kanchan = True
    is_good = ryanmen
    is_bad = not ryanmen and len(win_tiles) > 0
    if ryanmen and not (kanchan or penchan):
        wtype = 'ryanmen'
    elif ryanmen:
        wtype = 'multi'
    elif kanchan and not penchan:
        wtype = 'kanchan'
    elif penchan and not kanchan:
        wtype = 'penchan'
    elif len(win_tiles) == 1:
        wtype = 'tanki'
    else:
        wtype = 'complex'
    return {'win_tiles': win_tiles, 'is_good_shape': is_good, 'is_bad_shape': is_bad,
            'has_ryanmen': ryanmen, 'type': wtype, 'count': len(win_tiles)}


def _get_turn(state) -> int:
    return max(1, min(18, (state.tsumo_count - 1) // 4 + 1))


def _get_rank(state) -> int:
    if hasattr(state, 'scores') and state.scores:
        my_score = state.scores[state.my_seat]
        return sorted(state.scores, reverse=True).index(my_score)
    return -1


DEFAULT_WEIGHTS = {
    'RIICHI_W_BASE_SCORE': -100.0, 'RIICHI_W_HAND_QUALITY': 80.0,
    'RIICHI_W_HIGH_HAN': 100.0, 'RIICHI_W_EARLY_TURN': -100.0,
    'RIICHI_W_LATE_TURN': 80.0, 'RIICHI_W_TOP_PLACE': -100.0,
    'RIICHI_W_LAST_PLACE': 120.0, 'RIICHI_W_OPP_REACH': -80.0,
    'RIICHI_W_CLOSED_BONUS': 60.0, 'RIICHI_W_AGARI_LOW_HAN': 0.0,
}


def get_weights(params: dict) -> dict:
    w = dict(DEFAULT_WEIGHTS)
    if params:
        for k in w:
            v = params.get(k)
            if v is not None:
                w[k] = float(v)
    return w


def estimate_han_count(state) -> int:
    counts = hand_to_counts(state.my_hand)
    han = 0
    if state.doras:
        for d in state.doras:
            try:
                han += counts[tile_to_id(d)]
            except Exception:
                continue
    han += sum(1 for t in state.my_hand if t in ('0m', '0p', '0s'))
    SANGEN = {31, 32, 33}
    seat_wind = 27 + ((state.my_seat - state.ju) % 4)
    round_wind = 27 + (state.chang % 4)
    for t in set(state.my_hand):
        try:
            tid = tile_to_id(t)
        except Exception:
            continue
        if tid in SANGEN or tid in (seat_wind, round_wind):
            if counts[tid] >= 3:
                han += 1
    return han


def is_tenpai_closed(state) -> bool:
    if sum(1 for m in state.my_melds if m.is_open) > 0:
        return False
    return ShantenCalculatorV2.calculate_closed_effective(hand_to_counts(state.my_hand)) <= 0


def self_reached(state) -> bool:
    """@title 自分が既に立直しているか"""
    rs = state.reach_states[state.my_seat] if state.my_seat < len(state.reach_states) else None
    return rs is not None and rs.is_reach


def opp_reach_exists(state) -> bool:
    for s in range(4):
        if s == state.my_seat:
            continue
        rs = state.reach_states[s] if s < len(state.reach_states) else None
        if rs is not None and rs.is_reach:
            return True
    return False


def _explicit_decision(state) -> Tuple[Optional[bool], str]:
    # P0: basic checks
    if not is_tenpai_closed(state):
        return (False, "not tenpai or open")
    if self_reached(state):
        return (False, "already in reach (self)")

    # P1: prohibitive
    my_score = state.scores[state.my_seat] if state.scores else 25000
    if my_score < 1000:
        return (False, "score < 1000, riichi impossible")

    han = estimate_han_count(state)
    turn = _get_turn(state)
    rank = _get_rank(state)
    wait = _classify_wait_type(hand_to_counts(state.my_hand))
    opp_reach = opp_reach_exists(state)

    # P2: riichi positive rules
    if han == 0:
        return (True, "R1: no yaku, must riichi")
    if wait['is_good_shape'] and han >= 1 and not opp_reach:
        return (True, f"R2: good wait ({wait['type']}) + {han}han, riichi")
    if han >= 3 and not opp_reach:
        return (True, f"R2b: {han}han high value, riichi")
    if rank == 3 and han >= 1:
        return (True, "R4: last place, riichi to catch up")
    if turn >= 14 and han >= 2 and not opp_reach:
        return (True, "R5: late turn, riichi")

    # P3: damaten negative rules
    if opp_reach and wait['is_bad_shape'] and han <= 2:
        return (False, "R7: opp reach + bad shape, damaten")
    if opp_reach and han <= 1:
        return (False, "R7b: opp reach + low value, damaten")
    if wait['is_bad_shape'] and han <= 1:
        return (False, "R6: bad wait + low value, damaten")
    if turn <= 5 and wait['is_bad_shape'] and han <= 2:
        return (False, f"R8: early turn + bad shape, damaten")
    if rank == 0 and han <= 2:
        return (False, "R9: top rank, damaten")

    # No explicit rule fire -> fall through to EV comparison
    return (None, "")


def score_riichi(state, params: dict) -> Tuple[float, str]:
    decision, reason = _explicit_decision(state)
    if decision is True:
        return 9999.0, f"RIICHI ({reason})"
    if decision is False:
        return -9999.0, f"DAMATEN ({reason})"

    # EV fallback
    w = get_weights(params)
    if not is_tenpai_closed(state):
        return -9999.0, "not tenpai"
    if self_reached(state):
        return -9999.0, "already in reach (self)"

    score = w['RIICHI_W_BASE_SCORE']
    reasons = []
    han = estimate_han_count(state)
    turn = _get_turn(state)
    rank = _get_rank(state)
    wait = _classify_wait_type(hand_to_counts(state.my_hand))

    if han >= 1:
        score += w['RIICHI_W_HAND_QUALITY'] * 0.5
        reasons.append(f"yaku {han}han")
    if han >= 4:
        score += w['RIICHI_W_HIGH_HAN']
        reasons.append("mangan+")
    if han == 0:
        score += w['RIICHI_W_AGARI_LOW_HAN']
        reasons.append("no yaku")
    elif han >= 2:
        score += 20
        reasons.append(f"{han}han+")
    if wait['is_good_shape']:
        score += 50
        reasons.append(f"good wait ({wait['type']})")
    elif wait['is_bad_shape']:
        score -= 30
        reasons.append(f"bad wait ({wait['type']})")
    if wait['count'] >= 3:
        score += 30
        reasons.append("multi")
    score += w['RIICHI_W_CLOSED_BONUS']
    if turn <= 5:
        score += w['RIICHI_W_EARLY_TURN']
        reasons.append(f"early T{turn}")
    elif turn >= 14:
        score += w['RIICHI_W_LATE_TURN']
        reasons.append(f"late T{turn}")
    elif turn >= 10:
        score += 25
        reasons.append(f"mid T{turn}")
    if rank == 0:
        score += w['RIICHI_W_TOP_PLACE']
        reasons.append("top")
    elif rank == 3:
        score += w['RIICHI_W_LAST_PLACE']
        reasons.append("last")
    if opp_reach_exists(state):
        score += w['RIICHI_W_OPP_REACH']
        reasons.append("opp reach")
    if wait['is_bad_shape'] and opp_reach_exists(state):
        score -= 40
        reasons.append("bad+oppR penalty")

    reason = ", ".join(reasons) if reasons else "neutral"
    return score, f"EVscore={score:.0f} ({reason})"


def should_riichi(state, params: dict = None) -> bool:
    if params is None:
        params = {}
    score, _ = score_riichi(state, params)
    threshold = get_weights(params).get('RIICHI_THRESHOLD', 0.0)
    return score > threshold


def should_kan(state, call_type: int, tiles: List[str], from_seat: int, params: dict = None) -> bool:
    from core.meld_v2 import should_call_meld
    if params is None:
        params = {}
    decision, _reason = should_call_meld(state, call_type, tiles, from_seat, params)
    return bool(decision)
