# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Optional, Tuple

from game_state import GameState
from str_converter import (
    HONOR_IDS,
    TERMINAL_IDS,
    hand_to_counts,
    is_honor,
    is_red_five,
    is_terminal,
    tile_to_id,
    suji_safe_tiles,
)
from strategy_manager import ShantenCalculator, StrategyManager


SCORE_GENBUTSU = 1000
SCORE_SUJI = 500
SCORE_HONOR = 300
SCORE_MUSUJI = 0
SCORE_ATAMAKAKE_BONUS = 200

# 形テン（形式テンパイ）ボーナス: 終盤に和了形に一歩でも近づける打牌を評価する
# 巡目別加算値。18巡目以降はボーナス倍率を上げ、流局間際の押し返しを強調する設計。
KEITEN_BONUS_15_17 = 1500
KEITEN_BONUS_18 = 3000


class DefenseEvaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}

    def genbutsu_tiles(self) -> List[int]:
        genbutsu = set()
        for i in range(4):
            for t in self.state.river[i]:
                genbutsu.add(tile_to_id(t))
            for m in self.state.melds[i]:
                for t in m.tiles:
                    genbutsu.add(tile_to_id(t))
        if self.state.last_discard_seat >= 0 and self.state.last_discard_seat == self.state.my_seat:
            for i in range(4):
                if i == self.state.my_seat:
                    continue
                for rs_i, rs in enumerate(self.state.reach_states):
                    pass
        return list(genbutsu)

    def same_turn_furiten_tiles(self) -> List[int]:
        return []

    def is_suji_tile(self, my_seat: int, opponent_seat: int, tile_id: int) -> bool:
        return False

    def is_genbutsu(self, tile_id: int) -> bool:
        for i in range(4):
            for t in self.state.river[i]:
                if tile_to_id(t) == tile_id:
                    return True
        return False

    def is_suji_for_opponent(self, tile_id: int, opponent_seat: int) -> bool:
        if is_honor(tile_id):
            return False
        for t in self.state.river[opponent_seat]:
            try:
                if tile_to_id(t) == tile_id:
                    return True
            except Exception:
                continue
        return False

    def is_atamakake(self, tile_id: int) -> bool:
        return False

    def _active_reach_seats(self) -> List[int]:
        """
        @title 立直者の seat リスト
        @description 現在リーチ宣言している他家（自分以外）の seat インデックス一覧を返す。
        @returns {List[int]} リーチ中他家の seat 番号リスト
        """
        return [i for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach]

    def _common_genbutsu_ids(self, reach_seats: List[int]) -> set:
        """
        @title 共通現物の算出
        @description 立直している他家全員の河に共通して現れている牌IDの集合（共通現物）を返す。
        @param {List[int]} reach_seats - 立直者の seat リスト
        @returns {set} 共通現物牌IDの集合
        """
        if not reach_seats:
            return set()
        common = None
        for seat in reach_seats:
            ids = set()
            for t in self.state.river[seat]:
                try:
                    ids.add(tile_to_id(t))
                except Exception:
                    continue
            for m in self.state.melds[seat]:
                for t in m.tiles:
                    try:
                        ids.add(tile_to_id(t))
                    except Exception:
                        continue
            common = ids if common is None else common & ids
            if not common:
                return set()
        return common or set()

    def _reach_suji_ids(self, reach_seats: List[int]) -> set:
        """
        @title リーチ者河からのスジ集合
        @description いずれかの立直者の河にある牌の現物スジ（suji_safe_tiles で導出される安全牌）の集合を返す。
        @param {List[int]} reach_seats - 立直者の seat リスト
        @returns {set} スジ牌IDの集合
        """
        result = set()
        for seat in reach_seats:
            for t in self.state.river[seat]:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid):
                    continue
                for s in suji_safe_tiles(tid):
                    result.add(s)
        return result

    def defense_score_for_tile(self, tile: str) -> int:
        """
        @title 防御評価値の算出
        @description 立直している他家のみを基準に、共通現物 (1000)、現物スジ (500)、未晒字牌 (300) の安全度を返す。
        誰もリーチしていない序盤局面では、現物加点による自滅を防ぐため安全牌評価をスキップし 0 を返す。
        @param tile 評価対象の牌 (例: "5m")
        @returns int 防御評価値 (高いほど安全)
        """
        tile_id = tile_to_id(tile)
        reach_seats = self._active_reach_seats()
        if not reach_seats:
            return self.params.get('SCORE_MUSUJI', SCORE_MUSUJI)
        common_genbutsu = self._common_genbutsu_ids(reach_seats)
        if tile_id in common_genbutsu:
            return self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
        suji_ids = self._reach_suji_ids(reach_seats)
        if tile_id in suji_ids:
            return self.params.get('SCORE_SUJI', SCORE_SUJI)
        for seat in reach_seats:
            for t in self.state.river[seat]:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid) and tid == tile_id:
                    return self.params.get('SCORE_HONOR', SCORE_HONOR)
        if is_honor(tile_id):
            visible = self.state.all_visible_counts()
            if visible[tile_id] == 0:
                return self.params.get('SCORE_HONOR', SCORE_HONOR)
        return self.params.get('SCORE_MUSUJI', SCORE_MUSUJI)

    def _collect_suji_from_river(self, seat: int) -> List[int]:
        result = set()
        for t in self.state.river[seat]:
            try:
                tid = tile_to_id(t)
            except Exception:
                continue
            if is_honor(tid):
                continue
            for s in suji_safe_tiles(tid):
                result.add(s)
        return list(result)


class AttackEvaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}

    def ukeire_for_discard(self, discard_tile: str) -> Tuple[int, int]:
        """
        @title 有効牌の計算
        @description 指定された牌を捨てた後の手牌に対して、シャンテン数を下げる有効牌の総枚数と種類数を計算する。
        @param discard_tile 捨てる牌の文字列 (例: "5m")
        @returns Tuple[int, int] (有効牌の総山残り枚数, 有効牌の種類数)
        """
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)

        # 切った後のシャンテン数を計算
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)

        visible = self.state.all_visible_counts()
        ukeire_total = 0
        unique_ukeire = 0

        for tile_id in range(34):
            if new_counts[tile_id] >= 4:
                continue

            # 1枚仮に加える
            temp_counts = list(new_counts)
            temp_counts[tile_id] += 1

            # 加えた後のシャンテン数を計算
            if open_meld_count == 0:
                next_shanten = ShantenCalculator.calculate_closed_effective(temp_counts)
            else:
                next_shanten = ShantenCalculator.calculate_open(temp_counts, open_meld_count)

            # シャンテン数が下がっていれば有効牌
            if next_shanten < current_shanten:
                # 山に残っている枚数を算出 (見えている枚数を4枚から引く)
                remaining = 4 - visible[tile_id]
                if remaining > 0:
                    ukeire_total += remaining
                    unique_ukeire += 1

        return ukeire_total, unique_ukeire

    def shanten_after_discard(self, discard_tile: str) -> int:
        """
        @title 打牌後のシャンテン数
        @description 指定牌を打牌したと仮定したときの自家手牌のシャンテン数を計算する。
        @param discard_tile 捨てる牌の文字列 (例: "5m")
        @returns int 打牌後のシャンテン数（-1: 和了形, 0: テンパイ）
        """
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            return ShantenCalculator.calculate_open(new_counts, open_meld_count)

    def best_shanten_after_single_discard(self) -> int:
        """
        @title 最良シャンテン数の算出
        @description 14枚手牌から1枚を捨てた場合に達成可能な最小（最良）のシャンテン数を返す。手牌の牌種類数だけ評価し、最良値を採用する。
        @returns int 全候補打牌のうち最小のシャンテン数
        """
        hand_counts = list(self.state.my_hand_counts())
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        best = 8
        seen = set()
        for t in self.state.my_hand:
            tid = tile_to_id(t)
            if tid in seen or hand_counts[tid] <= 0:
                continue
            seen.add(tid)
            tmp = list(hand_counts)
            tmp[tid] -= 1
            if open_meld_count == 0:
                s = ShantenCalculator.calculate_closed_effective(tmp)
            else:
                s = ShantenCalculator.calculate_open(tmp, open_meld_count)
            if s < best:
                best = s
        return best

    def attack_score_for_tile(self, tile: str) -> int:
        """
        @title 攻撃評価値の算出
        @description 有効牌枚数と打牌後シャンテン数から攻撃寄りの評価値を計算する。打牌によって手牌全体の最良シャンテン数を後退させる牌には強いペナルティを科す。
        また、3向聴以下で6ブロック以上の状態を維持する打牌にもペナルティを科し、5ブロックへのスリム化（ブロック整理）を促す。
        @param tile 捨てる牌の文字列 (例: "5m")
        @returns int 攻撃評価値（高いほど和了に近い）
        """
        ukeire_total, _ = self.ukeire_for_discard(tile)
        shanten = self.shanten_after_discard(tile)
        SHANTEN_BACKTRACK_PENALTY = -self.params.get('PENALTY_SHANTEN_BACKWARD', 1000)
        best_shanten = self.best_shanten_after_single_discard()
        if shanten > best_shanten:
            return SHANTEN_BACKTRACK_PENALTY
        ukeire_mult = self.params.get('UKEIRE_MULTIPLIER', 10)
        shanten_mult = self.params.get('SHANTEN_MULTIPLIER', 100)
        score = ukeire_total * ukeire_mult - shanten * shanten_mult
        # Why: 打牌後にテンパイする場合、自河にある牌が和了牌に含まれているとロン和了できない（永久フリテン）。
        # Why: ただしツモ和了は常に可能なため、一律禁止ではなくフリテン和了牌の比率に応じた軽度なペナルティとする。
        # Why: ダマテンフリテン両面や国士十三面待ちなど戦術的にフリテンを選ぶケースを許容するため、最大でも300点の減点に留める。
        if shanten <= 0:
            score -= self._compute_furiten_penalty(tile)
        # Why: 3向聴以下で6ブロック以上を維持する打牌は、受入が狭まるだけでなくテンパイ時に余剰な危険牌を切り出す原因になる。
        # Why: ペナルティを適用して最も弱いターツを切らせ、5ブロックへスリム化させる。
        if shanten <= 3:
            hand_counts = self.state.my_hand_counts()
            discard_id = tile_to_id(tile)
            after_counts = list(hand_counts)
            after_counts[discard_id] = max(0, after_counts[discard_id] - 1)
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            blocks_before = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
            blocks_after = ShantenCalculator.calculate_blocks(after_counts, open_meld_count)
            if blocks_before >= 6 and blocks_after >= 6:
                penalty = self.params.get('PENALTY_6BLOCK_MAINTAIN', 80)
                score -= penalty
        return score

    def _get_furiten_tile_ids(self) -> set:
        my_river_ids = set()
        for t in self.state.river[self.state.my_seat]:
            try:
                my_river_ids.add(tile_to_id(t))
            except Exception:
                continue
        return my_river_ids

    def _compute_furiten_penalty(self, discard_tile: str) -> int:
        furiten_ids = self._get_furiten_tile_ids()
        if not furiten_ids:
            return 0
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        if current_shanten > 0:
            return 0
        furiten_wait = 0
        total_wait = 0
        for tile_id in range(34):
            if new_counts[tile_id] >= 4:
                continue
            test = list(new_counts)
            test[tile_id] += 1
            if open_meld_count == 0:
                test_shanten = ShantenCalculator.calculate_closed_effective(test)
            else:
                test_shanten = ShantenCalculator.calculate_open(test, open_meld_count)
            if test_shanten < current_shanten:
                total_wait += 1
                if tile_id in furiten_ids:
                    furiten_wait += 1
        if total_wait == 0:
            return 0
        ratio = furiten_wait / total_wait
        max_penalty = self.params.get('FURITEN_PENALTY', 300)
        return int(ratio * max_penalty)


class Evaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        self.attack = AttackEvaluator(state, params=self.params)
        self.defense = DefenseEvaluator(state, params=self.params)
        self.strategy = StrategyManager(state, params=self.params)

    def _get_keiten_bonus(self, tile: str) -> int:
        """
        @title 形式テンパイ（形テン）ボーナス
        @description 終盤において、打牌後にテンパイ（または和了）となる手牌に加算するボーナス値を返す。
        @param tile 捨てる牌の文字列 (例: "5m")
        @returns int ボーナス値（条件を満たさない場合は0）
        """
        tsumo = self.state.tsumo_count
        if 15 <= tsumo <= 17:
            shanten_after = self.attack.shanten_after_discard(tile)
            if shanten_after <= 0:
                return self.params.get('KEITEN_BONUS_15_17', KEITEN_BONUS_15_17)
        elif tsumo >= 18:
            shanten_after = self.attack.shanten_after_discard(tile)
            if shanten_after <= 0:
                return self.params.get('KEITEN_BONUS_18', KEITEN_BONUS_18)
        return 0

    @staticmethod
    def _any_opponent_has_open_meld(state: GameState) -> bool:
        for seat in range(4):
            if seat == state.my_seat:
                continue
            for m in state.melds[seat]:
                if m.is_open:
                    return True
        return False

    def evaluate_tile(self, tile: str) -> float:
        """
        @title 牌の総合評価
        @description 攻撃評価と防御評価を押し引き度 (PushScore) で重み付きブレンドし、終盤の形テンボーナスを加算する。
        誰もリーチしておらず他家に副露もない場合、防御評価が意味を持たないため攻撃評価を100%使う。
        @param tile 評価対象の牌 (例: "5m")
        @returns float 総合評価値
        """
        v_attack = self.attack.attack_score_for_tile(tile)
        v_defense = self.defense.defense_score_for_tile(tile)
        push_score = self.strategy.compute_push_score()
        if not self.state.is_any_opponent_reach() and not self._any_opponent_has_open_meld(self.state):
            v = float(v_attack)
        else:
            v = push_score * v_attack + (1.0 - push_score) * v_defense
        v += self._get_keiten_bonus(tile)
        return v

    def _hand_is_winning(self) -> bool:
        counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(counts) <= -1
        else:
            return ShantenCalculator.calculate_open(counts, open_meld_count) <= -1

    def best_discard(self, hand: List[str]) -> Optional[str]:
        """
        @title 最良打牌の選択
        @description 手牌の各牌タイプを評価し、最も評価値の高い牌を返す。
        手牌が既に和了形の場合は None を返す（和了を選択すべき）。
        @param hand 自家手牌のリスト
        @returns Optional[str] 最良打牌の文字列。handが空または和了形なら None。
        """
        if not hand:
            return None
        if self._hand_is_winning():
            return None
        unique_tiles = list(dict.fromkeys(hand))
        scored = [(self.evaluate_tile(t), t) for t in unique_tiles]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1]

    def best_discard_with_score(self, hand: List[str]) -> Tuple[Optional[str], float]:
        if not hand:
            return None, float('-inf')
        if self._hand_is_winning():
            return None, float('inf')
        unique_tiles = list(dict.fromkeys(hand))
        scored = [(self.evaluate_tile(t), t) for t in unique_tiles]
        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1], scored[0][0]

    _YAOCHU_INDICES = [0, 8, 9, 17, 18, 26] + list(range(27, 34))

    def _kokushi_pair_tile(self) -> Optional[str]:
        counts = self.state.my_hand_counts()
        yaochu_types = sum(1 for i in self._YAOCHU_INDICES if counts[i] >= 1)
        if yaochu_types != 13:
            return None
        for i in self._YAOCHU_INDICES:
            if counts[i] >= 2:
                for t in self.state.my_hand:
                    if tile_to_id(t) == i:
                        return t
        return None

    def _kokushi_13_benefit_score(self) -> float:
        counts = self.state.my_hand_counts()
        yaochu_types = sum(1 for i in self._YAOCHU_INDICES if counts[i] >= 1)
        if yaochu_types != 13:
            return 0.0
        visible = self.state.all_visible_counts()
        total_remaining = sum(max(0, 4 - visible[i]) for i in self._YAOCHU_INDICES)
        remaining_ratio = total_remaining / (13 * 4)
        tsumo = self.state.tsumo_count
        turn_factor = max(0.0, 1.0 - tsumo / 18.0)

        my_score = self.state.scores[self.state.my_seat]
        rank = self.state.my_score_rank()
        if rank == 0:
            score_necessity = 0.0
        else:
            above_score = sorted(self.state.scores, reverse=True)[rank - 1]
            gap = above_score - my_score
            score_necessity = min(1.0, max(0.0, gap / 32000))

        benefit = remaining_ratio * 0.15 + turn_factor * 0.15 + score_necessity * 0.70
        return max(0.0, min(1.0, benefit))

    def should_go_kokushi_13(self) -> bool:
        if self._kokushi_pair_tile() is None:
            return False
        benefit = self._kokushi_13_benefit_score()
        threshold = self.params.get('KOKUSHI_13_THRESHOLD', 0.5)
        return benefit >= threshold

    def should_kan(self) -> bool:
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count > 0:
            return False
        hand_counts = self.state.my_hand_counts()
        push = self.strategy.compute_push_score()
        for i, c in enumerate(hand_counts):
            if c == 4:
                if push > 0.6:
                    return True
        return False

    def should_riichi(self) -> bool:
        from sdk import all_tiles
        if any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat):
            return False
        hand_counts = self.state.my_hand_counts()
        if sum(hand_counts) != 14:
            return False
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count > 0:
            return False
        shanten = ShantenCalculator.calculate_closed(hand_counts)
        if shanten > 0:
            return False
        scores = self.state.scores
        if scores[self.state.my_seat] < 1000:
            return False
        return True

    def should_call_meld(self, type_: int, tiles: List[str], from_seat: int) -> bool:
        if not self.strategy.is_meld_open_allowed():
            return False
        return False
