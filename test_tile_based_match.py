"""
@title 牌選択レベルでの押す/オリる評価
@description
    各ベタオリ局面で、AIの選択した牌と人間の選択を比較する。
    人間データ:
    - 字牌切り = 押し (人間)
    - 中張切り = オリ (人間)
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean
import os

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile, is_honor
from core.strategy_manager import ShantenCalculator, StrategyManager
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Replay each betari moment, run AI evaluator on it
print('Loading betari data...')
with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)

# Group by log_id
data_by_log = defaultdict(list)
for d in data:
    data_by_log[d['log_id']].append(d)

# Load only 100 logs first
print('Loading logs (100)...')
with open('tools/_log_ids_10000.txt') as f:
    all_log_ids = [l.strip() for l in f if l.strip()]
log_ids = all_log_ids[:100]
# Find which log_ids have betari data
needed_log_ids = list(set([d['log_id'] for d in data]))[:100]
log_ids = list(set(log_ids + needed_log_ids))[:30]
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

# Track AI choice vs human choice
match = 0
mismatch = 0
ai_push_choice = 0  # AI picked 字牌/端牌 (interpreted as 押し)
ai_fold_choice = 0
human_push = 0
human_fold = 0
correct_push = 0  # AI chose push and human also push
correct_fold = 0

processed = 0
n_betari_found = 0
import time
t0 = time.time()
print(f'  data_by_log: {len(data_by_log)}, all_log_blobs: {len(all_log_blobs)}')
for log_id, blob in all_log_blobs.items():
    if log_id not in data_by_log:
        continue
    processed += 1
    if processed % 100 == 0:
        print(f'  処理: {processed}/{len(data_by_log)} ({time.time()-t0:.0f}s, {n_betari_found}betari)', flush=True)
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

    n_actions = 0
    for a in actions:
        n_actions += 1
        if n_actions % 200 == 0:
            print(f'    {log_id[-8:]} actions={n_actions} betari_found={n_betari_found}', flush=True)
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

            # Check if this is a betari moment
            kyoku = states[seat].chang * 4 + states[seat].ju + 1
            turn = (states[seat].tsumo_count - 1) // 4 + 1
            key = (kyoku, turn, seat, tile)
            if key in betari_to_check:
                bd = betari_to_check[key]
                # AI evaluation
                try:
                    ev = Evaluator(states[seat], params=params)
                    hand = list(states[seat].my_hand)
                    best = ev.best_discard(hand)
                    human_push = bd['defense_score'] > 0
                    if best is not None:
                        # AI's chosen tile's classification
                        ai_is_honor = is_honor(tile_to_id(best))
                        # 人間データ: 字牌・端牌 = 押し, 中張 = オリ
                        ai_is_push_tile = ai_is_honor or best[0] in ('1', '9')
                        # Track AI's mode for diagnostics
                        ai_mode = ev.strategy.get_strategy_mode()
                        ai_tile_class = '字牌' if ai_is_honor else ('端牌' if best[0] in ('1', '9') else '中張')
                        # Record
                        from collections import Counter as Cnt
                        global _counts, _no_choice, _errors
                        try:
                            _counts
                        except NameError:
                            _counts = Cnt()
                            _no_choice = 0
                            _errors = []
                        _counts[(ai_mode, ai_tile_class, human_push)] += 1
                        ai_push = ai_is_push_tile
                        # Compare tile type (字牌/端牌/中張) not push decision
                        human_tile = bd['discard_tile']
                        human_is_honor = is_honor(tile_to_id(human_tile))
                        human_is_push_tile = human_is_honor or human_tile[0] in ('1', '9')
                        # Match if both human and AI cut same tile type
                        if ai_is_push_tile == human_is_push_tile:
                            match += 1
                        else:
                            mismatch += 1
                    else:
                        try:
                            _no_choice
                        except NameError:
                            from collections import Counter as Cnt
                            _no_choice = 0
                        _no_choice += 1
                except Exception as e:
                    try:
                        _errors
                    except NameError:
                        _errors = []
                    _errors.append(str(e))
                n_betari_found += 1

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

total = match + mismatch
print(f'\n=== 牌選択レベルでの人間一致率 ===')
print(f'総局面: {total}件')
print(f'一致: {match} ({match/total*100:.1f}%)')
print(f'不一致: {mismatch} ({mismatch/total*100:.1f}%)')
print(f'  AI字牌切り+人間押す: {correct_push}件')
print(f'  AI中張切り+人間オリる: {correct_fold}件')
print(f'  過剰押し(AI押し/人間オリ): {mismatch - 0}件')

# Save result
print(f'\n一致率: {match/total*100:.2f}%')

# Mode × tile class × human push breakdown
print(f'\n=== AI選択(mode × tile class × human) ===')
try:
    _counts
    for (mode, tile_class, human), n in sorted(_counts.items()):
        if n > 5:
            print(f'  {mode:10} × {tile_class:4} × human_push={human}: {n}件')
except NameError:
    pass

try:
    print(f'\n_no_choice: {_no_choice}')
except NameError:
    pass

try:
    print(f'\n_errors: {len(_errors)}')
    for e in _errors[:5]:
        print(f'  {e}')
except NameError:
    pass
