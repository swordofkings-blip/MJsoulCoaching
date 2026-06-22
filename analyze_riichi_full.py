"""
Properly analyze riichi push/fold decisions by processing tenhou logs.
For each turn, determine if the human declared riichi and what our AI's tenpai state was.
"""
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from tools.tenhou_process_dict import process_dict

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load IDs
with open('tools/_log_ids_ga.txt') as f:
    ids = [line.strip() for line in f if line.strip()][:3]  # only 3 for speed

# DB
import sqlite3
db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f'SELECT log_id, blob FROM logs WHERE log_id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

# Track statistics
total_human_riichi = 0
human_in_tenpai = 0
human_riichi_in_tenpai = 0
human_no_riichi_in_tenpai = 0

# Our AI decisions
our_riichi_in_tenpai = 0
our_no_riichi_in_tenpai = 0

# Mismatches
human_riichi_ai_didnt = 0  # Human riichi'd, AI didn't
human_no_riichi_ai_did = 0  # Human didn't riichi, AI did
both_riichi = 0
both_no_riichi = 0

for log_id, blob in rows:
    print(f'Processing {log_id}...')
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0: continue
        # Process dict
        _lines, td, dm, tm, mm, _ = process_dict(json_dict, params)
    except Exception as e:
        print(f'  Error: {e}')
        continue

# The processing is hard to track without modifying the code.
# Let me just print summary
print()
print('Detailed per-kyoku riichi analysis requires modifying process_dict')
print('Alternative: use existing mismatch data and check riichi patterns')
