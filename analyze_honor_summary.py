import re, json
from collections import Counter, defaultdict

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'(===== 不一致 #\d+ \[[^\]]+\] =====)', text)[1:]
entries = []
for i in range(0, len(blocks), 2):
    entries.append(blocks[i] + (blocks[i+1] if i+1 < len(blocks) else ''))

honor_kanji = {'東':'1z','南':'2z','西':'3z','北':'4z','白':'5z','發':'6z','中':'7z'}

def to_raw(tile):
    return honor_kanji.get(tile, tile)

def tile_is_honor(t):
    return to_raw(t).endswith('z')

def parse_sit(blk):
    m = re.search(r'([東西南北])家(\(親\))?\s*/\s*(\d+)局\s*(\d+)本場\s*/\s*(\d+)巡目', blk)
    if not m:
        return None
    seat_name = m.group(1)
    round_num = int(m.group(3))
    turn = int(m.group(5))
    seat_idx = {'東':0, '南':1, '西':2, '北':3}[seat_name]
    chang = (round_num - 1) // 4
    rw = ['東','南','西','北'][chang]
    sw = ['東','南','西','北'][seat_idx]
    return {'seat': seat_idx, 'sw': sw, 'rw': rw, 'turn': turn, 'round': round_num}

def honor_cat(raw, sw, rw):
    name = {'1z':'東','2z':'南','3z':'西','4z':'北','5z':'白','6z':'發','7z':'中'}[raw]
    if name == sw == rw: return 'double_wind'
    if name == sw: return 'self_wind'
    if name == rw: return 'round_wind'
    if raw in ('5z','6z','7z'): return 'sangen'
    return 'guest_wind'

cats = Counter()
by_cat_detail = defaultdict(list)
turn_dist = Counter()
honor_count_dist = Counter()
ai_pick_dist = Counter()
score_line_samples = []

for entry in entries:
    if 'AI判断:' in entry:
        continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', entry)
    if not m:
        continue
    actual = m.group(1)
    ai_best = m.group(2)
    if not (tile_is_honor(actual) and not tile_is_honor(ai_best)):
        continue
    sit = parse_sit(entry)
    if not sit:
        continue
    raw = to_raw(actual)
    cat = honor_cat(raw, sit['sw'], sit['rw'])
    cats[cat] += 1
    turn_dist[sit['turn']] += 1

    hand_m = re.search(r'手牌\(\d+枚\):\s*([^\n]+)', entry)
    hand = hand_m.group(1).split(',') if hand_m else []
    honor_count = sum(1 for h in hand if tile_is_honor(h))
    honor_count_dist[honor_count] += 1
    ai_pick_dist[ai_best] += 1

    # Check if actual honor is isolated
    raw_actual = to_raw(actual)
    actual_count = sum(1 for h in hand if to_raw(h) == raw_actual)
    isolated = actual_count == 1

    by_cat_detail[cat].append({
        'turn': sit['turn'],
        'round': sit['round'],
        'seat': ['東','南','西','北'][sit['seat']],
        'hand': hand,
        'actual': actual,
        'ai': ai_best,
        'isolated': isolated,
        'honor_count': honor_count,
    })

# Write summary
lines = []
lines.append('=== 字牌ミスマッチ 価値カテゴリ別 ===')
total = sum(cats.values())
for cat, cnt in cats.most_common():
    lines.append('  %s: %d (%.1f%%)' % (cat, cnt, cnt/total*100))
lines.append('  total: %d' % total)

lines.append('')
lines.append('=== 孤立 vs 対子 ===')
iso = sum(1 for v in by_cat_detail.values() for e in v if e['isolated'])
all_e = sum(len(v) for v in by_cat_detail.values())
lines.append('  孤立: %d (%.1f%%)' % (iso, iso/all_e*100))
lines.append('  対子以上: %d' % (all_e - iso))

lines.append('')
lines.append('=== 手牌内字牌枚数 ===')
for cnt in sorted(honor_count_dist.keys()):
    lines.append('  %d枚: %d' % (cnt, honor_count_dist[cnt]))

lines.append('')
lines.append('=== AIが推した牌 top 15 ===')
for t, cnt in ai_pick_dist.most_common(15):
    lines.append('  %s: %d' % (t, cnt))

lines.append('')
lines.append('=== カテゴリ別 詳細サンプル ===')
for cat in ['guest_wind', 'sangen', 'self_wind', 'round_wind', 'double_wind']:
    cat_entries = [e for e in by_cat_detail.get(cat, []) if e['isolated'] and e['turn'] <= 6]
    if not cat_entries:
        continue
    lines.append('')
    lines.append('--- %s (%d samples) ---' % (cat, len(cat_entries)))
    for e in cat_entries[:3]:
        lines.append('  S%s %d局 %d巡: 手牌=%s, 実打=%s, AI=%s (字牌%d枚)' % (
            e['seat'], e['round'], e['turn'],
            ','.join(e['hand']), e['actual'], e['ai'], e['honor_count']))

with open('honor_mismatch_summary.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print('wrote honor_mismatch_summary.txt')
