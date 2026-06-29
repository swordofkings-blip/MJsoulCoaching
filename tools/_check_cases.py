# -*- coding: utf-8 -*-
"""@title 牌構成 winning 確認 (デバッグ)"""
import sys
sys.path.insert(0, '.')
from core.str_converter import hand_to_counts
from core.shanten_v2 import ShantenCalculatorV2

cases = {
    'ケース①': ['1m','2m','3m','4m','5m','6m','1p','2p','3p','5p','6p','7p','8p','8p'],
    'ケース②': ['1m','2m','3m','4m','5m','6m','5p','7p','1s','2s','3s','8p','8p','9p'],
    'ケース③': ['2m','3m','4m','5m','6m','7m','1p','2p','3p','4s','5s','6s','8p','8p'],
    'ケース④': ['1m','2m','3m','4p','5p','6p','7p','8p','9p','1s','2s','3s','4s','5s','6s','7s','8s'][:14],
    'ケース⑤': ['1m','2m','3m','1p','2p','3p','4p','5p','7p','8p','9p','4s','5s','6s','8s','8s'][:14],
    'ケース⑥': ['2m','3m','4m','5m','6m','7m','1p','2p','3p','4p','5p','7p','8p','8p'],
    'ケース⑦': ['1m','2m','3m','2m','3m','4m','5m','6m','7m','6m','7m','8m','8m','9m'],
    'ケース⑧': ['1m','2m','3m','4m','5m','6m','2p','3p','4p','5p','6p','7p','8p','8p'],
    'ケース⑨': ['1m','2m','3m','4m','5m','6m','5p','7p','1s','2s','3s','8p','8p','9p'],
    'ケース⑩': ['1m','2m','3m','4m','5m','6m','1p','2p','4p','5p','6p','7p','7s','8s','9s'][:14],
}

for name, hand in cases.items():
    counts = hand_to_counts(hand)
    sh = ShantenCalculatorV2.calculate_closed_effective(counts)
    print(f'{name}: シャンテン={sh} (0=テンパイ, 1=1 シャンテン) 手牌={hand}')
