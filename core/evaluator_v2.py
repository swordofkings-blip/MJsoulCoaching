# -*- coding: utf-8 -*-
"""
@title ver.2 メイン評価器
@description モード判定に基づいてタプルを構築し、打牌候補を lexicographic (辞書式) に比較する。
              各打牌の説明もタプル比較結果から自動生成する。

記号規約 (厳守):
- min() で打牌を選ぶ (小さいほど AI が選びたくなる)
- 「多いほど良い」値は符号反転 (-)
- 戦術ランクは 0-99 (小さいほど切りやすい)
- 安全度は符号反転 (-)

動的タプル長:
- 2 向聴以上: 6 層 (向聴, 戦術ランク, -良形, -愚形, ドラ, -安全)
- 1 向聴/テンパイ: 5 層 (向聴, -DFS, 戦術ランク, ドラ, -安全)
  → DFS 期待値で「良形+高打点」を先読み
"""
from __future__ import annotations
from typing import List, Optional, Tuple

from core.shanten_v2 import ShantenCalculatorV2
from core.tactical_rank_v2 import tactical_discard_rank
from core.ukeire_v2 import count_good_bad_ukeire
from core.dfs_v2 import run_1shanten_dfs
from core.defense_v2 import safety_score
from core.strategy_v2 import get_mode, Mode
from core.chiitoitsu_v2 import chiitoitsu_tuple
from core.yakuman_v2 import yakuman_tuple
from str_converter import tile_to_id, is_red_five


# 層名 (タプル位置 → 日本語名) 7D版
# Why: 12クラスのモードに対応するため7次元固定長タプルを使用。
#       各モードで異なる要素が同じ層に入るため、汎用的な名前にする。
TIER_NAMES_7D = [
    '向聴数',
    '受入/安全度',
    '手役補正',
    '戦術ランク/愚形',
    'ドラ損失/安全度',
    '安全度',
    '予備',
]


