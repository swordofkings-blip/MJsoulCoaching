import re
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
def to_raw(t): return honor_kanji.get(t, t)
def tile_type(t):
    r = to_raw(t)
    return 'H' if r.endswith('z') else 'Y' if t[0] in '019' else 'M'

# === Akochan's insight applied to tenhou analysis ===
# Akochan said: 押し判断が真逆。OurAIが押しすぎ・降りすぎ両方向で間違っている可能性

# Group mismatches by riichi state
riichi_state_counter = Counter()
riichi_patterns = Counter()  # M->M, M->H etc under riichi

# For each mismatch, check riichi state
# - Is it under riichi (our)?
# - Is it under riichi (opponent)?
# - Is it when both are tenpai?

# Also categorize by turn phase (early/mid/late)

early_phase = 0  # turn 1-4
mid_phase = 0    # turn 5-10
late_phase = 0   # turn 11+
riichi_mismatches = 0
non_riichi_mismatches = 0

# Track: did we have tenpai and chose to riichi differently than human?
# Since we can't see human's riichi state directly, infer from "is_dora" of "リーチ" line

# Simple categorization
mismatch_data = []

for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    
    at, ait = tile_type(a), tile_type(ai)
    pattern = f'{ait}->{at}'
    
    # Check riichi
    is_riichi = '\u30ea\u30fc\u30c1' in blk
    reach_count = blk.count('\u30ea\u30fc\u30c1')
    if is_riichi:
        riichi_mismatches += 1
    else:
        non_riichi_mismatches += 1
    
    # Turn
    sit_m = re.search(r'(\d+)\u5de1\u76ee', blk)
    turn = int(sit_m.group(1)) if sit_m else 0
    if turn <= 4: early_phase += 1
    elif turn <= 10: mid_phase += 1
    else: late_phase += 1
    
    riichi_state_counter[f'reach={reach_count}'] += 1
    riichi_patterns[pattern] += 1
    mismatch_data.append((a, ai, pattern, turn, reach_count))

# Count by riichi and turn
print('=== リーチ状態×ミスマッチ ===')
for s, c in sorted(riichi_state_counter.items()):
    print(f'  {s}: {c}')
print()

print('=== 巡目別ミスマッチ ===')
print(f'  序盤(1-4巡): {early_phase}')
print(f'  中盤(5-10巡): {mid_phase}')
print(f'  終盤(11+巡): {late_phase}')
print()

# Reachable cases: focus on REACH situations
reach_mismatches = [m for m in mismatch_data if m[4] > 0]
print(f'=== リーチ下ミスマッチ: {len(reach_mismatches)}/{len(mismatch_data)} ===')

# What tiles are cut under riichi?
reach_human_cuts = Counter()
reach_ai_cuts = Counter()
for a, ai, _, _, _ in reach_mismatches:
    reach_human_cuts[a] += 1
    reach_ai_cuts[ai] += 1

print()
print('人間が切った牌(リーチ下) top10:')
for t, c in reach_human_cuts.most_common(10):
    print(f'  {t}: {c}回')
print()
print('AIが推した牌(リーチ下) top10:')
for t, c in reach_ai_cuts.most_common(10):
    print(f'  {t}: {c}回')

# Save details for later
print()
print('=== リーチ下のミスマッチパターン ===')
reach_pat = Counter()
for a, ai, p, _, _ in reach_mismatches:
    reach_pat[p] += 1
for p, c in reach_pat.most_common():
    print(f'  {p}: {c}')
