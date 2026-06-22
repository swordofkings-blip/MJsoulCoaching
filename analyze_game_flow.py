import json
from collections import Counter

with open('logs/game_0.mjson') as f:
    lines = f.readlines()

# ゲーム0: Akochan=actor 3
# 局ごとに集計
kyoku_count = 0
for i, line in enumerate(lines):
    try:
        d = json.loads(line)
        if d.get('type') == 'start_kyoku':
            kyoku_count += 1
            kyoku = d.get('kyoku')
            honba = d.get('honba')
            oya = d.get('oya')
            print(f'\n=== 局 {kyoku} 本場 {honba} 親 {oya} ===')
            # Print scores
            scores = d.get('scores')
            if scores:
                for s_idx, s in enumerate(scores):
                    print(f'  seat {s_idx}: {s}点')
        if d.get('type') == 'reach' and d.get('actor') == 3:
            print(f'  *** Akochan riichi ***')
        if d.get('type') == 'hora':
            print(f'  AGARI: {d}')
        if d.get('type') == 'ryukyoku':
            print(f'  流局: {d}')
    except:
        pass
