# -*- coding: utf-8 -*-
"""
@title process_file のインライン版(JSON ファイル I/O をスキップ)
@description
    extract_mismatches.process_file のロジックを複写し、ファイル読み書き
    なしで dict を直接受け取るバージョン。並列ワーカーで JSON ファイル
    の読み書き I/O を回避するためのもの。

    process_file と同じ semantics を維持する(mismatches 詳細は返さない)。
    高速化のため evaluate_tile の結果を Evaluator の state ハッシュで
    プロセス内キャッシュして、best_discard と事後ループの重複評価(14回)を
    回避する。extract_mismatches.process_file と結果は同一になる。
"""
from __future__ import annotations

import sys
import os

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, THIS_DIR)

from core.game_state import GameState
from core.evaluator import Evaluator
from extract_mismatches import (
    generate_meld_candidates,
    SEAT_NAMES,
    CALL_NAMES,
    fmt_tile,
)


def _state_key(state: GameState) -> tuple:
    """Evaluator.evaluate_tile のキャッシュ用 state ハッシュ。
    score 計算に影響する属性を frozen tuple にして Python の hash に乗せる。"""
    return (
        state.my_seat,
        tuple(sorted(state.my_hand)),
        tuple(tuple(r) for r in state.river),
        tuple(tuple(m.tiles) for sm in state.melds for m in sm),
        tuple(tuple(m.froms) for sm in state.melds for m in sm),
        tuple(state.doras),
        tuple(state.scores),
        tuple((rs.is_reach, rs.reach_turn, rs.is_ippatsu) for rs in state.reach_states),
        state.tsumo_count,
        state.chang,
        state.ju,
        state.ben,
        state.liqibang,
        state.left_tile_count,
    )


# 1巡前キャッシュ(近似版)は defense_score が river 全体に依存するため、
# 厳密には1巡前(4巡間隔)で hand の 13/14 牌が同じでもスコアが変わり、
# 結果を保証できない。実験したところ:
#   - hand_count だけでキャッシュ: 89% 高速化、ただし 406/582 → 150/582 と一致率大低下
#   - hand_count + 牌ごと visible: 84% 高速化、ただし 174/582 と低下
#   - hand_count + 全 visible_signature: 0 hit、効果なし
# よって本実装では厳密キャッシュ (state_key + tile) のみ採用している。
# 1巡前キャッシュは attack_score の shanten / ukeire を hand ベースで持つ
# コア側の改修が必要 (defense を分離して再合成する設計が要る)。

_EVAL_CACHE: dict = {}
_EVAL_CACHE_HITS = 0
_EVAL_CACHE_MISSES = 0


def _reset_eval_cache():
    global _EVAL_CACHE, _EVAL_CACHE_HITS, _EVAL_CACHE_MISSES
    _EVAL_CACHE = {}
    _EVAL_CACHE_HITS = 0
    _EVAL_CACHE_MISSES = 0


def _cached_evaluate_tile(ev: Evaluator, tile: str, _raw=None):
    """evaluate_tile を state_key + tile で厳密キャッシュする。
    同一 state 内の重複呼び出し (best_discard 内部と事後ループ) でヒットする。"""
    global _EVAL_CACHE_HITS, _EVAL_CACHE_MISSES
    skey = (_state_key(ev.state), tile)
    cached = _EVAL_CACHE.get(skey)
    if cached is not None:
        _EVAL_CACHE_HITS += 1
        return cached
    _EVAL_CACHE_MISSES += 1
    if _raw is not None:
        score = _raw(ev, tile)
    else:
        score = Evaluator.evaluate_tile(ev, tile)
    _EVAL_CACHE[skey] = score
    return score


def get_cache_stats() -> tuple:
    """直近の process_dict 呼び出しでのキャッシュヒット率
    returns: (strict_hits, strict_misses)
    """
    return (_EVAL_CACHE_HITS, _EVAL_CACHE_MISSES)


