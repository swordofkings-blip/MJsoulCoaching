"""
Debug: find any reach event in a small sample
"""
import json
import sys
import sqlite3
sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.game_state import GameState

with open('tools/_log_ids_10000.txt') as f:
    ids = [l.strip() for l in f if l.strip()][:10]

db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
placeholders = ','.join(['?']*len(ids))
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', ids)
rows = cur.fetchall()
db.close()

# Find a log with reach and trace
for log_id, blob in rows:
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except:
        continue
    actions = json_dict.get('detail_records', {}).get('actions', [])
    reach_count = 0
    for a in actions:
        if a.get('type') != 1: continue
        cls = a.get('result', {}).get('class_name', '')
        d = a.get('result', {}).get('data', {})
        if cls == 'RecordDiscardTile' and d.get('isLiqi'):
            reach_count += 1
    if reach_count >= 2:
        print(f'Log {log_id}: {reach_count} reach events')
        # Trace this log
        states = [GameState() for _ in range(4)]
        for s in range(4):
            states[s].my_seat = s
        awaiting = [False] * 4

        for a in actions:
            if a.get('type') != 1: continue
            cls = a.get('result', {}).get('class_name', '')
            d = a.get('result', {}).get('data', {})
            if cls == 'RecordNewRound':
                for s in range(4):
                    k = f'tiles{s}'
                    states[s].on_new_round(0, 0, 0, 0, d.get(k, []), d.get('scores', [25000]*4), d.get('leftTileCount', 70), d.get('doras', []))
                awaiting = [True] * 4
                continue
            if cls == 'RecordDealTile':
                seat = d.get('seat')
                tile = d.get('tile')
                if seat is None or tile is None: continue
                for s in range(4):
                    if s == seat: states[s].on_self_draw(tile)
                    else: states[s].on_opponent_draw(seat)
                if 0 <= seat < 4: awaiting[seat] = True
                continue
            if cls == 'RecordDiscardTile':
                seat = d.get('seat')
                tile = d.get('tile')
                isL = d.get('isLiqi', False)
                reachers = [s for s in range(4) if states[s].reach_states[s].is_reach and s != seat]
                if reachers:
                    print(f'  Discard by {seat} ({tile}) isL={isL}, awaiting={awaiting[seat]}, reachers={reachers}')
                if isL:
                    print(f'  Riichi by {seat} ({tile})')
                for s in range(4):
                    if s == seat:
                        states[s].on_discard(seat, tile, isL, False)
                if 0 <= seat < 4: awaiting[seat] = False
                continue
        break
