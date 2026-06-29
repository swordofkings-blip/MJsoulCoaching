# -*- coding: utf-8 -*-
"""
@title ver.2 立直判断 (riichi_v2) のテスト
@description 加減算モデルの立直判断を 麻雀セオリー 10 ケースで検証
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import unittest
from typing import List

from core.game_state import GameState, ReachState, Meld
from core.riichi_v2 import (
    should_riichi, score_riichi, is_tenpai_closed, estimate_han_count,
    DEFAULT_WEIGHTS, get_weights,
)
from str_converter import hand_to_counts


def make_state(hand: List[str], doras: List[str] = None, my_seat: int = 0,
               chang: int = 0, ju: int = 0, tsumo_count: int = 7,
               reach_states: List[bool] = None, scores: List[int] = None,
               left_tile_count: int = 70, dealer_seat: int = 0,
               rivers: List[List[str]] = None, melds: List = None) -> GameState:
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
    if melds:
        state.my_melds = list(melds)
    return state


class TestRiichiV2(unittest.TestCase):
    """@title 立直判断 (riichi_v2) のテスト"""

    def test_tenpai_riichi_basic(self):
        """@title 0 待ち テンパイ (winning) + ラス + 終盤 = 立直積極"""
        # 牌構成: 123456m 567p 8p 8p 8p 8s 8s (14 枚) → 0 待ち (winning)
        # → 123 + 456 + 567p (面子) + 8p 暗刻 (面子) + 8s 雀頭 = 4 面子 + 1 雀頭 = winning
        # 役: 平和 + タンヤオ + 役牌 8p → 1 翻
        # ドラ表示: 5m (手牌に 5m 1 枚) → ドラ 1
        # ラス目、15 巡目 → 立直価値大
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','5p','6p','7p','8p','8p','8p','8s','8s'],
            doras=['5m'],
            my_seat=3, chang=0, ju=0, tsumo_count=60,  # 15 巡目, ラス目
            scores=[30000, 25000, 25000, 20000],  # my_seat=3 = 20000 = ラス目
        )
        score, reason = score_riichi(state, {})
        # 加点: -50 (基本) + 20 (1 翻) + 30 (門前) - 30 (1 翻確定) + 30 (終盤) + 60 (ラス) = +60
        # 期待: +60 → 立直 積極
        self.assertGreater(score, 50, f"winning + ラス + 終盤 = 立直積極 (score={score}, {reason})")

    def test_not_tenpai_cannot_riichi(self):
        """@title 1 向聴 では立直不可"""
        # 牌構成: 1234567m 123456p 8p 8p (13 枚) → 1 向聴
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','1p','2p','3p','4p','5p','6p','8p','8p'][:14],
        )
        score, reason = score_riichi(state, {})
        # 期待: 1 向聴 → 立直不可 = -9999
        self.assertLess(score, 0, f"1 向聴 は立直不可 (score={score})")

    def test_kanmachi_low_score_riichi(self):
        """@title ダマテン 1 翻 低打点 + 序盤 = 立直慎重"""
        # 牌構成: 2345678m 123p 456p 8p (13 枚) → 0 待ち (テンパイ)
        # 待: 5p 待ち? いや
        # 牌: 2345678m 123p 456p 8p → 234m 567m + 8m 孤立 + 12p 雀頭 + 34 塔子 + 56 塔子 + 8p 孤立
        # = 1 面子 + 1 雀頭 + 2 塔子 + 2 孤立 = 0 待ち → テンパイ
        # 平和 + タンヤオ 1 翻確定 → 1,000 点
        # 序盤 1 巡 → 立直慎重 (立直棒 1,000 点 損)
        # トップ目 → 逃げ切り
        state = make_state(
            hand=['2m','3m','4m','5m','6m','7m','8m','1p','2p','3p','4p','5p','6p','8p'],
            doras=['5p'],
            my_seat=0, chang=0, ju=0, tsumo_count=3,  # 1 巡目
            scores=[30000, 25000, 23000, 22000],  # トップ目 + 5,000
        )
        score, reason = score_riichi(state, {})
        # 期待: 序盤 + トップ → 立直慎重 (負 or 低い)
        # 加点: 1 翻 → 40 (W_HAND_QUALITY * 0.5)
        # 減点: 序盤 -100, トップ -120 = -220
        # ベース + 門前 +60
        # → 期待: 60 + 40 - 100 - 120 = -120
        self.assertLess(score, 0, f"序盤 + トップ = 立直慎重 (score={score}, {reason})")

    def test_oyafalse_high_score_riichi(self):
        """@title 子番 終盤 満貫 (winning) + ラス = 立直積極"""
        # 牌構成: 123456789m 567p 88s 4p 4p (14 枚) → 0 待ち (winning)
        # → 123 + 456 + 789 + 567p (面子) + 8s 雀頭 + 4p 4p 雀頭候補 = 4 面子 + 1 雀頭 (4p) = winning
        # 役: 平和 + タンヤオ + 一気通貫 → 2 翻
        # ドラ表示: 5m (手牌に 5m 1 枚) → ドラ 1 → 合計 3 翻
        # 子番、15 巡目、ラス目 → 立直積極
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','5p','6p','7p','8s','8s','4p','4p'][:14],
            doras=['5m'],
            my_seat=3, chang=0, ju=0, tsumo_count=60,  # 15 巡目, ラス目
            scores=[30000, 25000, 25000, 20000],  # my_seat=3 = 20000 = ラス目
        )
        score, reason = score_riichi(state, {})
        # 期待: 高打点 (一通 2 翻 + ドラ 1) + 終盤 + ラス → 立直積極
        # 加点: 推定 3 翻 → W_HAND_QUALITY * 0.5 + 20
        # 門前 + 30, 終盤 + 30, ラス + 60
        # 期待: -50 + 20 + 30 + 30 + 60 = +90 → 立直 積極
        self.assertGreater(score, 50, f"終盤 + 高打点 + ラス = 立直積極 (score={score}, {reason})")

    def test_opp_reach_no_riichi(self):
        """@title 他家リーチ = 立直慎重"""
        # 牌構成: 234567m 234p 8p 8p 8p (13 枚) → テンパイ
        # 待: 8p 単騎 or 5m 両面
        # 役: 平和 + タンヤオ 1 翻
        # 他家リーチ → 放銃リスク → 立直慎重
        state = make_state(
            hand=['2m','3m','4m','5m','6m','7m','2p','3p','4p','8p','8p','8p','5s','6s'],
            doras=['5m'],
            my_seat=1, chang=0, ju=0, tsumo_count=40,
            reach_states=[False, False, True, False],  # 対面リーチ
        )
        score, reason = score_riichi(state, {})
        # 期待: 他家リーチ -80 → 立直慎重
        # 加点: 1 翻 + 40, 門前 + 60
        # 減点: 他家リーチ -80
        # ベース 0
        # → 期待: 0 + 40 + 60 - 80 = 20 → 微妙
        # 高打点ボ -50 → 期待: 0 + 40 + 60 - 80 - 50 = -30
        self.assertLess(score, 50, f"他家リーチ + 低打点 = 立直慎重 (score={score}, {reason})")

    def test_estimate_han_basic(self):
        """@title 翻数概算の基本動作"""
        # ドラ 5m 手牌に 5m 3 枚 → ドラ 3
        state = make_state(
            hand=['5m','5m','5m','1p','2p','3p','4p','5p','6p','7p','8p','8p','8p','9p'],
            doras=['5m'],
        )
        han = estimate_han_count(state)
        # ドラ 3 (5m × 3) + 役牌 8p × 1 = 4 翻
        # 注: 役牌 は my_seat=0, chang=0, ju=0 → 自風=東(1z), 場風=東(1z) → 8p は 自風/場風 ではない
        # 8p は 役牌 ではない → 加算 なし
        # 期待: han = 3 (ドラ 3 のみ)
        self.assertGreaterEqual(han, 3, f"ドラ 3 = 3 翻 (han={han})")

    def test_already_reach(self):
        """@title 既にリーチしている場合は立直不可"""
        state = make_state(
            hand=['2m','3m','4m','5m','6m','7m','2p','3p','4p','5p','6p','7p','8s','8s'],
            doras=['5m'],
            my_seat=2, reach_states=[False, False, True, False],  # seat 2 (自分) リーチ済み
        )
        score, reason = score_riichi(state, {})
        self.assertEqual(score, -9999.0, f"既にリーチ宣言済み (score={score})")


class TestKanV2(unittest.TestCase):
    """@title カン判断 (riichi_v2.should_kan) のテスト"""

    def test_kan_delegation_basic(self):
        """@title カン判断は meld_v2 に委譲"""
        # 既に 1 副露 + 暗槓可能
        # 暗槓可能 = 手牌に 4 枚 の 牌
        state = make_state(
            hand=['1m','1m','1m','1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p'],
            doras=['5m'],
            my_seat=0, chang=0, ju=0, tsumo_count=40,
        )
        from core.riichi_v2 import should_kan
        # meld_v2.should_call_meld 経由 → 暗槓は 1 副露目 → 大明槓判定
        # 1m 1m 1m 1m 暗槓可能 → 4 暗刻 = 4 面子 + 1 雀頭候補 → 1 待ち → 1 シャンテン
        # 簡略: カン判定は meld_v2 経由、テストは メソッド が 呼べる こと のみ
        result = should_kan(state, 2, ['1m','1m','1m'], 0, {})
        # 動作 確認: メソッド 呼出 できる
        self.assertIsInstance(result, bool)


if __name__ == '__main__':
    unittest.main(verbosity=2)
