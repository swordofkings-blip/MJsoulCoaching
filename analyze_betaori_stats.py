"""
@title ベタオリ分析: 押す/オリるの境界パターン
@description
    78,504件のベタオリ局面から、人間が「押した」/「オリた」のパターンを抽出する。

    押す/オリるの判定:
    - 人間が「押した」: 切った牌の defense_score が低い(=安全牌) → オリていない
      - または、テンパイ/好形1シャンテンで、押すべき場面で押した
    - 人間が「オリた」: 切った牌の defense_score が高い(=危険牌を避けた)

    実はdefense_score=0が大量にある = 安全牌を切っているケースが大多数
    → 人間は「ベタオリのときは安全な牌だけ切る」のが普通

    問題は「ベタオリすべきでない場面でベタオリしている」と
        「押すべき場面で押している/していない」
"""
import pickle
import numpy as np
from collections import Counter, defaultdict
from statistics import mean, median

with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)

print(f'総局面: {len(data)}件')
print()


def rank_to_str(r):
    return f'{r:.1f}'

# === 1. defense_score の分布 ===
defense_scores = [d['defense_score'] for d in data]
print('=== defense_score 分布 ===')
score_counter = Counter()
for s in defense_scores:
    if s == 0: bucket = '0'
    elif s < 100: bucket = '1-99'
    elif s < 500: bucket = '100-499'
    elif s < 1000: bucket = '500-999'
    elif s < 2000: bucket = '1000-1999'
    elif s < 5000: bucket = '2000-4999'
    else: bucket = '5000+'
    score_counter[bucket] += 1

for k in ['0', '1-99', '100-499', '500-999', '1000-1999', '2000-4999', '5000+']:
    pct = score_counter[k] / len(data) * 100
    print(f'  {k:12}: {score_counter[k]:6}件 ({pct:5.1f}%)')

print()
print(f'平均: {mean(defense_scores):.0f}, 中央: {median(defense_scores):.0f}')

# === 2. シャンテン数別の分布 ===
print()
print('=== シャンテン数別: 人間の判断 ===')
shanten_data = defaultdict(list)
for d in data:
    shanten_data[d['shanten']].append(d)

for shanten in sorted(shanten_data.keys()):
    subset = shanten_data[shanten]
    n = len(subset)
    avg_def = mean(d['defense_score'] for d in subset)
    avg_turn = mean(d['turn'] for d in subset)
    avg_rank = mean(d['my_rank'] for d in subset)
    is_dealer_pct = sum(1 for d in subset if d['is_dealer']) / n * 100
    print(f'  {shanten}シャンテン: {n:5}件, 平均巡目{avg_turn:4.1f}, '
          f'平均defense={avg_def:6.0f}, {is_dealer_pct:4.1f}%親, 平均{rank_to_str(avg_rank)}位')

def rank_to_str(r):
    return f'{r:.1f}'

# === 3. 巡目×押す/オリる ===
print()
print('=== 巡目×人間判断 ===')
turn_bins = [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]
for lo, hi in turn_bins:
    subset = [d for d in data if lo <= d['turn'] <= hi]
    if not subset: continue
    n = len(subset)
    # 押す(defense_score<500) vs オリる(defense_score>=500)
    push_count = sum(1 for d in subset if d['defense_score'] < 500)
    fold_count = sum(1 for d in subset if d['defense_score'] >= 500)
    avg_score = mean(d['defense_score'] for d in subset)
    print(f'  巡目{lo:2}-{hi:2}: {n:5}件, 押す(def<500){push_count:5}({push_count/n*100:4.1f}%), '
          f'オリる(def>=500){fold_count:5}({fold_count/n*100:4.1f}%), avg_def={avg_score:5.0f}')

# === 4. 自分の順位×押す ===
print()
print('=== 自分の順位×押す/オリる ===')
for r in [1, 2, 3, 4]:
    subset = [d for d in data if d['my_rank'] == r]
    if not subset: continue
    n = len(subset)
    push_count = sum(1 for d in subset if d['defense_score'] < 500)
    fold_count = sum(1 for d in subset if d['defense_score'] >= 500)
    avg_score = mean(d['defense_score'] for d in subset)
    print(f'  {r}位: {n:5}件, 押す{push_count:5}({push_count/n*100:4.1f}%), '
          f'オリる{fold_count:5}({fold_count/n*100:4.1f}%), avg_def={avg_score:5.0f}')

