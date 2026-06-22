import re, json
from collections import Counter

with open('tools/mismatches_tenhou_10.txt', 'r', encoding='utf-8') as f:
    text = f.read()
blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]

honor_kanji = {'東':'1z','南':'2z','西':'3z','北':'4z','白':'5z','發':'6z','中':'7z'}

def tile_type(t):
    if t in honor_kanji or (len(t)==2 and t[1]=='z'):
        return 'honor'
    if t[0] in '019' and not t.startswith('0'):
        return 'yaochu'
    return 'middle'

counter = Counter()
ai_honors = 0; human_honors = 0
ai_yaochu = 0; human_yaochu = 0
ai_mid = 0; human_mid = 0

for blk in blocks:
    if 'AI判断:' in blk:
        continue
    m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
    if not m:
        continue
    a, ai = m.group(1), m.group(2)
    
    at = tile_type(a)
    ait = tile_type(ai)
    
    if ait == 'honor': ai_honors += 1
    if at == 'honor': human_honors += 1
    if ait == 'yaochu': ai_yaochu += 1
    if at == 'yaochu': human_yaochu += 1
    if ait == 'middle': ai_mid += 1
    if at == 'middle': human_mid += 1
    
    if at != ait:
        counter['%s->%s' % (ait, at)] += 1

    # Specific pattern: AI keeps honor, human discards it
    if at == 'honor' and ait != 'honor':
        # Human discarded an honor, AI recommended something else
        print('HUMAN CUTS HONOR: actual=%s ai=%s' % (a, ai))

results = [
    'Total discard mismatches: %d' % len(blocks),
    '',
    'AI 推奨: honor=%d, yaochu=%d, middle=%d' % (ai_honors, ai_yaochu, ai_mid),
    'Human 実打: honor=%d, yaochu=%d, middle=%d' % (human_honors, human_yaochu, human_mid),
    '',
    'AI vs Human 差: honor=%+d, yaochu=%+d, middle=%+d' % (
        human_honors - ai_honors, human_yaochu - ai_yaochu, human_mid - ai_mid),
    '',
    '=== パターン別 ===',
]
for k, cnt in counter.most_common():
    results.append('  %s: %d' % (k, cnt))

with open('mismatch_detailed_analysis.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(results))

print('wrote mismatch_detailed_analysis.txt')
