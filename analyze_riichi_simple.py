"""
Simple riichi push/fold analysis using direct database access.
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

# Process each log
total_human_riichi = 0
ai_would_also_riichi = 0
ai_would_not_riichi = 0
ai_would_riichi_human_didnt = 0
ai_tenpai_but_human_folded = 0

# For each log, simulate the AI's perspective at each turn
for log_id, blob in rows[:3]:  # only 3 for speed
    try:
        data = json.loads(blob)
    except:
        continue
    actions = data.get('detail_records', {}).get('actions', [])
    if not actions: continue

    # Simulate 4 game states
    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    human_riichi_seen = 0

    for a in actions:
        if a.get('type') != 1: continue
        r = a.get('result', {})
        cls = r.get('class_name', '')
        d = r.get('data', {})

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tehais{s}'
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

            # BEFORE processing the discard, check if AI is in tenpai
            if awaiting[seat]:
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    ai_tenpai = sh <= 0

                    if isL:
                        # Human declared riichi
                        total_human_riichi += 1
                        if ai_tenpai:
                            ai_would_also_riichi += 1
                        else:
                            ai_would_not_riichi += 1
                    else:
                        # Human didn't riichi
                        if ai_tenpai:
                            # AI is in tenpai but human didn't riichi
                            # The AI might choose to riichi but human didn't
                            ai_tenpai_but_human_folded += 1
                            # Check if AI would actually riichi based on should_riichi
                            if 0 <= seat < 4:
                                ev = Evaluator(states[seat], params)
                                should = ev.should_riichi(hand, tile)
                                if should:
                                    ai_would_riichi_human_didnt += 1

            # Process the discard
            for s in range(4):
                if s != seat:
                    states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4:
                states[seat].on_discard(seat, tile, isL, moq) if False else None

print('=' * 70)
print('リーチ宣言 vs AI判断 ミスマッチ分析 (3ログ限定)')
print('=' * 70)
print(f'人間のリーチ宣言: {total_human_riichi}回')
print(f'  AIがテンパイで人間と同調できた: {ai_would_also_riichi} ({ai_would_also_riichi/max(1,total_human_riichi)*100:.0f}%)')
print(f'  AIが非テンパイで同調不可: {ai_would_not_riichi} ({ai_would_not_riichi/max(1,total_human_riichi)*100:.0f}%)')
print()
print(f'人間がテンパイでリーチしなかった: {ai_tenpai_but_human_folded}回')
print(f'  そのうちAIはリーチしたかった: {ai_would_riichi_human_didnt} ({ai_would_riichi_human_didnt/max(1,ai_tenpai_but_human_folded)*100:.0f}%)')
