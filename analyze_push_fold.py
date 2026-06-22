"""
@title ベタオリ/押す の決定要因を抽出
@description
    人間は「ベタオリの時は完全に安全な牌(def=0)、押す時は危険牌(def>0)」を切る。
    押す/オリるの状況要因を抽出する:
    - シャンテン数、巡目、点数、ランク、リーチ数
    - 親/子、ドラ、手役
"""
import pickle
import json
from collections import Counter, defaultdict
from statistics import mean

with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)

# 押す/オリる分類
# 人間: defense_score > 0 の牌を切っている = 押している
# 人間: defense_score == 0 の牌を切っている = オリている
push = [d for d in data if d['defense_score'] > 0]
fold = [d for d in data if d['defense_score'] == 0]

print(f'押す局面: {len(push)}件 ({len(push)/len(data)*100:.1f}%)')
print(f'オリる局面: {len(fold)}件 ({len(fold)/len(data)*100:.1f}%)')
print()

# 比較表
print('=== 押す vs オリる 比較 ===')
metrics = [
    ('平均シャンテン', lambda d: d['shanten'], '{:.1f}'),
    ('平均巡目', lambda d: d['turn'], '{:.1f}'),
    ('平均順位', lambda d: d['my_rank'], '{:.2f}'),
    ('平均点数', lambda d: d['my_score'], '{:.0f}'),
    ('親率', lambda d: d['is_dealer'], '{:.1%}'),
    ('平均対家リーチ数', lambda d: d['reach_n'], '{:.2f}'),
    ('平均シャンテン+リーチ数', lambda d: d['shanten'] + d['reach_n'], '{:.2f}'),
    ('平均シャンテン - 巡目/3', lambda d: d['shanten'] - d['turn']/3.0, '{:.2f}'),
]

for name, fn, fmt in metrics:
    push_val = fn(push[0]) if push else 0
    fold_val = fn(fold[0]) if fold else 0
    push_avg = mean(fn(d) for d in push) if push else 0
    fold_avg = mean(fn(d) for d in fold) if fold else 0
    print(f'  {name:25}: 押す={fmt.format(push_avg)}, オリる={fmt.format(fold_avg)}, 差={push_avg-fold_avg:+.2f}')

# 巡目×シャンテン別の押す率
print()
print('=== 巡目×シャンテン: 押す率(%) ===')
turn_bins = [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]
shanten_bins = [0, 1, 2, 3, 4, 5, 6]
print(f'  {"":12}', end='')
for lo, hi in turn_bins:
    print(f' 巡{lo}-{hi}', end='')
print()
for sh in shanten_bins:
    if sh == 6:
        subset = [d for d in data if d['shanten'] >= 6]
        label = f'6+'
    else:
        subset = [d for d in data if d['shanten'] == sh]
        label = f'{sh}シャンテン'
    n_total = len(subset)
    print(f'  {label:12} ({n_total:4})', end='')
    for lo, hi in turn_bins:
        s = [d for d in subset if lo <= d['turn'] <= hi]
        if s:
            push_n = sum(1 for d in s if d['defense_score'] > 0)
            rate = push_n / len(s) * 100
            print(f' {rate:4.0f}%', end='')
        else:
            print(f'   - ', end='')
    print()

# シャンテン数×リーチ数別の押す率
print()
print('=== シャンテン×対家リーチ数: 押す率(%) ===')
print(f'  {"":12}', end='')
for rn in [1, 2, 3]:
    print(f' reach={rn}', end='')
print()
for sh in shanten_bins:
    if sh == 6:
        subset = [d for d in data if d['shanten'] >= 6]
        label = f'6+'
    else:
        subset = [d for d in data if d['shanten'] == sh]
        label = f'{sh}シャンテン'
    print(f'  {label:12} ({len(subset):5})', end='')
    for rn in [1, 2, 3]:
        s = [d for d in subset if d['reach_n'] == rn]
        if s:
            push_n = sum(1 for d in s if d['defense_score'] > 0)
            rate = push_n / len(s) * 100
            print(f' {rate:4.0f}%', end='')
        else:
            print(f'   - ', end='')
    print()

# スコア差×リーチ数の押す率
print()
print('=== 自分の点数 - 1位との差 × リーチ数: 押す率(%) ===')
for d in data:
    sorted_scores = sorted(d['scores'], reverse=True)
    top_score = sorted_scores[0]
    d['score_gap_to_top'] = d['my_score'] - top_score

gap_bins = [(-99999, -15000), (-15000, -5000), (-5000, 0), (0, 5000), (5000, 15000), (15000, 99999)]
gap_labels = ['-15k以下', '-15k〜-5k', '-5k〜0', '0〜5k', '5k〜15k', '15k以上']
print(f'  {"":18}', end='')
for rn in [1, 2]:
    print(f' reach={rn}', end='')
print()
for (lo, hi), label in zip(gap_bins, gap_labels):
    s = [d for d in data if lo <= d['score_gap_to_top'] < hi]
    print(f'  {label:18} ({len(s):5})', end='')
    for rn in [1, 2]:
        sn = [d for d in s if d['reach_n'] == rn]
        if sn:
            push_n = sum(1 for d in sn if d['defense_score'] > 0)
            rate = push_n / len(sn) * 100
            print(f' {rate:4.0f}%', end='')
        else:
            print(f'   - ', end='')
    print()
