"""
@title ベタオリ精度の局所テストスイート
@description
    人間データから抽出したベタオリ判断のテストケース。
    AIの push/fold 判断が人間と一致するかを高速に測定する。
"""
import pickle
import json
import sys
import time
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, is_honor
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load betari data
with open('betadata_full.pkl', 'rb') as f:
    betari_data = pickle.load(f)
print(f'ベタオリ局面総数: {len(betari_data)}件')

# Sample 2000 for testing
import random
random.seed(42)
test_data = random.sample(betari_data, 2000)
print(f'テストデータ: {len(test_data)}件')

# Group by log_id
data_by_log = defaultdict(list)
for d in test_data:
    data_by_log[d['log_id']].append(d)

# Load needed logs
needed_log_ids = list(set([d['log_id'] for d in test_data]))
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
print(f'  {len(all_log_blobs)} logs loaded')

# Run AI evaluation
match = 0
mismatch = 0
overpush = 0
overfold = 0
n_processed = 0
t0 = time.time()

for log_id, blob in all_log_blobs.items():
    if log_id not in data_by_log:
        continue
    n_processed += 1
    if n_processed % 100 == 0:
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
                    # 正しい解釈: defense_score>0 = 安全牌 = 人間はオリている
                    # defense_score==0 = 危険牌 = 人間は押し
                    human_push = bd['defense_score'] == 0
                    # AI判定: 戦略モードベース
                    if mode in ('全力攻撃', '押し気味', '危険度勝負', '積極駒組み'):
                        ai_is_push = True
                    elif mode in ('完全撤退', '撤退準備', 'スリム化', '回し打ち', '様子見'):
                        ai_is_push = False
                    else:
                        ai_is_push = None

                    if ai_is_push is not None:
                        if ai_is_push == human_push:
                            match += 1
                        else:
                            mismatch += 1
                            if ai_is_push and not human_push:
                                overpush += 1
                            else:
                                overfold += 1
                except Exception as e:
                    global _errors
                    try:
                        _errors
                    except NameError:
                        _errors = []
                    if len(_errors) < 5:
                        _errors.append(str(e))
                    pass
                if best is None:
                    global _no_best
                    try:
                        _no_best
                    except NameError:
                        _no_best = 0
                    _no_best += 1

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
print()
try:
    _no_best
    print(f'no_best count: {_no_best}')
except NameError:
    pass
try:
    _errors
    print(f'errors: {len(_errors)}')
    for e in _errors:
        print(f'  {e}')
except NameError:
    pass
print('=== ベタオリ精度テスト (2000件) ===')
print(f'  総局面: {total}件')
print(f'  一致: {match}件 ({match/total*100:.1f}%)')
print(f'  不一致: {mismatch}件 ({mismatch/total*100:.1f}%)')
print(f'    過剰押し(AI押し/人間オリ): {overpush}件 ({overpush/total*100:.1f}%)')
print(f'    過剰オリ(AIオリ/人間押): {overfold}件 ({overfold/total*100:.1f}%)')
print()
print(f'  処理時間: {time.time()-t0:.0f}秒')
