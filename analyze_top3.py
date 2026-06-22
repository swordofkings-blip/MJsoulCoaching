import re, json
from collections import Counter

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'\u6771':'1z','\u5357':'2z','\u897f':'3z','\u5317':'4z','\u767d':'5z','\u767c':'6z','\u4e2d':'7z'}
def to_raw(t):
    return honor_kanji.get(t, t)

total = 0
in_top1 = 0
in_top3 = 0
in_top5 = 0
not_in_any = 0

for blk in blocks:
    if 'AI\u5224\u65ad:' in blk:
        continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI\u63a8\u5968:\s*(\S+)', blk)
    if not m:
        continue
    actual = m.group(1)
    ai_best = m.group(2)
    total += 1
    
    # Parse scores
    score_m = re.search(r'\u30b9\u30b3\u30a2\u4e0a\u4f4d:\s*([^\n]+)', blk)
    if not score_m:
        continue
    scores = {}
    for tile_s, val_s in re.findall(r'([^\s(,]+)\((-?\d+(?:\.\d+)?)\)', score_m.group(1)):
        scores[tile_s.strip(',')] = float(val_s)
    
    # Sort by score descending
    ranked = sorted(scores.keys(), key=lambda t: -scores[t])
    
    # Check rank of actual tile (handle kanji)
    actual_norm = actual
    for r in ranked:
        if r == actual or to_raw(r) == to_raw(actual):
            actual_norm = r
            break
    
    if actual_norm in ranked:
        rank = ranked.index(actual_norm) + 1
        if rank == 1:
            in_top1 += 1
        if rank <= 3:
            in_top3 += 1
        if rank <= 5:
            in_top5 += 1
    else:
        not_in_any += 1

print('=' * 50)
print('Top-1/3/5 Accuracy (Discard Mismatches Only)')
print('=' * 50)
print('Total decisions analyzed: %d' % total)
print()
print('Top-1 exact match:  %d/%d = %.1f%%' % (in_top1, total, in_top1/total*100))
print('Top-3 within:       %d/%d = %.1f%%' % (in_top3, total, in_top3/total*100))
print('Top-5 within:       %d/%d = %.1f%%' % (in_top5, total, in_top5/total*100))
print('Not in top-5:       %d/%d = %.1f%%' % (not_in_any, total, not_in_any/total*100))
print()
print('Note: These are from the MISMATCHES only (discard cases where')
print('AI and human disagree). The overall top-1 accuracy = match rate.')
print()

# Break down by situation
print('=' * 50)
print('By rank within top-5')
print('=' * 50)
rank_dist = Counter()
actor_not_found = 0
for blk in blocks:
    if 'AI\u5224\u65ad:' in blk:
        continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI\u63a8\u5968:\s*(\S+)', blk)
    if not m:
        continue
    actual = m.group(1)
    score_m = re.search(r'\u30b9\u30b3\u30a2\u4e0a\u4f4d:\s*([^\n]+)', blk)
    if not score_m:
        continue
    scores = {}
    for tile_s, val_s in re.findall(r'([^\s(,]+)\((-?\d+(?:\.\d+)?)\)', score_m.group(1)):
        scores[tile_s.strip(',')] = float(val_s)
    ranked = sorted(scores.keys(), key=lambda t: -scores[t])
    actual_norm = actual
    for r in ranked:
        if r == actual or to_raw(r) == to_raw(actual):
            actual_norm = r
            break
    if actual_norm in ranked:
        rank = ranked.index(actual_norm) + 1
        rank_dist[rank] += 1
    else:
        actor_not_found += 1

for r in sorted(rank_dist.keys()):
    print('  Rank %d: %d (%.1f%%)' % (r, rank_dist[r], rank_dist[r]/total*100))
print('  Not in top5: %d (%.1f%%)' % (actor_not_found, actor_not_found/total*100))
