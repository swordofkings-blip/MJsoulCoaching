# -*- coding: utf-8 -*-
"""Run 20-seed test and save results to tmp_20seed.txt"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.v1_vs_v2_battle import run_one_game, load_params

params = load_params('config/config_parameters.json')
results = []
for seat in [0, 1]:
    for i in range(20):
        r = run_one_game(i, seat, params, 'tonpu')
        results.append(r)

n = len(results)  # 40
w = sum(r['v2_wins'] for r in results)
d = sum(r['v2_dealt_in'] for r in results)
rch = sum(r['v2_reach_declarations'] for r in results)
h = sum(r['v2_total_han'] for r in results)
ts = sum(r['v2_tsumo_wins'] for r in results)
ro = sum(r['v2_ron_wins'] for r in results)
hk = sum(r['total_kyoku'] for r in results)
ap = sum(r['v2_placement'] for r in results) / n
asc = sum(r['v2_score'] for r in results) / n
apt = sum(r['v2_pt'] for r in results) / n

avg_han = h / max(w, 1)

lines = [
    "=== 20 seeds 2v2 result ===",
    f"player-games: {n}",
    f"total hands: {hk}",
    f"avg placement: {ap:.2f}",
    f"avg score: {asc:.0f}",
    f"avg PT: {apt:+.1f}",
    f"total wins: {w} (tsumo={ts}, ron={ro})",
    f"total deal-in: {d}",
    f"total reach: {rch}",
    f"total han (sum): {h}",
    f"---- per game (rate) ----",
    f"win rate: {w/n*100:.1f}%",
    f"deal-in rate: {d/n*100:.1f}%",
    f"reach rate: {rch/n*100:.1f}%",
    f"---- per hand ----",
    f"win rate (per hand): {w/hk*100:.1f}%",
    f"deal-in rate (per hand): {d/hk*100:.1f}%",
    f"reach rate (per hand): {rch/hk*100:.1f}%",
    f"avg han (on win): {avg_han:.1f}",
]

with open('tmp_20seed.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))

print('\n'.join(lines))
