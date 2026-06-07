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
SCORE_WALL_SUJI = 800
SCORE_NO_CHANCE = 700
SCORE_ONE_CHANCE = 200
SCORE_HONOR = 300
SCORE_MUSUJI_BASE = 0
SCORE_MUSUJI_PER_REACH = -200
SCORE_ATAMAKAKE_BONUS = 200
MATAGI_PENALTY = 100

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

    def _visible_counts(self) -> List[int]:
        return self.state.all_visible_counts()

    def _wall_tile_ids(self) -> set:
        visible = self._visible_counts()
        return {i for i in range(27) if visible[i] >= 4}

    def _wall_suji_ids(self) -> set:
        walls = self._wall_tile_ids()
        result = set()
        for tid in walls:
            for s in suji_safe_tiles(tid):
                result.add(s)
        return result

    def _no_chance_ids(self) -> set:
        visible = self._visible_counts()
        return {i for i in range(34) if visible[i] >= 4}

    def _one_chance_ids(self) -> set:
        visible = self._visible_counts()
        return {i for i in range(27) if visible[i] == 3}

    def _matagi_danger_ids(self, reach_seats: List[int]) -> set:
        result = set()
        for seat in reach_seats:
            for t in self.state.river[seat]:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid):
                    continue
                base = (tid // 9) * 9
                off = tid - base
                for delta in (-1, 1):
                    adj = off + delta
                    if 0 <= adj <= 8:
                        result.add(base + adj)
        return result

    def defense_score_for_tile(self, tile: str) -> int:
        tile_id = tile_to_id(tile)
        reach_seats = self._active_reach_seats()
        if not reach_seats:
            return 0
        n_reach = len(reach_seats)
        use_p1 = self.params.get('USE_PHASE1_DEFENSE', True)

        common_genbutsu = self._common_genbutsu_ids(reach_seats)
        if tile_id in common_genbutsu:
            return self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)

        if use_p1:
            wall_suji = self._wall_suji_ids()
            if tile_id in wall_suji:
                return self.params.get('SCORE_WALL_SUJI', SCORE_WALL_SUJI)
            no_chance = self._no_chance_ids()
            if tile_id in no_chance and not is_honor(tile_id):
                return self.params.get('SCORE_NO_CHANCE', SCORE_NO_CHANCE)

        suji_ids = self._reach_suji_ids(reach_seats)
        if tile_id in suji_ids:
            return self.params.get('SCORE_SUJI', SCORE_SUJI)

        if use_p1:
            one_chance = self._one_chance_ids()
            if tile_id in one_chance and not is_honor(tile_id):
                return self.params.get('SCORE_ONE_CHANCE', SCORE_ONE_CHANCE)

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

        if use_p1:
            matagi = self._matagi_danger_ids(reach_seats)
            score = self.params.get('SCORE_MUSUJI_BASE', SCORE_MUSUJI_BASE)
            score += n_reach * self.params.get('SCORE_MUSUJI_PER_REACH', SCORE_MUSUJI_PER_REACH)
            if tile_id in matagi:
                score -= self.params.get('MATAGI_PENALTY', MATAGI_PENALTY)
            return score
        return self.params.get('SCORE_MUSUJI_BASE', SCORE_MUSUJI_BASE)

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
        ukeire_total, _ = self.ukeire_for_discard(tile)
        shanten = self.shanten_after_discard(tile)
        SHANTEN_BACKTRACK_PENALTY = -self.params.get('PENALTY_SHANTEN_BACKWARD', 1000)
        best_shanten = self.best_shanten_after_single_discard()
        if shanten > best_shanten:
            return SHANTEN_BACKTRACK_PENALTY
        USE_P2 = self.params.get('USE_PHASE2_ATTACK', True)
        ukeire_mult = self.params.get('UKEIRE_MULTIPLIER', 10)
        shanten_mult = self.params.get('SHANTEN_MULTIPLIER', 100)
        if USE_P2:
            quality = self._ukeire_quality_mult(tile)
            effective_ukeire = int(ukeire_total * quality)
            score = effective_ukeire * ukeire_mult - shanten * shanten_mult
            score += self._hand_value_bonus(tile)
        else:
            score = ukeire_total * ukeire_mult - shanten * shanten_mult
        if shanten <= 0:
            score -= self._compute_furiten_penalty(tile)
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

    def _ukeire_quality_mult(self, tile: str) -> float:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        if current_shanten > 0:
            return 1.0
        n_ryanmen = 0
        n_kanchan = 0
        n_penchan = 0
        n_tanki = 0
        total = 0
        visible = self.state.all_visible_counts()
        for tid in range(34):
            if new_counts[tid] >= 4:
                continue
            test = list(new_counts)
            test[tid] += 1
            if open_meld_count == 0:
                ns = ShantenCalculator.calculate_closed_effective(test)
            else:
                ns = ShantenCalculator.calculate_open(test, open_meld_count)
            if ns >= current_shanten:
                continue
            remaining = 4 - visible[tid]
            if remaining <= 0:
                continue
            total += remaining
            if is_honor(tid):
                n_tanki += remaining
            else:
                base = (tid // 9) * 9
                off = tid - base
                has_left = off > 0 and new_counts[base + off - 1] >= 1
                has_right = off < 8 and new_counts[base + off + 1] >= 1
                has_left2 = off >= 2 and new_counts[base + off - 2] >= 1
                has_right2 = off <= 6 and new_counts[base + off + 2] >= 1
                if has_left and has_right:
                    n_ryanmen += remaining
                elif has_left2 and has_left:
                    n_kanchan += remaining
                elif has_right and has_right2:
                    n_kanchan += remaining
                elif off == 0 and has_right and has_right2:
                    n_penchan += remaining
                elif off == 8 and has_left and has_left2:
                    n_penchan += remaining
                else:
                    n_tanki += remaining
        if total == 0:
            return 0.0
        ryanmen_w = self.params.get('WAIT_RYANMEN', 1.0)
        kanchan_w = self.params.get('WAIT_KANCHAN', 0.7)
        penchan_w = self.params.get('WAIT_PENCHAN', 0.5)
        tanki_w = self.params.get('WAIT_TANKI', 0.5)
        weighted = (n_ryanmen * ryanmen_w + n_kanchan * kanchan_w
                     + n_penchan * penchan_w + n_tanki * tanki_w)
        return weighted / total

    def _hand_value_bonus(self, tile: str) -> int:
        from hand_value import estimate_han_advanced, estimate_win_score
        hand = list(self.state.my_hand)
        melds = self.state.my_melds
        discard_id = tile_to_id(tile)
        after_hand = [t for t in hand if tile_to_id(t) != discard_id or hand.count(t) > 1]
        if tile in after_hand:
            after_hand.remove(tile)
        open_meld_count = sum(1 for m in melds if m.is_open)
        has_riichi = any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat)
        han = estimate_han_advanced(after_hand, melds, self.state.doras,
                                     is_open=open_meld_count > 0,
                                     has_reach=has_riichi, is_ippatsu=False, is_tsumo=False)
        is_dealer = (self.state.my_seat % 4) == 0
        score = estimate_win_score(han, is_dealer)
        return score // 10

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
        use_ev = self.params.get('USE_EV_FRAMEWORK', False)
        if use_ev:
            return self._evaluate_tile_ev(tile) + self._positional_ev()
        v_attack = self.attack.attack_score_for_tile(tile)
        v_defense = self.defense.defense_score_for_tile(tile)
        push_score = self.strategy.compute_push_score()
        if not self.state.is_any_opponent_reach() and not self._any_opponent_has_open_meld(self.state):
            v = float(v_attack)
        else:
            v = push_score * v_attack + (1.0 - push_score) * v_defense
        v += self._get_keiten_bonus(tile)
        if self.params.get('USE_POSITIONAL_EV', True):
            v += self._positional_ev()
        return v

    def _evaluate_tile_ev(self, tile: str) -> float:
        p_win = self._estimate_win_p(tile)
        p_deal_in = self._estimate_deal_in_p(tile)
        win_score = self._estimate_win_score()
        deal_loss = self._estimate_deal_loss(tile)
        ev_hand = p_win * win_score - p_deal_in * deal_loss
        pos_val = self._positional_ev()
        return float(ev_hand + pos_val)

    def _estimate_win_p(self, tile: str) -> float:
        ukeire_total, _ = self.attack.ukeire_for_discard(tile)
        if ukeire_total <= 0:
            return 0.0
        shanten = self.attack.shanten_after_discard(tile)
        remaining = self.state.left_tile_count
        if remaining <= 0:
            return 0.0
        draw_chance = ukeire_total / max(1, remaining)
        if shanten <= -1:
            return min(0.9, draw_chance * 4)
        elif shanten == 0:
            return min(0.7, draw_chance * 3)
        elif shanten == 1:
            return min(0.3, draw_chance * 2)
        else:
            return min(0.1, draw_chance * 0.5)

    def _estimate_deal_in_p(self, tile: str) -> float:
        n_reach = len(self.defense._active_reach_seats())
        if n_reach == 0:
            return 0.0
        tile_id = tile_to_id(tile)
        if self.defense.is_genbutsu(tile_id):
            return 0.0
        reach_seats = self.defense._active_reach_seats()
        if tile_id in self.defense._common_genbutsu_ids(reach_seats):
            return 0.0
        if tile_id in self.defense._wall_suji_ids():
            return 0.01
        if tile_id in self.defense._no_chance_ids() and not is_honor(tile_id):
            return 0.02
        if tile_id in self.defense._reach_suji_ids(reach_seats):
            return 0.03 * n_reach
        if tile_id in self.defense._one_chance_ids() and not is_honor(tile_id):
            return 0.05 * n_reach
        matagi = self.defense._matagi_danger_ids(reach_seats)
        danger = 0.06
        danger += n_reach * 0.05
        if tile_id in matagi:
            danger += 0.05
        return min(0.5, danger)

    def _estimate_win_score(self) -> int:
        from scoring import estimate_han
        hand = self.state.my_hand
        melds = self.state.my_melds
        open_melds = [m for m in melds if m.is_open]
        is_open = len(open_melds) > 0
        han = estimate_han(hand, melds, self.state.doras, is_open,
                           is_tsumo=False, has_reach=False, is_ippatsu=False)
        if any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat):
            han += 1
        is_dealer = (self.state.my_seat % 4) == 0
        if han >= 5:
            if han >= 13:
                base = 32000
            elif han >= 11:
                base = 24000
            elif han >= 8:
                base = 16000
            elif han >= 6:
                base = 12000
            else:
                base = 8000
        else:
            base = 30 * 4 * (2 ** (2 + han))
            base = ((base + 99) // 100) * 100
        if is_dealer:
            base = int(base * 1.5)
        return base

    def _estimate_deal_loss(self, tile: str) -> int:
        n_reach = len(self.defense._active_reach_seats())
        if n_reach == 0:
            return 0
        base_loss = 3000
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            if self.state.reach_states[seat].is_reach:
                base_loss += 1000
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            for m in self.state.melds[seat]:
                if m.is_open:
                    for t in m.tiles:
                        for d in self.state.doras:
                            if tile_to_id(t) == tile_to_id(d):
                                base_loss += 1000
        return base_loss

    def _positional_ev(self) -> float:
        scores = self.state.scores
        my_seat = self.state.my_seat
        my_score = scores[my_seat]
        sorted_scores = sorted(enumerate(scores), key=lambda x: -x[1])
        my_rank = next(i for i, (s, _) in enumerate(sorted_scores) if s == my_seat)
        sorted_vals = [s for s, _ in sorted_scores]

        rank_pt = {0: 45, 1: 15, 2: -15, 3: -45}
        current_pt = rank_pt.get(my_rank, 0) + (my_score - 25000) // 1000

        if my_rank > 0:
            gap_to_up = sorted_vals[my_rank - 1] - my_score
            pt_gain_up = (rank_pt[my_rank - 1] + ((sorted_vals[my_rank - 1] + (gap_to_up // 2)) - 25000) // 1000) - current_pt
        else:
            gap_to_up = float('inf')
            pt_gain_up = 0

        if my_rank < 3:
            gap_to_down = my_score - sorted_vals[my_rank + 1]
            pt_loss_down = current_pt - (rank_pt[my_rank + 1] + ((sorted_vals[my_rank + 1] + (gap_to_down // 2)) - 25000) // 1000)
        else:
            gap_to_down = float('inf')
            pt_loss_down = 0

        remaining = self._remaining_kyokus()

        if remaining <= 0:
            urgency = 2.0
        elif remaining <= 2:
            urgency = 1.5
        elif remaining <= 4:
            urgency = 1.0
        else:
            urgency = 0.5

        up_prob = max(0, min(1, 1.0 - gap_to_up / max(1, remaining * 3000)))
        down_prob = max(0, min(1, 1.0 - gap_to_down / max(1, remaining * 3000)))

        naniire_bonus = self._naniire_bonus()

        positional_value = (up_prob * pt_gain_up - down_prob * pt_loss_down) * urgency + naniire_bonus
        return float(positional_value)

    def _remaining_kyokus(self) -> int:
        ju = self.state.ju
        chang = self.state.chang
        total = chang * 4 + ju + 1
        max_kyoku = 8
        remaining = max(0, max_kyoku - total)
        scores = self.state.scores
        if max(scores) < 30000 and total >= max_kyoku:
            remaining += 4
        return max(1, remaining)

    def _naniire_bonus(self) -> float:
        scores = self.state.scores
        top_score = max(scores)
        if top_score >= 29000 and top_score < 30000:
            rank = self.state.my_score_rank()
            if rank == 0:
                return 15.0
            else:
                return -5.0
        if top_score >= 30000:
            return 0.0
        if top_score < 27000 and self._remaining_kyokus() <= 2:
            rank = self.state.my_score_rank()
            if rank >= 2:
                return 10.0
        return 0.0

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

    def _wait_tiles_for_tenpai(self) -> List[int]:
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        ukeire = []
        for tid in range(34):
            if hand_counts[tid] >= 4:
                continue
            test = list(hand_counts)
            test[tid] += 1
            if open_meld_count == 0:
                s = ShantenCalculator.calculate_closed_effective(test)
            else:
                s = ShantenCalculator.calculate_open(test, open_meld_count)
            if s < 0:
                ukeire.append(tid)
        return ukeire

    def _wait_quality_score(self) -> float:
        waits = self._wait_tiles_for_tenpai()
        if not waits:
            return -0.5
        n_ryanmen = 0
        n_kanchan = 0
        n_penchan = 0
        n_tanki = 0
        n_shanpon = 0
        hand_counts = self.state.my_hand_counts()
        for tid in waits:
            test = list(hand_counts)
            test[tid] += 1
            if is_honor(tid):
                n_tanki += 1
            else:
                base = (tid // 9) * 9
                off = tid - base
                left_adj = test[base + off - 1] if off > 0 else 0
                right_adj = test[base + off + 1] if off < 8 else 0
                left_pair = off >= 2 and test[base + off - 2] >= 2
                right_pair = off <= 6 and test[base + off + 2] >= 2
                if left_adj >= 1 and right_adj >= 1:
                    n_ryanmen += 1
                elif (off >= 2 and test[base + off - 2] >= 1 and test[base + off - 1] >= 1):
                    n_kanchan += 1
                elif (off <= 6 and test[base + off + 1] >= 1 and test[base + off + 2] >= 1):
                    n_kanchan += 1
                elif off == 0 and right_adj >= 1 and test[base + off + 2] >= 1:
                    n_penchan += 1
                elif off == 8 and left_adj >= 1 and test[base + off - 2] >= 1:
                    n_penchan += 1
                else:
                    n_tanki += 1

        total = n_ryanmen + n_kanchan + n_penchan + n_tanki + n_shanpon
        if total == 0:
            return 0.0
        return (n_ryanmen * 0.3 + n_shanpon * 0.1 - n_kanchan * 0.1 - n_penchan * 0.2 - n_tanki * 0.2) / total

    def should_riichi(self) -> bool:
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
        if self.state.scores[self.state.my_seat] < 1000:
            return False

        riichi_score = self.params.get('RIICHI_BASE', 0.6)

        wait_q = self._wait_quality_score()
        riichi_score += wait_q * self.params.get('RIICHI_WAIT_WEIGHT', 1.0)

        if self.state.is_any_opponent_reach():
            riichi_score += self.params.get('RIICHI_OPP_REACH_PENALTY', -0.4)

        dora_count = 0
        for t in self.state.my_hand:
            for d in self.state.doras:
                if tile_to_id(t) == tile_to_id(d):
                    dora_count += 1
            if is_red_five(t):
                dora_count += 1
        riichi_score += dora_count * self.params.get('RIICHI_DORA_PENALTY', -0.1)

        late_threshold = self.params.get('RIICHI_LATE_TURN', 14)
        if self.state.tsumo_count >= late_threshold:
            riichi_score += self.params.get('RIICHI_LATE_PENALTY', -0.2)

        rank = self.state.my_score_rank()
        if rank == 3:
            riichi_score += self.params.get('RIICHI_LAST_RANK_BONUS', 0.2)

        threshold = self.params.get('RIICHI_THRESHOLD', 0.0)
        return riichi_score > threshold

    def should_call_meld(self, type_: int, tiles: List[str], from_seat: int) -> bool:
        if not self.strategy.is_meld_open_allowed():
            return False

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count >= 4:
            return False

        hand_counts = self.state.my_hand_counts()
        melded_tiles = []
        for mt in tiles:
            melded_tiles.append(tile_to_id(mt))
        after_counts = list(hand_counts)
        for tid in melded_tiles:
            after_counts[tid] = max(0, after_counts[tid] - 1) if len(tiles) > 1 else after_counts[tid]
        after_counts = list(hand_counts)
        if type_ == 2:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 2)
        elif type_ == 1:
            for t in tiles[1:]:
                tid = tile_to_id(t)
                after_counts[tid] = max(0, after_counts[tid] - 1)

        before_shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        after_shanten = ShantenCalculator.calculate_open(after_counts, open_meld_count + 1)

        if after_shanten >= before_shanten:
            return False

        if type_ == 2:
            target_id = tile_to_id(tiles[0])
            if target_id in (31, 32, 33):
                return True
            if self.state.tsumo_count >= self.params.get('MELD_LATE_TURN', 10):
                return True
            push = self.strategy.compute_push_score()
            if push > 0.5:
                return True

        if type_ == 1:
            if self.state.tsumo_count >= self.params.get('MELD_LATE_TURN', 12):
                return True
            push = self.strategy.compute_push_score()
            if push > 0.7:
                return True

        return False
