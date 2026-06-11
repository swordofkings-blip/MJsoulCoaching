# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Optional, Tuple

from game_state import GameState
from str_converter import (
    HONOR_IDS,
    TERMINAL_IDS,
    hand_to_counts,
    id_to_tile,
    is_honor,
    is_red_five,
    is_terminal,
    tile_to_id,
    suji_safe_tiles,
)
from strategy_manager import ShantenCalculator, StrategyManager
from hand_value import SANGEN


SCORE_GENBUTSU = 1000
SCORE_SUJI = 500
SCORE_WALL_SUJI = 800
SCORE_KABE_EDGE = 750
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


class MeldSealTracker:
    """配牌時点の役進行度と初期向聴数から「副露封印モード」を判定"""

    _CLOSED_YAKU = {'pinfu', 'chiitoitsu', 'ryanpeikou', 'sanshoku', 'ittsuu'}
    _OPEN_YAKU = {'yakuhai', 'toitoi', 'honitsu', 'chinitsu', 'tanyao'}

    def __init__(self):
        self._sealed: bool | None = None

    def evaluate(self, hand, melds, seat, chang, ju) -> bool:
        if self._sealed is not None:
            return self._sealed
        # 初期向聴が4以上 = 手が極端に悪い → 門前維持（来るべき手を待つ）
        from strategy_manager import ShantenCalculator
        counts = hand_to_counts(hand)
        initial_shanten = ShantenCalculator.calculate_closed(counts)
        if initial_shanten >= 4:
            self._sealed = True
            return True
        try:
            from yaku_detector import analyze_all
            yi = analyze_all(hand, melds, seat=seat, chang=chang, ju=ju)
            closed_w = sum(y.progress * y.closed_han for n, y in yi.items() if n in self._CLOSED_YAKU)
            open_w = sum(y.progress * y.closed_han for n, y in yi.items() if n in self._OPEN_YAKU)
            self._sealed = closed_w >= open_w and closed_w > 0
        except Exception:
            self._sealed = False
        return self._sealed


class DefenseEvaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        self.evaluator = None

    def record_detail(self, tile: str, msg: str):
        if self.evaluator:
            self.evaluator.record_detail(tile, msg)

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
        return {i for i in range(34) if visible[i] == 3}

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

    def _kabe_edge_safe_ids(self) -> set:
        visible = self._visible_counts()
        result = set()
        for tid in range(27):
            if visible[tid] >= 4:
                off = tid % 9
                base = (tid // 9) * 9
                if off == 1:
                    result.add(base)
                elif off == 7:
                    result.add(base + 8)
        return result

    def defense_score_for_tile(self, tile: str) -> int:
        tile_id = tile_to_id(tile)
        reach_seats = self._active_reach_seats()
        n_reach = len(reach_seats)
        use_p1 = self.params.get('USE_PHASE1_DEFENSE', True)

        # リーチ者がいなくても基本的な安全度を評価
        if not reach_seats:
            # 字牌の見え枚数で安全判定
            if is_honor(tile_id):
                visible = self.state.all_visible_counts()
                count = visible[tile_id]
                if count >= 2:
                    score = self.params.get('SCORE_HONOR', SCORE_HONOR)
                    self.record_detail(tile, f"字牌{count}枚見え安全 (+{score})")
                    return score
                if count == 0:
                    score = self.params.get('SCORE_HONOR', SCORE_HONOR)
                    self.record_detail(tile, f"字牌・生牌安全 (+{score})")
                    return score
            # 現物（誰かの河にある牌）は基本安全
            for s in range(4):
                if s == self.state.my_seat:
                    continue
                for t in self.state.river[s]:
                    if tile_to_id(t) == tile_id:
                        score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU) // 2
                        self.record_detail(tile, f"現物安全 (+{score})")
                        return score

            # 非リーチ他家脅威による危険ペナルティ（終盤・他家テンパイ気配濃厚時）
            if self.evaluator and self.evaluator.strategy:
                max_threat = self.evaluator.strategy.compute_opponent_threat()
                local_turn = (self.state.tsumo_count - 1) // 4 + 1
                if max_threat >= 0.15 and local_turn >= 11:
                    penalty = int(-400 * max_threat)
                    self.record_detail(tile, f"非リーチ他家脅威による危険ペナルティ ({penalty})")
                    return penalty
            return 0

        common_genbutsu = self._common_genbutsu_ids(reach_seats)
        if tile_id in common_genbutsu:
            score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
            self.record_detail(tile, f"他家共通現物 (+{score})")
            return score

        # リーチ者が単独の場合のみ個別現物判定（複数リーチでは全員共通現物のみ安全）
        if n_reach == 1:
            for seat in reach_seats:
                for t in self.state.river[seat]:
                    if tile_to_id(t) == tile_id:
                        score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
                        self.record_detail(tile, f"リーチ者個別現物 (S{seat}) (+{score})")
                        return score

        # リーチ後通過牌（河越し）: リーチ後に誰かが切った牌がロンされなかった＝安牌
        for seat in reach_seats:
            # リーチ者の河で、リーチ以降のツモ切り枚数をカウント
            post_count = 0
            for m in reversed(self.state.river_moqie[seat]):
                if m:
                    post_count += 1
                else:
                    break
            if post_count <= 0:
                continue
            # 各他プレーヤーの河の末尾 post_count 枚がリーチ後通過牌
            for rseat in range(4):
                if rseat == seat:
                    continue
                river = self.state.river[rseat]
                if len(river) < post_count:
                    post_count = len(river)
                start = len(river) - post_count
                for i in range(start, len(river)):
                    if tile_to_id(river[i]) == tile_id:
                        score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
                        self.record_detail(tile, f"リーチ後通過牌 (S{rseat}→S{seat}) (+{score})")
                        return score

        # リーチ宣言牌の前後（±1）はスジより優先して危険判定
        riichi_neighbor_ids = self._get_riichi_neighbor_ids(reach_seats)

        suji_ids = self._reach_suji_ids(reach_seats)
        if tile_id in suji_ids and tile_id not in riichi_neighbor_ids:
            score = self.params.get('SCORE_SUJI', SCORE_SUJI)
            self.record_detail(tile, f"スジ安全 (+{score})")
            return score

        if use_p1:
            wall_suji = self._wall_suji_ids()
            if tile_id in wall_suji:
                score = self.params.get('SCORE_WALL_SUJI', SCORE_WALL_SUJI)
                self.record_detail(tile, f"壁スジ安全 (+{score})")
                return score
            no_chance = self._no_chance_ids()
            if tile_id in no_chance:
                score = self.params.get('SCORE_NO_CHANCE', SCORE_NO_CHANCE)
                self.record_detail(tile, f"ノーチャンス安全 (+{score})")
                return score
            kabe_edge = self._kabe_edge_safe_ids()
            if tile_id in kabe_edge:
                score = self.params.get('SCORE_KABE_EDGE', 750)
                self.record_detail(tile, f"壁端安全 (+{score})")
                return score
            one_chance = self._one_chance_ids()
            if tile_id in one_chance:
                score = self.params.get('SCORE_ONE_CHANCE', SCORE_ONE_CHANCE)
                self.record_detail(tile, f"ワンチャンス安全 (+{score})")
                return score

        for seat in reach_seats:
            for t in self.state.river[seat]:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid) and tid == tile_id:
                    score = self.params.get('SCORE_SUJI', SCORE_SUJI)
                    self.record_detail(tile, f"リーチ者河字牌安全 (+{score})")
                    return score
        if is_honor(tile_id):
            visible = self.state.all_visible_counts()
            count = visible[tile_id]
            if count >= 2:
                score = self.params.get('SCORE_HONOR', SCORE_HONOR)
                self.record_detail(tile, f"字牌{count}枚見え安全 (+{score})")
                return score
            if count == 0:
                score = self.params.get('SCORE_HONOR', SCORE_HONOR)
                self.record_detail(tile, f"字牌・生牌安全 (+{score})")
                return score

        if use_p1:
            matagi = self._matagi_danger_ids(reach_seats)
            score = self.params.get('SCORE_MUSUJI_BASE', SCORE_MUSUJI_BASE)
            score += n_reach * self.params.get('SCORE_MUSUJI_PER_REACH', SCORE_MUSUJI_PER_REACH)
            self.record_detail(tile, f"無筋危険 ({score})")
            if tile_id in matagi:
                penalty = self.params.get('MATAGI_PENALTY', MATAGI_PENALTY)
                score -= penalty
                self.record_detail(tile, f"マタギスジ危険 (-{penalty})")
            if tile_id in riichi_neighbor_ids:
                penalty = self.params.get('RIICHI_NEIGHBOR_PENALTY', 200)
                score -= penalty
                self.record_detail(tile, f"リーチ宣言牌隣接危険 (-{penalty})")
            return score
        score = self.params.get('SCORE_MUSUJI_BASE', SCORE_MUSUJI_BASE)
        self.record_detail(tile, f"無筋安全基準 ({score})")
        return score

    def _get_riichi_neighbor_ids(self, reach_seats: List[int]) -> set:
        result = set()
        for seat in reach_seats:
            river = self.state.river[seat]
            moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
            if len(river) < 2:
                continue
            post_riichi = 0
            for m in reversed(moqie):
                if m:
                    post_riichi += 1
                else:
                    break
            riichi_idx = len(river) - post_riichi - 1
            if riichi_idx < 0 or riichi_idx >= len(river):
                continue
            for idx in [riichi_idx, riichi_idx - 1]:
                if idx < 0:
                    continue
                tid = tile_to_id(river[idx])
                if tid >= 27:
                    continue
                off = tid % 9
                base = (tid // 9) * 9
                if off > 0:
                    result.add(base + off - 1)
                if off < 8:
                    result.add(base + off + 1)
        return result

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
        self.evaluator = None

    def record_detail(self, tile: str, msg: str):
        if self.evaluator:
            self.evaluator.record_detail(tile, msg)

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
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            return ShantenCalculator.calculate_open(new_counts, open_meld_count)

    def _standard_shanten_after(self, discard_tile: str) -> int:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(new_counts)
        return ShantenCalculator.calculate_open(new_counts, open_meld_count)

    def _best_standard_shanten(self) -> int:
        hand_counts = list(self.state.my_hand_counts())
        best = 8
        seen = set()
        for t in self.state.my_hand:
            tid = tile_to_id(t)
            if tid in seen or hand_counts[tid] <= 0:
                continue
            seen.add(tid)
            tmp = list(hand_counts)
            tmp[tid] -= 1
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            if open_meld_count == 0:
                s = ShantenCalculator.calculate_closed_effective(tmp)
            else:
                s = ShantenCalculator.calculate_open(tmp, open_meld_count)
            if s < best:
                best = s
        return best

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
        std_shanten = self._standard_shanten_after(tile)
        if std_shanten > self._best_standard_shanten():
            self.record_detail(tile, f"シャンテン後退ペナルティ ({SHANTEN_BACKTRACK_PENALTY})")
            return SHANTEN_BACKTRACK_PENALTY

        USE_P2 = self.params.get('USE_PHASE2_ATTACK', True)
        if USE_P2:
            quality = self._ukeire_quality_mult(tile)
            effective_ukeire = int(ukeire_total * quality)
            score = effective_ukeire * self.params.get('UKEIRE_MULTIPLIER', 10)
            self.record_detail(tile, f"有効牌枚数・質評価 (+{score})")
            shanten_penalty = max(0, shanten) * self.params.get('SHANTEN_MULTIPLIER', 500)
            score -= shanten_penalty
            if shanten_penalty > 0:
                self.record_detail(tile, f"シャンテン数ペナルティ (-{shanten_penalty})")
            score += self._hand_value_bonus(tile)
        else:
            score = ukeire_total * 10 - shanten * 500
            self.record_detail(tile, f"手効率基本評価 (+{score})")
        if shanten <= 0:
            furiten_pen = self._compute_furiten_penalty(tile)
            if furiten_pen > 0:
                score -= furiten_pen
                self.record_detail(tile, f"フリテンペナルティ (-{furiten_pen})")
            if shanten <= 3:
                hand_counts = self.state.my_hand_counts()
                discard_id = tile_to_id(tile)
                after_counts = list(hand_counts)
                after_counts[discard_id] = max(0, after_counts[discard_id] - 1)
                open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
                blocks_before = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
                if blocks_before >= 6:
                    is_isolated = (hand_counts[discard_id] == 1 and not is_honor(discard_id))
                    if is_isolated:
                        base = (discard_id // 9) * 9
                        off = discard_id - base
                        has_l = off > 0 and hand_counts[base + off - 1] > 0
                        has_r = off < 8 and hand_counts[base + off + 1] > 0
                        is_isolated = not has_l and not has_r
                    if not is_isolated:
                        blocks_after = ShantenCalculator.calculate_blocks(after_counts, open_meld_count)
                        if blocks_after >= 6:
                            penalty = self.params.get('PENALTY_6BLOCK_MAINTAIN', 80)
                            score -= penalty
                            self.record_detail(tile, f"6ブロック維持ペナルティ (-{penalty})")
            # テンパイかつ副露時の役なしチェック
            if open_meld_count > 0:
                has_yaku = False
                counts_after = list(hand_counts)
                counts_after[discard_id] = max(0, counts_after[discard_id] - 1)
                for tid in range(34):
                    if counts_after[tid] >= 4:
                        continue
                    temp = list(counts_after)
                    temp[tid] += 1
                    ns = ShantenCalculator._suit_shanten(temp, open_meld_count)
                    if ns < 0:
                        temp_hand = []
                        for i in range(34):
                            temp_hand.extend([id_to_tile(i)] * temp[i])
                        # Check tanyao (all 2-8, no terminals/honors)
                        all_tanyao = all(
                            not is_terminal(tile_to_id(t)) and not is_honor(tile_to_id(t))
                            for t in temp_hand
                        )
                        if all_tanyao:
                            # Also check melds for terminals/honors
                            for m in self.state.my_melds:
                                for mt in m.tiles:
                                    if is_terminal(tile_to_id(mt)) or is_honor(tile_to_id(mt)):
                                        all_tanyao = False
                                        break
                                if not all_tanyao:
                                    break
                        if all_tanyao:
                            has_yaku = True
                            break
                        # Check yakuhai in melds (dragon, seat wind, round wind)
                        yakuhai_ids = {31, 32, 33}
                        sw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.my_seat)
                        rw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.chang % 4)
                        if sw: yakuhai_ids.add(sw)
                        if rw: yakuhai_ids.add(rw)
                        for m in self.state.my_melds:
                            if getattr(m, 'is_open', True) and len(getattr(m, 'tiles', [])) >= 3:
                                mt = m.tiles[0]
                                mtid = tile_to_id(mt)
                                yakuhai_ids = {31, 32, 33}
                                sw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.my_seat)
                                rw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.chang % 4)
                                if sw: yakuhai_ids.add(sw)
                                if rw: yakuhai_ids.add(rw)
                                if mtid in yakuhai_ids:
                                    has_yaku = True  # yakuhai
                                    break
                if not has_yaku:
                    penalty = self.params.get('OPEN_TENPAI_NO_YAKU_PENALTY', 1500)
                    score -= penalty
                    self.record_detail(tile, f"役なしテンパイペナルティ (-{penalty})")

        # 通常手（面子手）の形状破壊ペナルティ: 七対子優先で全体シャンテンが変わらなくても
        # 通常手としてのシャンテンが後退する場合はペナルティ（即時returnはせず減算のみ）
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        best_std_shanten = 8
        for t in self.state.my_hand:
            tid = tile_to_id(t)
            tmp = list(hand_counts)
            tmp[tid] -= 1
            s = ShantenCalculator.calculate_standard(tmp)
            if s < best_std_shanten:
                best_std_shanten = s
        std_after = ShantenCalculator.calculate_standard(new_counts)
        if std_after > best_std_shanten:
            shape_pen = self.params.get('PENALTY_STANDARD_SHANTEN_BACKWARD', 350)
            score -= shape_pen
            self.record_detail(tile, f"通常手シャンテン後退（形状破壊）ペナルティ (-{shape_pen})")

        furiten_reserve, fr_reason = self._furiten_reserve_penalty(tile)
        if furiten_reserve > 0:
            score -= furiten_reserve
            self.record_detail(tile, fr_reason)
        if shanten >= self.params.get('BETAORI_PREP_SHANTEN', 4):
            score += self._betaori_prep_bonus(tile, shanten)
        return score

    def _betaori_prep_bonus(self, tile: str, shanten: int) -> int:
        turn = (self.state.tsumo_count - 1) // 4 + 1
        if not (5 <= turn <= 10):
            return 0
        if shanten < 3:
            return 0
        n_reach = sum(1 for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach)
        if n_reach > 0:
            return 0

        tid = tile_to_id(tile)
        counts = self.state.my_hand_counts()
        bonus = 0

        if is_honor(tid):
            visible = self.state.all_visible_counts()
            if visible[tid] < 4:
                return 0

        remaining = counts[tid]
        if remaining == 1 and not is_honor(tid):
            base = (tid // 9) * 9
            off = tid - base
            has_l = off > 0 and counts[base + off - 1] > 0
            has_r = off < 8 and counts[base + off + 1] > 0
            if not has_l and not has_r:
                suit_counts = [sum(counts[0:9]), sum(counts[9:18]), sum(counts[18:27])]
                my_idx = tid // 9 if tid < 27 else -1
                if my_idx >= 0:
                    my_suit = suit_counts[my_idx]
                    max_suit = max(suit_counts) if suit_counts else 0
                    if my_suit <= max_suit - 3:
                        bonus += self.params.get('BETAORI_SLIM_BONUS', 40)

        if remaining >= 2 and not is_honor(tid):
            base = (tid // 9) * 9
            off = tid - base
            has_adj = (off > 0 and counts[base + off - 1] > 0) or (off < 8 and counts[base + off + 1] > 0)
            if has_adj:
                return 0

        return bonus

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
        is_tenpai = current_shanten <= 0
        total = 0
        total_weighted = 0
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
                weight = self.params.get('UKEIRE_QUAL_HONOR', 0.4)
            elif is_tenpai:
                base = (tid // 9) * 9
                off = tid - base
                has_l = off > 0 and new_counts[base + off - 1] >= 1
                has_r = off < 8 and new_counts[base + off + 1] >= 1
                has_l2 = off >= 2 and new_counts[base + off - 2] >= 1
                has_r2 = off <= 6 and new_counts[base + off + 2] >= 1
                if has_l and has_r:
                    weight = self.params.get('UKEIRE_QUAL_RYANMEN', 1.0)
                elif has_l2 and has_l:
                    weight = self.params.get('UKEIRE_QUAL_KANCHAN', 0.7)
                elif has_r and has_r2:
                    weight = self.params.get('UKEIRE_QUAL_KANCHAN', 0.7)
                elif off == 0 and has_r and has_r2:
                    weight = self.params.get('UKEIRE_QUAL_PENCHAN', 0.5)
                elif off == 8 and has_l and has_l2:
                    weight = self.params.get('UKEIRE_QUAL_PENCHAN', 0.5)
                else:
                    weight = self.params.get('UKEIRE_QUAL_TANKI', 0.5)
            else:
                connect = 0
                off = tid % 9
                base = (tid // 9) * 9
                if off > 0 and new_counts[base + off - 1] > 0:
                    connect += 1
                if off < 8 and new_counts[base + off + 1] > 0:
                    connect += 1
                if new_counts[tid] >= 2:
                    connect += 1
                base_w = self.params.get('UKEIRE_QUAL_CONNECT_BASE', 0.4)
                per = self.params.get('UKEIRE_QUAL_CONNECT_PER', 0.2)
                weight = min(1.0, base_w + connect * per)
            total_weighted += remaining * weight
        if total == 0:
            return 0.0
        return total_weighted / total

    def _ukeire_quality_breakdown(self, tile: str) -> dict:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        is_tenpai = current_shanten <= 0
        n_good = 0
        n_bad = 0
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
                n_bad += remaining
            elif is_tenpai:
                off = tid % 9
                base = (tid // 9) * 9
                has_l = off > 0 and new_counts[base + off - 1] >= 1
                has_r = off < 8 and new_counts[base + off + 1] >= 1
                if has_l and has_r:
                    n_good += remaining
                else:
                    n_bad += remaining
            else:
                off = tid % 9
                base = (tid // 9) * 9
                has_l = off > 0 and new_counts[base + off - 1] > 0
                has_r = off < 8 and new_counts[base + off + 1] > 0
                if has_l and has_r:
                    n_good += remaining
                else:
                    n_bad += remaining
        return {'total': total, 'good': n_good, 'bad': n_bad}

    def _hand_value_bonus(self, tile: str) -> int:
        """
        @title 手牌評価の補正値（ボーナス/ペナルティ）計算
        @description 孤立牌の状況、字牌の安全度、染め手への移行状況、および進行度（シャンテン・ブロック数）に応じて打牌評価にボーナスを加減算する。
        @param {str} tile - 捨てる牌の文字列
        @returns {int} 補正スコア
        """
        from hand_value import estimate_hand_value
        hand = list(self.state.my_hand)
        melds = self.state.my_melds
        discard_id = tile_to_id(tile)
        after_hand = [t for t in hand if tile_to_id(t) != discard_id or hand.count(t) > 1]
        if tile in after_hand:
            after_hand.remove(tile)
        open_meld_count = sum(1 for m in melds if m.is_open)
        has_reach = any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat)
        wind_idx = (self.state.my_seat - self.state.ju) % 4
        is_dealer = wind_idx == 0
        score = estimate_hand_value(after_hand, melds, self.state.actual_doras,
                                     is_open=open_meld_count > 0,
                                     has_reach=has_reach, is_ippatsu=False,
                                     is_tsumo=False, is_dealer=is_dealer,
                                     seat=wind_idx, chang=self.state.chang,
                                     ju=self.state.ju)
        bonus = score // 10
        counts = self.state.my_hand_counts()
        shanten = ShantenCalculator.calculate_closed_effective(counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(counts, open_meld_count)
        if bonus > 0:
            if shanten >= 3 and open_meld_count > 0:
                damp = max(0.1, 1.0 - (shanten - 2) * 0.35)
                bonus = int(bonus * damp)
            self.record_detail(tile, f"手役・打点評価ボーナス (+{bonus})")
        blocks = ShantenCalculator.calculate_blocks(counts, open_meld_count)
        turn = (self.state.tsumo_count - 1) // 4 + 1

        # ホンイツ・清一色への移行判断
        # 萬子、筒子、索子の枚数を数える（字牌を除く）
        all_ids = [tile_to_id(t) for t in hand]
        for m in melds:
            all_ids.extend(tile_to_id(t) for t in getattr(m, 'tiles', []))
        
        suit_counts = {'m': 0, 'p': 0, 's': 0}
        z_count = 0
        for tid in all_ids:
            if tid < 9: suit_counts['m'] += 1
            elif tid < 18: suit_counts['p'] += 1
            elif tid < 27: suit_counts['s'] += 1
            else: z_count += 1
        
        dominant_suit = max(suit_counts, key=suit_counts.get)
        dominant_count = suit_counts[dominant_suit]

        # 色バイアス: 主色の孤立中張牌を残す動機付け（控えめに）
        honitsu_cfg = self.params.get('yaku_strategy', {}).get('honitsu', {})
        if honitsu_cfg.get('enabled', True) and dominant_count >= honitsu_cfg.get('suit_threshold', 6):
            bonus_per = 20
            max_bonus = 200
            concentration_bonus = min((dominant_count - 5) * bonus_per, max_bonus)
            if concentration_bonus > 0:
                bonus += concentration_bonus
                self.record_detail(tile, f"染めバイアス (+{concentration_bonus})")
        
        # 染め手（主力色が7枚以上かつ、通常進行がまだ遅い2向聴以上の状況）
        is_dyeing = (dominant_count >= 7) and (shanten >= 2)
        if is_dyeing and not is_honor(discard_id):
            tile_suit = None
            if discard_id < 9: tile_suit = 'm'
            elif discard_id < 18: tile_suit = 'p'
            elif discard_id < 27: tile_suit = 's'
            
            # 染める色以外に既に完成面子(3連続)がある場合は染め手移行を抑制
            has_other_meld = False
            if tile_suit != dominant_suit:
                for sb in [0, 9, 18]:
                    sn = ['m', 'p', 's'][sb // 9]
                    if sn == dominant_suit:
                        continue
                    for i in range(7):
                        if all(counts[sb + i + j] >= 1 for j in range(3)):
                            has_other_meld = True
                            break
                    if has_other_meld:
                        break
            
            # 染める色以外を捨てる際にボーナスを加算して移行を推進（赤5は除く）
            if tile_suit != dominant_suit and not has_other_meld and not is_red_five(tile):
                dye_bonus = self.params.get('BETAORI_HONITSU_BONUS', 40)
                bonus += dye_bonus
                self.record_detail(tile, f"染め手移行推進ボーナス (+{dye_bonus})")

        # 刻子・対子・順子構築に関する評価
        if counts[discard_id] == 2:
            if discard_id in SANGEN:
                penalty = self.params.get('YAKUHAI_PAIR_PENALTY', 30)
                bonus -= penalty
                self.record_detail(tile, f"三元牌対子キープペナルティ (-{penalty})")
            if discard_id in (27, 28, 29, 30):
                penalty = self.params.get('YAKUHAI_PAIR_PENALTY', 30)
                bonus -= penalty
                self.record_detail(tile, f"自風・場風対子キープペナルティ (-{penalty})")

        if not is_honor(discard_id):
            base = (discard_id // 9) * 9
            off = discard_id - base
            counts_after = hand_to_counts(after_hand)
            if off > 0 and counts_after[base + off - 1] >= 1:
                ryan_bonus = self.params.get('RYANMEN_KEEP_BONUS', 15)
                bonus += ryan_bonus
                self.record_detail(tile, f"両面変化維持ボーナス (+{ryan_bonus})")
            if off < 8 and counts_after[base + off + 1] >= 1:
                ryan_bonus = self.params.get('RYANMEN_KEEP_BONUS', 15)
                bonus += ryan_bonus
                self.record_detail(tile, f"両面変化維持ボーナス (+{ryan_bonus})")

            left = off > 0 and counts[base + off - 1] > 0
            right = off < 8 and counts[base + off + 1] > 0
            if left or right:
                penalty = self.params.get('SHAPE_BREAK_PENALTY', 20)
                bonus -= penalty
                self.record_detail(tile, f"搭子破壊ペナルティ (-{penalty})")

        if is_honor(discard_id):
            is_pair = counts[discard_id] >= 2
            is_dora = any(tile_to_id(d) == discard_id for d in self.state.actual_doras)
            if is_dora:
                penalty = self.params.get('DORA_DISCARD_PENALTY', 40)
                bonus -= penalty
                self.record_detail(tile, f"ドラ字牌放出ペナルティ (-{penalty})")
            visible_all = self.state.all_visible_counts()
            remaining = 4 - visible_all[discard_id]
            
            # 字牌の「他家役牌危険度・安全度」に応じた動的スケーリング
            # 場に見えている枚数が多いほど安全牌として保持したいため、捨てるボーナスを減衰させる
            vis_factor = 1.0 - (visible_all[discard_id] / 4.0)
            if shanten <= 2 and blocks >= 5:
                # 進行度が高く、十分なブロックがある場合は安全牌の抱えを優先（0.3は保持を強く動機付けるための定数）
                vis_factor *= 0.3

            base_penalty = self.params.get('HONOR_VALUE_PENALTY', 20)
            if discard_id in SANGEN:
                if is_pair and remaining >= 2:
                    bonus -= base_penalty
                    self.record_detail(tile, f"三元牌対子保持ペナルティ (-{base_penalty})")
                elif not is_pair:
                    sangen_mult = self.params.get('SANGEN_PENALTY_MULTIPLIER', 0.75)
                    val_penalty = int(base_penalty * sangen_mult * vis_factor)
                    bonus -= val_penalty
                    self.record_detail(tile, f"三元牌整理ペナルティ (-{val_penalty})")
            bakaze = 27 + (self.state.chang % 4)
            wind_idx = (self.state.my_seat - self.state.ju) % 4
            jikaze = 27 + wind_idx
            is_double_wind = (bakaze == jikaze) and (discard_id == bakaze)
            if discard_id == bakaze:
                if is_pair and remaining >= 2:
                    bonus -= base_penalty
                    self.record_detail(tile, f"場風対子保持ペナルティ (-{base_penalty})")
                elif is_double_wind:
                    if not is_pair:
                        val_penalty = int(base_penalty * 1.5 * vis_factor)
                        bonus -= val_penalty
                        self.record_detail(tile, f"ダブ風切りペナルティ (-{val_penalty})")
                else:
                    if not is_pair:
                        val_penalty = int(base_penalty * 0.5 * vis_factor)
                        bonus -= val_penalty
                        self.record_detail(tile, f"不要場風切りペナルティ (-{val_penalty})")
            if discard_id == jikaze:
                if not is_pair and not is_double_wind:
                    val_penalty = int(base_penalty * 1.0 * vis_factor)
                    bonus -= val_penalty
                    self.record_detail(tile, f"不要自風切りペナルティ (-{val_penalty})")
            elif not is_pair and discard_id not in SANGEN and discard_id != bakaze:
                val_bonus = int(self.params.get('HONOR_DISCARD_BONUS', 20) * vis_factor)
                bonus += val_bonus
                self.record_detail(tile, f"不要客風整理ボーナス (+{val_bonus})")

            ratio_base = self.params.get('VISIBLE_RATIO_HONOR', 80)
            is_keeping_safe = False
            if shanten <= 2 and blocks >= 5:
                # 安牌（見えている字牌）を残すため、捨てる際のボーナスをマイナス化（保持へ誘導）
                ratio_base = -ratio_base // 2
                is_keeping_safe = True
            
            vis = visible_all[discard_id]
            if vis >= 1:
                safe_start = self.params.get('SAFE_TILE_TURN_START', 6)
                safe_ramp = self.params.get('SAFE_TILE_RAMP_DURATION', 10)
                has_threat = self.state.is_any_opponent_reach() or Evaluator._any_opponent_has_open_meld(self.state)
                if has_threat:
                    effective_turn = max((self.state.tsumo_count - 1) // 4 + 1, safe_start)
                else:
                    effective_turn = (self.state.tsumo_count - 1) // 4 + 1
                turn_factor = max(0.0, min(1.0, (effective_turn - safe_start) / safe_ramp))
                if is_keeping_safe or turn_factor > 0:
                    ratio = 4.0 / max(1, 4 - vis) - 1.0
                    offset = int(ratio * ratio_base)
                    if not is_keeping_safe and turn_factor < 1.0:
                        offset = int(offset * turn_factor)
                    bonus += offset
                    if is_keeping_safe:
                        self.record_detail(tile, f"安全字牌抱えペナルティ ({offset})")
                    else:
                        self.record_detail(tile, f"安牌字牌整理ボーナス (+{offset})")
        else:
            is_dora = any(tile_to_id(d) == discard_id for d in self.state.actual_doras)
            if is_dora:
                penalty = self.params.get('DORA_DISCARD_PENALTY', 60)
                bonus -= penalty
                self.record_detail(tile, f"ドラ放出ペナルティ (-{penalty})")

            ratio_base = self.params.get('VISIBLE_RATIO_BASE', 20)
            visible_all = self.state.all_visible_counts()
            vis = visible_all[discard_id]
            safe_start = self.params.get('SAFE_TILE_TURN_START', 6)
            safe_ramp = self.params.get('SAFE_TILE_RAMP_DURATION', 10)
            has_threat = self.state.is_any_opponent_reach() or Evaluator._any_opponent_has_open_meld(self.state)
            if has_threat:
                effective_turn = max((self.state.tsumo_count - 1) // 4 + 1, safe_start)
            else:
                effective_turn = (self.state.tsumo_count - 1) // 4 + 1
            turn_factor = max(0.0, min(1.0, (effective_turn - safe_start) / safe_ramp))
            if vis >= 1 and counts[discard_id] == 1 and turn_factor > 0:
                ratio = 4.0 / max(1, 4 - vis) - 1.0
                offset = int(ratio * ratio_base)
                if turn_factor < 1.0:
                    offset = int(offset * turn_factor)
                bonus += offset
                self.record_detail(tile, f"安牌整理ボーナス (+{offset})")

            all_ids = [tile_to_id(t) for t in self.state.my_hand]
            all_ids.extend(tile_to_id(t) for m in self.state.my_melds for t in getattr(m, 'tiles', []))

            has_term = any(is_terminal(tid) for tid in all_ids)
            has_hon = any(is_honor(tid) for tid in all_ids)
            can_tanyao = not has_term and not has_hon
            if can_tanyao and not is_honor(discard_id):
                off = discard_id % 9
                if off == 0 or off == 8:
                    tan_bonus = self.params.get('TANYAO_TERMINAL_BONUS', 40)
                    bonus += tan_bonus
                    self.record_detail(tile, f"断么九変化端牌整理ボーナス (+{tan_bonus})")

            is_red = is_red_five(tile)
            if is_red:
                aka_bonus = self.params.get('AKA_KEEP_BONUS', 60)
                bonus += aka_bonus
                self.record_detail(tile, f"赤5整理ボーナス (+{aka_bonus})")

            if not is_honor(discard_id) and counts[discard_id] == 1:
                base = (discard_id // 9) * 9
                off = discard_id - base
                connect = 0
                if off > 0: connect += counts[base + off - 1] if counts[base + off - 1] > 0 else 0
                if off < 8: connect += counts[base + off + 1] if counts[base + off + 1] > 0 else 0
                if connect == 0:
                    if 2 <= off <= 6:
                        # 孤立中張牌: 序盤は手幅のために保持したいが、巡目が進むほど危険なため徐々に嫌う（ペナルティの減衰）
                        middle_penalty = self.params.get('ISOLATED_MIDDLE_BONUS', 10)
                        decay = max(-1.0, 1.0 - turn / 10.0) # 10巡目以降は逆に廃棄ボーナスに転じる
                        offset = int(middle_penalty * decay)
                        bonus -= offset
                        if offset > 0:
                            self.record_detail(tile, f"孤立中張牌保持ペナルティ (-{offset})")
                        elif offset < 0:
                            self.record_detail(tile, f"孤立中張牌整理ボーナス (+{-offset})")
                        
                        # 進行度が高くブロックが十分な場合は、不要な孤立中張牌を率先して捨てる
                        if shanten <= 2 and blocks >= 5:
                            disc_bonus = self.params.get('ISOLATED_MIDDLE_DISCARD_BONUS_5BLOCK', 30)
                            bonus += disc_bonus
                            self.record_detail(tile, f"5ブロック不要中張牌整理ボーナス (+{disc_bonus})")
                    elif off == 0 or off == 8:
                        # 孤立1/9（端牌）: 最も効率が低いため率先して捨てる（巡目減衰）
                        edge_bonus = self.params.get('ISOLATED_EDGE_BONUS', 25)
                        decayed_edge = int(edge_bonus * max(0.2, 1.0 - turn / 18.0))
                        bonus += decayed_edge
                        self.record_detail(tile, f"孤立端牌整理ボーナス (+{decayed_edge})")
                    else:
                        # 孤立2/8: 1/9よりは両面変化があるため少し残しやすい（巡目減衰）
                        bonus_28 = self.params.get('ISOLATED_28_BONUS', 10)
                        decayed_28 = int(bonus_28 * max(0.2, 1.0 - turn / 18.0))
                        bonus += decayed_28
                        self.record_detail(tile, f"孤立2/8牌整理ボーナス (+{decayed_28})")

        # 役満ボーナス
        yakuman_bonus = self._yakuman_bonus(tile)
        if yakuman_bonus > 0:
            bonus += yakuman_bonus

        return bonus

    def _yakuman_bonus(self, tile: str) -> int:
        """
        @title 役満ボーナス計算
        @description 各役満の進行度に応じてボーナスを加算する。
        @param {str} tile - 捨てる牌の文字列
        @returns {int} 役満ボーナス値
        """
        from yakuman_evaluator import YakumanEvaluator

        evaluator = YakumanEvaluator(self.state)
        results = evaluator.evaluate_all()

        total_bonus = 0
        turn = (self.state.tsumo_count - 1) // 4 + 1
        tile_id = tile_to_id(tile)

        # パラメータ読み込み
        yakuman_cfg = self.params.get('yakuman_strategy', {})
        top_necessity = yakuman_cfg.get('YAKUMAN_TOP_NECESSITY_FACTOR', 0.5)
        mangan_factor = yakuman_cfg.get('YAKUMAN_MANGAN_FACTOR', 0.75)
        over_mangan_factor = yakuman_cfg.get('YAKUMAN_OVER_MANGAN_FACTOR', 1.0)
        turn_early_threshold = yakuman_cfg.get('YAKUMAN_TURN_EARLY_THRESHOLD', 6)
        turn_mid_threshold = yakuman_cfg.get('YAKUMAN_TURN_MID_THRESHOLD', 12)
        turn_early_factor = yakuman_cfg.get('YAKUMAN_TURN_EARLY_FACTOR', 1.0)
        turn_mid_factor = yakuman_cfg.get('YAKUMAN_TURN_MID_FACTOR', 0.8)
        turn_late_factor = yakuman_cfg.get('YAKUMAN_TURN_LATE_FACTOR', 0.5)

        # 点数ラインの計算（GAで調整可能）
        score_line_name = yakuman_cfg.get('YAKUMAN_SCORE_LINE', 'mangan')
        score_lines = yakuman_cfg.get('YAKUMAN_SCORE_LINES', {
            'mangan':    { 'child': 10000, 'dealer': 16000 },
            'haneman':   { 'child': 15000, 'dealer': 24000 },
            'baiman':    { 'child': 20000, 'dealer': 32000 },
            'sanbaiman': { 'child': 30000, 'dealer': 48000 },
            'yakuman':   { 'child': 40000, 'dealer': 64000 }
        })
        line_config = score_lines.get(score_line_name, score_lines['mangan'])
        is_dealer = (self.state.my_seat - self.state.ju) % 4 == 0
        mangan_line = line_config['dealer'] if is_dealer else line_config['child']

        # 巡目補正
        if turn <= turn_early_threshold:
            turn_factor = turn_early_factor
        elif turn <= turn_mid_threshold:
            turn_factor = turn_mid_factor
        else:
            turn_factor = turn_late_factor

        # 点数必要度補正
        scores = self.state.scores
        my_score = scores[self.state.my_seat]
        top_score = max(scores)
        gap = top_score - my_score
        if gap <= 0:
            necessity_factor = top_necessity
        elif gap <= mangan_line:
            necessity_factor = mangan_factor
        else:
            necessity_factor = over_mangan_factor

        # 点差が大きい場合、遠い手でも役満を狙う（shanten上限を緩和）
        min_shanten = yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2)
        relax_cfg = yakuman_cfg.get('YAKUMAN_SHANTEN_RELAX_LINES', {})
        mult1 = relax_cfg.get('gap_multiplier_1', 1.5)
        mult2 = relax_cfg.get('gap_multiplier_2', 2.5)
        shanten_at1 = relax_cfg.get('shanten_at_multiplier_1', 3)
        shanten_at2 = relax_cfg.get('shanten_at_multiplier_2', 4)
        if gap > mangan_line * mult2:
            min_shanten = max(min_shanten, shanten_at2)
        elif gap > mangan_line * mult1:
            min_shanten = max(min_shanten, shanten_at1)

        max_yakuman_bonus = 0
        best_yakuman_name = ''
        best_selection_score = 0

        for name, result in results.items():
            if not result.is_possible:
                continue
            if result.shanten > min_shanten:
                continue

            # 牌貢献度判定: この牌が役満進行に貢献するか
            if yakuman_cfg.get('YAKUMAN_TILE_CONTRIBUTION_ENABLED', True):
                if not self._tile_contributes_to_yakuman(tile_id, name):
                    continue

            # シャンテン補正（二次関数）
            shanten_factor = max(0.0, (4 - result.shanten) ** 2 / 16.0)

            # 基本ボーナス
            base_bonus = self.params.get('YAKUMAN_BONUS_SCALE', 200)

            # 合計ボーナス（priority factorは選択用、ボーナス額には影響しない）
            yakuman_bonus = int(base_bonus * shanten_factor * turn_factor * necessity_factor * result.progress)
            if yakuman_bonus > 0:
                # priority factorを加味したスコアで最良を選択
                priority_factor = self._yakuman_priority_factor(name, result)
                selection_score = yakuman_bonus * priority_factor
                if selection_score > best_selection_score:
                    best_selection_score = selection_score
                    max_yakuman_bonus = yakuman_bonus
                    best_yakuman_name = name

        if max_yakuman_bonus > 0:
            total_bonus += max_yakuman_bonus
            self.record_detail(tile, f"役満ボーナス[{best_yakuman_name}] (+{max_yakuman_bonus})")
            # 統計
            ai = getattr(getattr(self, 'evaluator', None), '_ai_player', None)
            if ai is not None:
                ai.yakuman_bonus_count += 1
                if min_shanten > yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2):
                    ai.gap_relaxation_count += 1

        return total_bonus

    def _yakuman_priority_factor(self, yakuman_name: str, result) -> float:
        """役満の成立しやすさによる優先度補正（1.0が基準）"""
        # GAで調整可能な優先度因子をJSONから読み込み
        yakuman_cfg = self.params.get('yakuman_strategy', {})
        priority_factors = yakuman_cfg.get('YAKUMAN_PRIORITY_FACTORS', {})
        progress_bonus_rate = yakuman_cfg.get('YAKUMAN_PRIORITY_PROGRESS_BONUS', 0.2)

        base_factor = priority_factors.get(yakuman_name, 1.0)

        # 進行度が高いほど優先度を上げる
        progress_bonus = result.progress * progress_bonus_rate

        return base_factor + progress_bonus

    def _tile_contributes_to_yakuman(self, tile_id: int, yakuman_type: str) -> bool:
        """指定された牌が役牌が役満進行に貢献するか"""
        from yakuman_evaluator import YAOCHU_IDS, SANGEN_IDS, KAZE_IDS, RYUU_ISOU_IDS

        if yakuman_type == 'kokushi':
            # 国士無双: 老頭・字牌なら貢献
            return tile_id in YAOCHU_IDS
        elif yakuman_type == 'suuankou':
            # 四暗刻: 暗刻にできる牌（2枚以上持っている）なら貢献
            hand_counts = self.state.my_hand_counts()
            return hand_counts[tile_id] >= 2
        elif yakuman_type == 'daisangen':
            # 大三元: 三元牌なら貢献
            return tile_id in SANGEN_IDS
        elif yakuman_type == 'tsuuiisou':
            # 字一色: 字牌なら貢献
            return tile_id >= 27
        elif yakuman_type == 'chinroutou':
            # 清老頭: 老頭牌なら貢献
            from str_converter import is_terminal
            return is_terminal(tile_id)
        elif yakuman_type == 'chuuren':
            # 九蓮宝燈: 一色の牌なら貢献（简化版）
            return tile_id < 27  # 数牌のみ
        elif yakuman_type in ('daisuushii', 'shousuushii'):
            # 大四喜・小四喜: 風牌なら貢献
            return tile_id in KAZE_IDS
        elif yakuman_type == 'ryuuiisou':
            # 緑一色: 緑一色候補牌なら貢献
            return tile_id in RYUU_ISOU_IDS
        elif yakuman_type == 'suukantsu':
            # 四槓子: どの牌でも貢献（槓にするため）
            return True
        return True


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

    def _furiten_reserve_penalty(self, tile: str) -> int:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)

        my_river_ids = set()
        for t in self.state.river[self.state.my_seat]:
            my_river_ids.add(tile_to_id(t))
        if not my_river_ids:
            return 0, ""

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        if current_shanten >= 3:
            return 0, ""

        max_penalty = self.params.get('FURITEN_RESERVE_PENALTY', 300)
        total_penalty = 0
        reasons = []

        for tid in range(34):
            c = new_counts[tid]
            if c <= 0:
                continue
            if is_honor(tid):
                continue
            base = (tid // 9) * 9
            off = tid - base
            has_l = off > 0 and new_counts[base + off - 1] > 0
            has_r = off < 8 and new_counts[base + off + 1] > 0
            if has_l or has_r:
                continue
            if off > 0 and (base + off - 1) in my_river_ids:
                total_penalty += max_penalty
                reasons.append(f"{id_to_tile(tid)}")
            if off < 8 and (base + off + 1) in my_river_ids:
                total_penalty += max_penalty
                reasons.append(f"{id_to_tile(tid)}")

        total_penalty = min(max_penalty, total_penalty)
        if total_penalty > 0 and reasons:
            unique = list(dict.fromkeys(reasons))
            return total_penalty, f"フリテン予備軍: {','.join(unique)}の隣接牌が河にあるため将来フリテン待ちが含まれる (-{total_penalty})"
        return total_penalty, ""


class Evaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        self.details = {}  # tile -> List[str]
        self.attack = AttackEvaluator(state, params=self.params)
        self.attack.evaluator = self
        self.defense = DefenseEvaluator(state, params=self.params)
        self.defense.evaluator = self
        self.strategy = StrategyManager(state, params=self.params)
        self.strategy.evaluator = self
        self.meld_seal = MeldSealTracker()
        self._ai_player = None

    def record_detail(self, tile: str, msg: str):
        lst = self.details.setdefault(tile, [])
        if msg not in lst:
            lst.append(msg)

    def get_tile_description(self, tile: str) -> str:
        """
        @title 牌特性説明文生成
        @description 指定された牌がなぜ切りやすいかの簡潔な日本語説明を生成する。
        record_detail() で記録されたIF判定結果にも連動する。
        例: "早い順目のオタ風で孤立牌"、"孤立した端牌"、"6ブロック超過の不要牌"
        @param {str} tile - 評価対象の牌文字列 (例: "3z")
        @returns {str} 説明文字列（該当なしの場合は空文字）
        """
        try:
            tile_id = tile_to_id(tile)
        except Exception:
            return ""
        hand_counts = hand_to_counts(self.state.my_hand)
        human_turn = (self.state.tsumo_count - 1) // 4 + 1
        tile_details = self.details.get(tile, [])

        parts = []
        if human_turn <= 3:
            turn_tag = "早い順目"
        else:
            turn_tag = ""

        # ドラチェック（IF判定に連動）
        is_dora = any("ドラ" in d for d in tile_details)

        if is_honor(tile_id):
            bakaze = 27 + (self.state.chang % 4)
            wind_idx = (self.state.my_seat - self.state.ju) % 4
            jikaze = 27 + wind_idx

            if tile_id >= 31:
                wind_type = "三元牌"
            elif tile_id == bakaze and tile_id == jikaze:
                wind_type = "ダブル風"
            elif tile_id == bakaze:
                wind_type = "場風"
            elif tile_id == jikaze:
                wind_type = "自風"
            else:
                wind_type = "オタ風"

            count = hand_counts[tile_id]
            if count >= 3:
                return ""
            if count == 1:
                prefix = f"{turn_tag}の" if turn_tag else ""
                parts.append(f"{prefix}{wind_type}で孤立牌")
        else:
            base = (tile_id // 9) * 9
            off = tile_id - base
            has_l = off > 0 and hand_counts[base + off - 1] > 0
            has_r = off < 8 and hand_counts[base + off + 1] > 0
            is_isolated = not has_l and not has_r and hand_counts[tile_id] == 1

            if is_isolated:
                if off == 0 or off == 8:
                    parts.append("孤立した端牌")
                elif off == 1 or off == 7:
                    parts.append("孤立した2/8牌")
                else:
                    parts.append("孤立した中張牌")
            else:
                # details のIF判定結果から追加情報を抽出
                has_6block = any("6ブロック" in d for d in tile_details)
                has_shape_break = any("搭子破壊" in d for d in tile_details)
                if has_6block:
                    parts.append("6ブロック超過の不要牌")
                if not parts and has_shape_break:
                    # 搭子を壊す場合 → 打牌候補として不利な情報なので基本スキップ
                    pass

        # 詳細メッセージから補足タグを抽出（IF判定と連動）
        if is_dora:
            parts.append("ドラ牌")
        if any("フリテン" in d for d in tile_details):
            parts.append("フリテン懸念")
        has_yakuman_bonus = any("役満ボーナス" in d for d in tile_details)
        is_breaking_ankou = hand_counts[tile_id] >= 3
        if has_yakuman_bonus and not is_breaking_ankou:
            parts.append("役満狙い")

        if not parts:
            return ""
        return "".join(parts) + "のため"

    def _get_keiten_bonus(self, tile: str) -> int:
        """
        @title 形式テンパイ（形テン）ボーナス
        @description 終盤において、打牌後にテンパイとなる手牌に加算するボーナス値を返す。
                     放銃リスクが見合わない危険な局面では0を返し、緊急時のみ強行する。
        @param tile 捨てる牌の文字列 (例: "5m")
        @returns int ボーナス値（条件を満たさない場合は0）
        """
        # 他家テンパイ気配があり、切る牌が危険牌で、緊急事態でなければボーナス無効
        max_threat = self.strategy.compute_opponent_threat()
        v_defense = self.defense.defense_score_for_tile(tile)
        safe_threshold = self.params.get('SCORE_SUJI', 500)
        is_dealer = (self.state.my_seat - self.state.ju) % 4 == 0
        rank = self.state.my_score_rank()
        is_emergency = is_dealer and (self.state.ju == 3) and (rank >= 2)
        if max_threat >= 0.15 and v_defense < safe_threshold and not is_emergency:
            return 0

        tsumo = (self.state.tsumo_count - 1) // 4 + 1
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
            ev_val = self._evaluate_tile_ev(tile)
            pos_val = self._positional_ev()
            self.record_detail(tile, f"EV期待値評価 ({ev_val + pos_val:.1f})")
            return float(ev_val + pos_val)
        v_attack = self.attack.attack_score_for_tile(tile)
        v_defense = self.defense.defense_score_for_tile(tile)
        push_score = self.strategy.compute_push_score()
        mode = self.strategy.get_strategy_mode()

        if mode == "攻撃":
            v = float(v_attack)
            self.record_detail(tile, "戦略モード「攻撃」を適用")
        elif mode == "防御":
            safe_threshold = self.params.get('SCORE_SUJI', 500)
            if v_defense >= safe_threshold:
                v = float(v_defense * 2 + v_attack * 0.1)
                self.record_detail(tile, "戦略モード「防御」（安牌評価強化）を適用")
            else:
                v = float(v_defense + v_attack * 0.05)
                self.record_detail(tile, "戦略モード「防御」（非安牌・危険回避）を適用")
        else:
            if not self.state.is_any_opponent_reach() and not self._any_opponent_has_open_meld(self.state):
                v = float(v_attack)
                self.record_detail(tile, "戦略モード「平場攻撃」を適用")
            else:
                v = push_score * v_attack + (1.0 - push_score) * v_defense
                self.record_detail(tile, f"戦略モード「押し引きバランス」(Push={push_score:.2f})を適用")

        is_ippatsu_turn = any(
            rs.is_ippatsu for i, rs in enumerate(self.state.reach_states) if i != self.state.my_seat
        )
        if is_ippatsu_turn:
            tile_id = tile_to_id(tile)
            if not self.defense.is_genbutsu(tile_id):
                reach_seats = self.defense._active_reach_seats()
                genbutsu_safe = tile_id in self.defense._common_genbutsu_ids(reach_seats)
                if not genbutsu_safe:
                    penalty = self.params.get('IPPATSU_PENALTY', 300)
                    ippatsu_pen = penalty * (1.0 - push_score)
                    v -= ippatsu_pen
                    self.record_detail(tile, f"一発放銃回避安全牌保持ペナルティ (-{ippatsu_pen:.1f})")

        keiten_bonus = self._get_keiten_bonus(tile)
        if keiten_bonus > 0:
            v += push_score * keiten_bonus
            self.record_detail(tile, f"形テンボーナス (押し補正: {push_score:.2f}) (+{push_score * keiten_bonus:.0f})")

        threat = self.strategy.compute_opponent_threat()
        if is_honor(tile_to_id(tile)) and threat > 0.1 and mode != "防御":
            danger_scale = max(0.0, 1.0 - threat * 2.5)
            v *= 0.3 + 0.7 * danger_scale
            self.record_detail(tile, f"他家脅威による字牌評価減衰 (脅威度: {threat:.2f})")

        if self.params.get('USE_POSITIONAL_EV', True):
            pos_ev = self._positional_ev()
            v += pos_ev
            if pos_ev != 0:
                self.record_detail(tile, f"順位状況価値 (PositionalEV) (+{pos_ev:.1f})")
            assist_sq = self._assist_squeeze_bonus(tile)
            v += assist_sq
        return v

    def _assist_squeeze_bonus(self, tile: str) -> float:
        bonus = 0.0
        scores = self.state.scores
        my_seat = self.state.my_seat
        my_score = scores[my_seat]
        sorted_seats = sorted(range(4), key=lambda s: (-scores[s], s))
        my_rank = sorted_seats.index(my_seat)
        dealer_seat = self.state.ju % 4

        is_dealer_last = sorted_seats[-1] == dealer_seat
        is_dealer_winning = dealer_seat == sorted_seats[0]

        if is_dealer_last and my_rank <= 1 and self.strategy._remaining_kyokus() <= 2:
            ally_target = sorted_seats[1] if my_rank == 0 else sorted_seats[0]
            tid = tile_to_id(tile)
            if not is_honor(tid):
                opp_discards = set()
                for t in self.state.river[ally_target]:
                    opp_discards.add(tile_to_id(t))
                if (tid // 9) in {t // 9 for t in opp_discards}:
                    ally_bonus = self.params.get('ASSIST_BONUS', 20)
                    bonus += ally_bonus
                    self.record_detail(tile, f"アシストボーナス (+{ally_bonus})")

        n_reach = sum(1 for i in range(4) if i != my_seat and self.state.reach_states[i].is_reach)
        if n_reach > 0:
            tid = tile_to_id(tile)
            if not is_honor(tid):
                base = (tid // 9) * 9
                off = tid - base
                counts = self.state.my_hand_counts()
                if counts[tid] >= 2:
                    has_l = off > 0 and counts[base + off - 1] > 0
                    has_r = off < 8 and counts[base + off + 1] > 0
                    if has_l or has_r:
                        sq_bonus = self.params.get('SQUEEZE_BONUS', 25)
                        bonus += sq_bonus
                        self.record_detail(tile, f"絞りボーナス (+{sq_bonus})")
        return bonus

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
            return min(self.params.get('EV_WIN_MAX', 0.9), draw_chance * self.params.get('EV_WIN_AGARI_MULT', 4))
        elif shanten == 0:
            return min(self.params.get('EV_WIN_TENPAI_MAX', 0.7), draw_chance * self.params.get('EV_WIN_TENPAI_MULT', 3))
        elif shanten == 1:
            return min(self.params.get('EV_WIN_1S_MAX', 0.3), draw_chance * self.params.get('EV_WIN_1S_MULT', 2))
        else:
            return min(self.params.get('EV_WIN_HIGH_MAX', 0.1), draw_chance * self.params.get('EV_WIN_HIGH_MULT', 0.5))

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
            return self.params.get('EV_DEALIN_WALL', 0.01)
        if tile_id in self.defense._no_chance_ids() and not is_honor(tile_id):
            return self.params.get('EV_DEALIN_NOCHANCE', 0.02)
        if tile_id in self.defense._reach_suji_ids(reach_seats):
            return self.params.get('EV_DEALIN_SUJI', 0.03) * n_reach
        if tile_id in self.defense._one_chance_ids() and not is_honor(tile_id):
            return self.params.get('EV_DEALIN_ONECHANCE', 0.05) * n_reach
        matagi = self.defense._matagi_danger_ids(reach_seats)
        danger = self.params.get('EV_DEALIN_MUSUJI_BASE', 0.06)
        danger += n_reach * self.params.get('EV_DEALIN_MUSUJI_PER_REACH', 0.05)
        if tile_id in matagi:
            danger += self.params.get('EV_DEALIN_MATAGI', 0.05)
        return min(self.params.get('EV_DEALIN_MAX', 0.5), danger)

    def _estimate_win_score(self) -> int:
        from hand_value import estimate_hand_value
        hand = self.state.my_hand
        melds = self.state.my_melds
        open_melds = [m for m in melds if m.is_open]
        is_open = len(open_melds) > 0
        has_reach = any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat)
        wind_idx = (self.state.my_seat - self.state.ju) % 4
        is_dealer = wind_idx == 0
        return estimate_hand_value(hand, melds, self.state.doras, is_open,
                                    has_reach=has_reach, is_ippatsu=False,
                                    is_tsumo=False, is_dealer=is_dealer,
                                    seat=wind_idx, chang=self.state.chang,
                                    ju=self.state.ju)

    def _estimate_deal_loss(self, tile: str) -> int:
        from opponent_model import estimate_opponent_state
        tile_id = tile_to_id(tile)
        total_loss = 0
        n_threats = 0
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            opp = estimate_opponent_state(self.state, seat)
            if not opp['is_tenpai'] and not opp['is_riichi']:
                continue
            danger = 0.1
            if opp['is_riichi']:
                danger = 0.8
            elif opp['is_tenpai']:
                danger = 0.5
            if opp['is_riichi'] or opp['is_tenpai']:
                from hand_value import estimate_hand_value
                est_score = estimate_hand_value(
                    [], self.state.melds[seat], self.state.doras,
                    is_open=opp['open_meld_count'] > 0,
                    has_reach=opp['is_riichi'], is_ippatsu=False,
                    is_tsumo=False, is_dealer=(seat == 0),
                    seat=seat, chang=self.state.chang, ju=self.state.ju)
                est_score = max(1000, est_score)
                seat_loss = int(est_score * danger)
                total_loss += seat_loss
                n_threats += 1
        return max(total_loss, n_threats * 1000)

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
        if hasattr(self.attack, '_best_shanten_cache'):
            del self.attack._best_shanten_cache
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
        mode = self.strategy.get_strategy_mode()
        if mode == "防御":
            threshold = self.params.get('SCORE_SUJI', 500)
            safe = [(self.evaluate_tile(t), t) for t in unique_tiles
                    if self.defense.defense_score_for_tile(t) >= threshold]
            if safe:
                unique_tiles = [t for _, t in safe]
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
        tsumo = (self.state.tsumo_count - 1) // 4 + 1
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
        kan_cfg = self.params.get('yaku_strategy', {}).get('kan', {})
        min_push = kan_cfg.get('min_push_score', 0.6)
        for i, c in enumerate(hand_counts):
            if c == 4:
                if push > min_push:
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

    def get_riichi_decision_details(self) -> dict:
        """
        @title 立直判断の根拠詳細化
        @description 現在のテンパイ手牌において、立直推奨値を計算しその内訳と判断理由を日本語で返します。
        @returns {dict} {"should_riichi": bool, "score": float, "threshold": float, "reason": str}
        """
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        
        # 前提条件のチェック
        if any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat):
            return {"should_riichi": False, "score": 0.0, "threshold": 0.0, "reason": "すでに立直しています。"}
        if open_meld_count > 0:
            return {"should_riichi": False, "score": 0.0, "threshold": 0.0, "reason": "門前（メンゼン）ではないため立直できません。"}
        if self.state.scores[self.state.my_seat] < 1000:
            return {"should_riichi": False, "score": 0.0, "threshold": 0.0, "reason": "持ち点が1000点未満のため立直できません。"}

        riichi_base = self.params.get('RIICHI_BASE', 0.6)
        wait_q = self._wait_quality_score()
        wait_weight = self.params.get('RIICHI_WAIT_WEIGHT', 1.0)
        wait_score = wait_q * wait_weight
        
        opp_reach_score = 0.0
        if self.state.is_any_opponent_reach():
            opp_reach_score = self.params.get('RIICHI_OPP_REACH_PENALTY', -0.4)

        dora_count = 0
        for t in self.state.my_hand:
            for d in self.state.doras:
                if tile_to_id(t) == tile_to_id(d):
                    dora_count += 1
            if is_red_five(t):
                dora_count += 1
        dora_penalty_param = self.params.get('RIICHI_DORA_PENALTY', -0.1)
        dora_score = dora_count * dora_penalty_param

        late_score = 0.0
        late_threshold = self.params.get('RIICHI_LATE_TURN', 14)
        if (self.state.tsumo_count - 1) // 4 + 1 >= late_threshold:
            late_score = self.params.get('RIICHI_LATE_PENALTY', -0.2)

        rank_bonus = 0.0
        rank = self.state.my_score_rank()
        if rank == 3:
            rank_bonus = self.params.get('RIICHI_LAST_RANK_BONUS', 0.2)

        total_score = riichi_base + wait_score + opp_reach_score + dora_score + late_score + rank_bonus
        threshold = self.params.get('RIICHI_THRESHOLD', 0.0)
        should_riichi = total_score > threshold

        # 理由のテキスト構成
        reasons = []
        reasons.append(f"基礎価値 ({riichi_base:+.2f})")
        reasons.append(f"待ち品質 ({wait_score:+.2f})")
        if opp_reach_score != 0:
            reasons.append(f"他家リーチ有 ({opp_reach_score:+.2f})")
        if dora_score != 0:
            reasons.append(f"ドラ・赤ドラ枚数 ({dora_score:+.2f})")
        if late_score != 0:
            reasons.append(f"終盤ペナルティ ({late_score:+.2f})")
        if rank_bonus != 0:
            reasons.append(f"ラス回避価値 ({rank_bonus:+.2f})")

        reason_text = "立直判定値: {:.2f} (閾値: {:.2f})。内訳: {}".format(
            total_score, threshold, ", ".join(reasons)
        )
        if should_riichi:
            reason_text += " -> 【立直推奨】ダマテンよりリーチを推奨します。"
        else:
            reason_text += " -> 【ダマテン推奨】ダマテンを推奨します。"

        return {
            "should_riichi": should_riichi,
            "score": round(total_score, 3),
            "threshold": threshold,
            "reason": reason_text
        }

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
        if (self.state.tsumo_count - 1) // 4 + 1 >= late_threshold:
            riichi_score += self.params.get('RIICHI_LATE_PENALTY', -0.2)

        rank = self.state.my_score_rank()
        if rank == 3:
            riichi_score += self.params.get('RIICHI_LAST_RANK_BONUS', 0.2)

        riichi_cfg = self.params.get('yaku_strategy', {}).get('riichi', {})
        try:
            from yaku_detector import analyze_all
            yaku_infos = analyze_all(self.state.my_hand, self.state.my_melds,
                                      seat=self.state.my_seat, chang=self.state.chang,
                                      ju=self.state.ju)
            expected_han = 0
            pursuing_damaten = False
            for yi in yaku_infos.values():
                if yi.is_complete:
                    expected_han += yi.closed_han
                if not yi.is_complete and yi.progress > 0.6:
                    if yi.name in ('sanshoku', 'ittsuu'):
                        pursuing_damaten = True
            if expected_han <= 0:
                riichi_score += riichi_cfg.get('low_value_penalty', -0.2)
            elif expected_han >= 2:
                riichi_score += riichi_cfg.get('expected_han_bonus_per_han', 0.1) * expected_han
            if pursuing_damaten:
                penalty = riichi_cfg.get('damaten_sanshoku_penalty', -0.3)
                riichi_score += penalty
        except Exception:
            pass

        threshold = self.params.get('RIICHI_THRESHOLD', 0.0)
        return riichi_score > threshold

    def _estimate_open_han(self, hand: List[str] = None, melds: List = None) -> int:
        """
        @title 鳴き時の期待飜数の見積もり
        @description 鳴いた後の仮想手牌と仮想副露から期待飜数を見積もる。
        @param hand 仮想手牌（None=現在の手牌）
        @param melds 仮想副露リスト（None=現在の副露）
        @returns {int} 期待飜数（エラー時は0）
        """
        try:
            from hand_value import estimate_han_advanced
            h = hand if hand is not None else self.state.my_hand
            m = melds if melds is not None else self.state.my_melds
            return estimate_han_advanced(
                h, m, self.state.doras,
                is_open=True, has_reach=False, is_ippatsu=False, is_tsumo=False,
                seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju
            )
        except Exception:
            return 0

    def _yaku_meld_bias(self, type_: int, tiles: List[str], hand_after: List[str] = None, melds_after: List = None) -> Optional[bool]:
        try:
            from yaku_detector import analyze_all
            h = hand_after if hand_after is not None else self.state.my_hand
            m = melds_after if melds_after is not None else self.state.my_melds
            yaku_infos = analyze_all(h, m, seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju)
        except Exception:
            return None

        yaku_strategy = self.params.get('yaku_strategy', {})

        toitoi_cfg = yaku_strategy.get('toitoi', {})
        if toitoi_cfg.get('meld_bias') == 'pon_only':
            toitoi = yaku_infos.get('toitoi')
            target_threshold = toitoi_cfg.get('pairs_threshold', 3) / 5.0
            if toitoi and toitoi.progress >= target_threshold:
                    if type_ == 0:
                        return False
                    if type_ == 1:
                        return True

        honitsu_cfg = yaku_strategy.get('honitsu', {})
        if honitsu_cfg.get('meld_bias') == 'dominant_only' and type_ == 0:
            honitsu = yaku_infos.get('honitsu')
            chinitsu = yaku_infos.get('chinitsu')
            target = honitsu or chinitsu
            if target and target.main_suit is not None:
                tile_suit = tile_to_id(tiles[0]) // 9
                if tile_suit != target.main_suit and tile_suit < 3:
                    return False

        for yaku_name in ('ittsuu', 'sanshoku'):
            cfg = yaku_strategy.get(yaku_name, {})
            if cfg.get('meld_bias') == 'accept' and type_ == 0:
                yi = yaku_infos.get(yaku_name)
                if yi and yi.progress >= cfg.get('pursue_threshold', 0.0):
                    return True

        # 役牌ポンは常に価値があるため、pinfu/chiitoitsuなどのdeclineを無視
        is_yakuhai_pon = False
        if type_ == 1:
            target_id = tile_to_id(tiles[0])
            seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
            round_wind = 27 + (self.state.chang % 4)
            is_yakuhai_pon = target_id in (31, 32, 33, seat_wind, round_wind)

        # 既に副露している場合、pinfu/chiitoitsuなど閉局専用役は不可能なのでdeclineを無視
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        for yaku_name in ('chiitoitsu', 'ryanpeikou', 'pinfu'):
            cfg = yaku_strategy.get(yaku_name, {})
            if cfg.get('meld_bias') == 'decline':
                yi = yaku_infos.get(yaku_name)
                if yi and yi.progress >= cfg.get('pursue_threshold', 0.0):
                    if open_meld_count == 0 and not is_yakuhai_pon:
                        return False

        return None

    def _meld_defense_penalty(self, type_: int, tiles: List[str]) -> int:
        cfg = self.params.get('yaku_strategy', {}).get('meld_defense', {})
        riichi_weight = cfg.get('riichi_penalty_per_tile', 300)
        threat_weight = cfg.get('threat_penalty_per_tile', 150)
        min_defense = cfg.get('min_defense_weight', 0.2)
        abs_threshold = cfg.get('absolute_threshold', 300)
        cond_threshold = cfg.get('conditional_threshold', 150)
        cond_push = cfg.get('conditional_push_min', 0.7)

        consumed = []
        if type_ == 1:
            tid = tile_to_id(tiles[0])
            consumed = [tid, tid]
        elif type_ == 0:
            consumed = [tile_to_id(t) for t in tiles[1:]]
        elif type_ == 2:
            tid = tile_to_id(tiles[0])
            consumed = [tid, tid, tid]
        else:
            return 0

        hand_counts = self.state.my_hand_counts()
        open_count = sum(1 for m in self.state.my_melds if m.is_open)
        my_shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_count)

        push = self.strategy.compute_push_score()
        defense_weight = max(min_defense, 1.0 - push)
        speed_factor = max(1.0, my_shanten * 0.5)

        hand_ids = [tile_to_id(t) for t in self.state.my_hand]
        total_loss = 0

        for opp in range(4):
            if opp == self.state.my_seat:
                continue
            is_riichi = self.state.reach_states[opp].is_reach
            if not is_riichi:
                opp_threat = self.strategy.compute_opponent_threat()
                if opp_threat < 0.4:
                    continue

            opp_discards = set(tile_to_id(t) for t in self.state.river[opp])
            genbutsu = {tid for tid in set(hand_ids) if tid in opp_discards}
            lost = sum(1 for c in consumed if c in genbutsu)
            if lost == 0:
                continue
            total_loss += lost * (riichi_weight if is_riichi else threat_weight)

        self._last_def_penalty = int(total_loss * defense_weight * speed_factor)
        return self._last_def_penalty

    def should_call_meld(self, type_: int, tiles: List[str], from_seat: int) -> bool:
        if not self.strategy.is_meld_open_allowed():
            return False
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count >= 4:
            return False

        # 鳴いた後の仮想手牌・仮想副露を構築
        from game_state import Meld
        hand_after = list(self.state.my_hand)
        consumed = []
        if type_ == 1:
            consumed = [tiles[0], tiles[0]]
        elif type_ == 0:
            consumed = tiles[1:]
        elif type_ == 2:
            consumed = [tiles[0], tiles[0], tiles[0]]
        for t in consumed:
            target_id = tile_to_id(t)
            for h_tile in list(hand_after):
                if tile_to_id(h_tile) == target_id:
                    hand_after.remove(h_tile)
                    break
        new_meld = Meld(type=type_, tiles=list(tiles), froms=[from_seat] * len(tiles), tile_states=[0] * len(tiles))
        melds_after = list(self.state.my_melds) + [new_meld]

        bias = self._yaku_meld_bias(type_, tiles, hand_after, melds_after)
        if bias is not None:
            return bias

        hand_counts = self.state.my_hand_counts()
        before_shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        after_counts = list(hand_counts)
        if type_ == 1:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 2)
        elif type_ == 0:
            for t in tiles[1:]:
                tid = tile_to_id(t)
                after_counts[tid] = max(0, after_counts[tid] - 1)
        elif type_ == 2:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 3)
        after_shanten = ShantenCalculator.calculate_open(after_counts, open_meld_count + 1)
        if after_shanten >= before_shanten:
            return False

        turn = (self.state.tsumo_count - 1) // 4 + 1

        # ベタオリ時は原則副露禁止
        if self.strategy.get_strategy_mode() == '防御':
            if after_shanten <= 0:
                # 形式テンパイ: 12-15巡かつ必要性がある場合のみ許可
                if turn < 12 or turn > 15:
                    return False
                rank = self.state.my_score_rank()
                if rank < 2:
                    return False
                # 副露後に安全な捨て牌があるか
                consumed = set()
                if type_ == 0:
                    consumed = {tile_to_id(t) for t in tiles[1:]}
                elif type_ == 1:
                    consumed = {tile_to_id(tiles[0])}
                remain = [tid for tid in [tile_to_id(t) for t in self.state.my_hand]
                          if tid not in consumed]
                opp_discards = set()
                for opp in range(4):
                    if opp == self.state.my_seat: continue
                    for t in self.state.river[opp]:
                        opp_discards.add(tile_to_id(t))
                if any(tid in opp_discards for tid in remain):
                    return True
                return False
            return False
        is_closed = open_meld_count == 0

        expected_han = self._estimate_open_han(hand_after, melds_after)

        # 役牌ポン or 高価値手は防御ペナルティを無視
        is_yakuhai_meld = False
        if type_ == 1:
            target_id = tile_to_id(tiles[0])
            seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
            round_wind = 27 + (self.state.chang % 4)
            is_yakuhai_meld = target_id in (31, 32, 33, seat_wind, round_wind)

        # 【追加】防御ペナルティ: 安全牌喪失リスクを評価
        def_cfg = self.params.get('yaku_strategy', {}).get('meld_defense', {})
        push = self.strategy.compute_push_score()
        def_penalty = self._meld_defense_penalty(type_, tiles)
        abs_th = def_cfg.get('absolute_threshold', 300)
        cond_th = def_cfg.get('conditional_threshold', 150)
        cond_push = def_cfg.get('conditional_push_min', 0.7)
        if not is_yakuhai_meld and expected_han < 2:
            if def_penalty >= abs_th:
                return False
            if def_penalty >= cond_th and push < cond_push:
                return False

        # 副露後の安全な捨て牌の有無をチェック
        hand_ids = [tile_to_id(t) for t in self.state.my_hand]
        opp_discards = [set(tile_to_id(t) for t in self.state.river[opp])
                        for opp in range(4) if opp != self.state.my_seat]
        all_discards = set().union(*opp_discards) if opp_discards else set()

        # 副露に使う牌を手牌から除いた残り
        consumed_ids = set()
        if type_ == 0:
            consumed_ids = {tile_to_id(t) for t in tiles[1:]}
        elif type_ == 1:
            consumed_ids = {tile_to_id(tiles[0])}
        remaining = [tid for tid in hand_ids if tid not in consumed_ids]
        safe_after = any(tid in all_discards for tid in remaining)

        if not safe_after and push < 0.5 and expected_han < 2:
            return False

        # 周囲の警戒度: 他家リーチ・副露が多いほど慎重に
        opp_reach = sum(1 for i in range(4) if i != self.state.my_seat
                         and self.state.reach_states[i].is_reach)
        if opp_reach >= 1 and expected_han < 2 and not is_yakuhai_meld:
            if not safe_after:
                return False

        turn = (self.state.tsumo_count - 1) // 4 + 1
        is_dealer = self.state.my_seat == 0

        # 副露封印モード
        sealed = self.meld_seal.evaluate(self.state.my_hand, self.state.my_melds,
                                          self.state.my_seat, self.state.chang,
                                          self.state.ju)
        if sealed and is_closed:
            # 封印中: テンパイのみ許可（役牌すらポンしない）
            if after_shanten <= 0 and expected_han >= 1:
                return True
            return False

        # 役牌ポン（封印解除時のみ: 守備力変わらないので鳴く）
        if type_ == 1:
            target_id = tile_to_id(tiles[0])
            seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
            round_wind = 27 + (self.state.chang % 4)
            if target_id in (31,32,33,seat_wind,round_wind) and expected_han >= 1:
                return True

        # 大明槓
        if type_ == 2:
            if push > 0.6:
                return True
            dora_gain = 0
            for d in self.state.doras:
                if tile_to_id(tiles[0]) == tile_to_id(d):
                    dora_gain += 1
            if dora_gain > 0 and push > 0.3:
                return True
            return False

        # 0飜開局 = 和了れない → 絶対に鳴かない
        if expected_han < 1:
            return False

        # テンパイ → 鳴く（速度優先）
        if after_shanten <= 0:
            return True

        # 既開局 → コミットしているので鳴く
        if not is_closed:
            return True

        # 強い門前一向聴（両面x両面＋高打点）は鳴かない
        if is_closed and before_shanten <= 1 and expected_han >= 2 and turn < 6:
            return False

        # 終盤制限の緩和: 押し引きと巡目に応じて適用
        if turn >= 12 or push < 0.4:
            if after_shanten <= 0:
                return True
            if self.state.my_score_rank() == 3 and self.state.left_tile_count <= 20:
                return True
            return False

        # --- 価値比較 ---
        from hand_value import estimate_han_advanced, estimate_win_score
        is_dealer = self.state.my_seat == 0

        closed_han = estimate_han_advanced(
            self.state.my_hand, self.state.my_melds, self.state.doras,
            is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
            seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju)
        try:
            from yaku_detector import analyze_all
            yi = analyze_all(self.state.my_hand, self.state.my_melds,
                             seat=self.state.my_seat, chang=self.state.chang,
                             ju=self.state.ju)
            for name, y in yi.items():
                if y.progress > 0.3:
                    closed_han += max(0, y.closed_han - y.open_han)
        except Exception:
            pass
        if before_shanten <= 1:
            closed_han += 2

        closed_score = estimate_win_score(closed_han, 30, is_dealer)
        open_score = estimate_win_score(expected_han, 30, is_dealer)
        speed_bonus = (before_shanten - after_shanten) * 1000

        gap = closed_score - open_score
        if gap <= 500:
            return True
        elif gap >= 3000:
            return False
        else:
            return speed_bonus > gap

