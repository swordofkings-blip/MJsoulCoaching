# -*- coding: utf-8 -*-
from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple, Set, Set

from game_state import GameState, Meld
from str_converter import (
    hand_to_counts,
    is_red_five,
    is_honor,
    tile_to_id,
    dora_indicator_to_dora,
)


class ShantenCalculator:
    _cache: dict = {}

    @staticmethod
    def clear_cache():
        ShantenCalculator._cache.clear()

    @staticmethod
    def calculate_standard(hand_counts: List[int]) -> int:
        return ShantenCalculator._suit_shanten(hand_counts, 0)

    @staticmethod
    def calculate_closed(hand_counts: List[int]) -> int:
        std = ShantenCalculator._suit_shanten(hand_counts, 0)
        chiitoi = ShantenCalculator._chiitoitsu_shanten(hand_counts)
        kokushi = ShantenCalculator._kokushi_shanten(hand_counts)
        return min(std, chiitoi, kokushi)

    @staticmethod
    def calculate_open(hand_counts: List[int], open_meld_count: int) -> int:
        key = (tuple(hand_counts), open_meld_count)
        if key in ShantenCalculator._cache:
            return ShantenCalculator._cache[key]
        if open_meld_count >= 4:
            return -1
        result = ShantenCalculator._suit_shanten(hand_counts, open_meld_count)
        ShantenCalculator._cache[key] = result
        return result

    @staticmethod
    def calculate_open(hand_counts: List[int], open_meld_count: int) -> int:
        key = (tuple(hand_counts), open_meld_count)
        if key in ShantenCalculator._cache:
            return ShantenCalculator._cache[key]
        if open_meld_count >= 4:
            return -1
        result = ShantenCalculator._suit_shanten(hand_counts, open_meld_count)
        ShantenCalculator._cache[key] = result
        return result

    @staticmethod
    def calculate_closed_effective(hand_counts: List[int]) -> int:
        key = (tuple(hand_counts), 'ce')
        if key in ShantenCalculator._cache:
            return ShantenCalculator._cache[key]
        
        std = ShantenCalculator._suit_shanten(hand_counts, 0)
        pairs = sum(1 for c in hand_counts if c >= 2)
        yaochu_indices = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        yaochu_types = sum(1 for i in yaochu_indices if hand_counts[i] >= 1)
        best = std
        if pairs >= 4:
            chiitoi = ShantenCalculator._chiitoitsu_shanten(hand_counts)
            if chiitoi < best:
                best = chiitoi
        if yaochu_types >= 9:
            kokushi = ShantenCalculator._kokushi_shanten(hand_counts)
            if kokushi < best:
                best = kokushi
                
        ShantenCalculator._cache[key] = best
        return best

    @staticmethod
    @lru_cache(maxsize=None)
    def _solve_suit_combinations(counts9: Tuple[int, ...]) -> Set[Tuple[int, int, int]]:
        result = set()
        c = list(counts9)

        def dfs(idx, melds, taatsu, pairs):
            if idx == 9:
                result.add((melds, taatsu, pairs))
                return
            if c[idx] == 0:
                dfs(idx + 1, melds, taatsu, pairs)
                return
            n = c[idx]
            if n >= 3:
                c[idx] -= 3
                dfs(idx, melds + 1, taatsu, pairs)
                c[idx] += 3
            if n >= 2:
                c[idx] -= 2
                dfs(idx, melds, taatsu, pairs + 1)
                c[idx] += 2
            if idx <= 6 and c[idx + 1] > 0 and c[idx + 2] > 0:
                c[idx] -= 1
                c[idx + 1] -= 1
                c[idx + 2] -= 1
                dfs(idx, melds + 1, taatsu, pairs)
                c[idx] += 1
                c[idx + 1] += 1
                c[idx + 2] += 1
            if idx <= 7 and c[idx + 1] > 0:
                c[idx] -= 1
                c[idx + 1] -= 1
                dfs(idx, melds, taatsu + 1, pairs)
                c[idx] += 1
                c[idx + 1] += 1
            if idx <= 6 and c[idx + 2] > 0:
                c[idx] -= 1
                c[idx + 2] -= 1
                dfs(idx, melds, taatsu + 1, pairs)
                c[idx] += 1
                c[idx + 2] += 1
            c[idx] -= 1
            dfs(idx, melds, taatsu, pairs)
            c[idx] += 1

        dfs(0, 0, 0, 0)
        return result

    @staticmethod
    @lru_cache(maxsize=None)
    def _solve_honor_combinations(counts7: Tuple[int, ...]) -> Set[Tuple[int, int]]:
        result = set()
        c = list(counts7)

        def dfs(idx, melds, pairs):
            if idx == 7:
                result.add((melds, pairs))
                return
            if c[idx] == 0:
                dfs(idx + 1, melds, pairs)
                return
            n = c[idx]
            if n >= 3:
                c[idx] -= 3
                dfs(idx, melds + 1, pairs)
                c[idx] += 3
            if n >= 2:
                c[idx] -= 2
                dfs(idx, melds, pairs + 1)
                c[idx] += 2
            c[idx] -= n
            dfs(idx + 1, melds, pairs)
            c[idx] += n

        dfs(0, 0, 0)
        return result

    @staticmethod
    def _suit_shanten(counts: List[int], open_meld_count: int) -> int:
        m_combs = ShantenCalculator._solve_suit_combinations(tuple(counts[0:9]))
        p_combs = ShantenCalculator._solve_suit_combinations(tuple(counts[9:18]))
        s_combs = ShantenCalculator._solve_suit_combinations(tuple(counts[18:27]))
        h_combs = ShantenCalculator._solve_honor_combinations(tuple(counts[27:34]))
        best = 8

        for mm, mt, mp in m_combs:
            for pm, pt, pp in p_combs:
                for sm, st, sp in s_combs:
                    for hm, hp in h_combs:
                        total_melds = mm + pm + sm + hm + open_meld_count
                        total_taatsu = mt + pt + st
                        total_pairs = mp + pp + sp + hp
                        still_needed = 4 - total_melds
                        if total_pairs >= 1:
                            rem_blocks = total_taatsu + (total_pairs - 1)
                            s = still_needed + max(0, still_needed - rem_blocks) - 1
                        else:
                            rem_blocks = total_taatsu + total_pairs
                            s = still_needed + max(0, still_needed - rem_blocks)
                        if s < best:
                            best = s
        if best <= 0 and open_meld_count == 0 and not any(c >= 2 for c in counts):
            best = max(best, 1)
        return best

    @staticmethod
    def _chiitoitsu_shanten(counts: List[int]) -> int:
        pairs = sum(1 for c in counts if c >= 2)
        kinds = sum(1 for c in counts if c >= 1)
        if kinds < 7:
            return 8
        if pairs == 7:
            return -1
        return 6 - pairs

    @staticmethod
    def _kokushi_shanten(counts: List[int]) -> int:
        yao = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        unique = sum(1 for i in yao if counts[i] >= 1)
        has_pair = any(counts[i] >= 2 for i in yao)
        if unique == 13 and has_pair:
            return -1
        return 13 - unique - (1 if has_pair else 0)

    @staticmethod
    def calculate_blocks(hand_counts: List[int], open_meld_count: int = 0) -> int:
        """
        @title 手牌全体のブロック数算出
        @description 萬子・筒子・索子の各スートの最大ブロック数 ＋ 字牌の対子/刻子数 ＋ 副露数を合計する。
        @param {List[int]} hand_counts - 34種牌カウント
        @param {int} open_meld_count - 副露数
        @returns {int} 手牌全体のブロック数
        """
        m_blocks = ShantenCalculator._solve_blocks_mps(tuple(hand_counts[0:9]))
        p_blocks = ShantenCalculator._solve_blocks_mps(tuple(hand_counts[9:18]))
        s_blocks = ShantenCalculator._solve_blocks_mps(tuple(hand_counts[18:27]))
        z_blocks = sum(1 for c in hand_counts[27:34] if c >= 2)
        return m_blocks + p_blocks + s_blocks + z_blocks + open_meld_count

    @staticmethod
    @lru_cache(maxsize=None)
    def _solve_blocks_mps(counts9: Tuple[int, ...]) -> int:
        c = list(counts9)
        return ShantenCalculator._blocks_recursive(c)

    @staticmethod
    def _blocks_recursive(c: List[int]) -> int:
        best = 0
        first = None
        for i in range(9):
            if c[i] > 0:
                first = i
                break
        if first is None:
            return 0
        if c[first] >= 3:
            c2 = list(c)
            c2[first] -= 3
            best = max(best, 1 + ShantenCalculator._solve_blocks_mps(tuple(c2)))
        if c[first] >= 2:
            c2 = list(c)
            c2[first] -= 2
            best = max(best, 1 + ShantenCalculator._solve_blocks_mps(tuple(c2)))
        if first <= 6 and c[first+1] > 0 and c[first+2] > 0:
            c2 = list(c)
            c2[first] -= 1
            c2[first+1] -= 1
            c2[first+2] -= 1
            best = max(best, 1 + ShantenCalculator._solve_blocks_mps(tuple(c2)))
        if first <= 7 and c[first+1] > 0:
            c2 = list(c)
            c2[first] -= 1
            c2[first+1] -= 1
            best = max(best, 1 + ShantenCalculator._solve_blocks_mps(tuple(c2)))
        if first <= 6 and c[first+2] > 0:
            c2 = list(c)
            c2[first] -= 1
            c2[first+2] -= 1
            best = max(best, 1 + ShantenCalculator._solve_blocks_mps(tuple(c2)))
        c2 = list(c)
        c2[first] -= 1
        best = max(best, ShantenCalculator._solve_blocks_mps(tuple(c2)))
        return best