def process_dict(data: dict, params: dict) -> tuple:
    """
    @title インライン process_file
    @description actions 形式 dict を受け取り、process_file と同じ合計値を返す
    @param {dict} data - extract_mismatches.py が読む JSON dict
    @param {dict} params - config_parameters.json の dict
    @returns {tuple} (lines, total_discard, discard_match, total_meld, meld_match, fname)
    """
    lines = []
    def out(s=''):
        lines.append(s)

    _reset_eval_cache()
    actions = data.get('detail_records', {}).get('actions', [])
    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    def reset_ippatsu():
        for s in range(4):
            for rs in states[s].reach_states:
                rs.is_ippatsu = False

    fname = data.get('head', {}).get('uuid', 'inline')
    mismatch_idx = 0
    total_discard = 0
    discard_match = 0
    total_meld = 0
    meld_match = 0

    for idx, a in enumerate(actions):
        if a['type'] != 1:
            continue
        r = a['result']
        cls = r['class_name']
        d = r['data']

        if 'dora' in d:
            for s in range(4): states[s].doras = [d['dora']]
        if 'doras' in d:
            for s in range(4): states[s].doras = list(d['doras'])
        if 'liqibang' in d:
            for s in range(4): states[s].liqibang = d['liqibang']

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(
                    d.get('chang', 0), d.get('ju', 0), d.get('ben', 0),
                    d.get('liqibang', 0), d.get(k, []),
                    d.get('scores', [25000] * 4),
                    d.get('leftTileCount', 70),
                    d.get('doras', [d['dora']] if 'dora' in d else [])
                )
                states[s].chang = d.get('chang', 0)
                states[s].ju = d.get('ju', 0)
            awaiting = [True] * 4

        elif cls == 'RecordDealTile':
            seat = d['seat']
            tile = d['tile']
            for s in range(4):
                if s == seat: states[s].on_self_draw(tile)
                else: states[s].on_opponent_draw(seat)
            awaiting[seat] = True

        elif cls == 'RecordDiscardTile':
            seat = d['seat']
            tile = d['tile']
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if awaiting[seat]:
                hand = list(states[seat].my_hand)
                if len(hand) % 3 == 2:
                    is_riichi = states[seat].reach_states[seat].is_reach
                    if not is_riichi:
                        total_discard += 1
                        ev = Evaluator(states[seat], params)
                        # best_discard と同じ semantics (元のコードと同一結果)。
                        # best_discard_with_score 内部の evaluate_tile 呼び出しを
                        # キャッシュ経由に置き換えて、2回目のスコア計算ループで
                        # キャッシュヒットさせる
                        _raw_eval = Evaluator.evaluate_tile
                        ev.evaluate_tile = lambda t, _ev=ev, _r=_raw_eval: _cached_evaluate_tile(_ev, t, _raw=_r)
                        try:
                            best, _best_score = ev.best_discard_with_score(hand)
                        finally:
                            ev.evaluate_tile = _raw_eval
                        is_exact = (best == tile)
                        is_matched = False
                        if is_exact:
                            is_matched = True
                        else:
                            # best_discard 内部で同じ Evaluator/tile を評価済みなのですでにキャッシュヒット
                            scores = {t: _cached_evaluate_tile(ev, t) for t in dict.fromkeys(hand)}
                            best_score = scores.get(best, 0)
                            actual_score = scores.get(tile, min(scores.values()) if scores else 0)
                            range_val = max(best_score - min(scores.values()), params.get('MATCH_MIN_RANGE', 400.0))
                            diff = max(0.0, best_score - actual_score)
                            ratio = max(0.0, 1.0 - diff / range_val)
                            rating = 100.0 * (ratio ** 2)
                            is_matched = rating >= 90.0

                        if is_matched:
                            discard_match += 1
                        else:
                            mismatch_idx += 1

            # 他家が切った時、自分が鳴ける状況でスキップしたケースをチェック
            next_meld_action = None
            if idx + 1 < len(actions):
                next_act = actions[idx+1]
                if next_act['type'] == 1:
                    next_res = next_act['result']
                    if next_res['class_name'] == 'RecordChiPengGang':
                        next_meld_action = next_res['data']

            for opp in range(4):
                if opp == seat:
                    continue
                if states[opp].reach_states[opp].is_reach:
                    continue
                is_actual_meld_by_opp = False
                if next_meld_action is not None:
                    if next_meld_action['seat'] == opp:
                        is_actual_meld_by_opp = True
                if is_actual_meld_by_opp:
                    continue
                is_kamicha = ((opp - 1) % 4 == seat)
                opp_hand = list(states[opp].my_hand)
                cands = generate_meld_candidates(opp_hand, tile, is_kamicha)
                if cands:
                    ev = Evaluator(states[opp], params)
                    ai_wants_to_meld = False
                    for c_type, c_tiles in cands:
                        if ev.should_call_meld(c_type, c_tiles, seat):
                            ai_wants_to_meld = True
                            break
                    total_meld += 1
                    if not ai_wants_to_meld:
                        meld_match += 1
                    else:
                        mismatch_idx += 1

            awaiting[seat] = False
            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)
            reset_ippatsu()

        elif cls == 'RecordChiPengGang':
            call_type = d['type']
            call_seat = d['seat']
            tiles = d['tiles']
            froms = d.get('froms', [])
            tile_states = d.get('tileStates', [])

            if call_type in (0, 1, 2):
                total_meld += 1
                ev = Evaluator(states[call_seat], params)
                ai_decision = ev.should_call_meld(call_type, tiles, froms[0] if froms else -1)
                if ai_decision == True:
                    meld_match += 1
                else:
                    mismatch_idx += 1

            for s in range(4):
                states[s].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
            awaiting[call_seat] = True
            reset_ippatsu()

        elif cls == 'RecordAnGangAddGang':
            for s in range(4):
                states[s].on_an_gang_add_gang(d['type'], d['seat'], d['tiles'])

        elif cls in ('RecordHule', 'RecordNoTile'):
            awaiting = [False] * 4

    return lines, total_discard, discard_match, total_meld, meld_match, fname
