import re, json
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'東':'1z','南':'2z','西':'3z','北':'4z','白':'5z','發':'6z','中':'7z'}
rev_honor = {v:k for k,v in honor_kanji.items()}

def to_raw(t):
    return honor_kanji.get(t, t)

def tile_type(t):
    r = to_raw(t)
    if r.endswith('z'): return 'honor'
    if r[0] in '019' and not r.startswith('0'): return 'yaochu'
    return 'middle'

def parse_sit(blk):
    m = re.search(r'([東西南北])家(\(親\))?\s*/\s*(\d+)局\s*(\d+)本場\s*/\s*(\d+)巡目', blk)
    if not m: return None
    seat_name = m.group(1)
    round_num = int(m.group(3))
    turn = int(m.group(5))
    seat_idx = {'東':0, '南':1, '西':2, '北':3}[seat_name]
    chang = (round_num - 1) // 4
    rw = ['東','南','西','北'][chang]
    sw = ['東','南','西','北'][seat_idx]
    return {'seat': seat_idx, 'sw': sw, 'rw': rw, 'turn': turn, 'round': round_num}

# Collect all entries with score diff >= 1000
big_diff_entries = []

for blk in blocks:
    if 'AI判断:' in blk:
        continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m:
        continue
    actual = m.group(1)
    ai_best = m.group(2)
    
    # Parse scores
    score_m = re.search(r'スコア上位:\s*([^\n]+)', blk)
    if not score_m:
        continue
    scores = {}
    # Match both raw tiles and kanji tiles
    for tile_s, val_s in re.findall(r'([^\s(,]+)\((-?\d+(?:\.\d+)?)\)', score_m.group(1)):
        scores[tile_s] = float(val_s)
    # Remove commas from keys if any
    scores = {k.strip(','): v for k, v in scores.items()}
    
    if not scores:
        continue
    
    best_tile = max(scores, key=scores.get)
    best_score = scores[best_tile]
    
    # Find actual tile's score (may be in kanji)
    actual_score = None
    for k, v in scores.items():
        if k == actual or to_raw(k) == to_raw(actual):
            actual_score = v
            break
    
    if actual_score is None:
        continue
    
    diff = best_score - actual_score
    if diff < 1000:
        continue
    
    sit = parse_sit(blk)
    hand_m = re.search(r'手牌\(\d+枚\):\s*([^\n]+)', blk)
    hand = hand_m.group(1).split(',') if hand_m else []
    
    river_section = blk.split('河:')[1] if '河:' in blk else ''
    reach_count = river_section.count('リーチ')
    
    big_diff_entries.append({
        'diff': diff,
        'actual': actual,
        'ai_best': ai_best,
        'best_tile': best_tile,
        'best_score': best_score,
        'actual_score': actual_score,
        'scores': scores,
        'sit': sit,
        'hand': hand,
        'reach_count': reach_count,
        'blk': blk,
    })

print('=== スコア差1000+ 件数: %d ===' % len(big_diff_entries))
print()

# Pattern analysis
patterns = Counter()
tile_type_patterns = Counter()
reach_dist = Counter()
turn_dist = Counter()
ai_pick_type_dist = Counter()
actual_type_dist = Counter()

for e in big_diff_entries:
    at = tile_type(e['actual'])
    ait = tile_type(e['ai_best'])
    patterns['%s->%s' % (ait, at)] += 1
    tile_type_patterns['AI:%s vs Human:%s' % (ait, at)] += 1
    reach_dist[e['reach_count']] += 1
    if e['sit']:
        turn_dist[e['sit']['turn']] += 1
    ai_pick_type_dist[ait] += 1
    actual_type_dist[at] += 1

print('=== 牌タイプ不一致パターン ===')
for k, cnt in patterns.most_common():
    print('  %s: %d' % (k, cnt))

print()
print('=== AI推奨の種類 ===')
for t, cnt in ai_pick_type_dist.most_common():
    print('  %s: %d' % (t, cnt))

print()
print('=== 人間実打の種類 ===')
for t, cnt in actual_type_dist.most_common():
    print('  %s: %d' % (t, cnt))

print()
print('=== リーチ状況分布 ===')
for k, cnt in reach_dist.most_common():
    print('  reach=%d: %d' % (k, cnt))

print()
print('=== 巡目分布 ===')
for t in sorted(turn_dist.keys()):
    print('  %d巡: %d' % (t, turn_dist[t]))

print()
print('=== サンプル10件表示 ===')
for i, e in enumerate(big_diff_entries[:10]):
    s = e['sit']
    print('--- #%d diff=%.0f ---' % (i+1, e['diff']))
    if s:
        print('  席=%s %d局 %d巡目 reach=%d' % (s['sw'], s['round'], s['turn'], e['reach_count']))
    print('  手牌: %s' % ','.join(e['hand']))
    print('  実打: %s | AI推奨: %s | Best: %s(%.0f)' % (e['actual'], e['ai_best'], e['best_tile'], e['best_score']))
    print('  スコア: %s' % ', '.join('%s(%.0f)' % (t, s) for t, s in sorted(e['scores'].items(), key=lambda x: -x[1])[:5]))
    print()
