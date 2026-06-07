# -*- coding: utf-8 -*-
from __future__ import annotations
import argparse
import json
import os
import time
from typing import List, Tuple
from dataclasses import dataclass, field, asdict
from functools import partial
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing

from ai_player import AIPlayer
from mahjong_simulator import MahjongSimulator, GameResult
from evaluator import Evaluator


PT_TABLES = {
    'gold':  {0: 30, 1: 10, 2: -10, 3: -30},
    'jade':  {0: 45, 1: 15, 2: -15, 3: -45},
    'throne': {0: 60, 1: 20, 2: -20, 3: -60},
}

BASE_SCORE = 25000


def load_params(path: str) -> dict:
    if not path or not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def compute_pt(placement: int, final_score: int, room: str) -> int:
    placement_pt = PT_TABLES.get(room, PT_TABLES['jade']).get(placement, 0)
    score_bonus = (final_score - BASE_SCORE) // 1000
    return placement_pt + score_bonus


@dataclass
class BattleResult:
    seed: int
    baseline_pts: List[float]
    test_pts: List[float]
    baseline_placements: List[List[int]]
    test_placements: List[List[int]]
    baseline_scores: List[List[int]]
    test_scores: List[List[int]]


def _run_seed(seed: int, logic_a_params: dict, logic_b_params: dict,
              room: str, game_type: str) -> BattleResult:
    from strategy_manager import ShantenCalculator
    ShantenCalculator.clear_cache()

    base_ai = AIPlayer("base", Evaluator, logic_a_params)
    test_ai = AIPlayer("test", Evaluator, logic_b_params)

    baseline_pts = []
    baseline_placements = []
    baseline_scores = []

    for _ in range(4):
        players = [base_ai.clone(i) for i in range(4)]
        gr = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type).run_game()
        for s in range(4):
            pl = gr.placement_of(s)
            baseline_pts.append(compute_pt(pl, gr.final_scores[s], room))
        baseline_placements.append(gr.final_placements)
        baseline_scores.append(gr.final_scores)

    test_pts = []
    test_placements = []
    test_scores = []

    for test_seat in range(4):
        players = []
        for s in range(4):
            if s == test_seat:
                players.append(test_ai.clone(s))
            else:
                players.append(base_ai.clone(s))
        gr = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type).run_game()
        pl = gr.placement_of(test_seat)
        test_pts.append(compute_pt(pl, gr.final_scores[test_seat], room))
        test_placements.append(gr.final_placements)
        test_scores.append(gr.final_scores)

    return BattleResult(
        seed=seed,
        baseline_pts=baseline_pts,
        test_pts=test_pts,
        baseline_placements=baseline_placements,
        test_placements=test_placements,
        baseline_scores=baseline_scores,
        test_scores=test_scores,
    )


