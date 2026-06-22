"""
Quick test of new rule-based riichi decision against human data.
"""
import json
import sys
import sqlite3
import pickle
from collections import Counter

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

with open('tools/_log_ids_1000.txt') as f:
    ids = [line.strip() for line in f if line.strip()]

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

riichi_events = []
processed = 0

for log_id, blob in rows:
    processed += 1
    if processed % 200 == 0:
        print(f'処理: {processed}/{len(rows)} ({len(riichi_events)}件)', flush=True)
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

            if isL and awaiting[seat]:
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    if sh <= 0:
                        try:
                            ev = Evaluator(states[seat], params)
                            rule_result = ev._rule_based_should_riichi()
                            ev_result = ev._compare_riichi_vs_damaten()
                            # Test the new should_riichi
                            new_should = ev.should_riichi()
                            riichi_events.append({
                                'log_id': log_id, 'seat': seat,
                                'rule_result': rule_result,
                                'ev_should': ev_result[0] > ev_result[1],
                                'new_should': new_should,
                            })
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

total = len(riichi_events)
rule_match = sum(1 for e in riichi_events if e['rule_result'] == True)
ev_match = sum(1 for e in riichi_events if e['ev_should'] == True)
new_match = sum(1 for e in riichi_events if e['new_should'] == True)
print(f'\n人間リーチ宣言: {total}件')
print(f'ルールベース一致: {rule_match} ({rule_match/total*100:.1f}%)')
print(f'EVベース一致: {ev_match} ({ev_match/total*100:.1f}%)')
print(f'新should_riichi一致: {new_match} ({new_match/total*100:.1f}%)')

# Per-rule breakdown
print()
print('=== ルール判定の分布 ===')
rule_true = sum(1 for e in riichi_events if e['rule_result'] == True)
rule_false = sum(1 for e in riichi_events if e['rule_result'] == False)
rule_none = sum(1 for e in riichi_events if e['rule_result'] is None)
print(f'  ルール True: {rule_true} ({rule_true/total*100:.1f}%)')
print(f'  ルール False: {rule_false} ({rule_false/total*100:.1f}%)')
print(f'  ルール None (EV判定に委ねる): {rule_none} ({rule_none/total*100:.1f}%)')
