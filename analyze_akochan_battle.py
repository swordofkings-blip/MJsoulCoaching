import json
import os
import glob
from collections import Counter, defaultdict

honor_map = {'E':'1z','S':'2z','W':'3z','N':'4z','P':'5z','F':'6z','C':'7z'}
red5_map = {'5mr':'0m','5pr':'0p','5sr':'0s'}
def to_us(t):
    return honor_map.get(t, red5_map.get(t, t))

def parse_log(path):
    with open(path, 'r', encoding='utf-8') as f:
        events = []
        for line in f:
            try:
                events.append(json.loads(line.strip()))
            except:
                pass
    return events

# Aggregate stats
our_wins = 0
akochan_wins = 0
riichi_by_actor = Counter()
tenpai_by_actor = Counter()
agari_by_actor = Counter()
houju_by_actor = Counter()
yaku_by_actor = Counter()
kyoku_count = 0
total_events = 0

for path in sorted(glob.glob('logs/game_*.mjson'))[-100:]:
    if 'coach' in path: continue
    try:
        events = parse_log(path)
    except:
        continue
    if not events: continue
    
    kyoku_count += 1
    total_events += len(events)
    
    for ev in events:
        if ev.get('type') == 'reach' and 'actor' in ev:
            riichi_by_actor[ev['actor']] += 1
        if ev.get('type') == 'agari' and 'actor' in ev:
            agari_by_actor[ev['actor']] += 1
            if 'dora_ura_markers' in str(ev) or 'yaku' in ev:
                for y in ev.get('yaku', []):
                    yaku_by_actor[(ev['actor'], y)] += 1
        if ev.get('type') == 'reach_accepted' and 'actor' in ev:
            tenpai_by_actor[ev['actor']] += 1

print(f'=== 解析対象: {kyoku_count}ゲーム, 総イベント{total_events}件 ===')
print()

# Our AI is seats 0, 1, 2. Akochan is seat 3.
print('リーチ宣言数:')
for actor, cnt in sorted(riichi_by_actor.items()):
    name = 'Akochan' if actor == 3 else f'OurAI-{actor}'
    print(f'  {name}: {cnt}回')
print()
print('和了回数:')
for actor, cnt in sorted(agari_by_actor.items()):
    name = 'Akochan' if actor == 3 else f'OurAI-{actor}'
    print(f'  {name}: {cnt}回')
print()
print('和了役:')
yaku_by_our = 0; yaku_by_ako = 0
for (actor, yaku), cnt in yaku_by_actor.items():
    if actor == 3: yaku_by_ako += cnt
    else: yaku_by_our += cnt
print(f'  OurAI合計: {yaku_by_our}回')
print(f'  Akochan合計: {yaku_by_ako}回')
