"""
@title 牌選択ベースの押す/オリる判断ルール
@description
    人間データから導かれたルール:
    1. 字牌を切る = 押す(自分の弱い牌を処分)
    2. 中張牌を切る = オリる(安全牌を通す)
    3. 端牌を切る = 状況次第(中間)

    これをAIのstrategy_mode判定ではなく、
    牌選択レベルで適用する。
"""
import sys
sys.path.insert(0, '.')
import json
from core.str_converter import is_honor, tile_to_id

# Load config
with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# New parameters
params['PUSH_SAFE_TILES_BONUS'] = 0.3  # 字牌切り時に「押し」ボーナス
params['FOLD_SAFE_TILES_BONUS'] = 0.3  # 中張切り時に「オリ」ボーナス
params['TERMINAL_TILE_PUSH_BONUS'] = 0.15  # 端牌切り時に「中間」ボーナス

# Implementation in core/evaluator.py
# Modify compute_push_score to consider:
# - 牌の安全度(字牌/端牌/中張)による押し/オリ判断
# - 字牌を切る = 押す
# - 中張牌を切る = オリる

print("Parameters to add to config:")
for k, v in [
    ('PUSH_SAFE_TILES_BONUS', 0.3),
    ('FOLD_SAFE_TILES_BONUS', 0.3),
    ('TERMINAL_TILE_PUSH_BONUS', 0.15),
]:
    print(f'  {k}: {v}')

print()
print("Logic to add to strategy_manager.py:")
print("""
def _tile_classification_push_bonus(self, tile: str) -> float:
    '''
    @title 牌の分類による押し/オリボーナス
    @description 人間データから導かれたルール:
                - 字牌を切る = 押す(自分の弱い牌を処分)
                - 中張牌を切る = オリる(安全牌を通す)
                - 端牌を切る = 状況次第(中間)
    '''
    if is_honor(tile_to_id(tile)):
        return self.params.get('PUSH_SAFE_TILES_BONUS', 0.3)  # 押し
    elif tile[0] in ('1', '9'):
        return self.params.get('TERMINAL_TILE_PUSH_BONUS', 0.15)  # 中間(やや押し)
    else:
        return -self.params.get('FOLD_SAFE_TILES_BONUS', 0.3)  # オリ
""")
