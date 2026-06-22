import re, json
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
    m = re.search(r'([\u6771\u5357\u897f\u5317])\u5bb6(\(\u89aa\))?\s*/\s*(\d+)\u5c40\s*(\d+)\u672c\u5834\s*/\s*(\d+)\u5de1\u76ee', blk)
    if not m: return None
    return {'seat_name': m.group(1), 'round': int(m.group(3)), 'turn': int(m.group(5))}

# Collect all M->M cases
mm_cases = []
for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    if to_raw(a).endswith('z') or to_raw(ai).endswith('z'): continue
    if ai == 'None': continue
    if not (a[0].isdigit() and ai[0].isdigit()): continue
    if a[0] in '19' or ai[0] in '19': continue
    mm_cases.append({'blk': blk, 'actual': a, 'ai': ai})

print('Total M->M cases: %d' % len(mm_cases))
print()

# Detailed classification
def classify_case(blk, actual, ai_best):
    hand = parse_hand(blk)
    sit = parse_sit(blk)
    
    if not sit:
        return 'unknown'
    
    # Build counts per suit
    suit_tiles = {'m': [], 'p': [], 's': []}
    for h in hand:
        r = to_raw(h)
        if r.endswith('z'): continue
        suit = r[1]
        val = int(r[0])
        suit_tiles[suit].append(val)
    
    ai_suit = ai_best[1]
    human_suit = actual[1]
    ai_val = int(ai_best[0])
    human_val = int(actual[0])
    
    # 1. Same suit disagreement
    if ai_suit == human_suit:
        # Within same suit: which tile to cut?
        # Check if one is part of a complex shape and the other is isolated
        suit = ai_suit
        tiles = sorted(suit_tiles[suit])
        
        def is_isolated_in_suit(v, tiles_suit):
            return (v-1 not in tiles_suit and v+1 not in tiles_suit and
                    v-2 not in tiles_suit and v+2 not in tiles_suit)
        
        ai_isolated = is_isolated_in_suit(ai_val, tiles)
        human_isolated = is_isolated_in_suit(human_val, tiles)
        
        if ai_isolated and not human_isolated:
            return 'same_suit_ai_cuts_isolated_human_cuts_shape'
        elif not ai_isolated and human_isolated:
            return 'same_suit_human_cuts_isolated_ai_cuts_shape'
        elif not ai_isolated and not human_isolated:
            return 'same_suit_both_have_shape'
        else:
            return 'same_suit_both_isolated'
    
    # 2. Different suit disagreement  
    # Check dora
    dora_m = re.search(r'\u30c9\u30e9:\s*([^\n]+)', blk)
    dora_suit = None
    if dora_m:
        for d in re.findall(r'[0-9][a-z]', dora_m.group(1)):
            if d[1] != 'z':
                dora_suit = d[1]; break
    
    # Suit counts
    suit_counts = {s: len(t) for s, t in suit_tiles.items()}
    max_suit = max(suit_counts, key=suit_counts.get) if suit_counts else None
    
    ai_has_dora = (ai_suit == dora_suit)
    human_has_dora = (human_suit == dora_suit)
    ai_is_max = (ai_suit == max_suit)
    human_is_max = (human_suit == max_suit)
    
    # Check if suits have good shapes
    def has_shape(tiles_suit, v):
        return (v-1 in tiles_suit or v+1 in tiles_suit or
                v-2 in tiles_suit or v+2 in tiles_suit)
    
    ai_shape = has_shape(suit_tiles.get(ai_suit, []), ai_val)
    human_shape = has_shape(suit_tiles.get(human_suit, []), human_val)
    
    if ai_has_dora and not human_has_dora:
        # AI cuts from dora suit (bad), human doesn't
        return 'diff_suit_ai_cuts_dora_wrong'
    elif not ai_has_dora and human_has_dora:
        return 'diff_suit_human_cuts_dora_wrong'
    elif ai_is_max and not human_is_max:
        return 'diff_suit_ai_cuts_majority'
    elif not ai_is_max and human_is_max:
        return 'diff_suit_human_cuts_majority'
    elif ai_shape and not human_shape:
        return 'diff_suit_ai_cuts_shape_keeps_isolated'
    elif not ai_shape and human_shape:
        return 'diff_suit_human_cuts_shape_keeps_isolated'
    elif ai_val >= 5 and human_val <= 4:
        return 'diff_suit_ai_cuts_center_human_cuts_edge'
    elif ai_val <= 4 and human_val >= 5:
        return 'diff_suit_ai_cuts_edge_human_cuts_center'
    else:
        return 'diff_suit_other'

# Classify all cases
classifications = Counter()
for c in mm_cases:
    cat = classify_case(c['blk'], c['actual'], c['ai'])
    classifications[cat] += 1

print('=== Classification of M->M mismatches ===')
for cat, cnt in classifications.most_common():
    print('  %s: %d (%.1f%%)' % (cat, cnt, cnt/len(mm_cases)*100))
print()

# Now let's look at the most common categories with concrete examples
top_cats = [c for c, _ in classifications.most_common(10)]
for cat in top_cats:
    cat_cases = [c for c in mm_cases if classify_case(c['blk'], c['actual'], c['ai']) == cat]
    print('=== %s (%d cases) ===' % (cat, len(cat_cases)))
    for c in cat_cases[:3]:
        hand = parse_hand(c['blk'])
        sit = parse_sit(c['blk'])
        score_m = re.search(r'\u30b9\u30b3\u30a2\u4e0a\u4f4d:\s*([^\n]+)', c['blk'])
        scores = score_m.group(1) if score_m else ''
        print('  turn=%d hand=%s.. actual=%s ai=%s scores=%s' % (
            sit['turn'] if sit else -1, ','.join(hand[:8]),
            c['actual'], c['ai'], scores[:60]))
    print()
