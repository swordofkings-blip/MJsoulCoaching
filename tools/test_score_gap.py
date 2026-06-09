# -*- coding: utf-8 -*-
"""点差シナリオのテスト（簡易版）"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from game_state import GameState
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator


def load_params():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config_parameters.json')
    with open(config_path, encoding='utf-8') as f:
        return json.load(f)


def make_state(hand, scores=None, tsumo_count=5):
    state = GameState()
    state.my_seat = 0
    state.my_hand = list(hand)
    state.scores = scores or [25000, 25000, 25000, 25000]
    state.tsumo_count = tsumo_count
    state.doras = ['1m']
    state.left_tile_count = 70 - tsumo_count * 4
    return state


def test_hand(hand, scores, label, params):
    state = make_state(hand, scores=scores)
    evaluator = Evaluator(state, params=params)
    
    yak_eval = YakumanEvaluator(state)
    results = yak_eval.evaluate_all()
    
    unique_tiles = list(dict.fromkeys(hand))
    has_yakuman_bonus = False
    best_tile = None
    best_score = float('-inf')
    
    for tile in unique_tiles:
        score = evaluator.evaluate_tile(tile)
        details = evaluator.details.get(tile, [])
        yakuman_details = [d for d in details if '役満' in d]
        if yakuman_details:
            has_yakuman_bonus = True
        if score > best_score:
            best_score = score
            best_tile = tile
    
    status = "OK" if has_yakuman_bonus else "NG"
    print(f"[{status}] {label:<50} best={best_tile} score={best_score:.1f}")
    return has_yakuman_bonus


def main():
    params = load_params()
    
    print("=" * 70)
    print("  点差シナリオテスト: 役満ボーナスが点差に応じて適用されるか")
    print("=" * 70)
    
    # 国士無双 3向聴の手牌
    hand_3shanten = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    # 四暗刻 3向聴の手牌
    hand_suua_3shanten = ['1m','1m','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z','5z','5z']
    
    # テストケース: (scores, label)
    test_cases = [
        # 通常（差なし）
        ([25000, 25000, 25000, 25000], "通常（全員25000点）"),
        # 小さな差
        ([20000, 30000, 25000, 25000], "点差10000（倍満以下）"),
        # mangan_line（子10000点）
        ([15000, 25000, 25000, 25000], "点差10000（=mangan_line）"),
        # mangan_line超
        ([10000, 25000, 25000, 25000], "点差15000（mangan_line超）"),
        # 1.5倍
        ([5000, 20000, 25000, 25000], "点差15000（mangan_line×1.5）"),
        # 2.5倍
        ([5000, 30000, 25000, 25000], "点差25000（mangan_line×2.5）"),
        # 大きな差
        ([5000, 45000, 25000, 25000], "点差40000（大差）"),
    ]
    
    print("\n--- 国士無双 3向聴 ---")
    for scores, label in test_cases:
        test_hand(hand_3shanten, scores, label, params)
    
    print("\n--- 四暗刻 3向聴 ---")
    for scores, label in test_cases:
        test_hand(hand_suua_3shanten, scores, label, params)


if __name__ == '__main__':
    main()
