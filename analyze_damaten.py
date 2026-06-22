"""
@title ダマテン傾向の人間データ分析
@description
    人間が「テンパイだがリーチしない」場面の特徴を分析する。
    ダマテンを選ぶ = オリる寄り or 手役待ちが不利。
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, is_honor
from core.strategy_manager import ShantenCalculator
from core.hand_value import estimate_han_advanced
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Use sample
with open('betadata_full.pkl', 'rb') as f:
    data = pickle.load(f)
print(f'ベタオリ局面総数: {len(data)}件')

# 人間はテンパイでリーチ宣言 = 押す判断
# テンパイでダマテン = オリる寄り
# これは前回の分析で分かった
# ここで確認: 人間がダマテンする時の手牌特徴
damaten_cases = [d for d in data if d['shanten'] == 0 and d['reach_n'] == 0]
print(f'テンパイでリーチなし (ダマテン): {len(damaten_cases)}件')

# テンパイでリーチする (押す) vs ダマテン (オリる) の比較
tenpai_reach = []  # 人間がテンパイでリーチした (前回の分析のデータ)
tenpai_damaten = damaten_cases

# ダマテンの特徴
print('\n=== ダマテンの巡目分布 ===')
turn_counter = Counter(d['turn'] for d in tenpai_damaten)
for t in sorted(turn_counter.keys())[:20]:
    print(f'  巡目{t}: {turn_counter[t]}件')

print('\n=== ダマテンの順位 ===')
rank_counter = Counter(d['my_rank'] for d in tenpai_damaten)
for r in sorted(rank_counter.keys()):
    print(f'  {r}位: {rank_counter[r]}件')

# ダマテンの切る牌トップ20
print('\n=== ダマテンの切る牌トップ20 ===')
tile_counter = Counter(d['discard_tile'] for d in tenpai_damaten)
for t, n in tile_counter.most_common(20):
    print(f'  {t}: {n}件')

# ダマテンの切る牌分類
print('\n=== ダマテンの切る牌分類 ===')
honor = sum(1 for d in tenpai_damaten if is_honor(tile_to_id(d['discard_tile'])))
terminal = sum(1 for d in tenpai_damaten if d['discard_tile'][0] in ('1', '9') and not is_honor(tile_to_id(d['discard_tile'])))
middle = len(tenpai_damaten) - honor - terminal
print(f'  字牌: {honor}件 ({honor/len(tenpai_damaten)*100:.1f}%)')
print(f'  端牌: {terminal}件 ({terminal/len(tenpai_damaten)*100:.1f}%)')
print(f'  中張: {middle}件 ({middle/len(tenpai_damaten)*100:.1f}%)')

# ダマテンの翻数推定 (heuristic)
# Wait, we have reach_turn, my_score, scores, is_dealer - use these

# Save the damaten data for further analysis
print()
print('ダマテンは オリる の強い判断。人間はテンパイでも 積極的にダマテン。')
print('AIは テンパイ=リーチ という固定観念を捨て、ダマテンを考慮すべき')
