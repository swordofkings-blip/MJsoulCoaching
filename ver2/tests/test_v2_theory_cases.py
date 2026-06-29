# -*- coding: utf-8 -*-
"""
@title 麻雀セオリー 100% 確定 押し/オリ テストケース (牌構成 自動生成 版)
@description 10 ケースの確定的なセオリー解に基づく、push_fold_v2 の判断精度テスト。
              牌構成は hand_generator.py で 自動生成 (ドラ/役 制約あり)。

              ケース①〜⑤ = 即リーチ (push)
              ケース⑥〜⑧, ⑩ = ダマテン (neutral)
              ケース⑨ = オリ (fold)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import unittest
from typing import List

from core.game_state import GameState, ReachState, Meld
from core.push_fold_v2 import judge_push_fold
from tools.hand_generator import find_matching_hands


def make_state(hand, my_seat=0, doras=None, tsumo_count=24, ju=0, chang=0,
               reach_states=None, scores=None, left_tile_count=70, dealer_seat=0,
               rivers=None) -> GameState:
    state = GameState()
    state.my_hand = list(hand)
    state.my_seat = my_seat
    state.ju = ju
    state.chang = chang
    state.tsumo_count = tsumo_count
    state.doras = doras or ['1m']
    state.reach_states = [ReachState() for _ in range(4)]
    if reach_states:
        for s, r in enumerate(reach_states):
            if r:
                state.reach_states[s].is_reach = True
                state.reach_states[s].reach_turn = tsumo_count
    state.scores = scores or [25000, 25000, 25000, 25000]
    state.left_tile_count = left_tile_count
    state.dealer_seat = dealer_seat
    state.river = [[] for _ in range(4)]
    if rivers:
        for s, r in enumerate(rivers):
            if r:
                state.river[s] = list(r)
    state.my_melds = []
    return state


def gen_tenpai_hand(must_include=None, seed=0, max_total=50000):
    """@title テンパイ 牌構成 自動生成 (must_include 適用 確認)"""
    results = find_matching_hands(
        target_shanten=0,
        must_include=must_include,
        n_results=3,
        seed_start=seed,
        max_total=max_total,
    )
    if not results:
        raise ValueError(f"テンパイ 牌構成 生成 失敗 (must_include={must_include})")
    # must_include が 適用 さ れ た 牌構成 を 選ぶ (必須牌 が 含ま れ て いる こと)
    if must_include:
        for hand in results:
            for must_tile in must_include:
                if hand.count(must_tile) < must_include.count(must_tile):
                    break
            else:
                return hand
        # 適用 さ れ た 牌構成 が な れ ば 最初 の 結果 を 返す
    return results[0]


# 10 ケース 設定
CASE_CONFIGS = [
    # (name, doras, must_include, ju, chang, tsumo_count, my_seat, dealer_seat, reach_states, scores, left_tile, expected)
    ('ケース①', ['1m'], ['2m','2m','2m'], 0, 0, 24, 1, 0, [False]*4, None, 70, 'push'),  # 子
    ('ケース②', ['5m'], None, 1, 0, 16, 1, 0, [False]*4, None, 70, 'push'),  # 子
    ('ケース③', ['1z'], None, 2, 0, 32, 1, 0, [False]*4, None, 70, 'push'),  # 子
    ('ケース④', ['1z'], None, 3, 0, 36, 0, 0, [False]*4, None, 70, 'push'),  # 親
    ('ケース⑤', ['5m','5p'], ['6m','6p'], 0, 1, 40, 1, 0, [False,True,False,False], None, 70, 'push'),  # 子
    ('ケース⑥', ['1z'], None, 3, 3, 36, 1, 0, [False]*4, [25000,32000,25000,18000], 70, 'neutral'),  # 子
    ('ケース⑦', ['1z','1m'], ['2z','2z','2z','2z','2m','2m'], 1, 0, 32, 1, 0, [False]*4, None, 70, 'neutral'),  # 子、倍満
    ('ケース⑧', ['1z'], None, 2, 0, 64, 1, 0, [False]*4, None, 4, 'neutral'),  # 子、終盤
    ('ケース⑨', ['1z'], None, 1, 1, 44, 1, 0, [True,False,True,False], None, 70, 'fold'),  # 子、オリ
    ('ケース⑩', ['5s'], ['6s','6s'], 0, 0, 12, 1, 0, [False]*4, None, 70, 'neutral'),  # 子、好形手替わり
]


class TestTheoryCases(unittest.TestCase):
    """@title 麻雀セオリー 100% 確定 10 ケース"""

    def test_10cases(self):
        """@title 10 ケース 自動生成 + 判定"""
        results = []
        for idx, cfg in enumerate(CASE_CONFIGS):
            (name, doras, must_include, ju, chang, tsumo_count, my_seat, dealer_seat,
             reach_states, scores, left_tile, expected) = cfg
            with self.subTest(case=name):
                # ケース 別 で 違う seed_start を 使用
                seed_start = idx * 10000
                try:
                    hand = gen_tenpai_hand(must_include=must_include, seed=seed_start)
                except ValueError as e:
                    self.fail(f"{name}: 牌構成 自動生成 失敗: {e}")
                state = make_state(
                    hand=hand,
                    doras=doras,
                    my_seat=my_seat,
                    ju=ju, chang=chang,
                    tsumo_count=tsumo_count,
                    reach_states=reach_states,
                    scores=scores,
                    left_tile_count=left_tile,
                    dealer_seat=dealer_seat,
                )
                decision, reasons = judge_push_fold(state, shanten=0)
                # expected 判定
                if expected == 'push':
                    self.assertEqual(decision, 'push',
                        f"{name}: 即リーチ 期待 (hand={hand}, decision={decision}, reasons={reasons})")
                elif expected == 'neutral':
                    self.assertIn(decision, ['neutral', 'fold'],
                        f"{name}: ダマテン 期待 (hand={hand}, decision={decision}, reasons={reasons})")
                elif expected == 'fold':
                    self.assertEqual(decision, 'fold',
                        f"{name}: オリ 期待 (hand={hand}, decision={decision}, reasons={reasons})")
                results.append((name, hand, expected, decision, reasons))
        # 結果 表示
        print("\n=== 10 ケース 結果 ===")
        for name, hand, expected, decision, reasons in results:
            print(f"{name}: 期待={expected}, 実際={decision}")
            print(f"  牌構成: {hand}")
            print(f"  理由: {reasons[:3]}")


if __name__ == '__main__':
    unittest.main(verbosity=2)
