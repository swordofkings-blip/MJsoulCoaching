# -*- coding: utf-8 -*-
"""
Manue vs Existing AI の対戦スクリプト
battle_test.py の _run_seed を流用して ManueAI と既存 AI を対戦させる
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List
from functools import partial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, ReachState, Meld
from core.evaluator import Evaluator
from core.strategy_manager import ShantenCalculator
from core.str_converter import tile_to_id, id_to_tile, hand_to_counts
from tools.mahjong_simulator import MahjongSimulator, GameResult, PlayerGameStats
from tools.manue_battle import ManueAIPlayer, ManueGameAdapter, load_params, compute_pt, PT_TABLES, BASE_SCORE


def _run_seed_manue_vs_ai(seed: int, manue_ai, existing_params: dict,
                           room: str, game_type: str, quick: bool = False) -> dict:
    ShantenCalculator.clear_cache()

    from core.ai_player import AIPlayer
    existing_ai = AIPlayer("existing", Evaluator, existing_params)
    manue_player = ManueAIPlayer("manue", manue_ai)

    test_pts = []
    test_placements = []
    test_scores = []
    test_player_stats = []

    test_seats = range(1) if quick else range(4)
    for test_seat in test_seats:
        players = []
        for s in range(4):
            if s == test_seat:
                players.append(manue_player.clone(s))
            else:
                players.append(existing_ai.clone(s))

        gr = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type).run_game()
        pl = gr.placement_of(test_seat)
        pt = compute_pt(pl, gr.final_scores[test_seat], room)
        test_pts.append(pt)
        test_placements.append(gr.final_placements)
        test_scores.append(gr.final_scores)
        test_player_stats.append(gr.player_stats[test_seat])

    return {
        'seed': seed,
        'test_pts': test_pts,
        'test_placements': test_placements,
        'test_scores': test_scores,
        'test_player_stats': test_player_stats,
    }


def main():
    parser = argparse.ArgumentParser(description='Manue vs Existing AI Battle')
    parser.add_argument('--seeds', default='1-10', help='Seed range')
    parser.add_argument('--game-type', default='tonpu', choices=['tonpu', 'hanchan'])
    parser.add_argument('--room', default='jade', choices=['gold', 'jade', 'throne'])
    parser.add_argument('--params', default='config/config_parameters.json')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--quick', action='store_true', help='Test seat 0 only')
    parser.add_argument('--parallel', type=int, default=0, help='Workers (0=auto)')
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() in ('cp932', 'shift_jis'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    if '-' in args.seeds and ',' not in args.seeds:
        parts = args.seeds.split('-')
        seeds = list(range(int(parts[0]), int(parts[1]) + 1))
    elif ',' in args.seeds:
        seeds = [int(s.strip()) for s in args.seeds.split(',')]
    else:
        seeds = [int(args.seeds)]

    existing_params = load_params(args.params)

    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    from core.manue.manue_ai import ManueAI
    manue_ai = ManueAI(base_dir)

    workers = args.parallel
    if workers == 0:
        workers = min(multiprocessing.cpu_count(), len(seeds))

    print(f"Manue vs Existing AI Battle")
    print(f"Seeds: {len(seeds)} ({seeds[0]}-{seeds[-1]})")
    print(f"Game: {args.game_type} / Room: {args.room}")
    print(f"Workers: {workers}")
    print(f"Mode: {'quick (seat 0 only)' if args.quick else 'full (all seats)'}")
    print()

    start_time = time.time()
    all_results = []

    if workers <= 1:
        for idx, seed in enumerate(seeds):
            r = _run_seed_manue_vs_ai(seed, manue_ai, existing_params, args.room, args.game_type, args.quick)
            all_results.append(r)
            if args.quick:
                t = r['test_pts'][0]
                print(f"Seed {seed:4d}: pt={t:+.0f} ({idx+1}/{len(seeds)})")
            else:
                diffs = [r['test_pts'][s] for s in range(4)]
                print(f"Seed {seed:4d}: pt={[f'{p:+.0f}' for p in diffs]} ({idx+1}/{len(seeds)})")
    else:
        worker = partial(_run_seed_manue_vs_ai,
                         manue_ai=manue_ai, existing_params=existing_params,
                         room=args.room, game_type=args.game_type, quick=args.quick)

        with ProcessPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(worker, seed): seed for seed in seeds}
            done_count = 0
            for future in as_completed(futures):
                seed = futures[future]
                try:
                    r = future.result()
                    all_results.append(r)
                    done_count += 1
                    if args.verbose:
                        if args.quick:
                            t = r['test_pts'][0]
                            print(f"Seed {seed:4d}: pt={t:+.0f} ({done_count}/{len(seeds)})")
                        else:
                            diffs = [r['test_pts'][s] for s in range(4)]
                            print(f"Seed {seed:4d}: pt={[f'{p:+.0f}' for p in diffs]} ({done_count}/{len(seeds)})")
                except Exception as e:
                    print(f"Seed {seed} failed: {e}")
                    done_count += 1

    elapsed = time.time() - start_time

    all_test_pts = [p for r in all_results for p in r['test_pts']]
    all_test_placements = []
    all_stats = []
    for r in all_results:
        for seat in range(len(r['test_pts'])):
            all_test_placements.append(r['test_placements'][seat][seat])
            all_stats.append(r['test_player_stats'][seat])

    avg_pt = sum(all_test_pts) / len(all_test_pts) if all_test_pts else 0
    total_pt = sum(all_test_pts)
    avg_placement = sum(all_test_placements) / len(all_test_placements) + 1 if all_test_placements else 0

    placement_counts = [0, 0, 0, 0]
    for pl in all_test_placements:
        placement_counts[pl] += 1

    n = len(all_stats) if all_stats else 1
    total_wins = sum(s.wins for s in all_stats)
    total_kyoku = sum(s.num_kyoku for s in all_stats)
    total_dealt = sum(s.dealt_in for s in all_stats)
    total_tsumo_wins = sum(s.tsumo_wins for s in all_stats)
    total_ron_wins = sum(s.ron_wins for s in all_stats)
    total_reach = sum(s.reach_declarations for s in all_stats)
    total_reach_wins = sum(s.reach_wins for s in all_stats)
    total_open_wins = sum(s.open_wins for s in all_stats)
    total_damaten_wins = sum(s.damaten_wins for s in all_stats)
    total_kyoku_with_meld = sum(s.kyoku_with_meld for s in all_stats)
    total_han = sum(s.total_han for s in all_stats)
    total_win_points = sum(s.total_win_points for s in all_stats)
    win_turns = [t for s in all_stats for t in s.win_turns]
    max_renchan = max(s.max_renchan for s in all_stats) if all_stats else 0
    busts = sum(1 for s in all_stats if s.busted)

    avg_win_points = total_win_points / total_wins if total_wins else 0
    avg_win_turn = sum(win_turns) / len(win_turns) if win_turns else 0
    win_rate = total_wins / total_kyoku * 100 if total_kyoku else 0
    dealt_rate = total_dealt / total_kyoku * 100 if total_kyoku else 0
    tsumo_rate = total_tsumo_wins / total_wins * 100 if total_wins else 0
    reach_rate = total_reach_wins / total_wins * 100 if total_wins else 0
    meld_rate = total_open_wins / total_wins * 100 if total_wins else 0
    meld_kyoku_rate = total_kyoku_with_meld / total_kyoku * 100 if total_kyoku else 0
    bust_rate = busts / n * 100 if n else 0

    yaku_counts = {}
    for s in all_stats:
        for y, c in s.yaku_counts.items():
            yaku_counts[y] = yaku_counts.get(y, 0) + c

    num_test_games = len(seeds) if args.quick else len(seeds) * 4

    print()
    print("=== Battle Results ===")
    print(f"Seeds: {len(seeds)} ({seeds[0]}-{seeds[-1]})")
    print(f"Game: {args.game_type} / Room: {args.room}")
    print(f"Test games: {num_test_games}")
    print(f"Time: {elapsed:.1f}s")
    print()
    print(f"Manue AI:")
    print(f"  Avg PT: {avg_pt:+.2f}/game  (Total: {total_pt:+.0f})")
    print(f"  Avg Placement: {avg_placement:.2f}")
    print()
    print(f"  {'':<18} {'Value':>10}")
    print(f"  {'-'*30}")
    print(f"  {'Games':<18} {n:>5}戦{'':>3}")
    print(f"  {'Total Kyoku':<18} {total_kyoku:>5}局{'':>3}")
    print(f"  {'Win Rate':<18} {win_rate:>9.2f}%")
    print(f"  {'Deal-in Rate':<18} {dealt_rate:>9.2f}%")
    print(f"  {'Avg Placement':<18} {avg_placement:>9.3f}")
    for p in range(4):
        label = f'  {p+1}位'
        print(f"  {label:<18} {placement_counts[p]:>3}回 ({placement_counts[p]/num_test_games*100 if num_test_games else 0:>5.1f}%)")
    print(f"  {'Avg Win Points':<18} {avg_win_points:>9.0f}")
    print(f"  {'Avg Win Turn':<18} {avg_win_turn:>9.2f}")
    print(f"  {'Tsumo Rate':<18} {tsumo_rate:>9.2f}%")
    print(f"  {'Reach Rate':<18} {reach_rate:>9.2f}%")
    print(f"  {'Meld Win Rate':<18} {meld_rate:>9.2f}%")
    print(f"  {'Meld Kyoku Rate':<18} {meld_kyoku_rate:>9.2f}%")
    print(f"  {'Bust Rate':<18} {bust_rate:>9.2f}%")
    print(f"  {'Max Renchan':<18} {max_renchan:>5}局{'':>3}")
    print()
    print(f"  Yaku counts:")
    for y in sorted(yaku_counts.keys()):
        print(f"    {y:<18} {yaku_counts[y]:>4}回")


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
