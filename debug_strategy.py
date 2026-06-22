import sys
sys.path.insert(0, '.')
import json
import pickle
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts
from core.strategy_manager import ShantenCalculator, StrategyManager
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)
# Find a sample with reach and various shanten
for d in data:
    if d['reach_n'] == 1 and d['shanten'] == 2 and d['my_rank'] != 3 and d['defense_score'] == 0:
        sample = d
        break
else:
    for d in data:
        if d['reach_n'] == 1 and d['defense_score'] == 0:
            sample = d
            break
print('Sample:', sample)
print()

with open('tools/_log_ids_10000.txt') as f:
    log_ids = [l.strip() for l in f if l.strip()][:1000]
db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
ph = '?'
cur.execute(f'SELECT id, log FROM logs WHERE id = {ph}', [sample['log_id']])
log_id, blob = cur.fetchone()
db.close()

json_dict, n_rounds = tenhou_blob_to_actions(blob)
actions = json_dict.get('detail_records', {}).get('actions', [])

states = [GameState() for _ in range(4)]
for s in range(4):
    states[s].my_seat = s
awaiting = [False] * 4

target_tile = sample['discard_tile']
target_kyoku = sample['kyoku']
target_turn = sample['turn']
target_seat = sample['seat']

for a in actions:
    if a.get('type') != 1: continue
    cls = a.get('result', {}).get('class_name', '')
    d = a.get('result', {}).get('data', {})
    if cls == 'RecordNewRound':
        for s in range(4):
            k = f'tiles{s}'
            states[s].on_new_round(d.get('chang', 0), d.get('ju', 0), d.get('ben', 0), d.get('liqibang', 0), d.get(k, []), d.get('scores', [25000]*4), d.get('leftTileCount', 70), d.get('doras', []))
            states[s].chang = d.get('chang', 0)
            states[s].ju = d.get('ju', 0)
        oya = d.get('oya', 0)
        states[oya].dealer_seat = oya
        for s in range(4):
            if s != oya: states[s].dealer_seat = oya
        awaiting = [True] * 4
        continue
    if cls == 'RecordDealTile':
        seat = d.get('seat'); tile = d.get('tile')
        if seat is None or tile is None: continue
        for s in range(4):
            if s == seat: states[s].on_self_draw(tile)
            else: states[s].on_opponent_draw(seat)
        if 0 <= seat < 4: awaiting[seat] = True
        continue
    if cls == 'RecordDiscardTile':
        seat = d.get('seat'); tile = d.get('tile')
        isL = d.get('isLiqi', False)
        if seat is None or seat < 0 or seat >= 4: continue

        kyoku = states[seat].chang * 4 + states[seat].ju + 1
        turn = (states[seat].tsumo_count - 1) // 4 + 1
        if kyoku == target_kyoku and turn == target_turn and seat == target_seat and tile == target_tile:
            print(f'Found target: kyoku={kyoku} turn={turn} seat={seat} tile={tile}')
            for s in range(4):
                rs = states[s].reach_states[s]
                print(f'  reach_states[{s}].is_reach: {rs.is_reach} (turn={rs.reach_turn})')
            reachers = [s for s in range(4) if states[s].reach_states[s].is_reach and s != seat]
            print(f'  reachers: {reachers}')

            sm = StrategyManager(states[seat], params=params)
            mode = sm.get_strategy_mode()
            print(f'  Strategy mode: {mode}')
            print(f'  Push score: {sm.compute_push_score():.3f}')
            break

        for s in range(4):
            if s == seat: states[s].on_discard(seat, tile, isL, d.get('moqie', False))
        if 0 <= seat < 4: awaiting[seat] = False
        continue
