import re, json
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()

# Split by full mismatch blocks
# Each block starts with '===== 不一致 #N [file] ====='
blocks = re.split(r'(===== 不一致 #\d+ \[[^\]]+\] =====)', text)[1:]
# Interleave: [header1, body1, header2, body2, ...]
entries = []
for i in range(0, len(blocks), 2):
    header = blocks[i]
    body = blocks[i+1] if i+1 < len(blocks) else ''
    entries.append(header + body)

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

# Parse situation line for seat and round info
def parse_situation(blk):
    # Examples:
    # "東家(親) / 1局 0本場 / 1巡目(1ツモ)"
    # "南家 / 1局 0本場 / 2巡目(6ツモ)"
    sit_m = re.search(r'([東西南北])家(\(親\))?\s*/\s*(\d+)局\s*(\d+)本場\s*/\s*(\d+)巡目', blk)
    if not sit_m:
        return None
    seat_name = sit_m.group(1)
    is_dealer = sit_m.group(2) is not None
    round_num = int(sit_m.group(3))  # 0-indexed: 1局=round0, 2局=round1, etc.
    turn = int(sit_m.group(5))
    
    seat_idx = {'東':0, '南':1, '西':2, '北':3}[seat_name]
    chang = (round_num - 1) // 4  # 0=東場, 1=南場
    ju = (round_num - 1) % 4
    round_wind_id = chang  # 0=東, 1=南
    round_wind = ['東','南','西','北'][round_wind_id]
    self_wind = ['東','南','西','北'][seat_idx]
    
    # Determine honor value
    # 自風 = self_wind
    # 場風 = round_wind
    # 三元牌 = 白發中
    # 客風 = neither self, round, nor sangen
    
    return {
        'seat': seat_idx,
        'self_wind': self_wind,
        'round_wind': round_wind,
        'is_dealer': is_dealer,
        'turn': turn,
        'round_num': round_num,
        'chang': chang,
        'ju': ju,
    }

def get_honor_category(honor_raw, self_wind, round_wind):
    """honor_raw is like '1z', '6z'"""
    honor_name = {'1z':'東','2z':'南','3z':'西','4z':'北','5z':'白','6z':'發','7z':'中'}[honor_raw]
    if honor_name == self_wind and honor_name == round_wind:
        return 'ダブ東(自風+場風)' if honor_name == '東' else 'ダブ南(自風+場風)'
    if honor_name == self_wind:
        return '自風(%s)' % self_wind
    if honor_name == round_wind:
        return '場風(%s)' % round_wind
    if honor_raw in ('5z','6z','7z'):
        return '三元牌(%s)' % honor_name
    return '客風(%s)' % honor_name

# Collect detail for each honor mismatch
honor_mismatch_details = []
other_mismatch_samples = []

for entry in entries:
    if 'AI判断:' in entry:
        continue  # skip meld mismatches
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', entry)
    if not m:
        continue
    actual = m.group(1)
    ai_best = m.group(2)
    
    at = to_raw(actual)
    ait = to_raw(ai_best)
    
    if not (at.endswith('z') and not ait.endswith('z')):
        continue  # only interested in human-cuts-honor cases
    
    # Full context
    sit = parse_situation(entry)
    hand_m = re.search(r'手牌\(\d+枚\):\s*([^\n]+)', entry)
    hand = hand_m.group(1).split(',') if hand_m else []
    
    # River
    river_section = entry.split('河:')[1] if '河:' in entry else ''
    river_lines = river_section.strip().split('\n')
    
    # Score top5
    score_m = re.search(r'スコア上位:\s*([^\n]+)', entry)
    scores_line = score_m.group(1) if score_m else ''
    
    # Dora
    dora_m = re.search(r'ドラ:\s*([^\n]+)', entry)
    doras = dora_m.group(1) if dora_m else ''
    
    # Count honors in hand
    honor_count = sum(1 for h in hand if to_raw(h).endswith('z'))
    raw_actual = to_raw(actual)
    actual_count = sum(1 for h in hand if to_raw(h) == raw_actual)
    isolated = actual_count == 1
    
    honor_category = ''
    if sit:
        honor_category = get_honor_category(at, sit['self_wind'], sit['round_wind'])
    
    entry_rec = {
        'entry_text': entry,
        'actual': actual,
        'ai_best': ai_best,
        'honor_raw': at,
        'situation': sit,
        'hand': hand,
        'honor_count': honor_count,
        'isolated': isolated,
        'honor_category': honor_category,
        'scores_line': scores_line,
        'river_lines': river_lines,
        'doras': doras,
    }
    honor_mismatch_details.append(entry_rec)

print('Total honor mismatches (human cuts honor, AI picks non-honor): %d' % len(honor_mismatch_details))

# Categorize by honor type
cat_counter = Counter(e['honor_category'] for e in honor_mismatch_details)
print()
print('=== 字牌の価値カテゴリ別 ===')
for cat, cnt in cat_counter.most_common():
    print('  %s: %d' % (cat, cnt))

# Isolated vs paired
iso_count = sum(1 for e in honor_mismatch_details if e['isolated'])
paired_count = sum(1 for e in honor_mismatch_details if not e['isolated'])
print()
print('=== 孤立字牌: %d, 対子: %d ===' % (iso_count, paired_count))

# By turn
turn_dist = Counter()
for e in honor_mismatch_details:
    if e['situation']:
        turn_dist[e['situation']['turn']] += 1
print()
print('=== 巡目分布 (top 10) ===')
for t, cnt in sorted(turn_dist.items())[:10]:
    print('  %d巡目: %d' % (t, cnt))

# Honor count in hand distribution
honor_count_dist = Counter(e['honor_count'] for e in honor_mismatch_details)
print()
print('=== 手牌内字牌枚数 ===')
for cnt in sorted(honor_count_dist.keys()):
    print('  %d枚: %d' % (cnt, honor_count_dist[cnt]))
print()

# ===== SHOW CONCRETE EXAMPLES =====
# Show examples grouped by category
for cat in ['客風(北)', '客風(西)', '場風(東)', '三元牌(白)', '三元牌(發)', '三元牌(中)', '自風(東)', '自風(南)']:
    cat_entries = [e for e in honor_mismatch_details if e['honor_category'] == cat and e['isolated'] and e['situation'] and e['situation']['turn'] <= 6]
    if not cat_entries:
        continue
    print('=' * 60)
    print('例: %s (孤立, %d例中から2つ)' % (cat, len([e for e in honor_mismatch_details if e['honor_category'] == cat])))
    print('=' * 60)
    for sample in cat_entries[:2]:
        s = sample['situation']
        print('  南%d局 %d巡目 席=%s' % (s['round_num'], s['turn'], ['東','南','西','北'][s['seat']]))
        print('  手牌: %s' % ','.join(sample['hand']))
        print('  実打: %s | AI推奨: %s' % (sample['actual'], sample['ai_best']))
        print('  スコア: %s' % sample['scores_line'])
        print()
