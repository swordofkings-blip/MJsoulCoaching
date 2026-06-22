"""
@title 過剰押しミスマッチの詳細分析
@description
    AI押す&人間オリる 4,908件の分析:
    - どの巡目で過剰押しが起きているか
    - どのモードで過剰押しが起きているか
    - 人間が何牌を切っているか (中張が多い=オリる or 字牌=押し)
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')
from core.str_converter import tile_to_id, is_honor

with open('betadata_with_ai.pkl', 'rb') as f:
    data = pickle.load(f)

overpush = [d for d in data if d['ai_push'] and not d['human_push']]
overfold = [d for d in data if not d['ai_push'] and d['human_push']]

print(f'過剰押し: {len(overpush)}件')
print(f'過剰オリ: {len(overfold)}件')
print()

# 過剰押しの巡目×シャンテン
print('=== 過剰押しの巡目×シャンテン ===')
turn_bins = [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]
shanten_bins = [0, 1, 2, 3, 4, 5]
print(f'  {"":12}', end='')
for lo, hi in turn_bins:
    print(f' 巡{lo}-{hi}', end='')
print()
for sh in shanten_bins:
    if sh == 5:
        subset = [d for d in overpush if d['shanten'] >= 5]
        label = '5+'
    else:
        subset = [d for d in overpush if d['shanten'] == sh]
        label = f'{sh}'
    print(f'  {label:12} ({len(subset):5})', end='')
    for lo, hi in turn_bins:
        s = [d for d in subset if lo <= d['turn'] <= hi]
        print(f' {len(s):5}', end='')
    print()

# 過剰押しの人間の牌選択
print()
print('=== 過剰押しで人間が切った牌 ===')
tile_counter = Counter(d['discard_tile'] for d in overpush)
for t, n in tile_counter.most_common(20):
    print(f'  {t}: {n}件')

# 過剰押しの牌分類
honor = sum(1 for d in overpush if is_honor(tile_to_id(d['discard_tile'])))
terminal = sum(1 for d in overpush if d['discard_tile'][0] in ('1', '9') and not is_honor(tile_to_id(d['discard_tile'])))
middle = len(overpush) - honor - terminal
print()
print(f'  字牌: {honor}件 ({honor/len(overpush)*100:.1f}%)')
print(f'  端牌: {terminal}件 ({terminal/len(overpush)*100:.1f}%)')
print(f'  中張: {middle}件 ({middle/len(overpush)*100:.1f}%)')

# 過剰押しの人間ホールド牌の牌分類
# 人間は中張を切っているのに AI押すと言っている = AIは中張を切らずに危険牌を切ろうとしている
# 人間は「中張をオリで切る」= 安全
# 人間は「字牌を切ってオリる」もある = オリで字牌を処分
# 人間は「端牌を切ってオリる」もある

# 過剰オリの人間牌選択
print()
print('=== 過剰オリで人間が切った牌 ===')
tile_counter = Counter(d['discard_tile'] for d in overfold)
for t, n in tile_counter.most_common(20):
    print(f'  {t}: {n}件')

# 過剰オリの牌分類
honor = sum(1 for d in overfold if is_honor(tile_to_id(d['discard_tile'])))
terminal = sum(1 for d in overfold if d['discard_tile'][0] in ('1', '9') and not is_honor(tile_to_id(d['discard_tile'])))
middle = len(overfold) - honor - terminal
print()
print(f'  字牌: {honor}件 ({honor/len(overfold)*100:.1f}%)')
print(f'  端牌: {terminal}件 ({terminal/len(overfold)*100:.1f}%)')
print(f'  中張: {middle}件 ({middle/len(overfold)*100:.1f}%)')

# 過剰押しの対策案
print()
print('=== 過剰押しの対策 ===')
print('1. AIは人間の牌選択を「中張を切る」=「オリる」と認識すべき')
print('2. 過剰押し = AIが中張を切ろうとして人間も中張を切っている')
print('3. これは「中張を切る」モードと「中張を残す」モードの不一致')
print('4. 人間は「オリる時 中張を切る」ので、AIも同じ判断をすべき')
print()
print('=== 過剰オリの対策 ===')
print('1. AIは人間オリる&AIオリる = 過剰オリ')
print('2. 人間は「字牌を切って押す」ケースで AIがオリ判断')
print('3. 字牌切りで押す = 染め手進行中 or 端牌整理の押し')
print('4. 人間は字牌切りで「手を進めつつ押す中間形態」を使う')
