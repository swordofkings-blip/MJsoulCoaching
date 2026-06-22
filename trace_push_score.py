"""
Test: trace push_score distribution in betari data
"""
import pickle
import json
import sys
from collections import Counter

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

# Sample 100 from each category
import random
random.seed(42)
test_data = random.sample(betari_data, 200)

# Group by log_id
from collections import defaultdict
data_by_log = defaultdict(list)
for d in test_data:
    data_by_log[d['log_id']].append(d)

# Load needed logs
needed_log_ids = list(set([d['log_id'] for d in test_data]))
db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
ph = ','.join(['?']*len(needed_log_ids))
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({ph})', needed_log_ids)
rows = cur.fetchall()
db.close()
all_log_blobs = {lid: blob for lid, blob in rows}

# Process
results = []
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
                try:
                    ev = Evaluator(states[seat], params=params)
                    push_score = ev.strategy.compute_push_score()
                    mode = ev.strategy.get_strategy_mode()
                    hand = list(states[seat].my_hand)
                    best = ev.best_discard(hand)
                    human_push = bd['defense_score'] > 0
                    is_honor_tile = best and is_honor(tile_to_id(best))
                    is_push_tile = best and (is_honor_tile or best[0] in ('1', '9'))

                    results.append({
                        'shanten': bd['shanten'],
                        'turn': bd['turn'],
                        'reach_n': bd['reach_n'],
                        'rank': bd['my_rank'],
                        'push_score': push_score,
                        'mode': mode,
                        'best': best,
                        'is_honor': is_honor_tile,
                        'is_push_tile': is_push_tile,
                        'human_push': human_push,
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

# 分析
print(f'総分析数: {len(results)}件')
print()

# push_score分布
print('=== push_score 分布 ===')
ps_counter = Counter()
for r in results:
    bucket = int(r['push_score'] * 10) / 10
    ps_counter[bucket] += 1
for b in sorted(ps_counter.keys()):
    print(f'  {b:.1f}: {ps_counter[b]}件')

# 過剰オリ ケース (AIオリ+人間押す)
overfold = [r for r in results if not r['is_push_tile'] and r['human_push']]
print()
print(f'過剰オリ (AIオリ+人間押): {len(overfold)}件')
print('---過剰オリの push_score 分布---')
ps_counter = Counter()
for r in overfold:
    bucket = int(r['push_score'] * 10) / 10
    ps_counter[bucket] += 1
for b in sorted(ps_counter.keys()):
    print(f'  {b:.1f}: {ps_counter[b]}件')

# 過剰オリの AI が切った牌
tile_counter = Counter()
for r in overfold:
    if r['best']:
        tile_counter[r['best']] += 1
print()
print('---過剰オリでAIが切った牌トップ10---')
for t, n in tile_counter.most_common(10):
    print(f'  {t}: {n}件')
