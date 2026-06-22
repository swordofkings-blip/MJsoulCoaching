import re
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
def to_raw(t): return honor_kanji.get(t, t)

def parse_hand(blk):
    m = re.search(r'\u624b\u724c\(\d+\u679a\):\s*([^\n]+)', blk)
    return m.group(1).split(',') if m else []

def parse_sit(blk):
    m = re.search(r'(\d+)\u5de1\u76ee', blk)
    return int(m.group(1)) if m else 0

def suit_vals(hand, suit_char):
    return sorted([int(to_raw(h)[0]) for h in hand if to_raw(h)[1] == suit_char and to_raw(h)[0].isdigit()])

def classify_shape(v, vals):
    """Describe the shape this tile belongs to in the suit"""
    c = vals.count(v)
    has_l1 = (v-1) in vals
    has_r1 = (v+1) in vals
    has_l2 = (v-2) in vals
    has_r2 = (v+2) in vals
    
    if c >= 3: return 'triple'
    if c == 2:
        if has_l1 and has_r1: return 'pair_in_ryanmen'
        if has_l1: return 'pair_left'
        if has_r1: return 'pair_right'
        return 'isolated_pair'
    # c == 1
    if has_l1 and has_r1: return 'ryanmen_center'
    if has_l1 and has_r2: return 'kanchan_left_outer'
    if has_l2 and has_r1: return 'kanchan_right_outer'
    if has_l1: return 'penchan_right'
    if has_r1: return 'penchan_left'
    if has_l2: return 'kanchan_far_left'
    if has_r2: return 'kanchan_far_right'
    return 'isolated'

def max_shape_potential(vals):
    """Evaluate the maximum potential of this suit's tiles.
    Returns a score: higher = more potential."""
    if not vals:
        return 0
    score = 0
    # Check for completed sequences (3 consecutive)
    for i in range(min(vals), max(vals)+1):
        if i in vals and (i+1) in vals and (i+2) in vals:
            score += 10  # completed block
    # Check for ryanmen potential
    for i in range(min(vals), max(vals)+1):
        if i in vals and (i+1) in vals:
            score += 5  # ryanmen pair
    # Check for complex shapes (4+ tiles in a row like 3456)
    for i in range(min(vals), max(vals)-2):
        if all(v in vals for v in [i, i+1, i+2, i+3]):
            score += 8  # 4-tile complex
    return score

# Collect and classify all M->M cases
mm_data = []
for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    if to_raw(a).endswith('z') or to_raw(ai).endswith('z'): continue
    if ai == 'None' or not (a[0].isdigit() and ai[0].isdigit()): continue
    if a[0] in '19' or ai[0] in '19': continue
    mm_data.append({'blk': blk, 'actual': a, 'ai': ai})

print('Total M->M cases: %d' % len(mm_data))
print()

# === 1. SHAPE COMPARISON ===
print('=== 1. Shape category of CUT tile ===')
ai_shape_dist = Counter()
human_shape_dist = Counter()
for d in mm_data:
    hand = parse_hand(d['blk'])
    for suit_c in ['m','p','s']:
        sv = suit_vals(hand, suit_c)
        if d['ai'][1] == suit_c:
            ai_shape_dist[classify_shape(int(d['ai'][0]), sv)] += 1
        if d['actual'][1] == suit_c:
            human_shape_dist[classify_shape(int(d['actual'][0]), sv)] += 1

print('AI cuts:')
for sh, cnt in ai_shape_dist.most_common():
    print('  %s: %d' % (sh, cnt))
print('Human cuts:')
for sh, cnt in human_shape_dist.most_common():
    print('  %s: %d' % (sh, cnt))
print()

# Difference
print('Difference (AI - Human):')
for sh in set(list(ai_shape_dist.keys()) + list(human_shape_dist.keys())):
    diff = ai_shape_dist.get(sh, 0) - human_shape_dist.get(sh, 0)
    if diff != 0:
        print('  %s: %+d' % (sh, diff))
print()

# === 2. SUIT POTENTIAL ANALYSIS ===
print('=== 2. Does AI cut from HIGHER potential suit? ===')
ai_higher_pot = 0
human_higher_pot = 0
same_pot = 0
for d in mm_data:
    hand = parse_hand(d['blk'])
    ai_s = d['ai'][1]; hu_s = d['actual'][1]
    if ai_s == hu_s:
        same_pot += 1
        continue
    ai_pot = max_shape_potential(suit_vals(hand, ai_s))
    hu_pot = max_shape_potential(suit_vals(hand, hu_s))
    if ai_pot > hu_pot:
        ai_higher_pot += 1
    elif hu_pot > ai_pot:
        human_higher_pot += 1
    else:
        same_pot += 1

