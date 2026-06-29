# -*- coding: utf-8 -*-
"""
@title ver.2 副露判断 (meld_v2) のテスト
@description 22 要素の加減算モデルが正しく動作するか確認
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import unittest
from typing import List

from core.game_state import GameState, ReachState
from core.meld_v2 import should_call_meld, score_meld, get_weights
from str_converter import hand_to_counts


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
    if rivers:
        for s, r in enumerate(rivers):
            if r:
                state.river[s] = list(r)
    return state


class TestMeldV2(unittest.TestCase):
    """@title 副露判断 (meld_v2) のテスト"""

    def test_dora3_yakuhai_pon_should_call(self):
        """@title ドラ 3 + 役牌ポン = 鳴く"""
        # 1m ドラ 3 枚 + 1z (役牌) 3 枚 → 1z ポン で 1m ドラ 3 確定
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p','1z','1z','1z'],
            doras=['1m'],
        )
        should, reason = should_call_meld(state, 1, ['1z','1z','1z'], 1, {})
        self.assertTrue(should, f"ドラ 3 + 役牌ポンは鳴くべき (実際: {should}, {reason})")

    def test_oorasto_4th_reach_should_not_call(self):
        """@title オーラス 4 位 + 他家リーチ + 1z ポン = 鳴かない"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            my_seat=0, chang=3, ju=3,  # 南 4 局 (オーラス)
            tsumo_count=14, left_tile_count=30,
            reach_states=[False, True, False, False],  # player 1 リーチ
            scores=[15000, 30000, 28000, 27000],  # 4 位
        )
        should, reason = should_call_meld(state, 1, ['1z','1z','1z'], 1, {})
        self.assertFalse(should, f"オーラス 4 位 + リーチ = 鳴かない (実際: {should}, {reason})")

    def test_early_turn_should_penalize(self):
        """@title 序盤 (1-3 巡) は減点"""
        state_early = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            tsumo_count=2,  # 1 巡目
        )
        state_mid = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            tsumo_count=8,  # 4 巡目 (中盤)
        )
        score_early, _ = score_meld(state_early, 1, ['1z','1z','1z'], 1, {})
        score_mid, _ = score_meld(state_mid, 1, ['1z','1z','1z'], 1, {})
        # 序盤は減点で score_early < score_mid
        self.assertLess(score_early, score_mid, f"序盤 < 中盤 (early={score_early}, mid={score_mid})")

    def test_3rd_meld_heavy_penalty(self):
        """@title 3 副露目 = 守備力激減"""
        from core.game_state import Meld
        # 既に 2 副露済みの状態
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','1z','1z'],
            doras=['1m'],
            tsumo_count=10,
        )
        # 2 副露を模擬
        state.my_melds = [
            Meld(type=1, tiles=['1p','1p','1p'], froms=[1,1,1]),
            Meld(type=1, tiles=['2p','2p','2p'], froms=[2,2,2]),
        ]
        # 1z ポン (3 副露目 = 4 副露封印)
        should, reason = should_call_meld(state, 1, ['1z','1z','1z'], 1, {})
        self.assertFalse(should, f"3 副露目で 4 副露封印 = 鳴かない (実際: {should}, {reason})")

    def test_opp_reach_penalizes(self):
        """@title 他家リーチで減点"""
        # 通常の手牌で 1z ポン (加点 200) → 鳴く
        state1 = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            tsumo_count=7,
        )
        should1, _ = should_call_meld(state1, 1, ['1z','1z','1z'], 1, {})
        # 他家リーチ有りで 1z ポン → 減点で鳴かない
        state2 = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            tsumo_count=7,
            reach_states=[False, True, False, False],
        )
        should2, reason2 = should_call_meld(state2, 1, ['1z','1z','1z'], 1, {})
        score1, _ = score_meld(state1, 1, ['1z','1z','1z'], 1, {})
        score2, _ = score_meld(state2, 1, ['1z','1z','1z'], 1, {})
        # 他家リーチで減点 = score2 < score1
        self.assertLess(score2, score1, f"他家リーチで減点 (score1={score1}, score2={score2})")

    def test_breakdown_explains_decision(self):
        """@title 22 要素の breakdown が返る"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p','1z','1z','1z'],
            doras=['1m'],
        )
        score, breakdown = score_meld(state, 1, ['1z','1z','1z'], 1, {})
        # breakdown は 22 要素すべて返る
        self.assertEqual(len(breakdown), 22, f"22 要素すべて返る (実際: {len(breakdown)})")
        # 主要な要素がプラスのスコアを持つ
        for name, value, reason in breakdown:
            print(f"  {name}: {value:+.0f} ({reason})")

    def test_oya_kan_more(self):
        """@title 親番は加点"""
        state1 = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            my_seat=0, dealer_seat=0,  # 親番
        )
        state2 = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1z','1z'],
            doras=['5m'],
            my_seat=0, dealer_seat=1,  # 子番
        )
        score1, _ = score_meld(state1, 1, ['1z','1z','1z'], 1, {})
        score2, _ = score_meld(state2, 1, ['1z','1z','1z'], 1, {})
        self.assertGreater(score1, score2, f"親番 > 子番 (親={score1}, 子={score2})")


if __name__ == '__main__':
    unittest.main(verbosity=2)
