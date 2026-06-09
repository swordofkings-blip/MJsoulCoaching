# -*- coding: utf-8 -*-
"""四暗刻2向聴 vs 大三元1向聴のテスト"""
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


def main():
    params = load_params()

    print("=" * 60)
    print("  四暗刻2向聴 vs 大三元1向聴 テスト")
    print("=" * 60)

    # 四暗刻2向聴: 暗刻1組+対子3組
    # 大三元1向聴: 白・發刻子+中対子
    h = ['1m','1m','1m','5z','5z','5z','6z','6z','6z','7z','7z','9p','9p','9p']
    s = make_state(h)

    # 役満評価
    yak_eval = YakumanEvaluator(s)
    results = yak_eval.evaluate_all()

    print(f"\n手牌: {' '.join(h)}")
    print(f"\n役満評価:")
    for name, r in results.items():
        if r.progress > 0:
            print(f"  [{name}] progress={r.progress:.2f} shanten={r.shanten} possible={r.is_possible}")

    # シャンテン補正の計算
    print(f"\nシャンテン補正:")
    for name, r in results.items():
        if r.progress > 0 and r.is_possible:
            shanten_factor = max(0.0, (4 - r.shanten) ** 2 / 16.0)
            print(f"  [{name}] shanten={r.shanten} -> factor={shanten_factor:.4f}")

    # ボーナス計算
    evaluator = Evaluator(s, params=params)
    unique_tiles = list(dict.fromkeys(h))

    print(f"\n牌ごとのボーナス:")
    for tile in unique_tiles:
        score = evaluator.evaluate_tile(tile)
        details = evaluator.details.get(tile, [])
        yakuman_details = [d for d in details if '役満' in d]
        if yakuman_details:
            print(f"  {tile}: {score:.1f} - {' | '.join(yakuman_details)}")


if __name__ == '__main__':
    main()
