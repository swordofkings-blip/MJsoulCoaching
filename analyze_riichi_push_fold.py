"""
Analyze riichi push/fold mismatches.
For each tenhou log, track when the human declares riichi and check if our AI was in tenpai.
"""
import json
import os
import glob
import sys
from collections import Counter, defaultdict

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id

# We need to process each tenhou log and track:
# - When human declares riichi (state transition)
# - Our AI's state at the same moment (tenpai? in reach? folded?)

# Load params
with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Track statistics
human_riichi_count = 0
human_no_riichi_tenpai = 0  # Human tenpai but didn't riichi
our_ai_riichi_count = 0
our_ai_no_riichi_tenpai = 0

# Mismatch cases
riichi_mismatches = []  # Human riichi'd, AI didn't (when AI was tenpai)
defense_mismatches = []  # Human didn't riichi, AI did (when AI was tenpai)
# (we need to detect from tenhou logs - hard without playing each game)

# Actually a simpler approach: use the existing mismatch file
# But that only covers discards. Let me check the tenhou logs directly.

# Alternative: look at the tenhou_process_dict and track riichi decisions
# This is harder. Let me just count riichi-related mismatches from the existing data.

# Use the existing mismatch file to look at:
# - Mismatches where human chose riichi-discard (discard before riichi)
# - Mismatches where our AI chose different tile around the same time

# For now, let's look at the simpler metric:
# In each log, did the human declare riichi? Did the AI's evaluation show tenpai?

# Let me use the existing data
import sys
from tools.tenhou_process_dict import process_dict

# Process each log
ids_file = 'tools/_log_ids_ga.txt'
with open(ids_file) as f:
    ids = [line.strip() for line in f if line.strip()]

# DB setup
sys.path.insert(0, '.')
from tools.ga_fitness import _load_ids, _load_blobs

# Check if db_path is right
import os
db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
print(f'Loading from {db_path}')
print(f'IDs: {ids}')

# Just analyze a simple case
# Use the existing mismatch file approach
# Read the mismatch output
mismatch_path = 'tools/mismatches_tenhou_10.txt'
with open(mismatch_path, 'r', encoding='utf-8') as f:
    mismatch_text = f.read()

# Count riichi in mismatch data
mismatches = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', mismatch_text)[1:]

riichi_mismatch_count = 0
riichi_patterns = Counter()

for blk in mismatches:
    if 'AI判断:' in blk: continue
    is_riichi = '\u30ea\u30fc\u30c1' in blk
    if is_riichi:
        riichi_mismatch_count += 1
        # Check pattern
        m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
        if m:
            a, ai = m.group(1), m.group(2)
            honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
            def to_raw(t): return honor_kanji.get(t, t)
            def tt(t):
                r = to_raw(t)
                return 'H' if r.endswith('z') else 'Y' if t[0] in '019' else 'M'
            riichi_patterns[f'{tt(ai)}->{tt(a)}'] += 1

print(f'総ミスマッチ: {len(mismatches)}')
print(f'リーチ下ミスマッチ: {riichi_mismatch_count}')
print('リーチ下のパターン:')
for p, c in riichi_patterns.most_common():
    print(f'  {p}: {c}')