class EvaluatorV2:
    def __init__(self, state, params: dict = None):
        self.state = state
        self.params = params or {}
        self.current_turn = (state.tsumo_count - 1) // 4 + 1
        self.is_last_round = state.is_last_round() if hasattr(state, 'is_last_round') else False
        self._mode_cache = None
        self._dfs_cache = {}
        self.rank_reasons: dict = {}

    def get_tuple_labels(self, tile: str) -> list[str]:
        """
        @title 7Dタプル動的ラベル名解決
        @description 現在の戦術モードおよび向聴数における7次元タプルの各スロットのラベル名を返す。
        """
        mode = self.get_mode()
        if mode == Mode.FOLD:
            # 危険パターン、現物種別を優先する順に修正
            return ['危険パターン', '現物種別', '安全度', '向聴数', '戦術ランク', '予備', '予備']

        hand_counts = list(self.state.my_hand_counts())
        discard_id = tile_to_id(tile)
        if 0 <= discard_id < 34:
            hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            shanten_after = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
        else:
            shanten_after = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

        if shanten_after <= 1:
            if mode == Mode.RIICHI_ATTACK:
                return ['向聴数', '危険パターン', '手役補正(DFS)', 'ドラ/赤打点', '戦術ランク', '安全度', '予備']
            if mode == Mode.OPEN_ATTACK:
                return ['向聴数', '危険パターン', '手役補正(DFS)', '戦術ランク', 'ドラ/赤打点', '安全度', '予備']
            if mode == Mode.DAMA_ATTACK:
                return ['向聴数', '危険パターン', '安全度', '手役補正(DFS)', 'ドラ/赤打点', '戦術ランク', '予備']
            if mode == Mode.URGENT_ATTACK:
                return ['向聴数', '手役補正(DFS)', 'ドラ/赤打点', '戦術ランク', '予備', '予備', '予備']
            if mode == Mode.HONITSU_DEFEND:
                return ['向聴数', '安全度', '染め色補正', '戦術ランク', '手役補正(DFS)', '予備', '予備']
            if mode == Mode.CHANTA_DEFEND:
                return ['向聴数', '安全度', '端牌補正', '戦術ランク', '手役補正(DFS)', '予備', '予備']
            if mode == Mode.DEFEND:
                # DEFENDの第1次元を危険度レベルに修正
                return ['危険度レベル', '向聴数', '手役補正(DFS)', '戦術ランク', 'ドラ/赤打点', '予備', '予備']
            # BALANCED
            return ['向聴数', '手役補正(DFS)', '戦術ランク', 'ドラ損失期待値', '安全度', '予備', '予備']
        else:
            # 2シャンテン以上 (good/bad 受入枚数ルート)
            if mode == Mode.RIICHI_ATTACK:
                return ['向聴数', '危険パターン', '良形受入', '愚形受入', 'ドラ/赤打点', '戦術ランク', '安全度']
            if mode == Mode.OPEN_ATTACK:
                return ['向聴数', '危険パターン', '総受入数', '戦術ランク', 'ドラ/赤打点', '安全度', '予備']
            if mode == Mode.DAMA_ATTACK:
                return ['向聴数', '危険パターン', '安全度', '良形受入', '愚形受入', 'ドラ/赤打点', '戦術ランク']
            if mode == Mode.URGENT_ATTACK:
                return ['向聴数', '良形受入', '愚形受入', 'ドラ/赤打点', '戦術ランク', '予備', '予備']
            if mode == Mode.HONITSU_DEFEND:
                return ['向聴数', '安全度', '染め色補正', '戦術ランク', '良形受入', '愚形受入', 'ドラ損失期待値']
            if mode == Mode.CHANTA_DEFEND:
                return ['向聴数', '安全度', '端牌補正', '戦術ランク', '良形受入', '愚形受入', 'ドラ損失期待値']
            if mode == Mode.DEFEND:
                # DEFENDの第1次元を危険度レベルに修正
                return ['危険度レベル', '向聴数', '戦術ランク', '良形受入', '愚形受入', 'ドラ/赤打点', '予備']
            # BALANCED (安牌温存を追加した新しい順序に修正)
            return ['向聴数', '安牌温存', '良形受入', '愚形受入', 'ドラ損失期待値', '戦術ランク', '安全度']


    def get_mode(self) -> Mode:
        if self._mode_cache is not None:
            return self._mode_cache
        persona = self.params.get('target_persona', None)
        self._mode_cache = get_mode(self.state, self.current_turn, self.is_last_round,
                                     player_name=persona)
        return self._mode_cache

    def _tier_labels_for_mode(self, shanten_after: int) -> list:
        """
        @title 現在のモード・向聴数に対応する7Dタプルの層名を返す
        @description _normal_tuple の各 return 文のタプル順序と一致させる。
        """
        mode = self.get_mode()
        if mode == Mode.FOLD:
            return ['危険パターン', '現物種別', '安全度', '向聴数', '戦術ランク', '予備', '予備']

        if shanten_after <= 1:
            if mode == Mode.RIICHI_ATTACK:
                return ['向聴数', '危険パターン', '手役補正(DFS)', 'ドラ/赤打点', '戦術ランク', '安全度', '予備']
            if mode == Mode.OPEN_ATTACK:
                return ['向聴数', '危険パターン', '手役補正(DFS)', '戦術ランク', 'ドラ/赤打点', '安全度', '予備']
            if mode == Mode.DAMA_ATTACK:
                return ['向聴数', '危険パターン', '安全度', '手役補正(DFS)', 'ドラ/赤打点', '戦術ランク', '予備']
            if mode == Mode.URGENT_ATTACK:
                return ['向聴数', '手役補正(DFS)', 'ドラ/赤打点', '戦術ランク', '予備', '予備', '予備']
            if mode == Mode.HONITSU_DEFEND:
                return ['向聴数', '安全度', '染め色補正', '戦術ランク', '手役補正(DFS)', '予備', '予備']
            if mode == Mode.CHANTA_DEFEND:
                return ['向聴数', '安全度', '端牌補正', '戦術ランク', '手役補正(DFS)', '予備', '予備']
            if mode == Mode.DEFEND:
                return ['危険度レベル', '向聴数', '手役補正(DFS)', '戦術ランク', 'ドラ/赤打点', '予備', '予備']
            # BALANCED
            return ['向聴数', '手役補正(DFS)', '戦術ランク', 'ドラ損失期待値', '安全度', '予備', '予備']

        # shanten_after >= 2
        if mode == Mode.RIICHI_ATTACK:
            return ['向聴数', '危険パターン', '良形受入', '愚形受入', 'ドラ/赤打点', '戦術ランク', '安全度']
        if mode == Mode.OPEN_ATTACK:
            return ['向聴数', '危険パターン', '総受入数', '戦術ランク', 'ドラ/赤打点', '安全度', '予備']
        if mode == Mode.DAMA_ATTACK:
            return ['向聴数', '危険パターン', '安全度', '良形受入', '愚形受入', 'ドラ/赤打点', '戦術ランク']
        if mode == Mode.URGENT_ATTACK:
            return ['向聴数', '良形受入', '愚形受入', 'ドラ/赤打点', '戦術ランク', '予備', '予備']
        if mode == Mode.HONITSU_DEFEND:
            return ['向聴数', '安全度', '染め色補正', '戦術ランク', '良形受入', '愚形受入', 'ドラ損失期待値']
        if mode == Mode.CHANTA_DEFEND:
            return ['向聴数', '安全度', '端牌補正', '戦術ランク', '良形受入', '愚形受入', 'ドラ損失期待値']
        if mode == Mode.DEFEND:
            return ['危険度レベル', '向聴数', '戦術ランク', '良形受入', '愚形受入', 'ドラ/赤打点', '予備']
        # BALANCED
        return ['向聴数', '安牌温存', '良形受入', '愚形受入', 'ドラ損失期待値', '戦術ランク', '安全度']

    def evaluate_tile(self, tile: str) -> Tuple:
        """
        @title 打牌評価
        @description 牌を評価してタプルを返す
        @returns 比較可能なタプル
        """
        mode = self.get_mode()
        if mode == Mode.CHIITOITSU:
            return chiitoitsu_tuple(self.state, tile)
        if mode in (Mode.KOKUSHI, Mode.YAKUMAN):
            yakuman_type = 'kokushi' if mode == Mode.KOKUSHI else _detect_yakuman_type(self.state)
            return yakuman_tuple(self.state, tile, yakuman_type)
        return self._normal_tuple(tile)

    def _honitsu_score(self, tile: str) -> float:
        """
        @title 混一色防御進行用ペルソナ補正
        @description 切る牌が手牌の最大染め色でも字牌でもない場合 100.0 を返し、
                     優先的に切り出すように誘導する。
        Why: 染め手進行では、染める色以外の数牌を真っ先に処理する必要がある。
             この補正により、手牌を強制的に特定の1色+字牌に絞り込む。
        @returns {float} 0.0 (残す) / 100.0 (切る)
        """
        counts = self.state.my_hand_counts()
        suits = [sum(counts[0:9]), sum(counts[9:18]), sum(counts[18:27])]
        main_suit = suits.index(max(suits)) * 9  # 0, 9, or 18
        tid = tile_to_id(tile)
        if 27 <= tid <= 33:
            return 0.0
        if main_suit <= tid < main_suit + 9:
            return 0.0
        return 100.0

    def _chanta_score(self, tile: str) -> float:
        """
        @title チャンタ防御進行用ペルソナ補正
        @description 切る牌が中張牌(2-8)の場合 100.0 を返し、優先的に切り出す。
                     端牌(1,9)と字牌は 0.0 で残す。
        Why: チャンタ進行では中張牌を最優先で処理し、端牌と字牌を残す。
        @returns {float} 0.0 (残す) / 100.0 (切る)
        """
        tid = tile_to_id(tile)
        if 27 <= tid <= 33:
            return 0.0
        if tid % 9 in (0, 8):
            return 0.0
        return 100.0

    def _count_danger_patterns(self, tile: str) -> tuple:
        """
        @title 平沢麻雀パターン理論: (放銃パターン総数, リャンメン数)
        @description 6パターン(上側両面/下側両面/ペンチャン/カンチャン/シャンポン/単騎)
                    のうち何パターンが残っているかをカウントする。
                    加えてリャンメン(両面)の数も返し、同パターン数時の
                    危険度の差別化に使う。
        Why:
            - 同パターン数でもリャンメンが多い方が危険(待ち牌数が多いため)。
            - 3枚見え(疑似壁)はリャンメン/ペンチャン/カンチャンを事実上不可能にする。
              残り1枚の牌で順子を構成することは現実的でないため。
            - 単騎・シャンポンは残り1枚でも成立するため別扱い。
        @param {str} tile - 評価する牌
        @returns {(int, int)} (総パターン数(0-6), リャンメン数(0-2))
        """
        from str_converter import tile_to_id, is_honor
        tid = tile_to_id(tile)
        visible = self.state.all_visible_counts()
        base = (tid // 9) * 9
        off = tid - base

        ryanmen = 0
        patterns = 0

        # WALL閾値: 通常の壁(4枚見え)と疑似壁(3枚見え=残り1枚)を区別
        # Why: リャンメン/ペンチャン/カンチャンは特定の牌を必要とするため、
        #      残り1枚では事実上構成不可能。3枚見えでパターン消去して良い。
        WALL = 3  # 3枚見え=壁扱い(残り1枚では順子構成不能)
        # 単騎/シャンポン用の厳格な壁
        WALL_STRICT = 4  # 4枚見えで完全枯れ

        # 字牌
        if is_honor(tid):
            if visible[tid] < WALL_STRICT:
                patterns += 1  # 単騎
            if visible[tid] >= 2:
                patterns += 1  # シャンポン
            return (patterns, 0)

        # 1. 上側両面 (リャンメン)
        if off <= 6:
            if visible[base + off + 1] < WALL and visible[base + off + 2] < WALL:
                patterns += 1
                ryanmen += 1

        # 2. 下側両面 (リャンメン)
        if off >= 2:
            if visible[base + off - 2] < WALL and visible[base + off - 1] < WALL:
                patterns += 1
                ryanmen += 1

        # 3. ペンチャン
        if off == 2:
            if visible[base + 0] < WALL and visible[base + 1] < WALL:
                patterns += 1
        elif off == 6:
            if visible[base + 7] < WALL and visible[base + 8] < WALL:
                patterns += 1

        # 4. カンチャン
        if 1 <= off <= 7:
            if visible[base + off - 1] < WALL and visible[base + off + 1] < WALL:
                patterns += 1

        # 5. シャンポン: 同種が合計2枚あれば成立(残り1枚でも対子は可能)
        if visible[tid] >= 2:
            patterns += 1

        # 6. 単騎: 場に4枚出きっていなければ常に成立
        if visible[tid] < WALL_STRICT:
            patterns += 1

        return (patterns, ryanmen)

    def _normal_tuple(self, tile: str) -> Tuple:
        """
        @title モード別7D評価タプル
        @description 12クラスの戦術モードの意図を忠実に反映した7次元固定長タプル。
                    不要な層は 0.0 でパディングし、常に7要素を返すことで
                    安定した辞書式比較(min選択)を実現する。
                    要素順: (向聴数, 受入/安全度, 手役補正, 戦術ランク/愚形,
                             ドラ損失/安全度, 安全度, 予備)
        """
        hand_counts = list(self.state.my_hand_counts())
        discard_id = tile_to_id(tile)
        if 0 <= discard_id < 34:
            hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            shanten_after = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
        else:
            shanten_after = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

        rank_val, rank_reason = tactical_discard_rank(self.state, tile)
        self.rank_reasons[tile] = rank_reason
        rank = rank_val
        dora_loss = _dora_loss(self.state, tile)
        saf = safety_score(self.state, tile)
        mode = self.get_mode()

        # ====================================================
        # 危険牌ペナルティ (saf_penalty) の算出
        # Why: 平沢麻雀パターン理論に基づき、6パターン中何パターンの
        #      放銃可能性が残っているかをカウントする。
        #      0=絶対安全(現物), 6=超危険(全パターン)。
        #      アタック系モードでは、同じシャンテン数を維持できる安全牌が
        #      あるなら危険牌を迂回する。
        # ====================================================
        n_reach = sum(1 for s in range(4) if s != self.state.my_seat
                      and self.state.reach_states[s] is not None
                      and self.state.reach_states[s].is_reach)
        n_opp_melds = sum(1 for s in range(4) if s != self.state.my_seat
                          for m in self.state.melds[s] if m.is_open)
        has_threat = (n_reach >= 1 or n_opp_melds >= 2)

        if has_threat:
            # Why: 総パターン数を10倍+リャンメン数で重み付け。
            #      同パターン数ならリャンメンの多い方が危険。
            pcount, rcount = self._count_danger_patterns(tile)
            saf_penalty = pcount * 10.0 + rcount * 1.0
        else:
            saf_penalty = 0.0

        # ====================================================
        # 7D固定長タプル補助: (a, b, c, d, e, f, g)
        # ====================================================

        # --- FOLD: 危険度最優先、危険度同数の場合は個別現物→共通現物→非現物 の順で切る ---
        if mode == Mode.FOLD:
            pcount, rcount = self._count_danger_patterns(tile)
            danger = pcount * 10.0 + rcount * 1.0
            reach_seats = [s for s in range(4) if s != self.state.my_seat
                           and self.state.reach_states[s] is not None
                           and self.state.reach_states[s].is_reach]
            n_reach = len(reach_seats)
            gen_count = sum(1 for s in reach_seats if self._is_genbutsu_for(tile, s))
            if n_reach == 0 or gen_count == 0:
                gen_priority = 2  # 非現物
            elif gen_count < n_reach:
                gen_priority = 0  # 個別現物 (部分カバー) → 先に切る
            else:
                gen_priority = 1  # 共通現物 (全カバー) → 後で切る
            return (danger, gen_priority, -saf, shanten_after, rank, 0.0, 0.0)

        if shanten_after <= 1:
            dfs = self._get_dfs(tile)
            good, bad = 0, 0  # not used in 1-shanten path

            if mode == Mode.RIICHI_ATTACK:
                return (shanten_after, saf_penalty, -dfs, -dora_loss, rank, -saf, 0.0)
            if mode == Mode.OPEN_ATTACK:
                return (shanten_after, saf_penalty, -dfs, rank, -dora_loss, -saf, 0.0)
            if mode == Mode.DAMA_ATTACK:
                return (shanten_after, saf_penalty, -saf, -dfs, -dora_loss, rank, 0.0)
            if mode == Mode.URGENT_ATTACK:
                return (shanten_after, -dfs, -dora_loss, rank, 0.0, 0.0, 0.0)
            if mode == Mode.HONITSU_DEFEND:
                return (shanten_after, -saf, -self._honitsu_score(tile), rank, -dfs, 0.0, 0.0)
            if mode == Mode.CHANTA_DEFEND:
                return (shanten_after, -saf, -self._chanta_score(tile), rank, -dfs, 0.0, 0.0)
            if mode == Mode.DEFEND:
                if saf >= 1000:
                    danger_level = 0.0  # 共通現物
                elif saf >= 900:
                    danger_level = 1.0  # 特定現物
                elif saf >= 600:
                    danger_level = 2.0  # スジ・壁など
                else:
                    danger_level = 3.0  # 片スジ・無筋 (上限クランプして無駄なシャンテン戻しを防ぐ)
                return (danger_level, shanten_after, -dfs, rank, dora_loss, 0.0, 0.0)
            # BALANCED
            return (shanten_after, -dfs, rank, dora_loss, -saf, 0.0, 0.0)

        else:
            good, bad = count_good_bad_ukeire(self.state, tile)

            if mode == Mode.RIICHI_ATTACK:
                return (shanten_after, saf_penalty, -good, -bad, -dora_loss, rank, -saf)
            if mode == Mode.OPEN_ATTACK:
                return (shanten_after, saf_penalty, -(good + bad), rank, -dora_loss, -saf, 0.0)
            if mode == Mode.DAMA_ATTACK:
                return (shanten_after, saf_penalty, -saf, -good, -bad, -dora_loss, rank)
            if mode == Mode.URGENT_ATTACK:
                return (shanten_after, -good, -bad, -dora_loss, rank, 0.0, 0.0)
            if mode == Mode.HONITSU_DEFEND:
                return (shanten_after, -saf, -self._honitsu_score(tile), rank, -good, -bad, dora_loss)
            if mode == Mode.CHANTA_DEFEND:
                return (shanten_after, -saf, -self._chanta_score(tile), rank, -good, -bad, dora_loss)
            if mode == Mode.DEFEND:
                if saf >= 1000:
                    danger_level = 0.0  # 共通現物
                elif saf >= 900:
                    danger_level = 1.0  # 特定現物
                elif saf >= 600:
                    danger_level = 2.0  # スジ・壁など
                else:
                    danger_level = 3.0  # 片スジ・無筋 (上限クランプして無駄なシャンテン戻しを防ぐ)
                return (danger_level, shanten_after, rank, -good, -bad, dora_loss, 0.0)
            # BALANCED (安牌キープ→受入優先)
            safest = self._find_safest_tile()
            has_safe = 0.0 if tile == safest else -1.0
            return (shanten_after, has_safe, -good, -bad, dora_loss, rank, -saf)

    def _danger_score(self, tile: str) -> float:
        """1牌の危険度スコア (パターン理論: 大きい=危険)"""
        try:
            pcount, rcount = self._count_danger_patterns(tile)
            return pcount * 10.0 + rcount * 1.0
        except Exception:
            return 30.0

    def _is_genbutsu_for(self, tile: str, seat: int) -> bool:
        try:
            tid = tile_to_id(tile)
            for t in self.state.river[seat]:
                if tile_to_id(t) == tid:
                    return True
        except Exception:
            pass
        return False

    def _find_safest_tile(self) -> str:
        """手牌中でパターン理論の危険度が最小の牌を1枚返す (安牌キープ対象)"""
        best_tile = None
        best_danger = float('inf')
        for t in self.state.my_hand:
            danger = self._danger_score(t)
            if danger < best_danger:
                best_danger = danger
                best_tile = t
        return best_tile

    def _get_dfs(self, tile: str) -> float:
        """@title DFS 期待値 (キャッシュ付き)"""
        if tile in self._dfs_cache:
            return self._dfs_cache[tile]
        dfs = run_1shanten_dfs(self.state, tile)
        self._dfs_cache[tile] = dfs
        return dfs

    def best_discard(self, hand: List[str]) -> Optional[str]:
        """
        @title 最良打牌の選択
        @description 候補タプルの中で min() を選ぶ。
        @returns 最良打牌の文字列
        """
        if not hand:
            return None
        if self._is_winning():
            return None

        unique_tiles = list(dict.fromkeys(hand))
        scored: List[Tuple[Tuple, str]] = []
        for tile in unique_tiles:
            t = self.evaluate_tile(tile)
            scored.append((t, tile))

        scored.sort(key=lambda x: x[0])
        return scored[0][1]

    def best_discard_with_score(self, hand: List[str]) -> Tuple[Optional[str], Tuple]:
        if not hand:
            return None, None
        if self._is_winning():
            return None, None

        unique_tiles = list(dict.fromkeys(hand))
        scored: List[Tuple[Tuple, str]] = []
        for tile in unique_tiles:
            t = self.evaluate_tile(tile)
            scored.append((t, tile))

        scored.sort(key=lambda x: x[0])
        return scored[0][1], scored[0][0]

    def explain_discard(self, hand: List[str], chosen: str) -> str:
        """
        @title 打牌の理由をタプル比較結果から生成
        @description chosen がなぜ選ばれたかを日本語で説明する。
                    候補間で比較し、最初に差がついた層で勝敗が決まったことを示す。
        """
        if not hand or chosen is None:
            return "打牌なし"

        unique_tiles = list(dict.fromkeys(hand))
        scored: List[Tuple[Tuple, str]] = []
        for tile in unique_tiles:
            t = self.evaluate_tile(tile)
            scored.append((t, tile))
        scored.sort(key=lambda x: x[0])

        chosen_tuple = None
        for t, t_str in scored:
            if t_str == chosen:
                chosen_tuple = t
                break

        if chosen_tuple is None:
            return f"{_to_japanese(chosen)} を切ります。"

        # 現在のモード・向聴数に対応した層名を取得
        shanten_after = int(chosen_tuple[0]) if len(chosen_tuple) > 0 else 99
        layer_names = self._tier_labels_for_mode(shanten_after)

        for t, t_str in scored:
            if t_str == chosen:
                continue
            for i, (a, b) in enumerate(zip(chosen_tuple, t)):
                if a != b:
                    layer_name = layer_names[i] if i < len(layer_names) else f'層{i+1}'
                    cr = self.rank_reasons.get(chosen, "")
                    or_ = self.rank_reasons.get(t_str, "")
                    chosen_jp = _to_japanese(chosen)
                    other_jp = _to_japanese(t_str)
                    return _explain_difference(chosen_jp, other_jp, i, a, b, layer_name,
                                               chosen_reason=cr, other_reason=or_)
        chosen_jp = _to_japanese(chosen)
        return f"{chosen_jp} を切ります (タイ)。"

    def _is_winning(self) -> bool:
        """@title 和了形かどうか"""
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculatorV2.calculate_closed_effective(hand_counts) <= -1
        else:
            return ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count) <= -1

    def _v1_evaluator(self):
        """ver.1 Evaluator への委譲 (should_riichi 等の複雑なメソッド用)"""
        from core.evaluator import Evaluator
        return Evaluator(self.state, params=self.params)

    def should_tsumo(self) -> bool:
        """@title ツモ和了判定 (v1 委譲)"""
        try:
            return self._v1_evaluator().should_tsumo()
        except Exception:
            return bool(len(self.state.my_hand) >= 14)

    def should_ron(self) -> bool:
        """@title ロン和了判定 (v1 委譲)"""
        try:
            return self._v1_evaluator().should_ron()
        except Exception:
            return False

    def should_riichi(self) -> bool:
        """
        @title 立直判定 (ver.2 加減算モデル)
        @description core/riichi_v2.py の 自前実装
        """
        from core.riichi_v2 import should_riichi as _should_riichi_v2
        try:
            return _should_riichi_v2(self.state, self.params)
        except Exception:
            return False

    def should_call_meld(self, call_type: int, tiles: list, from_seat: int) -> bool:
        """@title 鳴き判定 (core/meld_v2.py 自前実装)"""
        from core.meld_v2 import should_call_meld as _should_call_meld_v2
        try:
            decision, _reason = _should_call_meld_v2(self.state, call_type, tiles, from_seat, self.params)
            return bool(decision)
        except Exception:
            return False

    def should_kan(self) -> bool:
        """
        @title 槓判定 (暗槓・加槓・大明槓)
        @description core/riichi_v2.py の 自前実装 (meld_v2 委譲)
        """
        from core.riichi_v2 import should_kan as _should_kan_v2
        try:
            # 加槓は 嶺上牌 + 1 枚 を加えるので call_type=1 (ポン) として
            # 槓元の牌 + 嶺上牌 で ポン判定 する代わりに
            # ここでは meld_v2.should_call_meld に 委譲 する 簡易版
            from core.meld_v2 import should_call_meld
            return should_call_meld(self.state, 1, self.state.my_hand[-1:] * 2, 0, self.params)
        except Exception:
            return False

    def should_ankan(self) -> bool:
        """@title 暗槓判定"""
        try:
            return self._v1_evaluator().should_ankan()
        except Exception:
            return False

    def should_kakan(self, tile: str) -> bool:
        """@title 加槓判定"""
        try:
            return self._v1_evaluator().should_kakan(tile)
        except Exception:
            return False

    def should_daiminkan(self, tile: str, from_seat: int) -> bool:
        """@title 大明槓判定"""
        try:
            return self._v1_evaluator().should_daiminkan(tile, from_seat)
        except Exception:
            return False

    def should_call_meld(self, call_type: int, tiles: List[str], from_seat: int) -> bool:
        """
        @title 鳴き判定 (ver.2 加減算モデル + モード同期)
        @description 22 要素の加重スコア + 現在の戦術モードに応じた門前崩しペナルティ
        """
        from core.meld_v2 import should_call_meld as _should_call_meld_v2
        try:
            mode = self.get_mode()
            decision, reason = _should_call_meld_v2(self.state, call_type, tiles, from_seat, self.params, mode=mode)
            self.last_meld_reason = reason
            return decision
        except Exception as e:
            self.last_meld_reason = f"ver.2 meld error: {e}"
            return False

    def should_go_kokushi_13(self) -> bool:
        """
        @title 国士無双 13 面待ち判定
        @description テンパイ時に 13 種全部 幺九牌ならツモる (国士)
        """
        from str_converter import hand_to_counts
        hand_counts = hand_to_counts(self.state.my_hand)
        yaochu_ids = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        yaochu_kinds = sum(1 for i in yaochu_ids if hand_counts[i] >= 1)
        return yaochu_kinds >= 13

    def get_tile_description(self, tile: str) -> str:
        """@title 牌の日本語説明"""
        return _to_japanese(tile)

    def record_detail(self, label: str, value) -> None:
        """@title デバッグ用: 詳細ログ (no-op)"""
        pass

    def describe_hand_structure(self) -> str:
        """
        @title 手牌構造の解説
        @description 面子手 (雀頭・塔子・面子) の構成を日本語で説明する。
                    例: 「3 面子 + 1 雀頭 + 0 塔子 (1 向聴)」
        @returns 日本語の説明文
        """
        hand_counts = list(self.state.my_hand_counts())
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        sh, melds, pairs, taatsu = ShantenCalculatorV2.explain_hand_structure(hand_counts, open_meld_count)
        if sh <= -1:
            return f"和了形 ({melds} 面子 + {pairs} 雀頭)"
        label = {0: 'テンパイ', 1: '1 向聴', 2: '2 向聴', 3: '3 向聴',
                 4: '4 向聴', 5: '5 向聴', 6: '6 向聴', 7: '7 向聴', 8: '8 向聴'}.get(sh, f'{sh} 向聴')
        parts = [f"{melds} 面子"]
        if pairs > 0:
            parts.append(f"{pairs} 雀頭")
        if taatsu > 0:
            parts.append(f"{taatsu} 塔子")
        return f"{label} (" + " + ".join(parts) + ")"


