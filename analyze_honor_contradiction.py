import re
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
rev_honor = {v:k for k,v in honor_kanji.items()}
def to_raw(t): return honor_kanji.get(t, t)
def tile_type(t):
    r = to_raw(t)
    if r.endswith('z'): return 'H'
    if r[0] in '019' and not r.startswith('0'): return 'Y'
    return 'M'

def parse_sit(blk):
    m = re.search(r'([\u6771\u5357\u897f\u5317])\u5bb6(\(\u89aa\))?\s*/\s*(\d+)\u5c40\s*(\d+)\u672c\u5834\s*/\s*(\d+)\u5de1\u76ee', blk)
    if not m: return None
    return {'seat': m.group(1), 'round': int(m.group(3)), 'turn': int(m.group(5))}

def parse_hand(blk):
    m = re.search(r'\u624b\u724c\(\d+\u679a\):\s*([^\n]+)', blk)
    return m.group(1).split(',') if m else []

# Collect mid-game honor-mismatch cases
mh_mid = []  # M->H: AI keeps honor, human cuts it
hm_mid = []  # H->M: AI cuts honor, human keeps it

for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    a, ai = m.group(1), m.group(2)
    sit = parse_sit(blk)
    if not sit or not (5 <= sit['turn'] <= 10):
        continue
    
    at = tile_type(a); ait = tile_type(ai)
    hand = parse_hand(blk)
    
    if at == 'H' and ait == 'M':
        # Human cuts honor, AI keeps it
        honor_tile = a
        middle_tile = ai
        rec = ('M->H', blk, sit, hand, honor_tile, middle_tile)
        mh_mid.append(rec)
    elif at == 'M' and ait == 'H':
        # Human keeps honor, AI cuts it
        honor_tile = ai
        middle_tile = a
        rec = ('H->M', blk, sit, hand, honor_tile, middle_tile)
        hm_mid.append(rec)

print('=== 中盤(5-10巡) Honor矛盾分析 ===')
print('  M->H (AI字牌残し): %d件' % len(mh_mid))
print('  H->M (AI字牌切り): %d件' % len(hm_mid))
print()

# Analyze honor types
def honor_type(raw, seat_name, round_num):
    name = {'1z':'\u6771','2z':'\u5357','3z':'\u897f','4z':'\u5317','5z':'\u767d','6z':'\u767c','7z':'\u4e2d'}[raw]
    chang = (round_num - 1) // 4
    rw = ['\u6771','\u5357','\u897f','\u5317'][chang]
    sw = seat_name
    if name == sw == rw: return 'double'
    if name == sw: return 'self'
    if name == rw: return 'round'
    if raw in ('5z','6z','7z'): return 'sangen'
    return 'guest'

def count_honors_in_hand(hand):
    return sum(1 for h in hand if to_raw(h).endswith('z'))

for label, cases in [('M->H (AI残し)', mh_mid), ('H->M (AI切り)', hm_mid)]:
    print('=== %s ===' % label)
    print('  Count: %d' % len(cases))
    
    htype_dist = Counter()
    isolated = 0
    paired = 0
    multi_honor = 0
    threat = 0
    early_mid = 0; late_mid = 0
    
    for _, blk, sit, hand, ht, mt in cases:
        raw_ht = to_raw(ht)
        ht_type = honor_type(raw_ht, sit['seat'], sit['round'])
        htype_dist[ht_type] += 1
        
        # Isolated or paired?
        c = sum(1 for h in hand if to_raw(h) == raw_ht)
        if c >= 2: paired += 1
        else: isolated += 1
        
        # Honor count in hand
        if count_honors_in_hand(hand) >= 3:
            multi_honor += 1
        
        # Threat (reach)
        if '\u30ea\u30fc\u30c1' in blk:
            threat += 1
        
        # Turn
        if sit['turn'] <= 7: early_mid += 1
        else: late_mid += 1
    
    print('  Honor type:', ', '.join('%s=%d' % (t, htype_dist[t]) for t in sorted(htype_dist.keys())))
    print('  Isolated: %d  Paired: %d' % (isolated, paired))
    print('  3+ honors in hand: %d' % multi_honor)
    print('  Under reach: %d' % threat)
    print('  Turn 5-7: %d  Turn 8-10: %d' % (early_mid, late_mid))
    
    # Show 3 examples
    for i, (_, blk, sit, hand, ht, mt) in enumerate(cases[:3]):
        print('  Example %d: turn=%d honor=%s middle=%s hand=%s..' % (
            i+1, sit['turn'], ht, mt, ','.join(hand[:8])))
    print()
