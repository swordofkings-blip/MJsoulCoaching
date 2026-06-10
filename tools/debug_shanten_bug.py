# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from str_converter import hand_to_counts
from strategy_manager import ShantenCalculator

# In-hand tiles (11 tiles):
# 手牌(10枚): 3萬 4筒 4筒 6筒 6筒 赤5索 5索 6索 6索 6索
# ツモ牌: 3索
# 副露: 1筒 1筒 1筒 (pon)
hand_tiles = ['3m', '4p', '4p', '6p', '6p', '0s', '5s', '6s', '6s', '6s', '3s']
open_meld_count = 1
counts = hand_to_counts(hand_tiles)

print("=" * 60)
print("【検証】手牌: 3m 4p 4p 6p 6p 0s 5s 6s 6s 6s | ツモ: 3s")
print("【副露】1p 1p 1p (ポン)")
print("=" * 60)
print(f"手牌枚数(副露除く): {sum(counts)}")
print(f"副露数: {open_meld_count}")
print()

# Shanten calculations
closed_shanten = ShantenCalculator.calculate_closed(counts)
open_shanten = ShantenCalculator.calculate_open(counts, open_meld_count)
std_shanten = ShantenCalculator.calculate_standard(counts)
print(f"標準シャンテン(closed): {closed_shanten}")
print(f"副露シャンテン(open):  {open_shanten}")
print(f"スタンダード(closed/head無): {std_shanten}")

# Also test each possible discard shanten
print()
print("=== 各打牌後のシャンテン数 ===")
unique_tiles = list(dict.fromkeys(hand_tiles))
for tile in unique_tiles:
    tmp = list(counts)
    tid = {'0s': 22, '5s': 22}.get(tile, -1)
    if tid == -1:
        from str_converter import tile_to_id
        tid = tile_to_id(tile)
    tmp[tid] = max(0, tmp[tid] - 1)
    s = ShantenCalculator.calculate_open(tmp, open_meld_count)
    print(f"  {tile} 切り: シャンテン={s}")

# Edge case: chiitoitsu with < 7 kinds
print()
print("=== チートイツ境界テスト ===")
# 7 pairs hand (chiitoitsu tenpai)
chiitoi_tenpai = [0]*34
for idx in [0, 1, 2, 9, 10, 11, 27]:
    chiitoi_tenpai[idx] = 2
print(f"  7対子テンパイ: {ShantenCalculator._chiitoitsu_shanten(chiitoi_tenpai)} (expect -1)")

# Hand with 6 kinds (previously bug: returned 0)
chiitoi_6kinds = [0]*34
for idx in [0, 1, 2, 9, 10, 11]:
    chiitoi_6kinds[idx] = 2
chiitoi_6kinds[0] = 3  # 13 tiles total
print(f"  6種類(チートイツ不可能): {ShantenCalculator._chiitoitsu_shanten(chiitoi_6kinds)} (expect >= 7)")
