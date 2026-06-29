# -*- coding: utf-8 -*-
"""
@title ver.2 押し引きルール テスト (天鳳位 戦術思想)
@description 麻雀セオリー ケース テスト (押し/オリ 判定)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import unittest
from typing import List

from core.game_state import GameState, ReachState, Meld
from core.push_fold_v2 import (
    judge_push_fold, get_suji_tiles, get_danger_tiles, get_safe_tiles,
    get_effective_han, select_push_discard, select_fold_discard,
)


def make_state(hand: List[str], doras: List[str] = None, my_seat: int = 0,
               chang: int = 0, ju: int = 0, tsumo_count: int = 7,
               reach_states: List[bool] = None, scores: List[int] = None,
               left_tile_count: int = 70, dealer_seat: int = 0,
               rivers: List[List[str]] = None) -> GameState:
    state = GameState()
    state.my_hand = list(hand)
    state.my_seat = my_seat
    state.chang = chang
    state.ju = ju
    state.tsumo_count = tsumo_count
    state.doras = doras or ['1m']
    state.reach_states = [ReachState() for _ in range(4)]
    if reach_states:
        for s, r in enumerate(reach_states):
            if r:
                state.reach_states[s].is_reach = True
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


class TestPushFoldRules(unittest.TestCase):
    """@title 押し引き ルール テスト"""

    def test_0_han_1shanten_fold(self):
        """@title 0 翻 1 シャンテン → オリ"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['1z'],
            tsumo_count=20,  # 5 巡目
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        self.assertEqual(decision, 'fold', f"0 翻 1 シャンテン = オリ (decision={decision}, {reasons})")

    def test_3_han_1shanten_push(self):
        """@title 3 翻 (満貫) 1 シャンテン → 押す"""
        # ドラ 5m × 2 + 役牌 6z (白) 暗刻 = ドラ 2 + 役牌 1 = 3 翻
        state = make_state(
            hand=['5m','5m','7m','8m','9m','1p','2p','3p','4p','5p','6p','6z','6z','6z'],
            doras=['5m'],
            tsumo_count=40,  # 10 巡目
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        self.assertEqual(decision, 'push', f"3 翻 1 シャンテン = 押す (decision={decision}, {reasons})")

    def test_top_place_fold(self):
        """@title トップ目 → オリ"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['5m'],
            tsumo_count=20,
            scores=[35000, 25000, 23000, 22000],  # トップ
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        # トップ目 = オリ逃げ
        self.assertIn('トップ目', ' '.join(reasons), f"トップ目 加点 あり (decision={decision}, {reasons})")

    def test_last_place_push(self):
        """@title ラス目 → 押す"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['5m'],
            tsumo_count=20,
            scores=[32000, 28000, 25000, 20000],  # ラス
            my_seat=3,
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        # ラス目 = 押す
        self.assertIn('ラス目', ' '.join(reasons), f"ラス目 加点 あり (decision={decision}, {reasons})")

    def test_late_turn_push(self):
        """@title 終盤 15 巡 → 押す"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['1z'],
            tsumo_count=60,  # 15 巡
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        self.assertIn('終盤', ' '.join(reasons), f"終盤 加点 あり (decision={decision}, {reasons})")

    def test_early_turn_fold(self):
        """@title 序盤 2 巡 → オリ"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['1z'],
            tsumo_count=8,  # 2 巡
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        self.assertIn('序盤', ' '.join(reasons), f"序盤 減点 あり (decision={decision}, {reasons})")

    def test_opp_2reach_fold(self):
        """@title 2 家リーチ → オリ"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['1z'],
            tsumo_count=40,
            reach_states=[False, True, True, False],  # 2 家リーチ
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        self.assertIn('他家リーチ 2', ' '.join(reasons), f"2家リーチ 減点 あり (decision={decision}, {reasons})")


class TestSuji(unittest.TestCase):
    """@title スジ計算 テスト"""

    def test_suji_5m(self):
        """@title 5m のスジ = 4m, 6m"""
        suji = get_suji_tiles('5m')
        self.assertIn('4m', suji, f"5m スジ = 4m ({suji})")
        self.assertIn('6m', suji, f"5m スジ = 6m ({suji})")

    def test_suji_1m(self):
        """@title 1m のスジ = 4m"""
        suji = get_suji_tiles('1m')
        self.assertIn('4m', suji, f"1m スジ = 4m ({suji})")

    def test_suji_9m(self):
        """@title 9m のスジ = 6m"""
        suji = get_suji_tiles('9m')
        self.assertIn('6m', suji, f"9m スジ = 6m ({suji})")

    def test_suji_honor(self):
        """@title 字牌のスジ = なし"""
        suji = get_suji_tiles('1z')
        self.assertEqual(suji, set(), f"字牌 スジ = なし ({suji})")


class TestSafeTiles(unittest.TestCase):
    """@title 安全牌 テスト"""

    def test_safe_own_river(self):
        """@title 自分の捨牌 = 安全"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['5p','6p','7p'], [], [], []],
        )
        safe = get_safe_tiles(state)
        self.assertIn('5p', safe, f"自分の捨牌 5p = 安全 ({safe})")
        self.assertIn('6p', safe, f"自分の捨牌 6p = 安全 ({safe})")
        self.assertIn('7p', safe, f"自分の捨牌 7p = 安全 ({safe})")

    def test_safe_4visible_honor(self):
        """@title 4枚見え字牌 = 安全"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['1z','1z','1z'], ['1z'], [], []],  # 1z 4 枚見え
        )
        safe = get_safe_tiles(state)
        self.assertIn('1z', safe, f"4枚見え字牌 1z = 安全 ({safe})")


class TestSelectDiscard(unittest.TestCase):
    """@title 打牌選択 テスト"""

    def test_select_push_safe(self):
        """@title 押し 際 安全牌 選択"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['5p','6p'], [], [], []],
        )
        candidates = ['5m', '6p', '5p']
        tile, reason = select_push_discard(state, candidates)
        # 安全牌 (5p, 6p) のうち いずれか
        self.assertIn(tile, ['5p', '6p'], f"押し 際 安全牌 選択 (tile={tile})")

    def test_select_fold_safe(self):
        """@title オリ 際 安全牌 選択"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['5p','6p','7p','8p'], [], [], []],
        )
        candidates = ['5m', '6p', '5p', '1z']
        tile, reason = select_fold_discard(state, candidates)
        # 安全牌 (5p, 6p, 7p, 8p) のうち いずれか
        self.assertIn(tile, ['5p', '6p', '7p', '8p'], f"オリ 際 安全牌 選択 (tile={tile})")


if __name__ == '__main__':
    unittest.main(verbosity=2)
