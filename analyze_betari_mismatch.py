"""
@title ベタオリミスマッチ分析ツール
@description
    78,504件のベタオリ局面を使って、AIの判断と人間判断のミスマッチを測定する。
    - AIのstrategy_mode(完全撤退/撤退準備/スリム化/全力攻撃/押し気味/危険度勝負/積極駒組み)を判定
    - 人間判断(def=0=オリる, def>0=押す)と比較
"""
import pickle
import sys
import os
import json
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')

# Load params
with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load betari data
with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)

print(f'ベタオリ局面: {len(data)}件')
print()

# === AI判断 vs 人間判断 ===
# AI判断: 押す=モードが「全力攻撃/押し気味/危険度勝負/積極駒組み」のいずれか
# 人間判断: def=0=オリる, def>0=押す

# Replay each situation and determine AI's mode
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

# Need to re-process logs to get full state at each moment
# For efficiency, let's use a simpler heuristic for AI mode based on the recorded features
# AI mode depends on:
# - shanten (lower = more aggressive)
# - turn (later = more aggressive)
# - score rank (4th = more aggressive)
# - reach_n (more = more defensive)

def predict_ai_mode(d):
    """Simplified prediction of AI's strategy mode based on recorded features."""
    shanten = d['shanten']
    turn = d['turn']
    rank = d['my_rank']
    reach_n = d['reach_n']

    # Reach_n >= 2: 完全撤退寄り
    if reach_n >= 2 and shanten >= 2:
        return '完全撤退'
    if reach_n >= 2 and shanten <= 1:
        return '全力攻撃'  # テン目指して押し

    # Reach_n == 1
    # 4位(ラス回避) + 1シャンテン以下: 全力攻撃(押す)
    if rank == 4 and shanten <= 1:
        return '全力攻撃'
    if rank == 4 and shanten >= 3:
        return 'スリム化'  # 手を進めてテンパイ目指す

    # 0-1シャンテン(テンパイ/1シャンテン): 全力攻撃(押せる)
    if shanten <= 1:
        return '全力攻撃'

    # 2シャンテン以上
    # 終盤(巡目12+)ならスリム化 (テン目指す準備)
    if turn >= 12:
        return 'スリム化'
    return '撤退準備'  # 序盤中盤は撤退準備(手を進めつつ安全)

# Classify each case
ai_push = []  # AI押すと予測
ai_fold = []  # AIオリると予測
unknown = []

for d in data:
    mode = predict_ai_mode(d)
    if mode in ('全力攻撃', '押し気味', '危険度勝負', '積極駒組み'):
        ai_push.append((d, mode))
    elif mode in ('完全撤退', '撤退準備', 'スリム化'):
        ai_fold.append((d, mode))
    else:
        unknown.append((d, mode))

print(f'AI押すと予測: {len(ai_push)}件')
print(f'AIオリると予測: {len(ai_fold)}件')
print(f'その他: {len(unknown)}件')
print()

# 人間判断の集計
human_push = sum(1 for d, m in ai_push if d['defense_score'] > 0)
human_fold_push = sum(1 for d, m in ai_push if d['defense_score'] == 0)
human_fold = sum(1 for d, m in ai_fold if d['defense_score'] == 0)
human_push_fold = sum(1 for d, m in ai_fold if d['defense_score'] > 0)

print('=== 比較 ===')
print(f'AI押す&人間押す: {human_push}件 ({human_push/len(ai_push)*100:.1f}% of AI押す)')
print(f'AI押す&人間オリる: {human_fold_push}件 ({human_fold_push/len(ai_push)*100:.1f}% of AI押す)')
print(f'AIオリる&人間オリる: {human_fold}件 ({human_fold/len(ai_fold)*100:.1f}% of AIオリる)')
print(f'AIオリる&人間押す: {human_push_fold}件 ({human_push_fold/len(ai_fold)*100:.1f}% of AIオリる)')
print()

# === Confusion matrix ===
print('=== 混同行列 ===')
print(f'                 人間押す   人間オリる')
print(f'  AI押す      : {human_push:6}    {human_fold_push:6}')
print(f'  AIオリる    : {human_push_fold:6}    {human_fold:6}')