class StrategyManager:
    """
    @title 戦略判定
    @description 対局状態（自家手牌・他家捨牌・副露状況）から、押し引きと攻撃度の指標を算出する。
    """
    REACH_THREAT = 1.0
    OPEN_BASE_BY_COUNT = {0: 0.0, 1: 0.15, 2: 0.40, 3: 0.75, 4: 0.95}
    YAKUHAI_DORA_MELD_BONUS = 0.15
    LATE_TEDASHI_MIDDLE_BONUS_OPEN = 0.10
    LATE_TEDASHI_MIDDLE_BONUS_CLOSED = 0.08
    LATE_THRESHOLD = 10
    CLOSED_TSUMO_10_14 = 0.05
    CLOSED_TSUMO_15_PLUS = 0.15
    BASE_THREAT = 0.0

    SEAT_NAMES = ['自家', '下家', '対面', '上家']

    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        from fuzzy_logic import FuzzyLogicEngine
        self.fuzzy_engine = FuzzyLogicEngine(self.params)

    def compute_opponent_threat(self) -> float:
        """
        @title 最大脅威度の算出
        @description 各他家のリーチ・副露数・捨牌の手出し中張牌・ドラ/役牌の鳴き状況から脅威度を算出し、その最大値を返す。
        @returns {float} 最大脅威度 0.0〜1.0
        """
        max_threat, _ = self._max_threat_with_reason()
        return max_threat

    def _max_threat_with_reason(self) -> Tuple[float, str]:
        """
        @title 脅威度と理由テキストの同時算出
        @description 各他家の脅威度を計算し、最も高い脅威を持つ他家の脅威値と日本語理由テキストを返す。
        @returns {Tuple[float, str]} (最大脅威度, 理由テキスト)
        """
        best_value = self.params.get('BASE_THREAT', 0.0)
        best_reason = '他家に脅威なし'
        for i in range(4):
            if i == self.state.my_seat:
                continue
            value, reason = self._opponent_threat_for_seat(i)
            if value > best_value:
                best_value = value
                best_reason = reason
        return best_value, best_reason

    def _opponent_threat_for_seat(self, seat: int) -> Tuple[float, str]:
        seat_name = self.SEAT_NAMES[seat] if 0 <= seat < 4 else f'Player {seat}'
        if self.state.reach_states[seat].is_reach:
            reach_threat = self.params.get('REACH_THREAT', 1.0)
            return reach_threat, f'{seat_name}: リーチ済（=テンパイ確定、脅威度 {reach_threat:.2f}）'
        # 他家リーチ後にベタオリしている相手は脅威度を大幅に下げる
        if self._is_betaori(seat):
            return self.params.get('BASE_THREAT', 0.0), f'{seat_name}: ベタオリ中（脅威低）'

        # 役満脅威度の確認
        yakuman_threat = self._yakuman_threat_for_seat(seat)
        if yakuman_threat > 0.3:
            return yakuman_threat, f'{seat_name}: 役満警戒（脅威度 {yakuman_threat:.2f}）'

        open_melds = [m for m in self.state.melds[seat] if m.is_open]
        n_open = len(open_melds)
        if n_open > 0:
            return self._threat_open_player(seat, seat_name, n_open, open_melds)
        return self._threat_closed_player(seat, seat_name)

    def _is_betaori(self, seat: int) -> bool:
        reach_seats = [i for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach]
        river = self.state.river[seat]
        if len(river) < 3:
            return False
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        from str_converter import tile_to_id, is_honor
        betaori_count = 0
        # 直近5枚の捨て牌をチェック
        for idx in range(max(0, len(river) - 5), len(river)):
            if idx >= len(river):
                break
            tiles = river[idx]
            is_moqie = moqie[idx] if idx < len(moqie) else False
            tid = tile_to_id(tiles)

            if reach_seats:
                # リーチ者がいる場合: リーチ者の現物かどうか
                is_genbutsu = False
                for rs in reach_seats:
                    for t in self.state.river[rs]:
                        if tile_to_id(t) == tid:
                            is_genbutsu = True
                            break
            else:
                # リーチ者がいない場合: 誰かの河にある牌 = 安全牌
                is_genbutsu = any(
                    tile_to_id(t) == tid
                    for s in range(4)
                    if s != seat
                    for t in self.state.river[s]
                )

            if is_moqie or is_genbutsu:
                betaori_count += 1
        recent = min(5, len(river) - max(0, len(river) - 5))
        if recent == 0:
            return False
        return betaori_count / recent >= 0.8

    def _yakuman_threat_for_seat(self, seat: int) -> float:
        """
        @title 他家の役満脅威度算出
        @description 国士無双・四槓子・大四喜・小四喜・大三元の警戒判断を行う。
        @param {int} seat - 対象 seat
        @returns {float} 脅威度（0.0〜1.0）
        """
        from yakuman_evaluator import YakumanEvaluator
        evaluator = YakumanEvaluator(self.state)
        return evaluator.opponent_yakuman_threat(seat)

    def _threat_open_player(self, seat: int, seat_name: str, n_open: int, open_melds: List[Meld]) -> Tuple[float, str]:
        """
        @title 副露者の脅威度算出
        @description 副露数に応じた基礎値に、ドラ/役牌ポン・後半手出し中張牌のボーナス加算を適用する。
        @param {int} seat - 対象 seat
        @param {str} seat_name - プレイヤー名
        @param {int} n_open - 副露数
        @param {List[Meld]} open_melds - 副露一覧
        @returns {Tuple[float, str]} (脅威度, 理由テキスト)
        """
        open_base_map = {
            0: 0.0,
            1: self.params.get('OPEN_BASE_BY_COUNT_1', 0.15),
            2: self.params.get('OPEN_BASE_BY_COUNT_2', 0.40),
            3: self.params.get('OPEN_BASE_BY_COUNT_3', 0.75),
            4: self.params.get('OPEN_BASE_BY_COUNT_4', 0.95),
        }
        base = open_base_map.get(n_open, 0.95)
        bonuses: List[Tuple[str, float]] = []
        if self._has_yakuhai_or_dora_meld(open_melds):
            bonuses.append(('役牌・ドラポン', self.params.get('YAKUHAI_DORA_MELD_BONUS', 0.15)))
        if (self.state.tsumo_count - 1) // 4 + 1 >= self.params.get('LATE_THRESHOLD', 10) and self._has_late_tedashi_middle(seat):
            bonuses.append(('後半手出し中張牌', self.params.get('LATE_TEDASHI_MIDDLE_BONUS_OPEN', 0.10)))
        value = min(1.0, base + sum(b[1] for b in bonuses))
        tsumo = (self.state.tsumo_count - 1) // 4 + 1
        if tsumo < 8:
            turn_scale = max(0.3, tsumo / 12.0)
            value = value * turn_scale
        elif tsumo < 12:
            turn_scale = max(0.5, tsumo / 12.0)
            value = value * turn_scale
        value = min(1.0, value)
        reason = f'{seat_name}: {n_open}副露 (基礎 {base:.2f})'
        for label, b in bonuses:
            reason += f' + {label} (+{b:.2f})'
        reason += f' = {value:.2f}'
        return value, reason

    def _threat_closed_player(self, seat: int, seat_name: str) -> Tuple[float, str]:
        """
        @title 門前者の脅威度算出
        @description 巡目と手出し中張牌履歴からダマテン接近の脅威度を算出する。
        @param {int} seat - 対象 seat
        @param {str} seat_name - プレイヤー名
        @returns {Tuple[float, str]} (脅威度, 理由テキスト)
        """
        bonuses: List[Tuple[str, float]] = []
        base = 0.0
        tsumo = (self.state.tsumo_count - 1) // 4 + 1
        if 10 <= tsumo <= 14:
            base = self.params.get('CLOSED_TSUMO_10_14', 0.05)
        elif tsumo >= 15:
            base = self.params.get('CLOSED_TSUMO_15_PLUS', 0.15)
        if base <= 0:
            return 0.0, f'{seat_name}: 序盤（{tsumo}巡）で脅威低'
        if tsumo >= self.params.get('LATE_THRESHOLD', 10) and self._has_late_tedashi_middle(seat):
            bonuses.append(('後半手出し中張牌', self.params.get('LATE_TEDASHI_MIDDLE_BONUS_CLOSED', 0.08)))

        # Damaten signal detection (late turn, no riichi)
        if tsumo >= 12:
            river = self.state.river[seat]
            moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
            # Check last 3 discards for danger signals
            recent_tedashi = []
            for idx in range(max(0, len(river)-5), len(river)):
                is_moqie = moqie[idx] if idx < len(moqie) else False
                if not is_moqie:
                    t = river[idx]
                    recent_tedashi.append(t)

            # Signal A: discarded dora from hand
            for d in self.state.doras:
                dora_tile = dora_indicator_to_dora(d)
                if dora_tile in recent_tedashi:
                    bonuses.append(('ドラ手出し', 0.15))
                    break

            # Signal B: discarded live honor tile (sangen/seat/round wind not yet visible)
            yakuhai_tiles = {31, 32, 33}  # haku, hatsu, chun
            sw = {0: 27, 1: 28, 2: 29, 3: 30}.get(seat)
            rw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.chang % 4)
            if sw: yakuhai_tiles.add(sw)
            if rw: yakuhai_tiles.add(rw)
            # Check if any yakuhai tile was tedashi
            try:
                for t in recent_tedashi:
                    tid = tile_to_id(t)
                    if tid in yakuhai_tiles:
                        # Check if it's a live tile (not yet visible in any river)
                        visible = sum(
                            1 for s in range(4)
                            for rt in self.state.river[s]
                            if tile_to_id(rt) == tid
                        )
                        if visible <= 1:  # only the one we just checked
                            bonuses.append(('生牌役牌手出し', 0.20))
                            break
            except Exception:
                pass

            # Signal C: multiple (>=2) consecutive middle tile tedashi in last 3 hand discards
            middle_tedashi_count = sum(
                1 for t in recent_tedashi[-3:]
                if not is_honor(tile_to_id(t)) and 2 <= (tile_to_id(t) % 9) <= 6
            )
            if middle_tedashi_count >= 2:
                bonuses.append(('中張連続手出し', 0.10))

        value = min(1.0, base + sum(b[1] for b in bonuses))
        reason = f'{seat_name}: 門前 (基礎 {base:.2f}, {tsumo}巡)'
        for label, b in bonuses:
            reason += f' + {label} (+{b:.2f})'
        reason += f' = {value:.2f}'
        return value, reason

    def _has_yakuhai_or_dora_meld(self, open_melds: List[Meld]) -> bool:
        """
        @title 役牌・ドラポン検出
        @description 副露牌の中に三元牌・自風牌・場風牌・ドラが含まれるかを判定する。
        @param {List[Meld]} open_melds - 副露一覧
        @returns {bool} 役牌またはドラのポン/大明槓を含むなら True
        """
        from str_converter import tile_to_id
        dora_ids = {tile_to_id(d) for d in self.state.actual_doras}
        dealer_seat = getattr(self.state, 'dealer_seat', 0)
        bakaze_id = 27 + (self.state.chang % 4)
        jikaze_id = 27 + ((self.state.my_seat - dealer_seat) % 4)
        honor_target_ids = set(range(27, 31)) | {27, 28, 29, 30} | {bakaze_id, jikaze_id}
        for m in open_melds:
            for t in m.tiles:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if tid in dora_ids:
                    return True
                if tid >= 27 and tid in honor_target_ids:
                    return True
        return False

    def _has_late_tedashi_middle(self, seat: int) -> bool:
        """
        @title 後半手出し中張牌の検出
        @description 該当他家の河に「ツモ切りではない」中張牌（3〜7）が含まれているか判定する。
        @param {int} seat - 対象 seat
        @returns {bool} 該当牌があれば True
        """
        from str_converter import tile_to_id
        river_tiles = self.state.river[seat]
        moqie_flags = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        for idx, t in enumerate(river_tiles):
            try:
                tid = tile_to_id(t)
            except Exception:
                continue
            if tid >= 27:
                continue
            offset = tid % 9
            if 2 <= offset <= 6:
                is_moqie = moqie_flags[idx] if idx < len(moqie_flags) else False
                if not is_moqie:
                    return True
        return False

    def _is_dora_heavy_or_color_drain(self, seat: int) -> bool:
        if not self.state.actual_doras:
            return False
        from str_converter import tile_to_id
        dora_id = tile_to_id(self.state.actual_doras[0])
        seat_visible = 0
        for t in self.state.river[seat]:
            if tile_to_id(t) == dora_id:
                seat_visible += 1
        for m in self.state.melds[seat]:
            for t in m.tiles:
                if tile_to_id(t) == dora_id:
                    seat_visible += 1
        if seat_visible >= 2:
            return True
        seat_visible_counts = [0] * 34
        for t in self.state.river[seat]:
            seat_visible_counts[tile_to_id(t)] += 1
        for m in self.state.melds[seat]:
            for t in m.tiles:
                seat_visible_counts[tile_to_id(t)] += 1
        for i in range(3):
            color_start = i * 9
            color_tiles = sum(seat_visible_counts[color_start:color_start + 9])
            if color_tiles >= 8:
                return True
        return False

    def _is_dora_heavy_or_color_drain(self, seat: int) -> bool:
        if not self.state.actual_doras:
            return False
        from str_converter import tile_to_id
        dora_id = tile_to_id(self.state.actual_doras[0])
        seat_visible = 0
        for t in self.state.river[seat]:
            if tile_to_id(t) == dora_id:
                seat_visible += 1
        for m in self.state.melds[seat]:
            for t in m.tiles:
                if tile_to_id(t) == dora_id:
                    seat_visible += 1
        if seat_visible >= 2:
            return True
        seat_visible_counts = [0] * 34
        for t in self.state.river[seat]:
            seat_visible_counts[tile_to_id(t)] += 1
        for m in self.state.melds[seat]:
            for t in m.tiles:
                seat_visible_counts[tile_to_id(t)] += 1
        for i in range(3):
            color_start = i * 9
            color_tiles = sum(seat_visible_counts[color_start:color_start + 9])
            if color_tiles >= 8:
                return True
        return False

    def compute_base_attack(self) -> float:
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        if shanten <= -1:
            han = self._estimate_han()
            if han >= 5:
                return self.params.get('BASE_ATTACK_TENPAI_HIGH', 1.0)
            else:
                return self.params.get('BASE_ATTACK_TENPAI_LOW', 0.7)
        if shanten == 0:
            return self.params.get('BASE_ATTACK_TENPAI_LOW', 0.7)
        if shanten == 1:
            return self.params.get('BASE_ATTACK_1SHANTEN', 0.4)
        max_shanten = self.params.get('BASE_ATTACK_MAX_SHANTEN', 6)
        if shanten >= 2:
            if shanten > max_shanten:
                return 0.0

            default_val = 0.4 * (0.5 ** (shanten - 1))
            param_key = f'BASE_ATTACK_{shanten}SHANTEN'
            base_val = self.params.get(param_key, default_val)

            blocks = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
            block_factor = max(0.0, (blocks - 4) / 3.0)

            return max(0.01, min(base_val, (base_val / 2.0) * block_factor))

        # 役満攻撃ブースト
        yakuman_boost = self._yakuman_attack_boost()
        if yakuman_boost > 0:
            return min(1.0, yakuman_boost)

        return 0.0

    def _yakuman_attack_boost(self) -> float:
        """
        @title 役満攻撃ブースト
        @description 役満進行度が高い場合、攻撃度を引き上げる。
                  他家が脅威の場合はブーストしない。
        @returns {float} 攻撃ブースト値（0.0〜1.0）
        """
        from yakuman_evaluator import YakumanEvaluator

        # パラメータ読み込み
        yakuman_cfg = self.params.get('yakuman_strategy', {})
        min_shanten = yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2)
        defense_threshold = yakuman_cfg.get('YAKUMAN_ATTACK_BOOST_DEFENSE_THRESHOLD', 0.5)

        # 他家脅威度チェック: 高い場合はブーストしない
        # 注意: compute_opponent_threat()は循環呼び出しを避けるため直接呼ばない
        threat, _ = self._max_threat_with_reason()
        if threat > defense_threshold:
            return 0.0

        evaluator = YakumanEvaluator(self.state)
        results = evaluator.evaluate_all()

        max_boost = 0.0
        for name, result in results.items():
            if not result.is_possible:
                continue
            if result.shanten > min_shanten:
                continue

            # シャンテン補正（二次関数）
            shanten_factor = max(0.0, (4 - result.shanten) ** 2 / 16.0)

            # 進行度に基づくブースト
            boost = shanten_factor * result.progress
            if boost > max_boost:
                max_boost = boost

        return min(1.0, max_boost)

    def _estimate_han(self) -> int:
        """
        @title 期待飜数の見積もり
        @description 現在の局状態から、和了時の期待飜数をHeuristicに見積もる。
        @returns {int} 期待飜数（最低1）
        """
        # アガる前の進行中の手牌から役を推測するため、strictなyaku_detectorではなくheuristicな予測ロジックを使用する
        is_open = any(m.is_open for m in self.state.my_melds)
        has_reach = any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat)
        from hand_value import estimate_han_advanced
        han = estimate_han_advanced(
            self.state.my_hand, self.state.my_melds, self.state.doras,
            is_open=is_open, has_reach=has_reach, is_ippatsu=False, is_tsumo=False,
            seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju
        )
        # 最低1飜を保証するための数値1
        return max(han, 1)

    def compute_push_score(self) -> float:
        a_base = self.compute_base_attack()
        t_max = self.compute_opponent_threat()
        if t_max <= 0.0:
            hand_counts = self.state.my_hand_counts()
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            if open_meld_count == 0:
                shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
            else:
                shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
            if shanten >= 3:
                return max(a_base, 0.3)
            return 1.0
        push_score = a_base * (1.0 - t_max)
        # --- 人読み: リーチ押し引き補正 ---
        push_score = self._apply_player_stats_riichi_adjust(push_score)
        push_score = self._apply_position_override(push_score)
        return max(0.0, min(1.0, push_score))

    def _apply_player_stats_riichi_adjust(self, push_score: float) -> float:
        player_stats = self.state.player_stats or {}
        adjust = 0.0
        for s in range(4):
            if s == self.state.my_seat:
                continue
            if not self.state.reach_states[s].is_reach:
                continue
            pstats = player_stats.get(str(s), {})
            deal_in_rate = pstats.get("deal_in_rate", 0.12)
            riichi_rate = pstats.get("riichi_rate", 0.20)
            if deal_in_rate < 0.11:
                adjust -= 0.10
            if riichi_rate > 0.24:
                adjust += 0.10
        if adjust != 0.0:
            pass
        return max(0.0, min(1.0, push_score + adjust))

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

    def _apply_position_override(self, push_score: float) -> float:
        """
        @title 順位状況に応じた押し引きの強制補正
        @description 残り局数や点数状況（ラス回避など）を考慮し、シャンテン数（進行度）に応じて動的に押し引きスコア（push_score）を補正する。
        @param {float} push_score - 補正前の押し引きスコア
        @returns {float} 補正後の押し引きスコア
        """
        rank = self.state.my_score_rank()
        remaining = self._remaining_kyokus()

        # 進行度（シャンテン数）を取得して、遠い手牌からの無謀な押しを防ぐ
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_meld_count)

        # 南入間近: トップ目が29000+でゲーム終了が近い（サドンデス終了条件の30000点突破を防ぐ・狙うための閾値）
        scores = self.state.scores
        top_score = max(scores)
        if top_score >= 29000 and remaining <= 2:
            if rank == 0:
                # オーラスor残り僅かでダントツトップ → 完璧ベタオリ(0.0)
                second_score = sorted(scores, reverse=True)[1] if len(scores) >= 2 else 25000
                gap_to_second = top_score - second_score
                if remaining <= 1 or gap_to_second >= 20000:
                    return 0.0
                return min(push_score, 0.2)
            if rank >= 2:
                # ラス回避のためのプッシュ（進行度に応じて動的に制限）
                if shanten <= 0:
                    return max(push_score, 0.8) # テンパイなら強く押す
                elif shanten == 1:
                    return max(push_score, 0.5) # 1向聴なら中程度に押す
                elif shanten == 2:
                    return max(push_score, 0.25) # 2向聴なら回し打ち可能な限界
                else:
                    return push_score # 3向聴以上なら押しを強制しない

        # 残り局数が少ない: 順位に応じて傾斜（3局以下は終盤戦）
        if remaining <= 3:
            if rank == 0:
                # トップ目の逃げ切り（0.4は放銃を回避するための安全ライン）
                return min(push_score, 0.4)
            if rank == 3:
                # ラス親またはラス席の押し返し（進行度に応じて補正）
                if shanten <= 0:
                    return max(push_score, 0.75) # 0.75は他家リーチに対しても戦う水準
                elif shanten == 1:
                    return max(push_score, 0.5) # 1向聴なら形維持を考慮した押し
                elif shanten == 2:
                    return max(push_score, 0.2) # 2向聴なら安牌優先で回す
                else:
                    return push_score

        if not self.state.is_last_round():
            return push_score
        if rank == 0:
            return min(push_score, self.params.get('LAST_ROUND_RANK0_PUSH_LIMIT', 0.2))
        if rank == 3 and self.state.ju >= 1:
            if shanten <= 0:
                return max(push_score, self.params.get('LAST_ROUND_RANK3_PUSH_MIN', 0.85))
            elif shanten == 1:
                return max(push_score, 0.6) # 1向聴ならある程度押す
            elif shanten == 2:
                return max(push_score, 0.3) # 2向聴ならギリギリ回し打ち可能なライン
            else:
                return push_score
        return push_score

    def is_orya_ori_mode(self) -> bool:
        return self.compute_push_score() <= 0.05

    def is_zenchi_mode(self) -> bool:
        if not self.state.is_last_round():
            return False
        return self.state.my_score_rank() == 3

    def is_meld_open_allowed(self) -> bool:
        # 門前限定役満（国士無双・四暗刻・九蓮宝燈）を狙っている場合は副露封印
        from yakuman_evaluator import YakumanEvaluator
        evaluator = YakumanEvaluator(self.state)
        if evaluator.should_seal_melds():
            # 統計
            if hasattr(self, 'evaluator') and self.evaluator is not None:
                ai = getattr(self.evaluator, '_ai_player', None)
                if ai is not None:
                    ai.meld_seal_count += 1
            return False
        return True

    def get_strategy_mode(self) -> str:
        if self.is_zenchi_mode():
            return "全力攻撃"

        base_attack = self.compute_base_attack()
        max_threat = self.compute_opponent_threat()

        mode, _ = self.fuzzy_engine.evaluate_strategy(base_attack, max_threat)
        return mode

    def get_strategy_details(self) -> dict:
        a_base = self.compute_base_attack()
        t_max, threat_reason = self._max_threat_with_reason()
        push = self.compute_push_score()

        mode, scores = self.fuzzy_engine.evaluate_strategy(a_base, t_max)

        return {
            "base_attack": round(a_base, 3),
            "max_threat": round(t_max, 3),
            "push_score": round(push, 3),
            "mode": mode,
            "threat_reason": threat_reason,
            "is_last_round": self.state.is_last_round(),
            "my_rank": self.state.my_score_rank(),
            "yakuman_seal": not self.is_meld_open_allowed(),
            "yakuman_boost": round(self._yakuman_attack_boost(), 3),
            "fuzzy_scores": {k: round(v, 3) for k, v in scores.items()}
        }
