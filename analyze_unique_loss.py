import re
from collections import Counter

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
def to_raw(t): return honor_kanji.get(t, t)

def tile_accepting_types(tile_id):
    """Returns set of draw IDs that form a shape with this tile"""
    draws = {tile_id}  # pair
    if not is_honor(tile_id):
        base = (tile_id // 9) * 9
        off = tile_id - base
        if off > 0: draws.add(tile_id - 1)  # left neighbor
        if off < 8: draws.add(tile_id + 1)  # right neighbor
        if off >= 2: draws.add(tile_id - 2)  # kanchan left
        if off <= 6: draws.add(tile_id + 2)  # kanchan right
        # edge tiles (1,9) only have limited connections but still include
    return draws

def is_honor(tid):
    return tid >= 27

def compute_unique_loss(hand_counts, tile_id):
    """How many accepting types are UNIQUE to this tile?"""
    my_draws = tile_accepting_types(tile_id)
    # Remove this tile from hand
    new_counts = list(hand_counts)
    new_counts[tile_id] = max(0, new_counts[tile_id] - 1)
    # Check which of my draws are still covered by other tiles
    still_covered = set()
    for other_id in range(34):
        if new_counts[other_id] <= 0:
            continue
        other_draws = tile_accepting_types(other_id)
        for d in other_draws:
            if d in my_draws:
                still_covered.add(d)
    return len(my_draws - still_covered)

def parse_hand(blk):
    m = re.search(r'\u624b\u724c\(\d+\u679a\):\s*([^\n]+)', blk)
    if not m: return [], {}
    hand = m.group(1).split(',')
    counts = {}
    for h in hand:
        raw = to_raw(h)
        if raw not in counts: counts[raw] = 0
        counts[raw] += 1
    return hand, counts

# Analyze M->M cases for unique loss
mm_cases = []
for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    if to_raw(a).endswith('z') or to_raw(ai).endswith('z'): continue
    if ai == 'None': continue
    if not (a[0].isdigit() and ai[0].isdigit()): continue
    if not (a[0] in '2345678' and ai[0] in '2345678'): continue
    mm_cases.append(blk)

# For each case, compute unique loss of both AI pick and human pick
ai_higher_loss = 0
human_higher_loss = 0
same_loss = 0
results = []

for blk in mm_cases[:200]:  # limit
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    a, ai = m.group(1), m.group(2)
    
    def tile_id(t):
        t_raw = to_raw(t)
        if t_raw.endswith('z'):
            return 27 + '1234567'.index(t_raw[0])
        return int(t_raw[0]) - 1 + {'m':0,'p':9,'s':18}[t_raw[1]]
    
    hand, hand_counts_raw = parse_hand(blk)
    # Convert to 34-array
    counts = [0]*34
    for h in hand:
        raw = to_raw(h)
        if raw.endswith('z'):
            idx = 27 + '1234567'.index(raw[0])
        else:
            idx = int(raw[0]) - 1 + {'m':0,'p':9,'s':18}[raw[1]]
        counts[idx] += 1
    
    ai_tid = tile_id(ai)
    human_tid = tile_id(a)
    
    ai_loss = compute_unique_loss(counts, ai_tid)
    human_loss = compute_unique_loss(counts, human_tid)
    
    if ai_loss > human_loss:
        ai_higher_loss += 1
    elif human_loss > ai_loss:
        human_higher_loss += 1
    else:
        same_loss += 1
    
    results.append((ai, a, ai_loss, human_loss))

print('M->M unique loss comparison (%d cases):' % len(results))
print('  AI losing MORE unique draws: %d (%.0f%%)' % (ai_higher_loss, ai_higher_loss/len(results)*100))
print('  Human losing MORE unique draws: %d (%.0f%%)' % (human_higher_loss, human_higher_loss/len(results)*100))
print('  Same: %d' % same_loss)
print()
print('In %d/%d cases, the AI is cutting the tile with HIGHER unique loss' % (ai_higher_loss, len(results)))
print('This means the AI is cutting MORE valuable tiles than humans.')
print()

# Show samples where AI loss > human loss (AI is making the wrong choice)
print('Samples where AI unique loss > human unique loss:')
shown = 0
for ai_t, h_t, ai_l, h_l in results:
    if ai_l > h_l and shown < 5:
        print('  AI=%s(loss=%d) Human=%s(loss=%d)' % (ai_t, ai_l, h_t, h_l))
        shown += 1
