"""
@title 改善版: ファジィ + 牌選択ベースの押す/オリる評価
@description
    各ベタオリ局面で:
    1. AI mode を fuzzy で取得
    2. AI の選ぶ牌を取得
    3. 牌タイプ判定 (字牌/端牌/中張)
    4. 人間判断と比較

    人間判断: def>0 = 押し (字牌/端牌切る)
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
import os
import time

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile, is_honor
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

print('Loading betari data...')
with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)
print(f'  {len(data)} betari situations')

# Sample for speed
import random
random.seed(42)
data = random.sample(data, min(3000, len(data)))
print(f'  Sampled to {len(data)} betari situations')

# Group by log_id
data_by_log = defaultdict(list)
for d in data:
    data_by_log[d['log_id']].append(d)

# Load needed logs
needed_log_ids = list(set([d['log_id'] for d in data]))
print(f'Loading {len(needed_log_ids)} logs...')
db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
all_log_blobs = {}
BATCH = 2000
for batch_start in range(0, len(needed_log_ids), BATCH):
    batch_ids = needed_log_ids[batch_start:batch_start+BATCH]
    placeholders = ','.join(['?'] * len(batch_ids))
    cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', batch_ids)
    rows = cur.fetchall()
    for lid, blob in rows:
        all_log_blobs[lid] = blob
db.close()

# Track results
mode_match = 0
mode_mismatch = 0
tile_match = 0
tile_mismatch = 0
tile_type_match = 0
n_processed = 0
n_betari_found = 0
t0 = time.time()

# Mode-based: AI mode 押す系(全力攻撃/押し気味/etc) = push, オリ系(撤退準備/完全撤退/etc) = fold
def mode_to_push_fold(mode):
    if mode in ('全力攻撃', '押し気味', '危険度勝負', '積極駒組み', '回し打ち'):
        return 'push'
    elif mode in ('完全撤退', '撤退準備', 'スリム化', '様子見'):
        return 'fold'
    return None

# Tile type-based: 字牌/端牌 = push, 中張 = fold
def tile_to_push_fold(tile):
    if is_honor(tile_to_id(tile)) or tile[0] in ('1', '9'):
        return 'push'
    return 'fold'

# Combined: tile choice if AI in push mode, else mode
def ai_decision(ai_mode, ai_tile):
    if ai_tile is None:
        return mode_to_push_fold(ai_mode)
    return tile_to_push_fold(ai_tile)

for log_id, blob in all_log_blobs.items():
    if log_id not in data_by_log:
        continue
    n_processed += 1
    if n_processed % 200 == 0:
        print(f'  処理: {n_processed}/{len(needed_log_ids)} ({time.time()-t0:.0f}s)', flush=True)
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

            # Check if this is a betari moment
            kyoku = states[seat].chang * 4 + states[seat].ju + 1
            turn = (states[seat].tsumo_count - 1) // 4 + 1
            key = (kyoku, turn, seat, tile)
            if key in betari_to_check:
                bd = betari_to_check[key]
                try:
                    ev = Evaluator(states[seat], params=params)
                    mode = ev.strategy.get_strategy_mode()
                    hand = list(states[seat].my_hand)
                    best = ev.best_discard(hand)
                    human_decision = 'push' if bd['defense_score'] > 0 else 'fold'

                    # Mode-based comparison
                    ai_mode_decision = mode_to_push_fold(mode)
                    if ai_mode_decision is not None:
                        if ai_mode_decision == human_decision:
                            mode_match += 1
                        else:
                            mode_mismatch += 1

                    # Tile-based comparison
                    if best is not None:
                        ai_tile_decision = tile_to_push_fold(best)
                        # Combined: tile type match
                        human_tile = bd['discard_tile']
                        human_tile_decision = tile_to_push_fold(human_tile)
                        if ai_tile_decision == human_tile_decision:
                            tile_type_match += 1
                        else:
                            tile_mismatch += 1

                        # Diagnostic: count AI mode and tile choices
                        global _diag
                        try:
                            _diag
                        except NameError:
                            _diag = Counter()
                        _diag[(mode, ai_tile_decision, human_decision)] += 1
                except Exception as e:
                    pass
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

print()
print('=== 結果サマリ ===')
total_mode = mode_match + mode_mismatch
total_tile = tile_type_match + tile_mismatch
print(f'モード判定: 一致 {mode_match}/{total_mode} ({mode_match/total_mode*100:.1f}%)')
print(f'牌タイプ判定: 一致 {tile_type_match}/{total_tile} ({tile_type_match/total_tile*100:.1f}%)')

# Diagnostic breakdown
print('\n=== mode × AI tile × human 分布 ===')
for (m, ai_d, h_d), n in sorted(_diag.items()):
    marker = '一致' if (m in ('全力攻撃', '押し気味', '危険度勝負', '積極駒組み', '回し打ち') and ai_d == 'push') or (m in ('完全撤退', '撤退準備', 'スリム化', '様子見') and ai_d == 'fold') else '不一致'
    if n > 30:
        print(f'  {m:10} × ai={ai_d:5} × human={h_d:5}: {n:5}件 {marker}')
