"""
Check v_defense values for honor vs middle tiles in betari
"""
import pickle
import json
import sys
from collections import defaultdict

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, is_honor
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

with open('betadata_full.pkl', 'rb') as f:
    betari_data = pickle.load(f)

import random
random.seed(42)
test_data = random.sample(betari_data, 100)

data_by_log = defaultdict(list)
for d in test_data:
    data_by_log[d['log_id']].append(d)

needed_log_ids = list(set([d['log_id'] for d in test_data]))
db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
ph = ','.join(['?']*len(needed_log_ids))
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({ph})', needed_log_ids)
rows = cur.fetchall()
db.close()
all_log_blobs = {lid: blob for lid, blob in rows}

# 過剰オリ ケース (AIオリ+人間押) を抽出
overfold_examples = []
for log_id, blob in all_log_blobs.items():
    if log_id not in data_by_log:
        continue
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except:
        continue
    if n_rounds == 0: continue
    actions = json_dict.get('detail_records', {}).get('actions', [])
    if not actions: continue

    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    betari_to_check = {(d['kyoku'], d['turn'], d['seat'], d['discard_tile']): d for d in data_by_log[log_id]}

    for a in actions:
        if a.get('type') != 1: continue
        r = a.get('result', {})
        cls = r.get('class_name', '')
        d = r.get('data', {})

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(
                    d.get('chang', 0), d.get('ju', 0), d.get('ben', 0), d.get('liqibang', 0),
                    d.get(k, []), d.get('scores', [25000] * 4), d.get('leftTileCount', 70),
                    d.get('doras', [])
                )
                states[s].chang = d.get('chang', 0)
                states[s].ju = d.get('ju', 0)
            oya = d.get('oya', 0)
            states[oya].dealer_seat = oya
            for s in range(4):
                if s != oya: states[s].dealer_seat = oya
            awaiting = [True] * 4
            continue

        if cls == 'RecordDealTile':
            seat = d.get('seat')
            tile = d.get('tile')
            if seat is None or tile is None: continue
            for s in range(4):
                if s == seat:
                    states[s].on_self_draw(tile)
                else:
                    states[s].on_opponent_draw(seat)
            if 0 <= seat < 4: awaiting[seat] = True
            continue

        if cls == 'RecordDiscardTile':
            seat = d.get('seat')
            tile = d.get('tile')
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if seat is None or seat < 0 or seat >= 4: continue

            kyoku = states[seat].chang * 4 + states[seat].ju + 1
            turn = (states[seat].tsumo_count - 1) // 4 + 1
            key = (kyoku, turn, seat, tile)
            if key in betari_to_check:
                bd = betari_to_check[key]
                if bd['defense_score'] > 0:  # 人間は押す
                    # 過剰オリ候補
                    try:
                        ev = Evaluator(states[seat], params=params)
                        hand = list(states[seat].my_hand)
                        scores = {}
                        for t in dict.fromkeys(hand):
                            scores[t] = ev.evaluate_tile(t)
                        best = ev.best_discard(hand)
                        if best is not None and is_honor(tile_to_id(best)):
                            ai_push = True
                        else:
                            ai_push = False
                        if not ai_push:  # 過剰オリ
                            overfold_examples.append({
                                'shanten': bd['shanten'],
                                'turn': bd['turn'],
                                'best': best,
                                'best_score': scores.get(best, 0),
                                'scores': scores,
                                'human_tile': bd['discard_tile'],
                                'human_score': scores.get(bd['discard_tile'], 0),
                            })
                    except Exception:
                        pass

            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4: awaiting[seat] = False
            continue

        if cls == 'RecordChiPengGang':
            call_type = d.get('type')
            call_seat = d.get('seat')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tile_states', [])
            if 0 <= call_seat < 4:
                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls in ('RecordHule', 'RecordNoTile'):
            for s in range(4):
                awaiting[s] = False
            continue

print(f'過剰オリケース: {len(overfold_examples)}件')
print()

# 過剰オリの最初の5件を表示
for i, ex in enumerate(overfold_examples[:5]):
    print(f'\n=== 過剰オリ {i+1} ===')
    print(f'  シャンテン: {ex["shanten"]}, 巡目: {ex["turn"]}')
    print(f'  AI best: {ex["best"]} (score: {ex["best_score"]:.0f})')
    print(f'  人間 cut: {ex["human_tile"]} (score: {ex["human_score"]:.0f})')
    sorted_scores = sorted(ex['scores'].items(), key=lambda x: -x[1])[:5]
    print(f'  Top 5 scores:')
    for t, s in sorted_scores:
        is_h = '*' if is_honor(tile_to_id(t)) else ' '
        print(f'    {is_h} {t}: {s:.0f}')