# Accuracy
total = len(data)
match_push = human_push + human_fold  # both agree
mismatch = human_fold_push + human_push_fold
print(f'\n一致: {match_push}/{total} ({match_push/total*100:.1f}%)')
print(f'不一致: {mismatch}/{total} ({mismatch/total*100:.1f}%)')
print()

# === 不一致の詳細 ===
print('=== AI押すが人間オリる (過剰押し) ===')
over_push = [(d, m) for d, m in ai_push if d['defense_score'] == 0]
print(f'  件数: {len(over_push)}')
if over_push:
    # シャンテン×巡目
    print('  シャンテン×巡目:')
    for sh in [0, 1, 2, 3, 4, 5]:
        for tr in [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]:
            lo, hi = tr
            s = [(d, m) for d, m in over_push if d['shanten'] == sh and lo <= d['turn'] <= hi]
            if s:
                print(f'    {sh}シャン 巡{lo}-{hi}: {len(s)}件')

print()
print('=== AIオリるが人間押す (過剰オリ) ===')
over_fold = [(d, m) for d, m in ai_fold if d['defense_score'] > 0]
print(f'  件数: {len(over_fold)}')
if over_fold:
    print('  シャンテン×巡目:')
    for sh in [0, 1, 2, 3, 4, 5]:
        for tr in [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]:
            lo, hi = tr
            s = [(d, m) for d, m in over_fold if d['shanten'] == sh and lo <= d['turn'] <= hi]
            if s:
                print(f'    {sh}シャン 巡{lo}-{hi}: {len(s)}件')

# === 人間の判断基準まとめ ===
print()
print('=== 人間の押す判断基準 (推論) ===')
# 人間が押す = def>0 (2092件)
# 人間の押す/オリるに影響する要因を抽出
# 1. テンパイかどうか
# 2. 終盤かどうか
# 3. 4位(ラス回避)かどうか
# 4. 自分の手役価値

push_data = [d for d in data if d['defense_score'] > 0]
fold_data = [d for d in data if d['defense_score'] == 0]

# ロジスティック回帰的検討
print(f'人間押す件数: {len(push_data)}, 人間オリる件数: {len(fold_data)}')
print()
print('各要因の押す率:')

# テンパイか
tenpai_push_rate = sum(1 for d in push_data if d['shanten'] == 0) / len(push_data) * 100
tenpai_fold_rate = sum(1 for d in fold_data if d['shanten'] == 0) / len(fold_data) * 100
print(f'  テンパイ: 押す時 {tenpai_push_rate:.1f}% / オリる時 {tenpai_fold_rate:.1f}%')

# 終盤か
late_push = sum(1 for d in push_data if d['turn'] >= 12)
late_fold = sum(1 for d in fold_data if d['turn'] >= 12)
print(f'  巡目12+: 押す {late_push}/{len(push_data)} ({late_push/len(push_data)*100:.1f}%) / '
      f'オリる {late_fold}/{len(fold_data)} ({late_fold/len(fold_data)*100:.1f}%)')

# 4位
is4_push = sum(1 for d in push_data if d['my_rank'] == 4)
is4_fold = sum(1 for d in fold_data if d['my_rank'] == 4)
print(f'  4位: 押す {is4_push}/{len(push_data)} ({is4_push/len(push_data)*100:.1f}%) / '
      f'オリる {is4_fold}/{len(fold_data)} ({is4_fold/len(fold_data)*100:.1f}%)')

# 親
dealer_push = sum(1 for d in push_data if d['is_dealer'])
dealer_fold = sum(1 for d in fold_data if d['is_dealer'])
print(f'  親: 押す {dealer_push}/{len(push_data)} ({dealer_push/len(push_data)*100:.1f}%) / '
      f'オリる {dealer_fold}/{len(fold_data)} ({dealer_fold/len(fold_data)*100:.1f}%)')

# リーチ数2
reach2_push = sum(1 for d in push_data if d['reach_n'] == 2)
reach2_fold = sum(1 for d in fold_data if d['reach_n'] == 2)
print(f'  対家リーチ2: 押す {reach2_push}/{len(push_data)} ({reach2_push/len(push_data)*100:.1f}%) / '
      f'オリる {reach2_fold}/{len(fold_data)} ({reach2_fold/len(fold_data)*100:.1f}%)')
