import json, os
from collections import Counter

actor_reach = Counter()
actor_hora = Counter()
actor_ryukyoku = Counter()
actor_tenpai = Counter()
actor_yaku = Counter()
total_kyoku = 0
final_scores = []

for path in sorted(os.listdir('logs')):
    if not path.startswith('game_') or not path.endswith('.mjson'): continue
    full = os.path.join('logs', path)
    if os.path.getsize(full) < 1000: continue
    with open(full, 'r', encoding='utf-8') as f:
        for line in f:
            try: ev = json.loads(line.strip())
            except: continue
            t = ev.get('type')
            actor = ev.get('actor')
            if t == 'reach' and actor is not None:
                actor_reach[actor] += 1
            elif t == 'reach_accepted' and actor is not None:
                actor_tenpai[actor] += 1
            elif t == 'hora' and actor is not None:
                actor_hora[actor] += 1
                for y in ev.get('yaku', []):
                    actor_yaku[actor, y] += 1
            elif t == 'start_kyoku':
                total_kyoku += 1

print(f'総局数: {total_kyoku}')
print()
print('リーチ宣言:')
for a, c in sorted(actor_reach.items()):
    name = 'Akochan' if a == 3 else f'OurAI-{a}'
    print(f'  {name}: {c}回')
print()
print('和了(hora):')
for a, c in sorted(actor_hora.items()):
    name = 'Akochan' if a == 3 else f'OurAI-{a}'
    print(f'  {name}: {c}回')
print()
print('テンパイ(reach_accepted):')
for a, c in sorted(actor_tenpai.items()):
    name = 'Akochan' if a == 3 else f'OurAI-{a}'
    print(f'  {name}: {c}回')
print()
our_yaku = Counter(); ako_yaku = Counter()
for (a, y), c in actor_yaku.items():
    if a == 3: ako_yaku[y] += c
    else: our_yaku[y] += c
print('和了役(Our AI 上位5):')
for y, c in our_yaku.most_common(5): print(f'  役ID{y}: {c}回')
print('和了役(Akochan 上位5):')
for y, c in ako_yaku.most_common(5): print(f'  役ID{y}: {c}回')
