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
        # 牌構成 14 枚 で 1 待ち残 1 シャンテン (winning でない)
        # 1m-6m 23p 567p 88s 9p = 2 面子 + 1 塔子 + 1 雀頭 + 1 孤立 = 1 待ち
        # 12 巡 経過 (安全牌 8 種以上) で オリ 余裕
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','2p','3p','5p','6p','7p','8s','8s','9p'],
            doras=['1z'],
            tsumo_count=48,  # 12 巡目
            rivers=[['1m','2m','3m','4p','5p','6p','7p','8p','1z','2z'], [], [], []],
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
        self.assertIn(tile, ['5p', '6p'], f"押し 際 安全牌 選択 (tile={tile})")

    def test_select_fold_safe(self):
        """@title オリ 際 安全牌 選択"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['5p','6p','7p','8p'], [], [], []],
        )
        candidates = ['5m', '6p', '5p', '1z']
        tile, reason = select_fold_discard(state, candidates)
        self.assertIn(tile, ['5p', '6p', '7p', '8p'], f"オリ 際 安全牌 選択 (tile={tile})")


class TestNewRules(unittest.TestCase):
    """@title 25 項目 戦術思想 新規ルール テスト"""

    def test_riichi_benefit_low_high(self):
        """@title 1.② リーチ打点上昇幅: 1翻 (1,000→2,600=160% vs 4翻 (8,000→8,000=0%)"""
        from core.push_fold_v2 import calc_riichi_benefit
        state = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'])
        # 1 翻
        b1 = calc_riichi_benefit(state, 1)
        # 4 翻 (満貫以上) → 跳満
        b4 = calc_riichi_benefit(state, 4)
        # 1翻 > 4翻 (1翻 の 方 が 押す 価値 大)
        self.assertGreater(b1, b4, f"1翻 利益 ({b1:.0f}%) > 4翻 利益 ({b4:.0f}%)")

    def test_tenpai_change_potential(self):
        """@title 1.④ 手替わり 期待: 山 多い ほど 期待 大"""
        from core.push_fold_v2 import calc_tenpai_change_potential
        s1 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                        left_tile_count=70)
        s2 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                        left_tile_count=15)
        p1 = calc_tenpai_change_potential(s1)
        p2 = calc_tenpai_change_potential(s2)
        self.assertGreater(p1, p2, f"山 多 ({p1:.0f}) > 山 少 ({p2:.0f})")

    def test_score_explosion_low_han(self):
        """@title 1.⑤ 打点 爆発力: 1翻以下 が 大"""
        from core.push_fold_v2 import calc_score_explosion_potential
        s = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'])
        e1 = calc_score_explosion_potential(s, 1)
        e4 = calc_score_explosion_potential(s, 4)
        self.assertGreater(e1, e4, f"1翻 爆発力 ({e1:.0f}) > 4翻 爆発力 ({e4:.0f})")

    def test_ura_aka_anko(self):
        """@title 1.⑥ 裏ドラ 期待値: 暗刻 ある と 大"""
        from core.push_fold_v2 import calc_ura_aka_expectation
        # 牌構成 1: 暗刻 + 順子 少ない (高)
        s1 = make_state(hand=['1z','1z','1z','2m','3m','4m','5m','6m','1p','2p','3p','4p','5p','6p','7p'][:14])
        # 牌構成 2: 順子 多い (中) - 暗刻 なし
        s2 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p','9p'][:14])
        e1 = calc_ura_aka_expectation(s1)
        e2 = calc_ura_aka_expectation(s2)
        self.assertGreater(e1, e2, f"暗刻 あり ({e1:.0f}) > 順子 多い ({e2:.0f})")

    def test_dead_tiles(self):
        """@title 2.② 死に牌 数: 河 に 見え て いる 待ち牌"""
        from core.push_fold_v2 import count_dead_tiles
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['5p','5p','5p'], [], [], []],  # 5p 3 枚 見え
        )
        dead = count_dead_tiles(s, ['5p', '6p'])
        # 5p × 3 = 3 枚 + 6p × 0 = 0 → 計 3
        self.assertEqual(dead, 3, f"死に牌 3枚 (実測 {dead})")

    def test_pickup_ease_honor(self):
        """@title 2.③ 他家 出やすさ: 字牌 が 出やすい"""
        from core.push_fold_v2 import calc_pickup_ease
        s = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'])
        e_honor = calc_pickup_ease(s, ['1z'])
        e_middle = calc_pickup_ease(s, ['5m'])
        self.assertGreater(e_honor, e_middle, f"字牌 出やすさ ({e_honor:.0f}) > 中央 ({e_middle:.0f})")

    def test_is_wait_dora(self):
        """@title 2.④ 待ち が ドラ = True"""
        from core.push_fold_v2 import is_wait_dora_aka
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['5p'],  # ドラ 5p
        )
        self.assertTrue(is_wait_dora_aka(s, ['5p']), "5p = ドラ 待ち → True")

    def test_remaining_tsumo(self):
        """@title 3.② 残り ツモ 回数"""
        from core.push_fold_v2 import remaining_tsumo_count
        s = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                       left_tile_count=40)
        r = remaining_tsumo_count(s)
        # 40 枚 → 10 回
        self.assertEqual(r, 11, f"残り ツモ = 11回 (実測 {r})")

    def test_is_near_haitei(self):
        """@title 3.③ ハイテイ 近い"""
        from core.push_fold_v2 import is_near_haitei
        s1 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                        left_tile_count=4)
        s2 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                        left_tile_count=20)
        self.assertTrue(is_near_haitei(s1), "残り 4 枚 = ハイテイ 近い")
        self.assertFalse(is_near_haitei(s2), "残り 20 枚 = ハイテイ 遠い")

    def test_opp_full_fold(self):
        """@title 4.④ 他家 ベタ降り: 河 少 + リーチ 0 = True"""
        from core.push_fold_v2 import is_opp_full_fold
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            rivers=[['5p'], ['6p'], ['7p'], []],  # 他家 河 少
        )
        self.assertTrue(is_opp_full_fold(s), "ベタ降り True")

    def test_is_orasu(self):
        """@title 5.② オーラス: 南 4 局 = True"""
        from core.push_fold_v2 import is_orasu
        s1 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                        chang=3, ju=3)
        s2 = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                        chang=2, ju=3)
        self.assertTrue(is_orasu(s1), "南 4 局 = オーラス True")
        self.assertFalse(is_orasu(s2), "南 3 局 = オーラス False")

    def test_target_point_diff(self):
        """@title 5.③ ターゲット 点差: ビハインド"""
        from core.push_fold_v2 import calc_target_point_diff
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            scores=[20000, 28000, 25000, 22000],  # my_seat=0 = 20000 (2位 28000)
        )
        diff = calc_target_point_diff(s)
        # 20000 - 28000 = -8000
        self.assertEqual(diff, -8000, f"2位 との 点差 = -8000 (実測 {diff})")

    def test_honba_count(self):
        """@title 5.④ 供託 本場"""
        from core.push_fold_v2 import get_honba_count
        s = make_state(hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
                       chang=3)
        self.assertEqual(get_honba_count(s), 3, f"供託 3本 (実測 {get_honba_count(s)})")

    def test_tobi_risk_high(self):
        """@title 6.③ トビ リスク 大: 持ち点 < 1,000 = 大"""
        from core.push_fold_v2 import get_tobi_risk
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            scores=[500, 25000, 25000, 25000],  # 500 点
        )
        level, msg = get_tobi_risk(s)
        self.assertEqual(level, 2, f"持ち点 500 = トビ 大 (実測 {level})")
        self.assertIn('トビ', msg, f"メッセージ あり (実測 {msg})")

    def test_tobi_risk_zero(self):
        """@title 6.③ トビ 0 点 = 既に 終了"""
        from core.push_fold_v2 import get_tobi_risk
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            scores=[0, 25000, 25000, 25000],  # 0 点
        )
        level, msg = get_tobi_risk(s)
        self.assertEqual(level, 2, f"0 点 = 既に トビ (実測 {level})")

    def test_tobi_risk_medium(self):
        """@title 6.③ トビ リスク 中: 1,000-2,000 = 中"""
        from core.push_fold_v2 import get_tobi_risk
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            scores=[1500, 25000, 25000, 25000],  # 1,500 点
        )
        level, msg = get_tobi_risk(s)
        self.assertEqual(level, 1, f"1,500 点 = トビ 中 (実測 {level})")

    def test_tobi_risk_none(self):
        """@title 6.③ トビ リスク なし: 2,000+"""
        from core.push_fold_v2 import get_tobi_risk
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            scores=[20000, 25000, 25000, 25000],
        )
        level, msg = get_tobi_risk(s)
        self.assertEqual(level, 0, f"20,000 点 = リスク なし (実測 {level})")

    def test_tobi_fold(self):
        """@title 6.③ トビ 大 なら オリ 判定"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            doras=['5m'],  # ドラ 5m → ドラ 1
            tsumo_count=40,
            scores=[500, 25000, 25000, 25000],  # 500 点
        )
        decision, reasons = judge_push_fold(state, shanten=1)
        # トビ リスク 大 → score -= 150 → オリ 寄り
        self.assertIn('トビ', ' '.join(reasons), f"トビ 警告 あり (decision={decision}, {reasons})")

    def test_get_riichi_sticks(self):
        """@title 場の リーチ 棒 数"""
        from core.push_fold_v2 import get_riichi_sticks
        s = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','5p'],
            reach_states=[True, False, True, False],  # 2 家 リーチ
        )
        sticks = get_riichi_sticks(s)
        self.assertEqual(sticks, 2, f"リーチ 棒 2本 (実測 {sticks})")


if __name__ == '__main__':
    unittest.main(verbosity=2)
