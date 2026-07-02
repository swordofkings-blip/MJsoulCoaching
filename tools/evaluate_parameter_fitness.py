# -*- coding: utf-8 -*-
"""
@title パラメータ適応度評価スクリプト
@description 遺伝的アルゴリズムで生成されたパラメータセットの適応度を
              人間打牌一致率で評価する。
"""
from __future__ import annotations
import argparse
import glob
import json
import os
import time
from typing import List
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id


def load_params_from_args(args) -> dict:
    params = {}
    if args.params:
        with open(args.params, 'r', encoding='utf-8') as f:
            params = json.load(f)
    if args.override:
        for pair in args.override.split(','):
            pair = pair.strip()
            if '=' not in pair:
                continue
            key, val = pair.split('=', 1)
            try:
                params[key] = int(val)
            except ValueError:
                try:
                    params[key] = float(val)
                except ValueError:
                    params[key] = val
    return params


def evaluate_all(record_path: str, params: dict, verbose: bool = False) -> dict:
    with open(record_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    actions = data.get('detail_records', {}).get('actions', [])
    if not actions:
        return {'error': 'No actions found', 'record': record_path}

    # 4人分の状態を個別に管理
    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s

    per_seat = {s: {'total': 0, 'matches': 0, 'details': []} for s in range(4)}
    all_hands = [list() for _ in range(4)]

    awaiting_discard = [False] * 4

    for action in actions:
        if action['type'] != 1:
            continue
        result = action['result']
        cls = result['class_name']
        d = result['data']

        if 'dora' in d:
            for s in range(4):
                states[s].doras = [d['dora']]
        if 'doras' in d:
            for s in range(4):
                states[s].doras = list(d['doras'])
        if 'liqibang' in d:
            for s in range(4):
                states[s].liqibang = d['liqibang']

        if cls == 'RecordNewRound':
            for s in range(4):
                tiles_key = f'tiles{s}'
                states[s].on_new_round(
                    chang=d.get('chang', 0),
                    ju=d.get('ju', 0),
                    ben=d.get('ben', 0),
                    liqibang=d.get('liqibang', 0),
                    tiles=d.get(tiles_key, []),
                    scores=d.get('scores', [25000] * 4),
                    left_tile_count=d.get('leftTileCount', 70),
                    doras=d.get('doras', [d['dora']] if 'dora' in d else []),
                )
            awaiting_discard = [True] * 4

        elif cls == 'RecordDealTile':
            seat = d['seat']
            tile = d['tile']
            for s in range(4):
                if s == seat:
                    states[s].on_self_draw(tile)
                else:
                    states[s].on_opponent_draw(seat)
            awaiting_discard[seat] = True

        elif cls == 'RecordDiscardTile':
            seat = d['seat']
            tile = d['tile']
            isLiqi = d.get('isLiqi', False)
            moqie = d.get('moqie', False)

            if awaiting_discard[seat]:
                hand = list(states[seat].my_hand)
                if len(hand) % 3 == 2:
                    is_riichi = states[seat].reach_states[seat].is_reach
                    if is_riichi:
                        is_match = True
                    else:
                        evaluator = Evaluator(states[seat], params=params)
                        recommended, rec_score = evaluator.best_discard_with_score(hand)
                        unique = list(dict.fromkeys(hand))
                        scores = {t: evaluator.evaluate_tile(t) for t in unique}
                        max_score = rec_score
                        min_score = min(scores.values()) if scores else 0.0
                        actual_score = scores.get(tile, min_score)
                        actual_score = min(actual_score, max_score)

                        min_range = params.get('MATCH_MIN_RANGE', 400.0)
                        score_range = max(max_score - min_score, min_range)
                        diff = max(0.0, max_score - actual_score)
                        ratio = max(0.0, 1.0 - diff / score_range)
                        # 100.0: Mortalのレーティング形式に合わせ、最善手を100点満点とするスケーリング
                        # 2: 最善手から少し外れた手のレーティングを厳しく減衰させるためのMortal準拠 of 2乗
                        rating = 100.0 * (ratio ** 2)

                        rating_threshold = params.get('MATCH_RATING_THRESHOLD', 90.0)

                        rec_shanten = evaluator.attack.shanten_after_discard(recommended) if recommended else 99
                        rec_defense = evaluator.defense.defense_score_for_tile(recommended) if recommended else -9999.0
                        actual_shanten = evaluator.attack.shanten_after_discard(tile)
                        actual_defense = evaluator.defense.defense_score_for_tile(tile)

                        # 安全度が同等以下かつシャンテン数が後退する無駄な危険牌は一致とみなさない
                        is_useless_discard = (actual_defense <= rec_defense and actual_shanten > rec_shanten)
                        scored_list = sorted(scores.items(), key=lambda x: -x[1])
                        top3 = [t for t, _ in scored_list[:3]]
                        is_match = ((tile in top3 and rating >= 70) or (rating >= rating_threshold and not is_useless_discard))
                    if is_match:
                        per_seat[seat]['matches'] += 1
                    else:
                        per_seat[seat]['details'].append({
                            'hand': hand, 'actual': tile, 'recommended': recommended,
                            'tsumo': states[seat].tsumo_count,
                        })
                    per_seat[seat]['total'] += 1
                    if verbose:
                        mark = 'OK' if is_match else 'XX'
                        print(f'  [S{seat}:T{states[seat].tsumo_count:>2}] {mark} actual={tile} rec={recommended}')
                awaiting_discard[seat] = False

            for s in range(4):
                states[s].on_discard(seat, tile, isLiqi, moqie)
            for s in range(4):
                for rs in states[s].reach_states:
                    rs.is_ippatsu = False

        elif cls == 'RecordChiPengGang':
            for s in range(4):
                states[s].on_chi_peng_gang(d['type'], d['seat'], d['tiles'],
                                            d.get('froms', []), d.get('tileStates', []))
            awaiting_discard[d['seat']] = True

        elif cls == 'RecordAnGangAddGang':
            for s in range(4):
                states[s].on_an_gang_add_gang(d['type'], d['seat'], d['tiles'])

        elif cls == 'RecordHule':
            awaiting_discard = [False] * 4
            if 'newScores' in d:
                for s in range(4):
                    states[s].scores = list(d['newScores'])

        elif cls == 'RecordNoTile':
            awaiting_discard = [False] * 4
            if 'newScores' in d:
                for s in range(4):
                    states[s].scores = list(d['newScores'])

    total_all = sum(per_seat[s]['total'] for s in range(4))
    matches_all = sum(per_seat[s]['matches'] for s in range(4))
    rate = matches_all / total_all if total_all > 0 else 0.0

    return {
        'record': os.path.basename(record_path),
        'per_seat': {
            str(s): {
                'total': per_seat[s]['total'],
                'matches': per_seat[s]['matches'],
                'rate': round(per_seat[s]['matches'] / per_seat[s]['total'], 4) if per_seat[s]['total'] > 0 else 0.0,
                'first_mismatches': per_seat[s]['details'][:5],
            } for s in range(4)
        },
        'total_discards': total_all,
        'matches': matches_all,
        'consistency_rate': round(rate, 4),
    }


def main():
    parser = argparse.ArgumentParser(description='何切る一致率評価（4人同時）')
    parser.add_argument('--records', nargs='*', default=None)
    parser.add_argument('--params', default=None)
    parser.add_argument('--override', default=None)
    parser.add_argument('--verbose', '-v', action='store_true')
    args = parser.parse_args()

    params = load_params_from_args(args)

    if args.records:
        record_files = args.records
    else:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
        record_files = sorted(glob.glob(os.path.join(data_dir, 'record_*_trimmed.json')))

    if not record_files:
        print('No record files found.')
        return

    all_results = []
    total_all = 0
    matches_all = 0

    for rpath in record_files:
        result = evaluate_all(rpath, params, verbose=args.verbose)
        all_results.append(result)
        total_all += result['total_discards']
        matches_all += result['matches']

        print(f'Record: {result["record"]}  '
              f'{result["matches"]}/{result["total_discards"]} = '
              f'{result["consistency_rate"]*100:.1f}%')
        for s in range(4):
            ps = result['per_seat'][str(s)]
            print(f'  Seat {s}: {ps["matches"]}/{ps["total"]} = {ps["rate"]*100:.1f}%')

    if total_all > 0:
        overall = matches_all / total_all
        print(f'---')
        print(f'Aggregate ({len(all_results)} records, 4 seats): '
              f'{matches_all}/{total_all} = {overall*100:.1f}%')

    output = {
        'params_used': params,
        'records': all_results,
        'aggregate': {
            'num_records': len(all_results),
            'total_discards': total_all,
            'matches': matches_all,
            'consistency_rate': round(matches_all / total_all, 4) if total_all > 0 else 0.0,
        },
    }
    print()
    print(json.dumps(output, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
