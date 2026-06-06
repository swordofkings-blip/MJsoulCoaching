# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import glob
import json
import os
import sys
import time
from typing import List, Optional, Tuple

from game_state import GameState
from evaluator import Evaluator
from str_converter import tile_to_id


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


def auto_select_target(record_data: dict) -> int:
    accounts = record_data.get('head', {}).get('accounts', [])
    if not accounts:
        return 0

    def level_score(acc):
        lv = acc.get('level', {})
        return lv.get('id', 0) * 10000 + lv.get('score', 0)

    best = max(accounts, key=level_score)
    return best.get('seat', 0)


def evaluate_record(record_path: str, target_seat: int, params: dict,
                    verbose: bool = False) -> dict:
    with open(record_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    actions = data.get('detail_records', {}).get('actions', [])
    if not actions:
        return {'error': 'No actions found', 'record': record_path}

    state = GameState()
    state.my_seat = target_seat

    total = 0
    matches = 0
    details = []
    awaiting_discard = False

    start_time = time.time()

    for action_idx, action in enumerate(actions):
        if action['type'] != 1:
            continue

        result = action['result']
        cls = result['class_name']
        d = result['data']

        if 'dora' in d:
            state.doras = [d['dora']]
        if 'doras' in d:
            state.doras = list(d['doras'])
        if 'liqibang' in d:
            state.liqibang = d['liqibang']

        if cls == 'RecordNewRound':
            tiles_key = f'tiles{target_seat}'
            target_hand = d.get(tiles_key, [])
            state.on_new_round(
                chang=d.get('chang', 0),
                ju=d.get('ju', 0),
                ben=d.get('ben', 0),
                liqibang=d.get('liqibang', 0),
                tiles=target_hand,
                scores=d.get('scores', [25000] * 4),
                left_tile_count=d.get('leftTileCount', 70),
                doras=[d.get('dora', '')] if d.get('dora') else [],
            )
            state.my_seat = target_seat
            awaiting_discard = True

        elif cls == 'RecordDealTile':
            seat = d['seat']
            tile = d['tile']
            if seat == target_seat:
                state.on_self_draw(tile)
                awaiting_discard = True
            else:
                state.on_opponent_draw(seat)

        elif cls == 'RecordDiscardTile':
            seat = d['seat']
            tile = d['tile']
            isLiqi = d.get('isLiqi', False)
            moqie = d.get('moqie', False)

            if seat == target_seat and awaiting_discard:
                hand = list(state.my_hand)
                if len(hand) % 3 == 2:
                    evaluator = Evaluator(state, params=params)
                    recommended, rec_score = evaluator.best_discard_with_score(hand)
                    is_match = (recommended == tile)
                    if is_match:
                        matches += 1
                    else:
                        details.append({
                            'hand': hand,
                            'actual': tile,
                            'recommended': recommended,
                            'tsumo': state.tsumo_count,
                        })
                    total += 1
                    if verbose:
                        mark = 'OK' if is_match else 'XX'
                        print(f'  [{state.tsumo_count:>2}] {mark} actual={tile} rec={recommended}')
                awaiting_discard = False

            state.on_discard(seat, tile, isLiqi, moqie)

        elif cls == 'RecordChiPengGang':
            state.on_chi_peng_gang(
                d['type'],
                d['seat'],
                d['tiles'],
                d.get('froms', []),
                d.get('tileStates', []),
            )

        elif cls == 'RecordAnGangAddGang':
            state.on_an_gang_add_gang(d['type'], d['seat'], d['tiles'])

        elif cls == 'RecordHule':
            awaiting_discard = False
            if 'newScores' in d:
                state.scores = list(d['newScores'])

        elif cls == 'RecordNoTile':
            awaiting_discard = False
            if 'newScores' in d:
                state.scores = list(d['newScores'])

    elapsed = time.time() - start_time
    rate = matches / total if total > 0 else 0.0

    return {
        'record': os.path.basename(record_path),
        'target_seat': target_seat,
        'total_discards': total,
        'matches': matches,
        'consistency_rate': round(rate, 4),
        'detail_count': len(details),
        'first_mismatches': details[:10],
        'elapsed_sec': round(elapsed, 3),
    }


def main():
    parser = argparse.ArgumentParser(description='何切る一致率評価スクリプト')
    parser.add_argument('--records', nargs='*', default=None,
                        help='評価する牌譜ファイルのパス（省略時は data/record_*_trimmed.json）')
    parser.add_argument('--target-seat', type=int, default=None,
                        help='評価対象プレイヤーの座席番号 (0-3)、省略時は最も段位の高いプレイヤーを自動選択')
    parser.add_argument('--params', default=None,
                        help='config_parameters.json のパス')
    parser.add_argument('--override', default=None,
                        help='個別パラメータ上書き: "PENALTY_6BLOCK_MAINTAIN=120,SCORE_GENBUTSU=900"')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='各打牌の一致結果を表示')
    args = parser.parse_args()

    params = load_params_from_args(args)

    if args.records:
        record_files = args.records
    else:
        data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
        record_files = sorted(glob.glob(os.path.join(data_dir, 'record_*_trimmed.json')))

    if not record_files:
        print('No record files found.')
        return

    all_results = []
    for rpath in record_files:
        target = args.target_seat
        if target is None:
            with open(rpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            target = auto_select_target(data)

        result = evaluate_record(rpath, target, params, verbose=args.verbose)
        all_results.append(result)

        info = result.get('error', '')
        print(f'Record: {result["record"]}  Seat={result["target_seat"]}  '
              f'{result["matches"]}/{result["total_discards"]} = '
              f'{result["consistency_rate"]*100:.1f}%  '
              f'{result["elapsed_sec"]:.1f}s  {info}')
        if result['first_mismatches']:
            for mm in result['first_mismatches'][:3]:
                print(f'    T{mm["tsumo"]}: actual={mm["actual"]} rec={mm["recommended"]}')

    total_all = sum(r['total_discards'] for r in all_results)
    matches_all = sum(r['matches'] for r in all_results)
    if total_all > 0:
        overall = matches_all / total_all
        print(f'---')
        print(f'Aggregate ({len(all_results)} records): '
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
