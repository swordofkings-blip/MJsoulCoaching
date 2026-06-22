"""
Analyze riichi declaration vs AI's state at that moment.
For each tenhou log, replay the actions and track:
- When human declares riichi (state transition)
- What was our AI's tenpai status at that moment
"""
import json
import os
import sys
import sqlite3
from collections import Counter, defaultdict

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

with open('tools/_log_ids_ga.txt') as f:
    ids = [line.strip() for line in f if line.strip()]

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

# Stats
human_riichi_events = 0
human_riichi_with_ai_tenpai = 0
human_riichi_with_ai_not_tenpai = 0

# When human didn't riichi
human_tenpai_no_riichi = 0
human_tenpai_no_riichi_ai_tenpai = 0  # AI was also in tenpai
human_tenpai_no_riichi_ai_would_riichi = 0  # AI would have called riichi

# Process each log
for log_id, blob in rows:
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except Exception as e:
        continue
    if n_rounds == 0: continue

    actions = json_dict.get('detail_records', {}).get('actions', [])
    if not actions: continue

    # Simulate 4 game states
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

            # Check AI state for this seat BEFORE processing the discard
            if awaiting[seat]:
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    ai_tenpai = sh <= 0

                    if isL:
                        # Human declared riichi
                        human_riichi_events += 1
                        if ai_tenpai:
                            human_riichi_with_ai_tenpai += 1
                        else:
                            human_riichi_with_ai_not_tenpai += 1
                    else:
                        # Human didn't riichi
                        if ai_tenpai:
                            # AI was in tenpai but human didn't riichi
                            human_tenpai_no_riichi += 1
                            # Check if AI's should_riichi would say yes
                            try:
                                ev = Evaluator(states[seat], params)
                                if ev.should_riichi(hand, tile):
                                    human_tenpai_no_riichi_ai_would_riichi += 1
                            except:
                                pass

            # Process the discard
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

# Print summary
print('=' * 70)
print('リーチ宣言 vs AI判断 ミスマッチ分析')
print('=' * 70)
print(f'人間のリーチ宣言総数: {human_riichi_events}回')
print()
if human_riichi_events > 0:
    print('リーチ宣言時のAI状態:')
    print(f'  AIがテンパイで同調可能: {human_riichi_with_ai_tenpai} ({human_riichi_with_ai_tenpai/human_riichi_events*100:.1f}%)')
    print(f'  AIが非テンパイで同調不可: {human_riichi_with_ai_not_tenpai} ({human_riichi_with_ai_not_tenpai/human_riichi_events*100:.1f}%)')
print()
print(f'人間がテンパイでリーチしなかった場面: {human_tenpai_no_riichi}回')
if human_tenpai_no_riichi > 0:
    print(f'  そのうちAIがshould_riichi=Trueと言っていた: {human_tenpai_no_riichi_ai_would_riichi} ({human_tenpai_no_riichi_ai_would_riichi/human_tenpai_no_riichi*100:.1f}%)')
print('  → この差分が「押し判断ミスマッチ」')
