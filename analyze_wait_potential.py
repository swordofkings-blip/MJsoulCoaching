import re
from collections import Counter

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
def to_raw(t): return honor_kanji.get(t, t)

def suit_vals(hand, suit):
    return sorted(int(to_raw(h)[0]) for h in hand if to_raw(h)[1] == suit and to_raw(h)[0].isdigit())

def analyze_suit_potential(vals):
    """Analyze the wait potential of a suit.
    Returns the number of distinct waits this suit can form."""
    if not vals:
        return 0
    
    uniq = sorted(set(vals))
    waits = set()
    
    # For each possible wait tile (1-9), check if the suit can form a winning hand with it
    for w in range(1, 10):
        # Check ryanmen: pair + ryanmen or completed block + ryanmen
        # A wait on 'w' is possible if the suit has tiles that form a shape needing 'w'
        # e.g., wait on 3: hand has 45 (ryanmen), or 13 (kanchan), or 12 (penchan), or 3 (tanki)
        
        # Tanki: if w is in vals
        if w in vals:
            waits.add(('tanki', w))
            continue
        
        # Ryanmen: if w-1,w in vals (wait on w+2) OR w,w+1 in vals (wait on w-1)
        if w-1 in vals and w in vals:
            waits.add(('ryanmen', w))
        # w+2: if w+1,w+2 in vals → wait on w for ryanmen
        if w+1 in vals and w+2 in vals:
            # wait on w as left of ryanmen w+1,w+2
            pass  # already counted above
        
        # Kanchan: if w-2,w in vals (gap of 1 at w-1)
        if w-2 in vals and w in vals:
            waits.add(('kanchan', w))
        # if w,w+2 in vals
        if w in vals and w+2 in vals:
            waits.add(('kanchan', w))
        
        # Penchan: 1,2 → wait on 3; 8,9 → wait on 7
        if w == 3 and 1 in vals and 2 in vals:
            waits.add(('penchan', w))
        if w == 7 and 8 in vals and 9 in vals:
            waits.add(('penchan', w))
    
    return len(waits)

def count_multi_sided_patterns(vals):
    """Count multi-sided patterns (3+ possible waits)."""
    uniq = sorted(set(vals))
    if len(uniq) < 4:
        return 0
    
    patterns = 0
    # Sanmenchan: 34567 → waits 2,5,8
    for i in range(len(uniq)-4):
        if uniq[i+4] - uniq[i] == 4:  # 5 consecutive values
            patterns += 1
    
    # 4 consecutive + an extra: 3456 + extra 5 → 34456 → waits 2,5,6,7,8 (5 waits)
    # or 3456 + extra 4 → 34456
    for i in range(len(uniq)-3):
        if uniq[i+3] - uniq[i] == 3:  # 4 consecutive
            # Check if there's an extra copy of one of these tiles
            for j in range(4):
                if vals.count(uniq[i+j]) >= 2:
                    patterns += 1
                    break
    
    # Double ryanmen: 3456 → two overlapping ryanmen (34 and 56)
    # → waits 2,5,7
    for i in range(len(uniq)-3):
        if uniq[i+3] - uniq[i] == 3:  # 4 consecutive
            patterns += 1  # at minimum, 3 possible waits
    
    return patterns

# Collect M->M cases
mm_data = []
for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    if to_raw(a).endswith('z') or to_raw(ai).endswith('z'): continue
    if ai == 'None' or not (a[0].isdigit() and ai[0].isdigit()): continue
    if a[0] in '19' or ai[0] in '19': continue
    hand_m = re.search(r'\u624b\u724c\(\d+\u679a\):\s*([^\n]+)', blk)
    hand = hand_m.group(1).split(',') if hand_m else []
    mm_data.append(hand)

print('M->M cases: %d' % len(mm_data))
print()

# Analyze: for each suit in each hand, what's the wait potential?
all_potentials = []
for hand in mm_data:
    for suit in ['m','p','s']:
        sv = suit_vals(hand, suit)
        if len(sv) >= 3:
            pot = analyze_suit_potential(sv)
            ms = count_multi_sided_patterns(sv)
            all_potentials.append((suit, sv, pot, ms))

# Distribution of wait potentials
pot_dist = Counter()
ms_dist = Counter()
for _, _, pot, ms in all_potentials:
    pot_dist[pot] += 1
    if ms > 0:
        ms_dist[ms] += 1

print('=== Wait potential distribution (suits with 3+ tiles) ===')
for pot in sorted(pot_dist.keys()):
    print('  %d possible waits: %d suits (%.0f%%)' % (pot, pot_dist[pot], pot_dist[pot]/len(all_potentials)*100))
print()
print('=== Multi-sided patterns detected ===')
print('  Total suits with multi-sided patterns: %d' % sum(ms_dist.values()))
print()

# Now check: in M->M cases, does the AI cut from a suit with MORE wait potential?
print('=== Wait potential comparison: AI vs Human cut suit ===')
ai_higher_wait = 0
human_higher_wait = 0
same = 0
for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    if to_raw(a).endswith('z') or to_raw(ai).endswith('z'): continue
    if ai == 'None' or not (a[0].isdigit() and ai[0].isdigit()): continue
    if a[0] in '19' or ai[0] in '19': continue
    if a[1] == ai[1]: continue  # skip same-suit
    hand_m = re.search(r'\u624b\u724c\(\d+\u679a\):\s*([^\n]+)', blk)
    hand = hand_m.group(1).split(',') if hand_m else []
    
    ai_wait = analyze_suit_potential(suit_vals(hand, ai[1]))
    human_wait = analyze_suit_potential(suit_vals(hand, a[1]))
    
    if ai_wait > human_wait:
        ai_higher_wait += 1
    elif human_wait > ai_wait:
        human_higher_wait += 1
    else:
        same += 1

print('AI cuts from HIGHER wait-potential suit: %d' % ai_higher_wait)
print('Human cuts from HIGHER wait-potential suit: %d' % human_higher_wait)
print('Same: %d' % same)
print()

# Multi-sided pattern preservation
print('=== Multi-sided pattern destroyed? ===')
ai_destroys_ms = 0
human_destroys_ms = 0
for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    if to_raw(a).endswith('z') or to_raw(ai).endswith('z'): continue
    if ai == 'None' or not (a[0].isdigit() and ai[0].isdigit()): continue
    if a[0] in '19' or ai[0] in '19': continue
    hand_m = re.search(r'\u624b\u724c\(\d+\u679a\):\s*([^\n]+)', blk)
    hand = hand_m.group(1).split(',') if hand_m else []
    
    # Check AI's choice suit
    ai_sv = suit_vals(hand, ai[1])
    ai_ms_before = count_multi_sided_patterns(ai_sv)
    # Simulate removing AI's tile
    ai_after = list(ai_sv)
    if int(ai[0]) in ai_after:
        ai_after.remove(int(ai[0]))
    ai_ms_after = count_multi_sided_patterns(ai_after)
    if ai_ms_before > ai_ms_after:
        ai_destroys_ms += 1
    
    # Check human's choice suit
    hu_sv = suit_vals(hand, a[1])
    hu_ms_before = count_multi_sided_patterns(hu_sv)
    hu_after = list(hu_sv)
    if int(a[0]) in hu_after:
        hu_after.remove(int(a[0]))
    hu_ms_after = count_multi_sided_patterns(hu_after)
    if hu_ms_before > hu_ms_after:
        human_destroys_ms += 1

print('AI destroys multi-sided pattern: %d' % ai_destroys_ms)
print('Human destroys multi-sided pattern: %d' % human_destroys_ms)
