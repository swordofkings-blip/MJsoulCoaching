# -*- coding: utf-8 -*-
"""@title 10 ケース テンパイ 牌構成 自動 生成"""
import sys
sys.path.insert(0, '.')
from tools.hand_generator import generate_hand, find_matching_hands


def main():
    """10 ケース 自動 生成 (shanten=0 テンパイ)"""
    cases = {
        'ケース①': "東1局 6巡目 / 子 / ドラ表示牌 1m → ドラ = 2m",
        'ケース②': "東2局 4巡目 / 子 / ドラ表示牌 5m → ドラ = 6m",
        'ケース③': "東3局 8巡目 / 子 / ドラ表示牌 1z",
        'ケース④': "東4局 (親) 9巡目 / ドラ表示牌 1z",
        'ケース⑤': "南1局 10巡目 / 対面リーチ / ドラ表示牌 5m, 5p",
        'ケース⑥': "南4局 9巡目 / トップ 7,000点リード / 子",
        'ケース⑦': "東2局 8巡目 / 子 / ドラ表示牌 1z, 1m",
        'ケース⑧': "東3局 16巡目 / 子 / ドラ表示牌 1z",
        'ケース⑨': "南2局 11巡目 / 上家 + 下家 リーチ / 子",
        'ケース⑩': "東1局 3巡目 / 子 / ドラ表示牌 5s",
    }
    for name, desc in cases.items():
        print(f"\n=== {name}: {desc} ===")
        results = find_matching_hands(
            target_shanten=0,
            n_results=1,
            max_total=10000,
        )
        if results:
            hand = results[0]
            print(f"  牌構成 (14 枚): {hand}")
        else:
            print("  見つからず")


if __name__ == "__main__":
    main()
