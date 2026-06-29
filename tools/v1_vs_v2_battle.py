# -*- coding: utf-8 -*-
"""
@title ver.1 vs ver.2 対局テスト
@description 1 ver.2 + 3 ver.1 で半荘を回し、ver.2 の平均順位・スコアを測定。
              ver.2 が平均より上なら改善、下なら要修正。
              既存の MahjongSimulator + AIPlayer を使用。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from typing import List

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.ai_player import AIPlayer
from core.evaluator import Evaluator
from core.evaluator_v2 import EvaluatorV2
from tools.mahjong_simulator import MahjongSimulator, GameResult, PlayerGameStats


PT_TABLE = {0: 95, 1: 45, 2: -5, 3: -125}
BASE_SCORE = 25000


def load_params(path: str) -> dict:
    if not path:
        return {}
    _base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    _paths = [path, os.path.join(_base, 'config', path), os.path.join(_base, path)]
    for _p in _paths:
        if os.path.exists(_p):
            with open(_p, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
    return {}


def make_v1_ai(params: dict) -> AIPlayer:
    return AIPlayer("v1", Evaluator, params)


def make_v2_ai(params: dict) -> AIPlayer:
    return AIPlayer("v2", EvaluatorV2, params)


def run_one_game(seed: int, v2_seat: int, params: dict, game_type: str = 'tonpu') -> dict:
    """v2_seat に ver.2 を配置、それ以外 ver.1"""
    players = []
    for seat in range(4):
        if seat == v2_seat:
            players.append(make_v2_ai(params))
        else:
            players.append(make_v1_ai(params))
    sim = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type)
    result = sim.run_game()

    v2_placement = result.placement_of(v2_seat)
    v2_score = result.final_scores[v2_seat]
    v2_pt = PT_TABLE.get(v2_placement, 0) + (v2_score - BASE_SCORE) // 1000
    v2_stats = result.player_stats[v2_seat]

    return {
        'seed': seed,
        'v2_seat': v2_seat,
        'v2_placement': v2_placement,
        'v2_score': v2_score,
        'v2_pt': v2_pt,
        'v2_wins': v2_stats.wins,
        'v2_tsumo_wins': v2_stats.tsumo_wins,
        'v2_ron_wins': v2_stats.ron_wins,
        'v2_dealt_in': v2_stats.dealt_in,
        'v2_reach_declarations': v2_stats.reach_declarations,
        'v2_total_han': v2_stats.total_han,
        'final_scores': result.final_scores,
    }


def main(seeds: int, v2_seats: str, params_path: str, game_type: str):
    params = load_params(params_path)
    seat_list = [int(s) for s in v2_seats.split(',')]
    if any(s < 0 or s > 3 for s in seat_list):
        raise ValueError(f"v2_seats must be 0-3, got {v2_seats}")

    print(f"=== ver.1 vs ver.2 対局テスト ===")
    print(f"  seeds: {seeds}")
    print(f"  v2 配置: {seat_list}")
    print(f"  ゲーム形式: {game_type}")
    print(f"  パラメータ: {params_path or '(default)'}")
    print()

    all_results = []
    t0 = time.time()
    for i in range(seeds):
        for v2_seat in seat_list:
            try:
                r = run_one_game(seed=i, v2_seat=v2_seat, params=params, game_type=game_type)
                all_results.append(r)
                if len(all_results) % 5 == 0:
                    elapsed = time.time() - t0
                    print(f"  ... {len(all_results)} 局完了 ({elapsed:.1f}秒)")
            except Exception as e:
                print(f"  ! seed={i} seat={v2_seat} エラー: {e}")
                import traceback
                traceback.print_exc()

    if not all_results:
        print("結果なし")
        return

    n = len(all_results)
    avg_placement = sum(r['v2_placement'] for r in all_results) / n
    avg_score = sum(r['v2_score'] for r in all_results) / n
    avg_pt = sum(r['v2_pt'] for r in all_results) / n
    total_wins = sum(r['v2_wins'] for r in all_results)
    total_tsumo = sum(r['v2_tsumo_wins'] for r in all_results)
    total_ron = sum(r['v2_ron_wins'] for r in all_results)
    total_dealt_in = sum(r['v2_dealt_in'] for r in all_results)
    total_reach = sum(r['v2_reach_declarations'] for r in all_results)
    total_han = sum(r['v2_total_han'] for r in all_results)
    win_rate = total_wins / n * 100
    deal_in_rate = total_dealt_in / n * 100
    reach_rate = total_reach / n * 100
    avg_han = total_han / max(total_wins, 1)

    print()
    print("=== 結果サマリ ===")
    print(f"  局数: {n}")
    print(f"  ver.2 平均順位: {avg_placement:.2f} (1.0 が最高、3.0 が最低)")
    print(f"  ver.2 平均スコア: {avg_score:.0f} (25000 がベース)")
    print(f"  ver.2 平均 PT: {avg_pt:+.1f}")
    print(f"  和了率: {win_rate:.1f}% (玉座の間基準: 20-21%)")
    print(f"  放銃率: {deal_in_rate:.1f}% (玉座の間基準: 12-14%)")
    print(f"  立直率: {reach_rate:.1f}% (玉座の間基準: 18-19%)")
    print(f"  ツモ和了: {total_tsumo}, ロン和了: {total_ron}")
    print(f"  平均翻数 (和了時): {avg_han:.1f}")
    print()
    print(f"  経過時間: {time.time() - t0:.1f}秒")
    print(f"  局あたり: {(time.time() - t0)/n:.2f}秒")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--seeds", type=int, default=20, help="シード数 (各席に配置)")
    p.add_argument("--v2-seats", type=str, default="0,1,2,3", help="ver.2 を配置する席 (カンマ区切り)")
    p.add_argument("--params", type=str, default="config/config_parameters.json")
    p.add_argument("--game-type", type=str, default="tonpu", choices=["tonpu", "hanchan"])
    args = p.parse_args()
    main(args.seeds, args.v2_seats, args.params, args.game_type)
