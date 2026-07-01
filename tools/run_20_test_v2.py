# -*- coding: utf-8 -*-
"""Run 20-seed 2v2 test with proper per-hand stats"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.ai_player import AIPlayer
from core.evaluator import Evaluator
from core.evaluator_v2 import EvaluatorV2
from tools.mahjong_simulator import MahjongSimulator

params = None  # defaults

def run_game(seed, v2_seat, game_type='tonpu'):
    players = []
    for seat in range(4):
        if seat == v2_seat:
            players.append(AIPlayer('v2', EvaluatorV2, params))
        else:
            players.append(AIPlayer('v1', Evaluator, params))
    sim = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type)
    result = sim.run_game()
    st = result.player_stats[v2_seat]
    pt_table = {0:95, 1:45, 2:-5, 3:-125}
    plc = result.placement_of(v2_seat)
    pt = pt_table.get(plc, 0) + (result.final_scores[v2_seat] - 25000) // 1000
    return {
        'w': st.wins, 't': st.tsumo_wins, 'r': st.ron_wins,
        'd': st.dealt_in, 'rc': st.reach_declarations, 'h': st.total_han,
        'nk': result.num_kyoku, 'pl': plc, 'sc': result.final_scores[v2_seat], 'pt': pt,
    }

for seeds in [8, 20]:
    results = []
    for seat in [0, 1]:
        for i in range(seeds):
            results.append(run_game(i, seat))
    n = len(results)
    w = sum(r['w'] for r in results)
    d = sum(r['d'] for r in results)
    rc = sum(r['rc'] for r in results)
    h = sum(r['h'] for r in results)
    hk = sum(r['nk'] for r in results)
    ap = sum(r['pl'] for r in results) / n
    asc = sum(r['sc'] for r in results) / n
    apt = sum(r['pt'] for r in results) / n
    print(f"=== {seeds} seeds x 2 seats = {n} player-games ===")
    print(f"  total hands: {hk}")
    print(f"  avg placement: {ap:.2f}  score: {asc:.0f}  PT: {apt:+.1f}")
    print(f"  wins: {w}  deal-in: {d}  reach: {rc}")
    print(f"  --- per hand ---")
    print(f"  win rate: {w/hk*100:.1f}%")
    print(f"  deal-in rate: {d/hk*100:.1f}%")
    print(f"  reach rate: {rc/hk*100:.1f}%")
    print(f"  avg han (on win): {h/max(w,1):.1f}")
    print()
