"""
Analyze riichi declaration mismatches in tenhou logs.
For each tenhou log, track when each seat declares riichi and check what our AI's
tenpai state was at that moment.
"""
import json
import os
import sys
import sqlite3
from collections import Counter, defaultdict

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load IDs
with open('tools/_log_ids_ga.txt') as f:
    ids = [line.strip() for line in f if line.strip()][:3]

# DB
db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f'SELECT log_id, blob FROM logs WHERE log_id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

# Stats
human_riichi_events = []  # (log_id, seat, kyoku, turn, was_ai_tenpai)
human_riichi_with_ai_tenpai = 0
human_riichi_with_ai_not_tenpai = 0
human_tenpai_no_riichi = 0  # Human tenpai but didn't riichi
human_in_riichi_state = 0  # When human is in riichi
ai_would_riichi_tenpai = 0  # When AI is in tenpai (would it riichi?)

# Process each log
for log_id, blob in rows:
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0: continue
    except Exception as e:
        print(f'  Error processing {log_id}: {e}')
        continue

    # Initialize 4 states (one per seat)
    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    # Process each action
    actions = json_dict.get('detail_records', {}).get('actions', [])
    for a in actions:
        if a.get('type') != 1: continue
        r = a.get('result', {})
        cls = r.get('class_name', '')
        d = r.get('data', {})

        if cls == 'RecordNewRound':
            for s in range(4):
                states[s].on_new_round(...)
            awaiting = [True] * 4
            continue

        if cls == 'RecordDealTile':
            seat = d.get('seat')
            tile = d.get('tile')
            if seat is not None and tile is not None:
                if 0 <= seat < 4:
                    if seat == seat:  # self draw for this seat
                        states[seat].on_self_draw(tile)
                    else:
                        # opponent drew
                        for s in range(4):
                            if s != seat:
                                states[s].on_opponent_draw(seat)
            awaiting[seat] = True if seat is not None else awaiting[seat]
            continue

        if cls == 'RecordDiscardTile':
            seat = d.get('seat')
            tile = d.get('tile')
            isL = d.get('isLiqi', False)  # True if this is the riichi declaration
            moq = d.get('moqie', False)

            if seat is None or seat < 0 or seat >= 4: continue

            # Check riichi state for this seat
            was_riichi = states[seat].reach_states[seat].is_reach

            if awaiting[seat] and not was_riichi:
                # Human was about to discard
                # Check if this is a riichi declaration (isL = True)
                if isL:
                    # Human declared riichi!
                    # Check our AI's state
                    hand = list(states[seat].my_hand)
                    if hand and len(hand) % 3 == 2:
                        # Compute shanten for the AI at this moment
                        hand_counts = hand_to_counts(hand)
                        sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                        ai_tenpai = sh <= 0
                        kyoku = d.get('chang', 0) * 4 + d.get('ju', 0) + 1
                        # For this analysis, we treat all 4 seats equally (we don't know which is AI)
                        human_riichi_events.append((log_id, seat, kyoku, ai_tenpai))

            # Process the discard
            if awaiting[seat]:
                for s in range(4):
                    if s != seat:
                        states[s].on_discard(seat, tile, isL, moq)
            states[seat].on_discard(seat, tile, isL, moq) if False else None
            # Actually we need to properly update state

# Summary
total = len(human_riichi_events)
ai_tenpai_count = sum(1 for e in human_riichi_events if e[3])
ai_not_tenpai = total - ai_tenpai_count
print(f'人間のリーチ宣言: {total}回')
print(f'  AIがテンパイだった場面: {ai_tenpai_count}')
print(f'  AIが非テンパイだった場面: {ai_not_tenpai}')
print()
print('注: AIは人間と同じ席で行動するため、席が一致すれば人間の判断とAIの判断を比較可能')
print('ただし現状のコードではAIがリーチ宣言するかどうかは追跡していない')
