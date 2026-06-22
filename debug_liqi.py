import json
import sys
import sqlite3
sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.game_state import GameState

with open('tools/_log_ids_ga.txt') as f:
    ids = [line.strip() for line in f if line.strip()][:3]

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
placeholders = ','.join(['?']*len(ids))
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', ids)
rows = cur.fetchall()
conn.close()

liqi_count = 0
total_discards = 0
liqi_samples = []

for log_id, blob in rows:
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except:
        continue
    actions = json_dict.get('detail_records', {}).get('actions', [])
    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s

    for a in actions:
        if a.get('type') != 1: continue
        cls = a.get('result', {}).get('class_name', '')
        d = a.get('result', {}).get('data', {})
        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(0, 0, 0, 0, d.get(k, []), d.get('scores', [25000]*4), d.get('leftTileCount', 70), d.get('doras', []))
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
            continue
        if cls == 'RecordDiscardTile':
            total_discards += 1
            seat = d.get('seat')
            tile = d.get('tile')
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)
            if isL:
                liqi_count += 1
                if len(liqi_samples) < 5 and seat is not None and 0 <= seat < 4:
                    hand_size = len(states[seat].my_hand)
                    liqi_samples.append({'log_id': log_id, 'data': d, 'hand_size': hand_size, 'seat_used': seat})
            for s in range(4):
                if s == seat:
                    states[s].on_discard(seat, tile, isL, moq)
            continue

print(f'total discards: {total_discards}, isLiqi=True: {liqi_count}')
for s in liqi_samples:
    print(s)