# === 5. リーチ者数 ===
print()
print('=== 対家リーチ数×押す/オリる ===')
for rn in [1, 2, 3]:
    subset = [d for d in data if d['reach_n'] == rn]
    if not subset: continue
    n = len(subset)
    push_count = sum(1 for d in subset if d['defense_score'] < 500)
    fold_count = sum(1 for d in subset if d['defense_score'] >= 500)
    avg_score = mean(d['defense_score'] for d in subset)
    print(f'  reach={rn}: {n:5}件, 押す{push_count:5}({push_count/n*100:4.1f}%), '
          f'オリる{fold_count:5}({fold_count/n*100:4.1f}%), avg_def={avg_score:5.0f}')

# === 6. 親 vs 子 ===
print()
print('=== 親 vs 子 ===')
for label, pred in [('親', lambda d: d['is_dealer']), ('子', lambda d: not d['is_dealer'])]:
    subset = [d for d in data if pred(d)]
    if not subset: continue
    n = len(subset)
    push_count = sum(1 for d in subset if d['defense_score'] < 500)
    fold_count = sum(1 for d in subset if d['defense_score'] >= 500)
    avg_score = mean(d['defense_score'] for d in subset)
    print(f'  {label}: {n:5}件, 押す{push_count:5}({push_count/n*100:4.1f}%), '
          f'オリる{fold_count:5}({fold_count/n*100:4.1f}%), avg_def={avg_score:5.0f}')

# === 7. 待ち判定の指針 ===
# 人間がオリる = シャンテン進める打牌をしてない
# テンパイ(0シャンテン)でオリている = ベタオリ中
print()
print('=== テンパイ(0シャンテン)×押す/オリる ===')
subset = [d for d in data if d['shanten'] == 0]
if subset:
    n = len(subset)
    push_count = sum(1 for d in subset if d['defense_score'] < 500)
    fold_count = sum(1 for d in subset if d['defense_score'] >= 500)
    avg_score = mean(d['defense_score'] for d in subset)
    print(f'  テンパイ: {n}件, 押す{push_count}({push_count/n*100:.1f}%), '
          f'オリる{fold_count}({fold_count/n*100:.1f}%)')
    # テンパイでオリる = ベタオリ(他家打牌で和了を狙う)
    subset_ori = [d for d in subset if d['defense_score'] >= 500]
    if subset_ori:
        avg_turn = mean(d['turn'] for d in subset_ori)
        avg_rank = mean(d['my_rank'] for d in subset_ori)
        print(f'  テンパイでオリる: {len(subset_ori)}件, 平均巡目{avg_turn:.1f}, 平均{rank_to_str(avg_rank)}位')

print()
print('=== 1シャンテン×押す/オリる ===')
subset = [d for d in data if d['shanten'] == 1]
if subset:
    n = len(subset)
    push_count = sum(1 for d in subset if d['defense_score'] < 500)
    fold_count = sum(1 for d in subset if d['defense_score'] >= 500)
    avg_score = mean(d['defense_score'] for d in subset)
    print(f'  1シャンテン: {n}件, 押す{push_count}({push_count/n*100:.1f}%), '
          f'オリる{fold_count}({fold_count/n*100:.1f}%)')

# === 8. 待ち改善の試み ===
# オリている(オリ=def>=500)とき、手変わり狙いで切る牌は普通の中張牌
# 押している(押す=def<500)とき、ロンを狙いに行く牌
print()
print('=== 押す/オリると切った牌の種類 ===')
push_tiles = [d['discard_tile'] for d in data if d['defense_score'] < 500]
fold_tiles = [d['discard_tile'] for d in data if d['defense_score'] >= 500]

# 字牌の割合
def is_honor_tile(t):
    return t.endswith('z') or t.endswith('h')

honor_push = sum(1 for t in push_tiles if is_honor_tile(t)) / len(push_tiles) * 100 if push_tiles else 0
honor_fold = sum(1 for t in fold_tiles if is_honor_tile(t)) / len(fold_tiles) * 100 if fold_tiles else 0
print(f'  押す時 字牌率: {honor_push:.1f}%, オリる時 字牌率: {honor_fold:.1f}%')

# 端牌の割合
def is_terminal_tile(t):
    return t.startswith('1') or t.startswith('9')
term_push = sum(1 for t in push_tiles if is_terminal_tile(t)) / len(push_tiles) * 100 if push_tiles else 0
term_fold = sum(1 for t in fold_tiles if is_terminal_tile(t)) / len(fold_tiles) * 100 if fold_tiles else 0
print(f'  押す時 端牌率: {term_push:.1f}%, オリる時 端牌率: {term_fold:.1f}%')
