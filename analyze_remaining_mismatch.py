"""
Detailed analysis of remaining mismatches after fix.
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')

with open('betadata_with_ai.pkl', 'rb') as f:
    data = pickle.load(f)

print(f'総局面: {len(data)}件')

# Categorize mismatches
mismatch_overpush = [d for d in data if d['ai_push'] and not d['human_push']]
mismatch_overfold = [d for d in data if not d['ai_push'] and d['human_push']]
match = [d for d in data if d['match']]

print(f'過剰押し(AI押す/人間オリる): {len(mismatch_overpush)}件')
print(f'過剰オリ(AIオリる/人間押す): {len(mismatch_overfold)}件')
print(f'一致: {len(match)}件')
print()

# === 過剰オリ(人間が押したのにAIはオリた)の詳細 ===
print('=== 過剰オリ(人間が押したのにAIオリた)のシャンテン×巡目 ===')
print(f'  {"":12}', end='')
for tr in [(1,5), (6,8), (9,11), (12,14), (15,18)]:
    print(f' 巡{tr[0]}-{tr[1]}', end='')
print()
for sh in [0, 1, 2, 3, 4, 5]:
    if sh == 5:
        subset = [d for d in mismatch_overfold if d['shanten'] >= 5]
        label = '5+'
    else:
        subset = [d for d in mismatch_overfold if d['shanten'] == sh]
        label = f'{sh}'
    print(f'  {label:12} ({len(subset):5})', end='')
    for lo, hi in [(1,5), (6,8), (9,11), (12,14), (15,18)]:
        s = [d for d in subset if lo <= d['turn'] <= hi]
        if s:
            print(f' {len(s):5}', end='')
        else:
            print(f'    - ', end='')
    print()

# 過剰オリのreach_n分布
print()
print('=== 過剰オリの対家リーチ数 ===')
reach_counter = Counter(d['reach_n'] for d in mismatch_overfold)
for rn in sorted(reach_counter.keys()):
    print(f'  reach={rn}: {reach_counter[rn]}件')

# 過剰オリの人間切った牌
print()
print('=== 過剰オリで人間が切った牌トップ20 ===')
tile_counter = Counter(d['discard_tile'] for d in mismatch_overfold)
for t, n in tile_counter.most_common(20):
    print(f'  {t}: {n}件')

# 過剰オリのmy_rank分布
print()
print('=== 過剰オリの自分の順位 ===')
rank_counter = Counter(d['my_rank'] for d in mismatch_overfold)
for r in sorted(rank_counter.keys()):
    print(f'  {r}位: {rank_counter[r]}件 ({rank_counter[r]/len(mismatch_overfold)*100:.1f}%)')

# 過剰オリの親率
print()
print(f'過剰オリの親率: {sum(1 for d in mismatch_overfold if d["is_dealer"])/len(mismatch_overfold)*100:.1f}%')

# === 過剰押しの詳細 ===
print()
print('=== 過剰押し(人間オリたのにAI押す)のシャンテン×巡目 ===')
print(f'  {"":12}', end='')
for tr in [(1,5), (6,8), (9,11), (12,14), (15,18)]:
    print(f' 巡{tr[0]}-{tr[1]}', end='')
print()
for sh in [0, 1, 2, 3, 4, 5]:
    if sh == 5:
        subset = [d for d in mismatch_overpush if d['shanten'] >= 5]
        label = '5+'
    else:
        subset = [d for d in mismatch_overpush if d['shanten'] == sh]
        label = f'{sh}'
    print(f'  {label:12} ({len(subset):5})', end='')
    for lo, hi in [(1,5), (6,8), (9,11), (12,14), (15,18)]:
        s = [d for d in subset if lo <= d['turn'] <= hi]
        if s:
            print(f' {len(s):5}', end='')
        else:
            print(f'    - ', end='')
    print()
