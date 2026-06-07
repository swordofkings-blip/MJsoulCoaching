# -*- coding: utf-8 -*-
from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple

from game_state import GameState, Meld
from str_converter import (
    hand_to_counts,
    is_red_five,
    tile_to_id,
)


class ShantenCalculator:
    _cache: dict = {}

    @staticmethod
    def clear_cache():
        ShantenCalculator._cache.clear()

    @staticmethod
    def calculate_standard(hand_counts: List[int]) -> int:
        return ShantenCalculator._standard_shanten(hand_counts)

    @staticmethod
    def calculate_closed(hand_counts: List[int]) -> int:
        std = ShantenCalculator._standard_shanten(hand_counts)
        chiitoi = ShantenCalculator._chiitoitsu_shanten(hand_counts)
        kokushi = ShantenCalculator._kokushi_shanten(hand_counts)
        return min(std, chiitoi, kokushi)

    @staticmethod
    def calculate_open(hand_counts: List[int], open_meld_count: int) -> int:
        key = tuple(hand_counts)
        cache_key = ('op', key, open_meld_count)
        if cache_key in ShantenCalculator._cache:
            return ShantenCalculator._cache[cache_key]
        result = ShantenCalculator._open_shanten(hand_counts, open_meld_count)
        ShantenCalculator._cache[cache_key] = result
        return result



    @staticmethod
    def _standard_shanten(counts: List[int]) -> int:
        best = 8
        for head in range(34):
            if counts[head] < 2:
                continue
            tmp = list(counts)
            tmp[head] -= 2
            melds = ShantenCalculator._max_meld_mps(tuple(tmp[0:9])) + ShantenCalculator._max_meld_mps(tuple(tmp[9:18])) + ShantenCalculator._max_meld_mps(tuple(tmp[18:27])) + ShantenCalculator._max_meld_z(tmp[27:34])
            s = 8 - 2 * melds - 1
            extra_pairs = 0
            for i in range(34):
                if tmp[i] >= 2:
                    if i >= 27:
                        extra_pairs += 1
                    else:
                        base = (i // 9) * 9
                        off = i - base
                        has_l = off > 0 and tmp[base + off - 1] > 0
                        has_r = off < 8 and tmp[base + off + 1] > 0
                        if not has_l and not has_r:
                            extra_pairs += 1
            if extra_pairs >= 1:
                s -= 1
            if s < best:
                best = s
        melds = ShantenCalculator._max_meld_mps(tuple(counts[0:9])) + ShantenCalculator._max_meld_mps(tuple(counts[9:18])) + ShantenCalculator._max_meld_mps(tuple(counts[18:27])) + ShantenCalculator._max_meld_z(counts[27:34])
        s = 8 - 2 * melds
        if s < best:
            best = s
        return best

    @staticmethod
    def _open_shanten(counts: List[int], open_meld_count: int) -> int:
        if open_meld_count >= 4:
            return -1
        best = 8
        for head in range(34):
            if counts[head] < 2:
                continue
            tmp = list(counts)
            tmp[head] -= 2
            melds = ShantenCalculator._max_meld_mps(tuple(tmp[0:9])) + ShantenCalculator._max_meld_mps(tuple(tmp[9:18])) + ShantenCalculator._max_meld_mps(tuple(tmp[18:27])) + ShantenCalculator._max_meld_z(tmp[27:34])
            s = (4 - open_meld_count) * 2 - 2 * melds - 1
            if s < best:
                best = s
        melds = ShantenCalculator._max_meld_mps(tuple(counts[0:9])) + ShantenCalculator._max_meld_mps(tuple(counts[9:18])) + ShantenCalculator._max_meld_mps(tuple(counts[18:27])) + ShantenCalculator._max_meld_z(counts[27:34])
        s = (4 - open_meld_count) * 2 - 2 * melds
        if s < best:
            best = s
        return best

    @staticmethod
    def _max_meld_z(counts7: List[int]) -> int:
        return sum(c // 3 for c in counts7)

    @staticmethod
    @lru_cache(maxsize=None)
    def _max_meld_mps(counts9: Tuple[int, ...]) -> int:
        c = list(counts9)
        return ShantenCalculator._solve_mps(c)

    @staticmethod
    def _solve_mps(c: List[int]) -> int:
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
            v = 1 + ShantenCalculator._solve_mps(c2)
            if v > best:
                best = v
        if first <= 6 and c[first + 1] > 0 and c[first + 2] > 0:
            c2 = list(c)
            c2[first] -= 1
            c2[first + 1] -= 1
            c2[first + 2] -= 1
            v = 1 + ShantenCalculator._solve_mps(c2)
            if v > best:
                best = v
        c2 = list(c)
        c2[first] -= 1
        v = ShantenCalculator._solve_mps(c2)
        if v > best:
            best = v
        return best

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
    def calculate_closed_effective(hand_counts: List[int]) -> int:
        key = tuple(hand_counts)
        cache_key = ('ce', key)
        if cache_key in ShantenCalculator._cache:
            return ShantenCalculator._cache[cache_key]
        result = ShantenCalculator._calc_closed_effective(hand_counts)
        ShantenCalculator._cache[cache_key] = result
        return result

    @staticmethod
    def _calc_closed_effective(hand_counts: List[int]) -> int:
        std = ShantenCalculator._standard_shanten(hand_counts)
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
        return best

    @staticmethod
    def _chiitoitsu_shanten(counts: List[int]) -> int:
        pairs = sum(1 for c in counts if c >= 2)
        kinds = sum(1 for c in counts if c >= 1)
        if kinds < 7:
            return 6 - kinds
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
        open_melds = [m for m in self.state.melds[seat] if m.is_open]
        n_open = len(open_melds)
        if n_open > 0:
            return self._threat_open_player(seat, seat_name, n_open, open_melds)
        return self._threat_closed_player(seat, seat_name)

    def _is_betaori(self, seat: int) -> bool:
        reach_seats = [i for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach]
        if not reach_seats:
            return False
        river = self.state.river[seat]
        if len(river) < 3:
            return False
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        from str_converter import tile_to_id, is_honor
        betaori_count = 0
        for idx in range(max(0, len(river) - 5), len(river)):
            if idx >= len(river):
                break
            tiles = river[idx]
            is_moqie = moqie[idx] if idx < len(moqie) else False
            tid = tile_to_id(tiles)
            is_genbutsu = False
            for rs in reach_seats:
                for t in self.state.river[rs]:
                    if tile_to_id(t) == tid:
                        is_genbutsu = True
                        break
            if is_moqie or is_genbutsu:
                betaori_count += 1
        recent = min(5, len(river) - max(0, len(river) - 5))
        if recent == 0:
            return False
        return betaori_count / recent >= 0.8

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
        if self.state.tsumo_count >= self.params.get('LATE_THRESHOLD', 10) and self._has_late_tedashi_middle(seat):
            bonuses.append(('後半手出し中張牌', self.params.get('LATE_TEDASHI_MIDDLE_BONUS_OPEN', 0.10)))
        value = min(1.0, base + sum(b[1] for b in bonuses))
        tsumo = self.state.tsumo_count
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
        tsumo = self.state.tsumo_count
        if 10 <= tsumo <= 14:
            base = self.params.get('CLOSED_TSUMO_10_14', 0.05)
        elif tsumo >= 15:
            base = self.params.get('CLOSED_TSUMO_15_PLUS', 0.15)
        if base <= 0:
            return 0.0, f'{seat_name}: 序盤（{tsumo}巡）で脅威低'
        if tsumo >= self.params.get('LATE_THRESHOLD', 10) and self._has_late_tedashi_middle(seat):
            bonuses.append(('後半手出し中張牌', self.params.get('LATE_TEDASHI_MIDDLE_BONUS_CLOSED', 0.08)))
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
        dora_ids = {tile_to_id(d) for d in self.state.doras}
        chang_id = 27 + (self.state.chang - 1) if 0 <= self.state.chang - 1 < 4 else -1
        bakaze_id = 27 + (self.state.ju - 1) if 0 <= self.state.ju - 1 < 4 else -1
        honor_target_ids = set(range(27, 31)) | {27, 28, 29, 30} | {bakaze_id, chang_id}
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
        if not self.state.doras:
            return False
        from str_converter import tile_to_id
        dora_id = tile_to_id(self.state.doras[0])
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
        if not self.state.doras:
            return False
        from str_converter import tile_to_id
        dora_id = tile_to_id(self.state.doras[0])
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
        if shanten >= 2:
            blocks = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
            block_factor = max(0.0, (blocks - 4) / 3.0)
            if shanten == 2:
                return min(0.2, 0.10 * block_factor)
            if shanten == 3:
                return min(0.1, 0.05 * block_factor)
        return 0.0

    def _estimate_han(self) -> int:
        han = 1
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            han += 1
        for dora in self.state.doras:
            for t in self.state.my_hand:
                if t == dora or (is_red_five(t) and tile_to_id(t) == tile_to_id(dora)):
                    han += 1
        if any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat):
            han += 1
        return han

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
        push_score = self._apply_position_override(push_score)
        return max(0.0, min(1.0, push_score))

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
        rank = self.state.my_score_rank()
        remaining = self._remaining_kyokus()

        # 南入間近: トップ目が29000+でゲーム終了が近い
        scores = self.state.scores
        top_score = max(scores)
        if top_score >= 29000 and remaining <= 2:
            if rank == 0:
                return min(push_score, 0.3)
            if rank >= 2:
                return max(push_score, 0.6)

        # 残り局数が少ない: 順位に応じて傾斜
        if remaining <= 3:
            if rank == 0:
                return min(push_score, 0.4)
            if rank == 3:
                return max(push_score, 0.7)

        if not self.state.is_last_round():
            return push_score
        if rank == 0:
            return min(push_score, self.params.get('LAST_ROUND_RANK0_PUSH_LIMIT', 0.2))
        if rank == 3 and self.state.ju >= 1:
            return max(push_score, self.params.get('LAST_ROUND_RANK3_PUSH_MIN', 0.85))
        return push_score

    def is_orya_ori_mode(self) -> bool:
        return self.compute_push_score() <= 0.05

    def is_zenchi_mode(self) -> bool:
        if not self.state.is_last_round():
            return False
        return self.state.my_score_rank() == 3

    def is_meld_open_allowed(self) -> bool:
        return True

    def get_strategy_mode(self) -> str:
        push = self.compute_push_score()
        zentsu_th = self.params.get('MODE_ZENTSU_THRESHOLD', 0.7)
        betaori_th = self.params.get('MODE_BETAORI_THRESHOLD', 0.05)
        if push >= zentsu_th or self.is_zenchi_mode():
            return "全ツ"
        if push <= betaori_th:
            return "ベタオリ"
        return "回し打ち"

    def is_zenchi_mode(self) -> bool:
        if not self.state.is_last_round():
            return False
        return self.state.my_score_rank() == 3

    def get_strategy_details(self) -> dict:
        """
        @title 戦略パラメータ開示
        @description UIで可視化するために、戦略計算の中間パラメータを辞書形式で返す。最大脅威度と脅威理由テキストも含む。
        @returns {dict} base_attack, max_threat, push_score, mode, threat_reason などを含む辞書
        """
        a_base = self.compute_base_attack()
        t_max, threat_reason = self._max_threat_with_reason()
        push = self.compute_push_score()
        return {
            "base_attack": round(a_base, 3),
            "max_threat": round(t_max, 3),
            "push_score": round(push, 3),
            "mode": self.get_strategy_mode(),
            "threat_reason": threat_reason,
            "is_last_round": self.state.is_last_round(),
            "my_rank": self.state.my_score_rank(),
        }
