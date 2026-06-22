"""
Analyze the 2092 'push' cases in detail.
Find what makes humans decide to push.
"""
import pickle
from collections import Counter
from statistics import mean

with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)

push = [d for d in data if d['defense_score'] > 0]
print(f'押す局面: {len(push)}件')
print()

# Reach=1, late turn の押すケース(押すべき場面で押した)
print('=== 押すケース: reach=1, 巡目12+の分布 ===')
late_push = [d for d in push if d['reach_n'] == 1 and d['turn'] >= 12]
print(f'  件数: {len(late_push)}')
if late_push:
    sh_counter = Counter(d['shanten'] for d in late_push)
    print(f'  シャンテン分布: {dict(sorted(sh_counter.items()))}')
    rank_counter = Counter(d['my_rank'] for d in late_push)
    print(f'  ランク分布: {dict(sorted(rank_counter.items()))}')
    is_dealer = sum(1 for d in late_push if d['is_dealer'])
    print(f'  親: {is_dealer} / {len(late_push)} ({is_dealer/len(late_push)*100:.1f}%)')

# reach=1, 0-1シャンテン: テンパイ/1シャンテンで押した
print()
print('=== 押すケース: reach=1, 0-1シャンテン (テン目指す押し) ===')
tenpai_push = [d for d in push if d['reach_n'] == 1 and d['shanten'] in (0, 1)]
print(f'  件数: {len(tenpai_push)}')
if tenpai_push:
    sh_counter = Counter(d['shanten'] for d in tenpai_push)
    print(f'  シャンテン分布: {dict(sorted(sh_counter.items()))}')
    t_counter = Counter()
    for d in tenpai_push:
        t_counter[d['turn']] += 1
    print(f'  巡目上位: {t_counter.most_common(5)}')

# 押すケース: 3シャンテン以上の押し = 考えにくい
print()
print('=== 押すケース: 3+シャンテン (押すのは異常) ===')
deep_push = [d for d in push if d['shanten'] >= 3]
print(f'  件数: {len(deep_push)}')
if deep_push:
    sh_counter = Counter(d['shanten'] for d in deep_push)
    print(f'  シャンテン分布: {dict(sorted(sh_counter.items()))}')
    t_counter = Counter(d['turn'] for d in deep_push)
    print(f'  巡目分布: {t_counter.most_common(5)}')

# Most extreme push cases
print()
print('=== 押すケースの最も押しが弱い状況 ===')
# 0シャンテン + 巡目15以降 + reach=1 + 4位
extreme = [d for d in push if d['shanten'] == 0 and d['turn'] >= 15 and d['reach_n'] == 1 and d['my_rank'] == 4]
print(f'  0シャン+巡目15+&reach=1&4位: {len(extreme)}件')
if extreme:
    print('  人間の判断: 終盤・4位・テンパイ・対家1リーチ という強押し状況')
    print('  人間はそれでも押す = ラス回避のため全力')

# 押すケースのスコア平均
print()
print(f'押す平均点数: {mean(d["my_score"] for d in push):.0f}')
print(f'オリる平均点数: {mean(d["my_score"] for d in data if d["defense_score"] == 0):.0f}')

# 押すとき、よく切る牌は何か?
print()
print('=== 押すとき切る牌トップ20 ===')
tile_counter = Counter(d['discard_tile'] for d in push)
for t, n in tile_counter.most_common(20):
    print(f'  {t}: {n}件')
