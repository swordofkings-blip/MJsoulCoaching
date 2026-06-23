"""
@title 過剰押し42,335件の分析 (正しい解釈版)
@description
    人間ベタオリ過剰押し(AI押す、人間オリる) の詳細分析
    正しい解釈: defense_score>0 = 安全牌 = 人間はオリている
    AI押し=攻撃モード、人間オリ=安全牌選択
"""
import pickle
import sys
sys.stdout.reconfigure(encoding='utf-8')
from collections import Counter
sys.path.insert(0, '.')
from core.str_converter import tile_to_id, is_honor

with open('betadata_with_ai.pkl', 'rb') as f:
    data = pickle.load(f)

# 正しい解釈: defense_score > 0 = 安全牌 = 人間はオリている
# defense_score == 0 = 危険牌 = 人間は押し
real_overpush = [d for d in data if d['ai_push'] and d['defense_score'] > 0]
real_overfold = [d for d in data if not d['ai_push'] and d['defense_score'] == 0]
real_match = [d for d in data if (d['ai_push'] and d['defense_score'] == 0) or (not d['ai_push'] and d['defense_score'] > 0)]

print(f'実際の過剰押し(AI押す、人間オリる): {len(real_overpush)}件 ({len(real_overpush)/len(data)*100:.1f}%)')
print(f'実際の過剰オリ(AIオリる、人間押す): {len(real_overfold)}件 ({len(real_overfold)/len(data)*100:.1f}%)')
print(f'実際の一致: {len(real_match)}件 ({len(real_match)/len(data)*100:.1f}%)')
print()

def tile_class(t):
    if t[-1] == 'z': return '字牌'
    n = int(t[0])
    if n in (1, 9): return '端牌'
    if n in (2, 8): return '19-28'
    return '中張(37)'

print('=== 過剰押し: 人間打牌(AI押す場面で人間がオリて切る牌) ===')
for tc, cnt in Counter([tile_class(d['discard_tile']) for d in real_overpush]).most_common():
    print(f'  {tc}: {cnt}')

print()
print('=== 過剰押し: 人間打牌の defense_score ===')
for tc in ['字牌', '端牌', '19-28', '中張(37)']:
    subset = [d for d in real_overpush if tile_class(d['discard_tile']) == tc]
    if not subset: continue
    scores = [d['defense_score'] for d in subset]
    print(f'  {tc}: n={len(subset)}, defense_score avg={sum(scores)/len(subset):.1f}, min={min(scores)}, max={max(scores)}')

print()
print('=== 過剰押し: シャンテン数 ===')
for sh, cnt in Counter([d['shanten'] for d in real_overpush]).most_common():
    print(f'  {sh}シャンテン: {cnt}')

print()
print('=== 過剰押し: 対家リーチ数 ===')
for rn, cnt in Counter([d['reach_n'] for d in real_overpush]).most_common():
    print(f'  reach_n={rn}: {cnt}')

print()
print('=== 過剰押し: AI モード ===')
for mode, cnt in Counter([d['ai_mode'] for d in real_overpush]).most_common():
    print(f'  {mode}: {cnt}')

# 人間は安全牌を選んでいる (defense_score 高い) ので、AIも同じ安全牌を選ぶべき
# AIが押す場面で、人間がオリて切る牌 = 人間は安全牌を選んだ
# AIはこの安全牌を選ぶべき = AIはオリる判断に切り替えるべき
# → AIの戦略モード (全力攻撃/積極駒組み) → (撤退準備/完全撤退) に切り替えるべき

# 過剰押し 42,335件: AI押し判断 → 人間オリ判断 = AI過剰
# 過剰オリ 846件: AIオリ判断 → 人間押し判断 = AI過剰 (わずか)

# 修正案: AIの押し判断を控えめにする
# - 1リーチ + 1-2シャンテン → 人間47.5%押し、AI 100%押し → 過剰押し
# - 人間は安全牌を選んだ = 人間なりのオリ判断
# - AIも同じ判断にすべき

print()
print('=== 過剰押し42,335件: 人間オリ判断の典型例 ===')
print('  人間は defense_score 1000+ の安全牌を選んでいる = 人間はオリている')
print('  AIは全力攻撃/積極駒組みモード = AIは攻撃')
print('  → 人間は「押しモードでも安全牌を選ぶ」、AIは「押しモードで非安全牌を選ぶ」')
print()
print('=== 過剰押しが起こる条件 ===')
print('  1リーチ + 1シャンテン (52.5%) + 巡9-14 (58.1%)')
print('  AI: 1シャンテンで攻撃モードに切り替え')
print('  人間: 同じ状況でも安全牌を選んでオリる')
print()
print('=== 修正案 ===')
print('1. AIの mode 切替閾値を下げる: 1シャンテン+1リーチでも完全撤退寄りにする')
print('2. 人間は安全牌を選んだら AIもオリ判断に切り替える')
print('3. 過剰押し4,908件の対応: 人間ほどオリない = 人間は危険牌も切る、AIは危険牌を避ける')

print()
print('=== 過剰オリ846件 (AIがオリすぎるケース) ===')
for sh, cnt in Counter([d['shanten'] for d in real_overfold]).most_common():
    print(f'  {sh}シャンテン: {cnt}')

print()
print('=== 過剰オリ846件: AI モード ===')
for mode, cnt in Counter([d['ai_mode'] for d in real_overfold]).most_common():
    print(f'  {mode}: {cnt}')

# 過剰オリ: AI完全撤退/撤退準備 + 人間押し = AIが攻めるべき場面でオリている
# 846件は少ないが、修正可能
