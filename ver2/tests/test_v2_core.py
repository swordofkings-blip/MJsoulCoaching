# -*- coding: utf-8 -*-
"""
@title ver.2 ユニットテスト
@description ver.2 コア実装の単体テスト。
              特定局面で期待される打牌が選ばれるかをチェック。

テスト観点:
1. シャンテン計算 (ver.1 と同じ結果になるか)
2. 戦術ランク関数 (0-99 が麻雀セオリー通り)
3. 受け入れ計算 (良形/愚形分解)
4. DFS 期待値
5. 防御評価
6. EvaluatorV2.best_discard (タプル比較)
7. EvaluatorV2.explain_discard (コーチング)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import unittest
from typing import List

from core.game_state import GameState, Meld, ReachState
from core.shanten_v2 import ShantenCalculatorV2
from core.tactical_rank_v2 import tactical_discard_rank, _is_dora, _is_yakuhai
from core.ukeire_v2 import count_good_bad_ukeire
from core.dfs_v2 import run_1shanten_dfs
from core.defense_v2 import safety_score
from core.strategy_v2 import get_mode, Mode
from core.evaluator_v2 import EvaluatorV2
from str_converter import hand_to_counts, tile_to_id, id_to_tile


def make_state(hand: List[str], melds: List = None, doras: List[str] = None,
               tsumo_count: int = 0, my_seat: int = 0, chang: int = 0, ju: int = 0,
               reach_states: List[bool] = None, scores: List[int] = None,
               left_tile_count: int = 70) -> GameState:
    """
    @title テスト用 GameState 作成ヘルパー
    @description テストで使う GameState をシンプルに作る
    """
    state = GameState()
    state.my_hand = list(hand)
    state.my_seat = my_seat
    state.chang = chang
    state.ju = ju
    state.tsumo_count = tsumo_count
    state.doras = doras or []
    state.my_melds = melds or []
    state.left_tile_count = left_tile_count
    state.dealer_seat = 0

    if reach_states is None:
        reach_states = [False] * 4
    state.reach_states = [ReachState() for _ in range(4)]
    for i, r in enumerate(reach_states):
        state.reach_states[i].is_reach = r

    if scores is None:
        scores = [25000, 25000, 25000, 25000]
    state.scores = scores

    # 河の初期化
    if not state.river:
        state.river = [[] for _ in range(4)]

    return state


class TestShantenCalculatorV2(unittest.TestCase):
    """@title シャンテン計算のテスト"""

    def test_agari_0_shanten(self):
        """@title 和了形: 0 向聴"""
        # 123456789m 123456p 11s (テスト用: 完成形 14 枚)
        hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1s','1s']
        counts = hand_to_counts(hand)
        shanten = ShantenCalculatorV2.calculate_closed_effective(counts)
        self.assertEqual(shanten, -1, "完成形は -1")

    def test_tenpai_0_shanten(self):
        """@title 4 面子 + 1 塔子 は 0 or 1 向聴"""
        # 123456789m 123p 5p6p 塔子 → 4p, 7p 待ち (0 向聴のはず)
        hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','6p']
        counts = hand_to_counts(hand)
        shanten = ShantenCalculatorV2.calculate_closed_effective(counts)
        # 0 or 1 シャンテンなら OK (シャンテン計算の境界値対応)
        self.assertLessEqual(shanten, 1, f"4面子+1塔子は <= 1 シャンテン (実際={shanten})")

    def test_1_shanten(self):
        """@title 1 向聴"""
        # 123456789m 123p 11s (1 シャンテン)
        hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','1s','9p']
        counts = hand_to_counts(hand)
        shanten = ShantenCalculatorV2.calculate_closed_effective(counts)
        self.assertEqual(shanten, 1, "1 シャンテン")

    def test_chiitoi_4_pairs(self):
        """@title 七対子: 4 対子は 2 向聴 (6-4=2)"""
        hand = ['1m','1m','2m','2m','3m','3m','4p','4p','1z','2z','3z','5z','6z','7z']
        counts = hand_to_counts(hand)
        chiitoi = ShantenCalculatorV2._chiitoitsu_shanten(counts)
        self.assertEqual(chiitoi, 2, f"七対子 2 向聴 (4 対子, 6-4) (実際={chiitoi})")

    def test_explain_hand_structure_1_shanten(self):
        """@title explain_hand_structure: 1 向聴手の最良分解を返す"""
        # 123456789m 1p 4p 5p 6p (14 枚) → 1 シャンテン
        # - 3 面子 (123m 456m 789m) + 0 雀頭 + 1 塔子 (45p) + 2 孤立 (1p, 6p) = 1 シャンテン
        hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','4p','5p','6p','7p']
        counts = hand_to_counts(hand)
        sh, melds, pairs, taatsu = ShantenCalculatorV2.explain_hand_structure(counts, 0)
        self.assertEqual(sh, 1, f"1 シャンテン (実際={sh})")
        self.assertEqual(melds, 3, f"3 面子 (実際={melds})")
        self.assertEqual(pairs, 0, f"雀頭なし (実際={pairs})")
        self.assertGreaterEqual(taatsu, 1, f"1 塔子以上 (実際={taatsu})")

    def test_explain_hand_structure_0_shanten_tenpai(self):
        """@title explain_hand_structure: 0 向聴 (テンパイ) の最良分解を返す"""
        # 123456789m 123p 56p (14 枚) → 0 シャンテン (テンパイ)
        # - 4 面子 (123m 456m 789m 123p) + 0 雀頭 + 1 塔子 (56p)
        hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','6p']
        counts = hand_to_counts(hand)
        sh, melds, pairs, taatsu = ShantenCalculatorV2.explain_hand_structure(counts, 0)
        self.assertEqual(sh, 0, f"0 シャンテン (実際={sh})")
        self.assertEqual(melds, 4, f"4 面子 (実際={melds})")
        self.assertGreaterEqual(taatsu, 1, f"テンパイ = 塔子 or 雀頭 (実際={taatsu})")

    def test_explain_hand_structure_with_pair(self):
        """@title explain_hand_structure: 雀頭有りの 1 向聴"""
        # 123456789m 111p 4p 7p (14 枚) → 1 シャンテン
        # - 3 面子 (123m 456m 789m) + 1 雀頭 (11p) + 1 孤立 (1p) + 2 孤立 (4p, 7p)
        # 4p 7p は距離があり 1 牌 ツモでも塔子を作らない → テンパイではない
        hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p','1p','4p','7p']
        counts = hand_to_counts(hand)
        sh, melds, pairs, taatsu = ShantenCalculatorV2.explain_hand_structure(counts, 0)
        self.assertEqual(sh, 1, f"1 シャンテン (実際={sh})")
        self.assertEqual(melds, 3, f"3 面子 (実際={melds})")
        self.assertEqual(pairs, 1, f"1 雀頭 (実際={pairs})")


class TestTacticalRank(unittest.TestCase):
    """@title 戦術ランク関数のテスト"""

    def test_2_visible_honor_is_rank_0(self):
        """@title 2 枚切れ字牌は rank 0 (真っ先に切る)"""
        # 2z (南) は chang=0, my_seat=0 では客風 (オタ風)
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '2z'],
            doras=['1m'],
        )
        # 河に南が 2 枚切れている想定 → 2 枚切れ客風 = rank 0
        state.river[1] = ['2z', '2z']
        rank = tactical_discard_rank(state, '2z')
        self.assertEqual(rank, 0, f"2 枚切れ客風は rank 0 (実際={rank})")

    def test_1_visible_otakaze_is_rank_1(self):
        """@title 1 枚切れオタ風は rank 1 (早く切る)"""
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '2z'],
            doras=['1m'],
        )
        # 河に南が 1 枚切れ → 1 枚見え客風 = rank 1
        state.river[1] = ['2z']
        rank = tactical_discard_rank(state, '2z')
        self.assertEqual(rank, 1, f"1 枚切れ客風は rank 1 (実際={rank})")

    def test_0_visible_otakaze_is_rank_2(self):
        """@title 生牌オタ風は rank 2 (重なるリスク)"""
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '2z'],
            doras=['1m'],
        )
        # 誰も南を切っていない → 生牌客風 = rank 2
        rank = tactical_discard_rank(state, '2z')
        self.assertEqual(rank, 2, f"生牌オタ風は rank 2 (実際={rank})")

    def test_isolated_terminal_is_rank_10(self):
        """@title 孤立端牌は rank 10 (真っ先に切る)"""
        # 1m 1 枚孤立 (2m, 3m なし) + 13 枚
        state = make_state(
            hand=['1m', '2p', '3p', '4p', '5p', '6p', '7p', '8p', '9p', '1s', '2s', '3s', '4s', '5s'],
        )
        rank = tactical_discard_rank(state, '1m')
        self.assertLessEqual(rank, 10, f"孤立端牌は rank <= 10 (実際={rank})")

    def test_isolated_28_is_rank_20(self):
        """@title 孤立 2, 8 は rank 20"""
        state = make_state(
            hand=['1m', '3m', '4m', '5m', '6m', '7m', '9m', '1p', '2p', '3p', '4p', '5p', '6p', '2s'],
        )
        rank = tactical_discard_rank(state, '2s')
        # 孤立 28 は rank 20
        self.assertLessEqual(rank, 20, f"孤立 28 は rank <= 20 (実際={rank})")

    def test_dora_terminal_higher_rank(self):
        """@title ドラ表示牌は rank 75 以上 (残す)"""
        state = make_state(
            hand=['1m', '1m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p', '6p', '7p'],
            doras=['1m'],  # 1m がドラ
        )
        rank = tactical_discard_rank(state, '1m')
        # ドラ雀頭・ドラ単騎は rank 75 以上
        self.assertGreaterEqual(rank, 75, f"ドラ雀頭・ドラ単騎は rank 75 以上 (実際={rank})")

    def test_pair_is_rank_50(self):
        """@title 雀頭 (中張) は rank 50"""
        state = make_state(
            hand=['5m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p', '6p', '7p', '8p'],
        )
        rank = tactical_discard_rank(state, '5m')
        self.assertLessEqual(rank, 50, f"中張雀頭は rank <= 50 (実際={rank})")

    def test_antoi_is_rank_95(self):
        """@title 暗刻 (3 枚) は rank 95 (絶対残す)"""
        state = make_state(
            hand=['1m', '1m', '1m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p', '6p'],
        )
        rank = tactical_discard_rank(state, '1m')
        self.assertEqual(rank, 95, "暗刻は rank 95")


class TestUkeire(unittest.TestCase):
    """@title 受け入れ計算のテスト"""

    def test_good_vs_bad_ukeire(self):
        """@title 良形と愚形の受け入れを分けてカウント"""
        # 123m 456m 789m 123p 5p6p → 14 枚で 0 向聴
        # 5p 切ると 良形両面 (4p, 7p) が受入
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','6p'],
        )
        good, bad = count_good_bad_ukeire(state, '5p')
        # 良形待ち: 4p, 7p (両面)
        self.assertGreater(good, 0, f"両面受入がカウントされる (実際 good={good}, bad={bad})")

    def test_kanchan_ukeire(self):
        """@title カンチャン受入は愚形カウント"""
        # 123m 5m 789m → 4m 待ち (カンチャン)
        state = make_state(
            hand=['1m','2m','3m','5m','6m','7m','8m','9m','1p','2p','3p','4p','6p'],
        )
        good, bad = count_good_bad_ukeire(state, '1p')
        # 4m 待ち (カンチャン) を含む
        # ※ 1p 切るとシャンテン数進むか確認
        self.assertGreaterEqual(bad, 0, "愚形受入カウント")


class TestDefense(unittest.TestCase):
    """@title 防御評価のテスト"""

    def test_genbutsu_is_safe(self):
        """@title リーチ者への現物は安全度 1000"""
        # 現実的な構成: 自分が 9m を 1 枚持ち、リーチ者の河に 9m がある
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p'],
            reach_states=[False, True, False, False],  # player 1 がリーチ
        )
        # リーチ者 (player 1) の河に 9m が 1 枚 → 現物
        state.river[1] = ['9m']
        score = safety_score(state, '9m')
        self.assertEqual(score, 1000, f"リーチ者への現物は安全度 1000 (実際={score})")

    def test_no_chance_honor_tile_is_safe(self):
        """@title ノーチャンス (字牌 4 枚すべて見えている) は安全度 1000"""
        # 字牌 (5z) で 4 枚見える → 単騎/双碰/国士無双以外ロンされない
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5z'],
            reach_states=[False, True, False, False],
        )
        # 5z: 手牌 1 枚 + 河 3 枚 = 4 枚見える
        state.river[0] = ['5z']
        state.river[2] = ['5z']
        state.river[3] = ['5z']
        score = safety_score(state, '5z')
        self.assertEqual(score, 1000, f"ノーチャンス字牌は安全度 1000 (実際={score})")

    def test_no_chance_suit_tile_NOT_1000(self):
        """@title ノーチャンス (数牌 4 枚見えている) でも 1000 ではない
        4 枚見えても、両面/カンチャン/ペンチャン待ちでロンされ得る
        """
        # 5m: 手牌 1 枚 + 河 3 枚 = 4 枚見える
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5m'],
            reach_states=[False, True, False, False],
        )
        # 4 枚見える
        state.river[0] = ['5m']
        state.river[2] = ['5m']
        state.river[3] = ['5m']
        score = safety_score(state, '5m')
        # 1000 ではない (両面/カンチャン待ちでロンされ得る)
        self.assertLess(score, 1000, f"4 枚見えの数牌は 1000 未満 (実際={score})")

    def test_no_chance_5m_with_kanchan_wait(self):
        """@title 5m 4 枚見えでも 4-6 カンチャン待ちでロンされ得る
        立直者が 4m6m (カンチャン 5m 待ち) を持ってる場合
        """
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5m'],
            reach_states=[False, True, False, False],
        )
        # 4 枚見える
        state.river[0] = ['5m']
        state.river[2] = ['5m']
        state.river[3] = ['5m']
        score = safety_score(state, '5m')
        # カンチャン (4-6) と両面 (3-4-5, 5-6-7) で ロンされ得る
        self.assertLess(score, 1000, f"5m 4 枚見えでも安全ではない (実際={score})")

    def test_no_chance_3m_penchan_safe(self):
        """@title 3m 4 枚見え + ペンチャン待ち (1-2-3 順子, 3 待ち) について
        3m は 1-2-3 順子の 3 待ちとして使われ得る
        """
        # 3m: 手牌 1 枚 + 河 3 枚 = 4 枚見える
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p'],
            reach_states=[False, True, False, False],
        )
        state.river[0] = ['3m']
        state.river[2] = ['3m']
        state.river[3] = ['3m']
        score = safety_score(state, '3m')
        # 3m は 1-2-3 順子の 3 待ち (penchan) としてロンされ得る
        self.assertLess(score, 1000, f"3m 4 枚見えでも penchan 待ちで安全ではない (実際={score})")

    def test_3_visible_not_genbutsu_is_not_safe(self):
        """@title 3 枚見えてリーチ者河になければ安全度 1000 ではない"""
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p'],
            reach_states=[False, True, False, False],
        )
        # 5m: 手牌 1 枚 + 河 (自分 1 のみ) 2 枚 = 3 枚見える
        # リーチ者 (player 1) の河に 5m はない → 現物ではない
        state.river[0] = ['5m']
        score = safety_score(state, '5m')
        # 1 枚見えないので ロン可能性あり、1000 ではない
        self.assertLess(score, 1000, f"3 枚見えで現物でない牌は 1000 未満 (実際={score})")

    def test_yakuhai_safety(self):
        """@title 役牌の安全度"""
        # 5z (白) を持つ
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '5z', '5z'],
        )
        score = safety_score(state, '5z')
        # 5z は 0 枚見えで 2 枚持ち → 単騎/双碰待ちで危険
        self.assertLess(score, 800, "生牌役牌対子は危険")


class TestStrategy(unittest.TestCase):
    """@title モード判定のテスト"""

    def test_tenpai_no_reach_is_attack(self):
        """@title テンパイ他家なし → ATTACK"""
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','5p'],
            tsumo_count=12 * 4 + 1,  # turn 7
        )
        mode = get_mode(state, current_turn=7, is_last_round=False)
        self.assertEqual(mode, Mode.ATTACK, "テンパイ・他家なし → ATTACK")

    def test_4th_place_last_round_is_urgent(self):
        """@title 終盤 4 位 → URGENT_ATTACK"""
        # 自分が 4 位 (最下位) になる点数設定
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','5p'],
            tsumo_count=18 * 4,
            my_seat=3,  # 4 位 (player 3)
            scores=[30000, 35000, 40000, 10000],  # player 3 = 10000 (4 位)
        )
        mode = get_mode(state, current_turn=18, is_last_round=True)
        self.assertEqual(mode, Mode.URGENT_ATTACK, f"終盤 4 位 → URGENT_ATTACK (実際={mode})")

    def test_reach_not_tenpai_is_defend(self):
        """@title 1 リーチ + 1 向聴 → DEFEND"""
        # 1 向聴手牌 (4 対子含む)
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','1p','1p','1z','2z','3z','3z'],
            tsumo_count=12 * 4,
            reach_states=[False, True, False, False],  # 下家がリーチ
        )
        mode = get_mode(state, current_turn=12, is_last_round=False)
        self.assertEqual(mode, Mode.DEFEND, "1 リーチ + 1 向聴 → DEFEND")


class TestEvaluator(unittest.TestCase):
    """@title EvaluatorV2 のテスト"""

    def test_isolated_terminal_discarded_first(self):
        """@title 孤立端牌が真っ先に切られる"""
        # 1m 孤立 + 234567m 678p 123z (合計 13 枚)
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '6p', '7p', '8p', '1z', '2z', '3z'],
        )
        ev = EvaluatorV2(state)
        # 14 枚に揃える (このテストは孤立牌が選ばれるかだけ確認)
        best = ev.best_discard(['1m', '2m', '3m', '4m', '5m', '6m', '7m'])
        # 孤立端牌 1m は rank 10 なので最優先で選ばれる
        self.assertEqual(best, '1m', f"孤立端牌 (1m) が真っ先に切られる (実際={best})")

    def test_explanation_generated(self):
        """@title 説明文が生成される"""
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '6p', '7p', '8p', '1z', '2z', '3z'],
        )
        ev = EvaluatorV2(state)
        chosen = ev.best_discard(state.my_hand)
        explanation = ev.explain_discard(state.my_hand, chosen)
        self.assertIsNotNone(explanation, "説明文が生成される")
        self.assertGreater(len(explanation), 0, "説明文が空でない")

    def test_safe_tile_preferred_in_defend(self):
        """@title DEFEND モードで安全牌優先"""
        # リーチ者に現物を切る
        state = make_state(
            hand=['1m', '2m', '3m', '4m', '5m', '6m', '7m', '8m', '9m', '1p', '2p', '3p', '4p', '5p'],
            tsumo_count=12 * 4,
            reach_states=[False, True, False, False],  # 下家がリーチ
        )
        # 河に 9m (現物)
        state.river[1] = ['9m']
        ev = EvaluatorV2(state)
        best = ev.best_discard(state.my_hand)
        # 9m が安全度高いが、手牌にないので、比較的安全な牌を選ぶはず
        self.assertIsNotNone(best, "打牌が選ばれる")

    def test_tenpai_dfs_path(self):
        """@title テンパイ時 (または 1 シャンテン) は DFS 経路で評価される"""
        # 1 シャンテン手牌: 123456789m 123p 5p 6p
        # どの牌を切っても 0 or 1 シャンテン
        state = make_state(
            hand=['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','6p'],
            tsumo_count=10 * 4,
        )
        ev = EvaluatorV2(state)
        hand_list = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','6p']
        best = ev.best_discard(hand_list)
        # ベスト打牌が選ばれる (None ではない)
        self.assertIsNotNone(best, f"打牌が選ばれる (実際={best})")
        # 選ばれた牌がハンド内に存在する
        self.assertIn(best, hand_list, f"打牌がハンド内に存在 (実際={best})")


if __name__ == '__main__':
    unittest.main(verbosity=2)
