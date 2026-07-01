# -*- coding: utf-8 -*-
"""Incremental 2v2 test with file output"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.ai_player import AIPlayer
from core.evaluator import Evaluator
from core.evaluator_v2 import EvaluatorV2
from tools.mahjong_simulator import MahjongSimulator

params = {}
PT_TABLE = {0: 95, 1: 45, 2: -5, 3: -125}
BASE_SCORE = 25000

out_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'tmp_10seed_result.txt')
t0 = time.time()

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
    plc = result.placement_of(v2_seat)
    pt = PT_TABLE.get(plc, 0) + (result.final_scores[v2_seat] - BASE_SCORE) // 1000
    return {
        'wins': st.wins, 'tsumo': st.tsumo_wins, 'ron': st.ron_wins,
        'deal': st.dealt_in, 'reach': st.reach_declarations, 'han': st.total_han,
        'nkyoku': result.num_kyoku, 'placement': plc, 'score': result.final_scores[v2_seat], 'pt': pt,
    }

results = []
for seat in [0, 1]:
    for i in range(10):
        g = i * 2 + seat
        r = run_game(i, seat)
        results.append(r)
        elapsed = time.time() - t0
        with open(out_path, 'w', encoding='utf-8') as f:
            n = len(results)
            w = sum(rr['wins'] for rr in results)
            d = sum(rr['deal'] for rr in results)
            rc = sum(rr['reach'] for rr in results)
            h = sum(rr['han'] for rr in results)
            hk = sum(rr['nkyoku'] for rr in results)
            ap = sum(rr['placement'] for rr in results) / n
            asc = sum(rr['score'] for rr in results) / n
            apt = sum(rr['pt'] for rr in results) / n
            f.write(f"completed: {n}/20 games ({g+1} done)\n")
            f.write(f"hands: {hk}  seconds: {elapsed:.0f}\n")
            f.write(f"avgPlace: {ap:.2f}  avgScore: {asc:.0f}  avgPT: {apt:+.1f}\n")
            f.write(f"total: wins={w} deal={d} reach={rc} han={h}\n")
            f.write(f"perGame: win={w/n*100:.1f}% deal={d/n*100:.1f}% reach={rc/n*100:.1f}%\n")
            f.write(f"perHand: win={w/hk*100:.1f}% deal={d/hk*100:.1f}% reach={rc/hk*100:.1f}%\n")
            f.write(f"avgHan={h/max(w,1):.1f}\n")
        print(f"  game {g+1}/20: seed={i} seat={seat} done ({elapsed:.0f}s)")

# Final output
with open(out_path, 'w', encoding='utf-8') as f:
    n = len(results)
    w = sum(rr['wins'] for rr in results)
    d = sum(rr['deal'] for rr in results)
    rc = sum(rr['reach'] for rr in results)
    h = sum(rr['han'] for rr in results)
    hk = sum(rr['nkyoku'] for rr in results)
    ap = sum(rr['placement'] for rr in results) / n
    asc = sum(rr['score'] for rr in results) / n
    apt = sum(rr['pt'] for rr in results) / n
    lines = [
        "=== 10 seeds x 2 seats (2v2) result ===",
        f"player-games: {n}",
        f"total hands: {hk}",
        f"avg placement: {ap:.2f}",
        f"avg score: {asc:.0f}",
        f"avg PT: {apt:+.1f}",
        f"total wins: {w} (tsumo={sum(rr['tsumo'] for rr in results)}, ron={sum(rr['ron'] for rr in results)})",
        f"total deal-in: {d}",
        f"total reach: {rc}",
        f"total han (sum): {h}",
        f"---- per game (total/player-games) ----",
        f"win rate: {w/n*100:.1f}%",
        f"deal-in rate: {d/n*100:.1f}%",
        f"reach rate: {rc/n*100:.1f}%",
        f"---- per hand ----",
        f"win rate: {w/hk*100:.1f}%",
        f"deal-in rate: {d/hk*100:.1f}%",
        f"reach rate: {rc/hk*100:.1f}%",
        f"avg han (on win): {h/max(w,1):.1f}",
        f"elapsed: {time.time()-t0:.0f}s",
    ]
    f.write('\n'.join(lines))
    print('\n'.join(lines))