print('AI cuts from higher-potential suit: %d' % ai_higher_pot)
print('Human cuts from higher-potential suit: %d' % human_higher_pot)
print('Same or same suit: %d' % same_pot)
print()

# === 3. CENTER vs EDGE within suit ===
print('=== 3. Center(4-6) vs Edge(2,3,7,8) within same suit ===')
ai_center = 0; ai_edge = 0
human_center = 0; human_edge = 0
for d in mm_data:
    ai_v = int(d['ai'][0])
    hu_v = int(d['actual'][0])
    if 4 <= ai_v <= 6: ai_center += 1
    else: ai_edge += 1
    if 4 <= hu_v <= 6: human_center += 1
    else: human_edge += 1

print('AI cuts:   center(4-6)=%d edge(2,3,7,8)=%d' % (ai_center, ai_edge))
print('Human cuts: center(4-6)=%d edge(2,3,7,8)=%d' % (human_center, human_edge))
print()

# === 4. HAND STRUCTURE DIFFERENCE: Does one tile leave a complex shape? ===
print('=== 4. After-cut hand structure ===')
# For each case, check if the OTHER tile (the one NOT cut) leaves a complex shape
ai_leaves_complex = 0
human_leaves_complex = 0
for d in mm_data:
    hand = parse_hand(d['blk'])
    ai_s = d['ai'][1]; hu_s = d['actual'][1]
    # The tile the AI wants to cut, vs the tile the human wants to cut
    # Which one, if KEPT, gives a more complex shape?
    ai_tile = int(d['ai'][0])
    hu_tile = int(d['actual'][0])
    
    # AI: keep the human's choice, cut AI's choice
    # Human: keep AI's choice, cut human's choice
    
    # Check: does keeping AI's tile give better structure?
    def shape_score(v, sv):
        """Score how well this tile integrates with the suit"""
        s = 0
        if (v-1) in sv: s += 3
        if (v+1) in sv: s += 3
        if (v-2) in sv: s += 1
        if (v+2) in sv: s += 1
        if sv.count(v) >= 2: s += 2
        return s
    
    ai_sv = suit_vals(hand, ai_s)
    hu_sv = suit_vals(hand, hu_s)
    
    ai_kept_score = shape_score(ai_tile, ai_sv)  # score if AI's tile is kept
    hu_kept_score = shape_score(hu_tile, hu_sv)  # score if human's tile is kept
    
    if ai_kept_score > hu_kept_score:
        ai_leaves_complex += 1  # AI's choice leaves more complex shape
    elif hu_kept_score > ai_kept_score:
        human_leaves_complex += 1  # Human's choice leaves more complex shape

print('AI choice leaves MORE complex shape: %d' % ai_leaves_complex)
print('Human choice leaves MORE complex shape: %d' % human_leaves_complex)
print()

# === 5. COMPLEX SHAPE PATTERNS ===
print('=== 5. Complex shape patterns (34567 type) ===')
ai_misses_complex = 0
human_misses_complex = 0
for d in mm_data:
    hand = parse_hand(d['blk'])
    ai_s = d['ai'][1]
    sv = suit_vals(hand, ai_s)
    v = int(d['ai'][0])
    # Check if this suit has 4+ tiles with consecutive values (like 3456)
    uniq = sorted(set(sv))
    for i in range(len(uniq)-3):
        if uniq[i+3] - uniq[i] == 3:  # 4 consecutive tiles
            if uniq[i] <= v <= uniq[i+3]:
                # AI is cutting from a complex shape!
                ai_misses_complex += 1
                break
    
    hu_s = d['actual'][1]
    sv2 = suit_vals(hand, hu_s)
    v2 = int(d['actual'][0])
    uniq2 = sorted(set(sv2))
    for i in range(len(uniq2)-3):
        if uniq2[i+3] - uniq2[i] == 3:
            if uniq2[i] <= v2 <= uniq2[i+3]:
                human_misses_complex += 1
                break

print('AI cuts from a 4+ consecutive shape: %d' % ai_misses_complex)
print('Human cuts from a 4+ consecutive shape: %d' % human_misses_complex)
