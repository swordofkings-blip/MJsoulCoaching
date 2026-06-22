import re, sys
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}

def to_raw(t):
    return honor_kanji.get(t, t)

def tile_type(t):
    r = to_raw(t)
    if r.endswith('z'): return 'honor'
    if r[0] in '019' and not r.startswith('0'): return 'yaochu'
    return 'middle'

def parse_sit(blk):
    m = re.search(r'([\u6771\u5357\u897f\u5317])\u5bb6(\\(\u89aa\\))?\\s*/\\s*(\\d+)\u5c40\\s*(\\d+)\u672c\u5834\\s*/\\s*(\\d+)\u5de1\u76ee', blk)
    if not m: return None
    return {'turn': int(m.group(5))}

def parse_hand(blk):
    m = re.search(r'\u624b\u724c\\(\\d+\u679a\\):\\s*([^\\n]+)', blk)
    return m.group(1).split(',') if m else []

def parse_scores(blk):
    score_m = re.search(r'\u30b9\u30b3\u30a2\u4e0a\u4f4d:\\s*([^\\n]+)', blk)
    if not score_m: return {}
    scores = {}
    for tile_s, val_s in re.findall(r'([^\\s(,]+)\\((-?\\d+(?:\\.\\d+)?)\\)', score_m.group(1)):
        scores[tile_s.strip(',')] = float(val_s)
    return scores

lines = []
def out(s=''):
    lines.append(s)

by_pattern = defaultdict(list)

for blk in blocks:
    if 'AI\u5224\u65ad:' in blk: continue
    m = re.search(r'actual:\\s*(\\S+)\\s*\\|\\s*AI\u63a8\u5968:\\s*(\\S+)', blk)
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
    out('=== Pattern: %s (%d cases) ===' % (pattern, len(entries)))
    
    turn_dist = Counter(e['sit']['turn'] for e in entries if e['sit'])
    out('  turns: %s' % ', '.join('%d=%d' % (t, turn_dist[t]) for t in sorted(turn_dist)))
    
    honor_count_dist = Counter()
    for e in entries:
        hand = e['hand']
        honor_count = sum(1 for h in hand if to_raw(h).endswith('z'))
        honor_count_dist[honor_count] += 1
    out('  honors_in_hand: %s' % ', '.join('%d=%d' % (k, honor_count_dist[k]) for k in sorted(honor_count_dist)))
    
    ai_tile_dist = Counter(e['ai_best'] for e in entries)
    human_tile_dist = Counter(e['actual'] for e in entries)
    out('  AI top5: %s' % ', '.join('%s(%d)' % (t, ai_tile_dist[t]) for t, _ in ai_tile_dist.most_common(5)))
    out('  Human top5: %s' % ', '.join('%s(%d)' % (t, human_tile_dist[t]) for t, _ in human_tile_dist.most_common(5)))
    
    for i, e in enumerate(entries[:3]):
        s = e['sit']
        out('  -- sample %d diff=%.0f --' % (i+1, e['diff']))
        if s: out('    turn=%d' % s['turn'])
        out('    hand: %s' % ','.join(e['hand']))
        out('    actual=%s ai=%s best=%s(%.0f)' % (e['actual'], e['ai_best'], e['best_tile'], e['best_score']))
        out('    scores: %s' % ', '.join('%s(%.0f)' % (t, s) for t, s in sorted(e['scores'].items(), key=lambda x: -x[1])[:5]))
    out('')

with open('big_diff_analysis.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('wrote big_diff_analysis.txt')