def main():
    parser = argparse.ArgumentParser(description='デュプリケーター式バトルテスト')
    parser.add_argument('--seeds', default='1-100',
                        help='山牌シード範囲 (例: 1-1000, または 1,2,3,5)')
    parser.add_argument('--game-type', default='tonpu', choices=['tonpu', 'hanchan'],
                        help='東風戦(tonpu) or 半荘戦(hanchan)')
    parser.add_argument('--room', default='jade', choices=['gold', 'jade', 'throne'],
                        help='部屋ランク')
    parser.add_argument('--logic-a-params', default='config_parameters.json',
                        help='LogicA (現行) のパラメータJSON')
    parser.add_argument('--logic-b-params', default='',
                        help='LogicB (拡張) のパラメータJSON (空=LogicAと同じ)')
    parser.add_argument('--output', default='battle_result.json',
                        help='結果出力先')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='各ゲームの詳細を表示')
    parser.add_argument('--parallel', type=int, default=0,
                        help='並列実行ワーカー数 (0=自動, 1=逐次)')
    args = parser.parse_args()

    if args.seeds and '-' in args.seeds and ',' not in args.seeds:
        parts = args.seeds.split('-')
        seeds = list(range(int(parts[0]), int(parts[1]) + 1))
    elif ',' in args.seeds:
        seeds = [int(s.strip()) for s in args.seeds.split(',')]
    else:
        seeds = [int(args.seeds)]

    logic_a_params = load_params(args.logic_a_params)
    logic_b_params = load_params(args.logic_b_params) if args.logic_b_params else dict(logic_a_params)

    n_workers = args.parallel
    if n_workers == 0:
        n_workers = min(multiprocessing.cpu_count(), len(seeds))

    if args.verbose:
        print(f'Seeds: {len(seeds)} ({seeds[0]}-{seeds[-1]})')
        print(f'Game type: {args.game_type}')
        print(f'Room: {args.room}')
        print(f'Logic A: {args.logic_a_params}')
        print(f'Logic B: {args.logic_b_params or "(same as A)"}')
        print(f'Workers: {n_workers}')
        print()

    start_time = time.time()
    all_results: List[BattleResult] = []

    if n_workers <= 1:
        for idx, seed in enumerate(seeds):
            br = _run_seed(seed, logic_a_params, logic_b_params, args.room, args.game_type)
            all_results.append(br)
            if args.verbose:
                base_seats = [sum(br.baseline_pts[game*4 + s] for game in range(4)) / 4 for s in range(4)]
                test_seats = br.test_pts
                seat_labels = ['東','南','西','北']
                diffs = [test_seats[s] - base_seats[s] for s in range(4)]
                diff_str = ' '.join(f'{seat_labels[s]}={diffs[s]:+.0f}' for s in range(4))
                print(f'Seed {seed:4d}: B[{",".join(f"{base_seats[s]:+.0f}" for s in range(4))}]  '
                      f'T[{",".join(f"{test_seats[s]:+.0f}" for s in range(4))}]  '
                      f'diff: {diff_str}')
            if (idx + 1) % 10 == 0 and args.verbose:
                print(f'  ... {idx+1}/{len(seeds)}  ({time.time()-start_time:.1f}s)')
    else:
        worker = partial(_run_seed,
                         logic_a_params=logic_a_params,
                         logic_b_params=logic_b_params,
                         room=args.room,
                         game_type=args.game_type)

        with ProcessPoolExecutor(max_workers=n_workers) as pool:
            futures = {pool.submit(worker, seed): seed for seed in seeds}
            done_count = 0
            for future in as_completed(futures):
                seed = futures[future]
                br = future.result()
                all_results.append(br)
                done_count += 1
                if args.verbose:
                    base_seats = [sum(br.baseline_pts[game*4 + s] for game in range(4)) / 4 for s in range(4)]
                    test_seats = br.test_pts
                    seat_labels = ['東','南','西','北']
                    diffs = [test_seats[s] - base_seats[s] for s in range(4)]
                    diff_str = ' '.join(f'{seat_labels[s]}={diffs[s]:+.0f}' for s in range(4))
                    print(f'Seed {seed:4d}: B[{",".join(f"{base_seats[s]:+.0f}" for s in range(4))}]  '
                          f'T[{",".join(f"{test_seats[s]:+.0f}" for s in range(4))}]  '
                          f'diff: {diff_str}  ({done_count}/{len(seeds)})')
                if done_count % 10 == 0 and args.verbose:
                    print(f'  ... {done_count}/{len(seeds)}  ({time.time()-start_time:.1f}s)')

    all_baseline_pts = [p for br in all_results for p in br.baseline_pts]
    all_test_pts = [p for br in all_results for p in br.test_pts]

    total_base = sum(all_baseline_pts)
    total_test = sum(all_test_pts)
    avg_base = total_base / len(all_baseline_pts) if all_baseline_pts else 0
    avg_test = total_test / len(all_test_pts) if all_test_pts else 0

    by_seat = {s: {'base': [], 'test': []} for s in range(4)}
    for br in all_results:
        for game in range(4):
            for seat in range(4):
                by_seat[seat]['base'].append(br.baseline_pts[game * 4 + seat])
        for seat in range(4):
            by_seat[seat]['test'].append(br.test_pts[seat])

    elapsed = time.time() - start_time

    print()
    print(f'=== バトルテスト結果 ===')
    print(f'シード: {seeds[0]}〜{seeds[-1]} ({len(seeds)}シード)')
    print(f'ゲーム: {args.game_type} / 部屋: {args.room}')
    print(f'対戦数: ベースライン {len(seeds)*4}戦 / テスト {len(seeds)*4}戦')
    print(f'所要時間: {elapsed:.1f}s / ワーカー数: {n_workers}')
    print()
    print(f'ベースライン(A): 平均 {avg_base:+6.2f}pt/戦  (合計 {total_base:+8.0f}pt)')
    print(f'拡張ロジック(B): 平均 {avg_test:+6.2f}pt/戦  (合計 {total_test:+8.0f}pt)')
    print(f'pt差: {avg_test - avg_base:+6.2f}pt/戦  '
          f'({"B優勢" if avg_test > avg_base else "A優勢" if avg_base > avg_test else "互角"})')

    print()
    for seat in range(4):
        b_avg = sum(by_seat[seat]['base']) / len(by_seat[seat]['base'])
        t_avg = sum(by_seat[seat]['test']) / len(by_seat[seat]['test'])
        print(f'  {["東","南","西","北"][seat]}家: base={b_avg:+5.1f}pt  test={t_avg:+5.1f}pt  '
              f'diff={t_avg - b_avg:+5.1f}pt')

    output = {
        'config': {
            'seeds': [seeds[0], seeds[-1]] if len(seeds) > 1 else seeds[0],
            'num_seeds': len(seeds),
            'game_type': args.game_type,
            'room': args.room,
            'workers': n_workers,
            'logic_a_params': args.logic_a_params,
            'logic_b_params': args.logic_b_params or '(same)',
        },
        'summary': {
            'baseline_avg_pt': round(avg_base, 2),
            'test_avg_pt': round(avg_test, 2),
            'pt_difference': round(avg_test - avg_base, 2),
            'baseline_total_pt': total_base,
            'test_total_pt': total_test,
            'num_baseline_games': len(all_baseline_pts),
            'num_test_games': len(all_test_pts),
            'elapsed_sec': round(elapsed, 1),
        },
        'per_seat': {
            str(s): {
                'baseline_avg': round(sum(by_seat[s]['base']) / len(by_seat[s]['base']), 2),
                'test_avg': round(sum(by_seat[s]['test']) / len(by_seat[s]['test']), 2),
            } for s in range(4)
        },
        'results': [asdict(br) for br in all_results],
    }

    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    if args.verbose:
        print(f'\n結果を {args.output} に保存しました')


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