def _dora_loss(state, tile: str) -> int:
    """@title ドラ表示牌を捨てる際の損失"""
    loss = 0
    tile_id = tile_to_id(tile)
    for d in state.doras:
        try:
            if tile_to_id(d) == tile_id:
                loss += 1
        except Exception:
            pass
    return loss


def _detect_yakuman_type(state) -> str:
    """@title 進行中の役満タイプを返す"""
    from core.yakuman_v2 import get_active_yakuman
    y = get_active_yakuman(state)
    return y or 'kokushi'


def _to_japanese(tile: str) -> str:
    """@title 牌の日本語表記"""
    from str_converter import tile_to_id
    tid = tile_to_id(tile)
    if tid is None or tid < 0:
        return tile
    if 0 <= tid <= 26:  # 数牌
        n = (tid % 9) + 1
        suit = '萬' if tid < 9 else ('筒' if tid < 18 else '索')
        if tile.startswith('0'):
            return f"赤{n}{suit}"
        return f"{n}{suit}"
    # 字牌
    honors = ['東', '南', '西', '北', '白', '發', '中']
    return honors[tid - 27]


def _explain_difference(chosen: str, other: str, layer: int, a, b, layer_name: str,
                         chosen_reason: str = "", other_reason: str = "") -> str:
    """
    @title 差分説明
    @description layer_name に応じた日本語理由テキストを動的に生成する。
    """
    layer_num = layer + 1
    num_str = {1: '①', 2: '②', 3: '③', 4: '④', 5: '⑤', 6: '⑥', 7: '⑦'}.get(layer_num, f'層{layer_num}')
    # A. 向聴数
    if layer_name == '向聴数':
        if a < b:
            return f"{num_str}向聴数: {chosen} を切ると {a} 向聴、{other} を切ると {b} 向聴。前進するので {chosen} を切ります。"
        else:
            return f"{num_str}向聴数: {other} を切ったほうが前進 ({a} < {b})。{chosen} は温存します。"
    # B. DFS期待値 / 手役補正(DFS)
    elif 'DFS' in layer_name or '手役' in layer_name:
        if a < b:
            return f"{num_str}{layer_name}: {chosen} を切ると手役/打点期待値 {-a:.2f} (高い)。{other} は {-b:.2f}。{chosen} のほうが良形変化や高打点が見込めます。"
        else:
            return f"{num_str}{layer_name}: {other} のほうが手役/打点期待値が高い ({other}={-b:.2f}, {chosen}={-a:.2f})。{chosen} は温存します。"
    # C. 戦術ランク
    elif '戦術ランク' in layer_name:
        cr = f"({chosen_reason})" if chosen_reason else ""
        or_ = f"({other_reason})" if other_reason else ""
        if a < b:
            return f"{num_str}{layer_name}: {chosen} は {a:.0f} {cr}で切りやすい、{other} は {b:.0f} {or_}で残したい。まず {chosen} から切ります。"
        else:
            return f"{num_str}{layer_name}: {other} は {b:.0f} {or_}で切りやすい、{chosen} は {a:.0f} {cr}で残したい。{chosen} は温存します。"
    # D. 良形受入 / 総受入数 / 受入
    elif '受入' in layer_name or '枚数' in layer_name:
        try:
            val_a = -int(a)
            val_b = -int(b)
        except Exception:
            val_a = abs(a)
            val_b = abs(b)
        if a < b:
            return f"{num_str}{layer_name}: {chosen} を切ると受け入れが {val_a} 枚。{other} を切ると {val_b} 枚。{chosen} のほうが受け入れが増えます。"
        else:
            return f"{num_str}{layer_name}: {other} のほうが受け入れが多い ({other}={val_b}枚, {chosen}={val_a}枚)。{chosen} は温存します。"
    # E. 安全度
    elif '安全度' in layer_name or '安全' in layer_name:
        val_a = abs(a)
        val_b = abs(b)
        if a < b:
            return f"{num_str}{layer_name}: {chosen} は安全度指標 {val_a:.1f} (高い)。{other} は {val_b:.1f}。{chosen} のほうが安全なので切ります。"
        else:
            return f"{num_str}{layer_name}: {other} のほうが安全 ({other}={val_b:.1f}, {chosen}={val_a:.1f})。{chosen} は温存します。"
    # F. ドラ損失 / ドラ/赤打点
    elif 'ドラ' in layer_name:
        val_a = abs(a)
        val_b = abs(b)
        if a < b:
            return f"{num_str}{layer_name}: {chosen} はドラ損失/打点指標 {val_a:.1f} (有利)。{other} は {val_b:.1f}。{chosen} のほうがドラを活かせます。"
        else:
            return f"{num_str}{layer_name}: {other} のほうがドラを活かせる ({other}={val_b:.1f}, {chosen}={val_a:.1f})。{chosen} は温存します。"
    # G. 危険パターン / 危険度
    elif '危険' in layer_name or 'パターン' in layer_name:
        if a < b:
            return f"{num_str}{layer_name}: {chosen} は危険パターン {a:.1f} (低い)。{other} は {b:.1f}。{chosen} のほうが放銃パターンが少ないため切ります。"
        else:
            return f"{num_str}{layer_name}: {other} のほうが危険パターンが少ない ({other}={b:.1f}, {chosen}={a:.1f})。{chosen} は温存します。"
    # H. その他・デフォルト
    return f"{num_str} {layer_name} で {chosen} (={a:.2f}) vs {other} (={b:.2f}) の比較結果、{chosen} を選びます。"
