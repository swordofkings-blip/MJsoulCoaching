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
    return {'seat': seat_idx, 'turn': turn, 'round': round_num}

def parse_hand(blk):
    m = re.search(r'手牌\(\d+枚\):\s*([^\n]+)', blk)
    return m.group(1).split(',') if m else []

def parse_scores(blk):
    score_m = re.search(r'スコア上位:\s*([^\n]+)', blk)
    if not score_m: return {}
    scores = {}
    for tile_s, val_s in re.findall(r'([^\s(,]+)\((-?\d+(?:\.\d+)?)\)', score_m.group(1)):
        scores[tile_s.strip(',')] = float(val_s)
    return scores

# Collect entries by pattern
by_pattern = defaultdict(list)

for blk in blocks:
    if 'AI判断:' in blk: continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m: continue
    actual, ai_best = m.group(1), m.group(2)
    
    scores = parse_scores(blk)
    if not scores: continue
    best_tile = max(scores, key=scores.get)
    best_score = scores[best_tile]
    
    actual_score = None
    for k, v in scores.items():
        if k == actual or to_raw(k) == to_raw(actual):
            actual_score = v; break
    if actual_score is None: continue
    
    diff = best_score - actual_score
    if diff < 1000: continue
    
    at, ait = tile_type(actual), tile_type(ai_best)
    pattern = '%s->%s' % (ait, at)
    hand = parse_hand(blk)
    sit = parse_sit(blk)
    
    by_pattern[pattern].append({
        'blk': blk, 'actual': actual, 'ai_best': ai_best,
        'diff': diff, 'best_score': best_score,
        'best_tile': best_tile, 'hand': hand, 'sit': sit,
        'actual_score': actual_score, 'scores': scores,
    })

for pattern in sorted(by_pattern.keys()):
    entries = by_pattern[pattern]
    print('=' * 70)
    print('Pattern: %s (%d cases)' % (pattern, len(entries)))
    print('=' * 70)
    
    # Turn distribution
    turn_dist = Counter(e['sit']['turn'] for e in entries if e['sit'])
    print('  巡目:', ', '.join('%d=%d' % (t, turn_dist[t]) for t in sorted(turn_dist)))
    
    # Hand composition analysis
    honor_count_dist = Counter()
    yaochu_count_dist = Counter()
    for e in entries:
        hand = e['hand']
        honor_count = sum(1 for h in hand if to_raw(h).endswith('z'))
        yaochu_count = sum(1 for h in hand if tile_type(h) == 'yaochu')
        honor_count_dist[honor_count] += 1
        yaochu_count_dist[yaochu_count] += 1
    
    print('  手牌字牌枚数:', ', '.join('%d=%d' % (k, honor_count_dist[k]) for k in sorted(honor_count_dist)))
    print('  手牌么九枚数:', ', '.join('%d=%d' % (k, yaochu_count_dist[k]) for k in sorted(yaochu_count_dist)))
    
    # AI recommend tile analysis  
    ai_tile_dist = Counter(e['ai_best'] for e in entries)
    human_tile_dist = Counter(e['actual'] for e in entries)
    print('  AI推奨 top5:', ', '.join('%s(%d)' % (t, ai_tile_dist[t]) for t, _ in ai_tile_dist.most_common(5)))
    print('  人間実打 top5:', ', '.join('%s(%d)' % (t, human_tile_dist[t]) for t, _ in human_tile_dist.most_common(5)))
    
    # Sample entries
    for i, e in enumerate(entries[:3]):
        s = e['sit']
        print('  --- sample %d (diff=%.0f) ---' % (i+1, e['diff']))
        if s: print('    %d巡目 seat=%d' % (s['turn'], s['seat']))
        print('    手牌: %s' % ','.join(e['hand']))
        print('    実打: %s | AI推奨: %s | スコア上位: %s' % (
            e['actual'], e['ai_best'],
            ', '.join('%s(%.0f)' % (t, s) for t, s in sorted(e['scores'].items(), key=lambda x: -x[1])[:5])))
    print()
