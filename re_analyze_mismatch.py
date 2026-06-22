"""
Re-analyze betari mismatch with new strategy logic.
"""
import pickle
import sys
import os
import json
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')

# Reload params (with new ones)
with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load betari data
with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)

print(f'ベタオリ局面: {len(data)}件')
print()

# === AI judgment with NEW logic ===
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, is_honor
from core.strategy_manager import ShantenCalculator
import sqlite3
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

# Re-process logs to get full state, but this time compute strategy mode
print('Loading logs for state reconstruction...')
with open('tools/_log_ids_10000.txt') as f:
    log_ids = [line.strip() for line in f if line.strip()]

db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
BATCH = 2000
all_log_blobs = {}
for batch_start in range(0, len(log_ids), BATCH):
    batch_ids = log_ids[batch_start:batch_start+BATCH]
    placeholders = ','.join(['?'] * len(batch_ids))
    cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', batch_ids)
    rows = cur.fetchall()
    for lid, blob in rows:
        all_log_blobs[lid] = blob
db.close()
print(f'  {len(all_log_blobs)} logs loaded')

# Group data by log_id
data_by_log = defaultdict(list)
for d in data:
    data_by_log[d['log_id']].append(d)

# Process each log and compute AI mode at each betari moment
print('Computing AI strategy mode for each betari situation...')
ai_push_count = 0
ai_fold_count = 0
match_count = 0
mismatch_count = 0
mismatch_overpush = 0
mismatch_overfold = 0
new_data = []  # updated data with AI mode

processed = 0
for log_id, blob in all_log_blobs.items():
    if log_id not in data_by_log:
        continue
    processed += 1
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

            # Check if this is a betari moment to evaluate
            kyoku = states[seat].chang * 4 + states[seat].ju + 1
            turn = (states[seat].tsumo_count - 1) // 4 + 1
            key = (kyoku, turn, seat, tile)
            if key in betari_to_check:
                bd = betari_to_check[key]
                # Compute AI strategy mode
                try:
                    from core.strategy_manager import StrategyManager
                    sm = StrategyManager(states[seat], params=params)
                    mode = sm.get_strategy_mode()
                    if mode in ('全力攻撃', '押し気味', '危険度勝負', '積極駒組み'):
                        ai_push = True
                        ai_fold = False
                    elif mode in ('完全撤退', '撤退準備', 'スリム化'):
                        ai_push = False
                        ai_fold = True
                    else:
                        ai_push = None
                        ai_fold = None
                    human_push = bd['defense_score'] > 0

                    if ai_push is not None:
                        if ai_push == human_push:
                            match_count += 1
                        else:
                            mismatch_count += 1
                            if ai_push and not human_push:
                                mismatch_overpush += 1
                            else:
                                mismatch_overfold += 1
                        new_data.append({**bd, 'ai_mode': mode, 'ai_push': ai_push, 'human_push': human_push, 'match': ai_push == human_push})
                except Exception as e:
                    pass

            for s in range(4):
                if s == seat:
                    states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4: awaiting[seat] = False
            continue

        if cls == 'RecordChiPengGang':
            call_type = d.get('type')
            call_seat = d.get('seat')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tileStates', [])
            if 0 <= call_seat < 4:
                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls in ('RecordHule', 'RecordNoTile'):
            for s in range(4):
                awaiting[s] = False
            continue

# Save
with open('betadata_with_ai.pkl', 'wb') as f:
    pickle.dump(new_data, f)

print(f'\n=== 結果 ===')
print(f'分析対象: {len(new_data)}件')
print(f'一致: {match_count} ({match_count/(match_count+mismatch_count)*100:.1f}%)')
print(f'不一致: {mismatch_count} ({mismatch_count/(match_count+mismatch_count)*100:.1f}%)')
print()
print(f'過剰押し(AI押す/人間オリる): {mismatch_overpush}件')
print(f'過剰オリ(AIオリる/人間押す): {mismatch_overfold}件')
print()

# 混同行列
print('=== 混同行列 ===')
ai_push_match = sum(1 for d in new_data if d['ai_push'] and d['human_push'])
ai_push_fold = sum(1 for d in new_data if d['ai_push'] and not d['human_push'])
ai_fold_match = sum(1 for d in new_data if not d['ai_push'] and not d['human_push'])
ai_fold_push = sum(1 for d in new_data if not d['ai_push'] and d['human_push'])
print(f'                 人間押す   人間オリる')
print(f'  AI押す      : {ai_push_match:6}    {ai_push_fold:6}')
print(f'  AIオリる    : {ai_fold_push:6}    {ai_fold_match:6}')
