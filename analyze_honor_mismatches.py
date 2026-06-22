import re, json
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'東':'1z','南':'2z','西':'3z','北':'4z','白':'5z','發':'6z','中':'7z'}
honor_kanji_rev = {v:k for k,v in honor_kanji.items()}

def to_raw(tile):
    if tile in honor_kanji:
        return honor_kanji[tile]
    return tile

def tile_type(t):
    r = to_raw(t)
    if r.endswith('z'):
        return 'honor'
    if r[0] in '019' and not r.startswith('0'):
        return 'yaochu'
    return 'middle'

# Category honor mismatches
honor_mismatches = {
    'ai_middle_human_honor': [],
    'ai_yaochu_human_honor': [],
    'all': [],
}

for blk in blocks:
    if 'AI判断:' in blk:
        continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m:
        continue
    actual = m.group(1)
    ai_best = m.group(2)
    
    at = tile_type(actual)
    ait = tile_type(ai_best)
    
    if at == 'honor' and ait != 'honor':
        # 1) Extract turn
        turn_m = re.search(r'(\d+)巡目', blk)
        turn = int(turn_m.group(1)) if turn_m else -1
        
        # 2) Extract hand
        hand_m = re.search(r'手牌\(\d+枚\):\s*([^\n]+)', blk)
        hand = hand_m.group(1).split(',') if hand_m else []
        
        # 3) Count honors in hand (raw format)
        honor_count = sum(1 for h in hand if to_raw(h).endswith('z'))
        
        # 4) Is actual honor isolated?
        # (check if same honor is elsewhere in hand)
        raw_actual = to_raw(actual)
        actual_count = sum(1 for h in hand if to_raw(h) == raw_actual)
        isolated = actual_count == 1
        
        # 5) Score difference
        score_m = re.search(r'スコア上位:\s*([^\n]+)', blk)
        scores_top = []
        if score_m:
            for tile_s, val_s in re.findall(r'([0-9a-zA-Z]+)\((-?\d+(?:\.\d+)?)\)', score_m.group(1)):
                scores_top.append((tile_s, float(val_s)))
        best_score = scores_top[0][1] if scores_top else 0
        actual_score = None
        for tile_s, val_s in scores_top:
            if tile_s == actual or to_raw(tile_s) == raw_actual:
                actual_score = val_s
                break
        
        entry = {
            'turn': turn,
            'hand': hand,
            'honor_count': honor_count,
            'actual': actual,
            'ai_best': ai_best,
            'isolated': isolated,
            'best_score': best_score,
            'actual_score': actual_score,
            'type': 'ai_%s_human_honor' % tile_type(ai_best),
        }
        honor_mismatches['all'].append(entry)
        honor_mismatches[entry['type']].append(entry)

print('=== 字牌ミスマッチ全体像 ===')
print('  total: %d' % len(honor_mismatches['all']))
print('  AI middle -> human honor: %d' % len(honor_mismatches['ai_middle_human_honor']))
print('  AI yaochu -> human honor: %d' % len(honor_mismatches['ai_yaochu_human_honor']))
print()

# Turn distribution
turn_dist = Counter(e['turn'] for e in honor_mismatches['all'])
print('=== 巡目分布 ===')
for t in sorted(turn_dist.keys()):
    print('  %d巡目: %d' % (t, turn_dist[t]))
print()

# Honor count in hand
honor_count_dist = Counter(e['honor_count'] for e in honor_mismatches['all'])
print('=== 手牌内字牌枚数分布 ===')
for cnt in sorted(honor_count_dist.keys()):
    print('  %d枚: %d' % (cnt, honor_count_dist[cnt]))
print()

# Isolated vs paired
iso_count = sum(1 for e in honor_mismatches['all'] if e['isolated'])
paired_count = sum(1 for e in honor_mismatches['all'] if not e['isolated'])
print('=== 孤立/対子の内訳 ===')
print('  孤立字牌: %d' % iso_count)
print('  対子以上: %d' % paired_count)
print()

# Human actual honor breakdown
honor_actual_dist = Counter(to_raw(e['actual']) for e in honor_mismatches['all'])
print('=== 人間が切った字牌 ===')
for h, cnt in sorted(honor_actual_dist.items(), key=lambda x: -x[1]):
    print('  %s: %d' % (h, cnt))
print()

# AI best tile patterns when human cuts honor
ai_best_dist = Counter(e['ai_best'] for e in honor_mismatches['all'])
print('=== AIが推した牌(字牌ミスマッチ時) top 15 ===')
for t, cnt in ai_best_dist.most_common(15):
    print('  %s: %d' % (t, cnt))
print()

# Score difference analysis
diff_scores = []
for e in honor_mismatches['all']:
    if e['actual_score'] is not None:
        diff_scores.append(e['best_score'] - e['actual_score'])

print('=== スコア差 ===')
if diff_scores:
    print('  mean: %.1f' % (sum(diff_scores)/len(diff_scores)))
    print('  median: %.1f' % sorted(diff_scores)[len(diff_scores)//2])
    print('  >=1000: %d' % sum(1 for d in diff_scores if d >= 1000))
    print('  300-999: %d' % sum(1 for d in diff_scores if 300 <= d < 1000))
    print('  <300: %d' % sum(1 for d in diff_scores if d < 300))

# Sample detailed entries for deep analysis
print()
print('=== サンプル(孤立字牌、中盤、スコア差大) ===')
samples = [e for e in honor_mismatches['all'] if e['isolated'] and 3 <= e['turn'] <= 8 and e['actual_score'] is not None and e['best_score'] - e['actual_score'] >= 300]
print('  matched: %d entries' % len(samples))
