# -*- coding: utf-8 -*-
from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple, Set
import threading

from game_state import GameState, Meld
from str_converter import (
    hand_to_counts,
    is_red_five,
    is_honor,
    tile_to_id,
    dora_indicator_to_dora,
)


class ShantenCalculator:
    _thread_local = threading.local()

    @staticmethod
    def _get_cache() -> dict:
        """
        @title スレッドローカルなキャッシュの取得
        @description 現在実行中のスレッドに紐づくシャンテン数キャッシュ辞書を返します。
        @returns {dict} スレッドローカルなキャッシュ辞書
        """
        # なぜこのようにするか：各AIクライアントが同一プロセス内の別スレッドで並行して動作するため、
        # 共有キャッシュの競合と破壊を防ぐためにスレッドごとにキャッシュを分離する必要があるからです。
        if not hasattr(ShantenCalculator._thread_local, 'cache'):
            ShantenCalculator._thread_local.cache = {}
        return ShantenCalculator._thread_local.cache

    @staticmethod
    def clear_cache():
        """
        @title キャッシュのクリア
        @description 現在のスレッドのシャンテン数キャッシュをクリアします。
        """
        ShantenCalculator._get_cache().clear()

    @staticmethod
    def calculate_standard(hand_counts: List[int]) -> int:
        """
        @title 標準形シャンテン数計算
        @description 一般的な4面子1雀頭の形における最小シャンテン数を計算し、スレッドローカルキャッシュに保存します。
        @param {List[int]} hand_counts - 手牌の34種牌カウント
        @returns {int} シャンテン数
        """
        # 重複計算によるCPU負荷とタイムアウトを防ぐため、スレッドローカルキャッシュを利用します。
        key = (tuple(hand_counts), 's')
        cache = ShantenCalculator._get_cache()
        if key in cache:
            return cache[key]
        result = ShantenCalculator._suit_shanten(hand_counts, 0)
        cache[key] = result
        return result

    @staticmethod
    def calculate_closed(hand_counts: List[int]) -> int:
        """
        @title 門前手シャンテン数計算
        @description 門前時の標準形・七対子・国士無双のうち最小のシャンテン数を計算し、スレッドローカルキャッシュに保存します。
        @param {List[int]} hand_counts - 手牌の34種牌カウント
        @returns {int} 最小のシャンテン数
        """
        # 評価値計算で繰り返し呼び出されるため、スレッドローカルキャッシュにより再計算を防止します。
        key = (tuple(hand_counts), 'c')
        cache = ShantenCalculator._get_cache()
        if key in cache:
            return cache[key]
        std = ShantenCalculator._suit_shanten(hand_counts, 0)
        chiitoi = ShantenCalculator._chiitoitsu_shanten(hand_counts)
        kokushi = ShantenCalculator._kokushi_shanten(hand_counts)
        result = min(std, chiitoi, kokushi)
        cache[key] = result
        return result

    @staticmethod
    def calculate_open(hand_counts: List[int], open_meld_count: int) -> int:
        """
        @title 副露手シャンテン数計算
        @description 副露が存在する場合の最小シャンテン数を計算し、スレッドローカルキャッシュに保存します。
        @param {List[int]} hand_counts - 手牌の34種牌カウント
        @param {int} open_meld_count - 副露数
        @returns {int} シャンテン数
        """
        key = (tuple(hand_counts), open_meld_count)
        cache = ShantenCalculator._get_cache()
        if key in cache:
            return cache[key]
        if open_meld_count >= 4:
            return -1
        result = ShantenCalculator._suit_shanten(hand_counts, open_meld_count)
        cache[key] = result
        return result

    @staticmethod
    def calculate_closed_effective(hand_counts: List[int]) -> int:
        """
        @title 門前有効シャンテン数計算
        @description 門前時の標準手・七対子・国士無双のうち最小の有効シャンテン数を計算し、スレッドローカルキャッシュに保存します。
        @param {List[int]} hand_counts - 手牌の34種牌カウント
        @returns {int} 最小の有効シャンテン数
        """
        key = (tuple(hand_counts), 'ce')
        cache = ShantenCalculator._get_cache()
        if key in cache:
            return cache[key]
        
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
                
        cache[key] = best
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
            # この牌に対する探索を終了し、残りをすべて孤立牌として次の牌に進みます。
            # 1枚ずつの再帰による指数爆発を防ぐため、一括で次のインデックスに進めます。
            orig = c[idx]
            c[idx] = 0
            dfs(idx + 1, melds, taatsu, pairs)
            c[idx] = orig

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
    def calculate_effective_blocks(hand_counts: List[int], open_meld_count: int = 0,
                                   honor_weight: float = 0.3, yaochu_weight: float = 0.5) -> float:
        """
        @title 有効ブロック数の算出（孤立牌を割引）
        @description 孤立字牌・孤立端牌のブロック価値を下げた実効ブロック数を返す。
        孤立字牌(1枚) = honor_weight ブロック、孤立端牌(1/9,隣接なし)=yaochu_weight ブロック。
        @param {List[int]} hand_counts - 34種牌カウント
        @param {int} open_meld_count - 副露数
        @param {float} honor_weight - 孤立字牌1枚あたりのブロック重み (0.0〜1.0)
        @param {float} yaochu_weight - 孤立端牌1枚あたりのブロック重み (0.0〜1.0)
        @returns {float} 実効ブロック数
        """
        raw = float(ShantenCalculator.calculate_blocks(hand_counts, open_meld_count))
        # 孤立字牌の割引: count==1 の字牌は honor_weight 分だけ価値が低い
        for c in hand_counts[27:34]:
            if c == 1:
                raw -= (1.0 - honor_weight)
        # 孤立端牌の割引: 1/9 で隣接牌がなく孤立している場合
        for i in range(0, 27, 9):
            # 1 (i+0)
            if hand_counts[i] == 1 and hand_counts[i+1] == 0:
                raw -= (1.0 - yaochu_weight)
            # 9 (i+8)
            if hand_counts[i+8] == 1 and hand_counts[i+7] == 0:
                raw -= (1.0 - yaochu_weight)
        return raw

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
        """
        @title 役判定初期化
        @description 各評価キャッシュ変数およびファジィ推論エンジンを初期化します。
        @param {GameState} state - 対局状態管理オブジェクト
        @param {dict} [params=None] - 設定パラメータ辞書
        """
        self.state = state
        self.params = params or {}
        from fuzzy_logic import FuzzyLogicEngine
        self.fuzzy_engine = FuzzyLogicEngine(self.params)
        
        # なぜこのようにするか：1回の打牌決定処理（Evaluator実行）の間はGameStateが変更されないため、
        # 評価関数を再帰的に何度も計算する際の重複処理を避け、評価速度を劇的に高速化するためです。
        self._opponent_threat_cache = None
        self._max_threat_with_reason_cache = None
        self._base_attack_cache = None
        self._yakuman_attack_boost_cache = None
        self._push_score_cache = None
        self._strategy_mode_cache = None
        self._deal_in_rate_cache = None
        self._win_rate_cache = None
        self._win_score_cache = None

    def compute_opponent_threat(self) -> float:
        """
        @title 最大脅威度の算出
        @description 各他家のリーチ・副露数・捨牌の手出し中張牌・ドラ/役牌の鳴き状況から脅威度を算出し、その最大値を返す。
        @returns {float} 最大脅威度 0.0〜1.0
        """
        if self._opponent_threat_cache is not None:
            return self._opponent_threat_cache
        max_threat, _ = self._max_threat_with_reason()
        self._opponent_threat_cache = max_threat
        return max_threat

    def _max_threat_with_reason(self) -> Tuple[float, str]:
        """
        @title 脅威度と理由テキストの同時算出
        @description 各他家の脅威度を計算し、最も高い脅威を持つ他家の脅威値と日本語理由テキストを返す。
        @returns {Tuple[float, str]} (最大脅威度, 理由テキスト)
        """
        if self._max_threat_with_reason_cache is not None:
            return self._max_threat_with_reason_cache
        best_value = self.params.get('BASE_THREAT', 0.0)
        best_reason = '他家に脅威なし'
        for i in range(4):
            if i == self.state.my_seat:
                continue
            value, reason = self._opponent_threat_for_seat(i)
            if value > best_value:
                best_value = value
                best_reason = reason
        self._max_threat_with_reason_cache = (best_value, best_reason)
        return self._max_threat_with_reason_cache

    def _get_visible_counts(self) -> List[int]:
        """
        @title 見えている牌のカウント
        @description 自家の手牌、全プレイヤーの捨牌、全副露、およびドラ表示牌から、各牌（0〜33）の自分の目から見えている枚数をカウントします。
        @returns {List[int]} 各牌の露出枚数配列（サイズ34）
        """
        from str_converter import tile_to_id
        counts = [0] * 34
        # 自家の手牌
        for t in self.state.my_hand:
            try:
                counts[tile_to_id(t)] += 1
            except Exception:
                pass
        # 全プレイヤーの捨牌
        for s in range(4):
            for t in self.state.river[s]:
                try:
                    counts[tile_to_id(t)] += 1
                except Exception:
                    pass
        # 全プレイヤーの副露
        for s in range(4):
            for m in self.state.melds[s]:
                for t in m.tiles:
                    try:
                        counts[tile_to_id(t)] += 1
                    except Exception:
                        pass
        # ドラ表示牌
        for d in self.state.doras:
            try:
                counts[tile_to_id(d)] += 1
            except Exception:
                pass
        return counts

    def _opponent_threat_for_seat(self, seat: int) -> Tuple[float, str]:
        """
        @title 各プレイヤーの脅威度算出
        @description 期待打点 A, 有効枚数 U, 向聴数 S から他家の脅威度 V = (A * U) / (S + 1) を算出します。
                     フリテン現物や安全牌の残り枚数に応じて有効枚数 U を減衰させ、放銃リスクを反映させます。
        @param {int} seat - 対象プレイヤーの座席インデックス
        @returns {Tuple[float, str]} (脅威度 0.0〜1.0, 理由テキスト)
        """
        seat_name = self.SEAT_NAMES[seat] if 0 <= seat < 4 else f'Player {seat}'
        
        # 1. ベタオリしている他家はアガリを目指していないため脅威度を 0 にする
        if self._is_betaori(seat):
            return self.params.get('BASE_THREAT', 0.0), f'{seat_name}: ベタオリ中（脅威低）'

        # 2. 役満脅威度のチェック
        yakuman_threat = self._yakuman_threat_for_seat(seat)
        if yakuman_threat > 0.3:
            return yakuman_threat, f'{seat_name}: 役満警戒（脅威度 {yakuman_threat:.2f}）'

        # 各種情報の取得
        is_reach = self.state.reach_states[seat].is_reach
        open_melds = [m for m in self.state.melds[seat] if m.is_open]
        n_open = len(open_melds)
        tsumo = (self.state.tsumo_count - 1) // 4 + 1

        # 3. 推定向聴数 S
        # 3副露はテンパイ(S=0)、2副露は1向聴(S=1)、1副露は2向聴(S=2)をベースに、
        # 巡目が進む（10巡目、15巡目など）と向聴数が減少してテンパイに近づく（加速）ようにモデル化
        if is_reach:
            S = 0
        elif n_open >= 3:
            S = 0
        elif n_open == 2:
            S = 0 if tsumo >= 10 else 1
        elif n_open == 1:
            if tsumo >= 15:
                S = 0
            elif tsumo >= 10:
                S = 1
            else:
                S = 2
        else:  # 門前ダマ
            if tsumo >= 13:
                S = 1
            elif tsumo >= 7:
                S = 2
            else:
                S = 3

        # 4. 推定期待飜数 H と期待打点 A (点数)
        # 役牌・ドラ・染め手の露出状況から打点を推定。親の場合は打点が1.5倍になるため脅威度も上がる。
        is_dealer = (getattr(self.state, 'dealer_seat', 0) == seat)
        
        if is_reach:
            H = 3  # リーチ + 平均2飜
            reason_detail = "リーチ"
        elif n_open > 0:
            H = 1  # 基礎1飜
            
            # 役牌ポン数のカウント
            dealer_seat = getattr(self.state, 'dealer_seat', 0)
            bakaze_id = 27 + (self.state.chang % 4)
            jikaze_id = 27 + ((seat - dealer_seat) % 4)
            yakuhai_ids = {31, 32, 33, bakaze_id, jikaze_id}
            
            from str_converter import tile_to_id
            yakuhai_count = 0
            dora_count = 0
            for m in open_melds:
                if m.type in ('cpg', 'minggang', 'ankan', 'kankan') and len(m.tiles) >= 3:
                    try:
                        tid = tile_to_id(m.tiles[0])
                        if tid in yakuhai_ids:
                            yakuhai_count += 1
                    except Exception:
                        pass
                for t in m.tiles:
                    try:
                        tid = tile_to_id(t)
                        dora_ids = {tile_to_id(d) for d in self.state.actual_doras}
                        if tid in dora_ids:
                            dora_count += 1
                        if t.startswith('0'):
                            dora_count += 1
                    except Exception:
                        pass
            
            H += yakuhai_count + dora_count

            # 染め手（ホンイツ・チンイツ）の簡易判定
            is_flush = False
            # Why: 1副露だけでは手牌が染まっているか判別不能なため、2副露以上（n_open >= 2）を条件とする。
            if n_open >= 2:
                suits = set()
                has_honors = False
                num_tiles_count = 0
                for m in open_melds:
                    for t in m.tiles:
                        try:
                            tid = tile_to_id(t)
                            if tid >= 27:
                                has_honors = True
                            else:
                                suits.add(t[1] if len(t) >= 2 else t[0])
                                num_tiles_count += 1
                        except Exception:
                            pass

                # 数牌が1つのスートだけで構成されている場合
                if len(suits) == 1 and num_tiles_count >= 3:
                    flush_suit = list(suits)[0]
                    # 他家の河（捨牌）をチェック。染め手スートの牌が何枚切られているか
                    river_suit_count = 0
                    for t in self.state.river[seat]:
                        try:
                            tid = tile_to_id(t)
                            if tid < 27 and t[1] == flush_suit:
                                river_suit_count += 1
                        except Exception:
                            pass
                    # Why: 染め手スートが2枚以上（2は閾値）切られていない場合のみ、染め手（ flush ）とみなす
                    if river_suit_count < 2:
                        is_flush = True
            
            if is_flush:
                if has_honors:
                    H += 2  # ホンイツの2飜
                else:
                    H += 3  # チンイツへの移行期（安全のため3飜に抑える）

            reason_detail = f"{n_open}副露(飜数:{H})"
        else:  # 門前ダマ
            H = 3 if tsumo >= 10 else 2
            reason_detail = "門前"

        # 推定飜数 H から期待打点 A (点数) を算出 (麻雀の得点計算に準拠)
        if H <= 4:
            A = 1000 * (2 ** H)
        elif H == 5:
            A = 8000
        elif H in (6, 7):
            A = 12000
        elif H in (8, 9, 10):
            A = 16000
        else:
            A = 24000

        # 親なら打点1.5倍
        if is_dealer:
            A = int(A * 1.5)

        # 5. 実質有効枚数 U の計算
        # シャンテン数 S に応じた基礎枚数。テンパイなら平均待ち枚数の 6 枚とする。
        U_base_map = {0: 6, 1: 12, 2: 18, 3: 24}
        U_base = U_base_map.get(S, 24)

        # Why: 以前は相手の河にある安全牌の残り割合（safe_ratio）で有効枚数 U を減衰させていましたが、
        # これにより巡目が進む（河が長くなる）につれて相手の脅威度 V が極端に低下する問題が発生していました。
        # 相手がテンパイしている場合の危険度（無筋を通すリスク）は巡目が進んでも低下しないため、
        # 一般的な他家全体の脅威度としては減衰させず、基礎枚数 U_base をそのまま使用します。
        # 個別の牌の安全度評価は Evaluator 側の v_defense（ベタオリ安全度スコア）で別途処理されます。
        U = U_base

        # 6. 期待値 V の計算
        V = (A * U) / (S + 1)

        # 7. 正規化して脅威度（0.0〜1.0）を算出
        # 子の満貫テンパイ基準値 (V_max = 48000.0) を目安に正規化
        # Why: 48000.0は子の満貫テンパイ（打点8000 * 有効枚数6）時の期待値 V です。
        V_max = self.params.get('THREAT_V_MAX', 48000.0)
        value = min(1.0, V / V_max)

        # Why: 0巡目（あるいは序盤で他家の河に捨て牌がない段階）では他家の手牌情報が完全にゼロ。
        # この状態で「平均的な手」の脅威を仮定すると、序盤の判断を誤らせる。
        # 河に捨牌が1枚もない = その家から何の情報も得ていない、という意味なので
        # 脅威度は 0 にする (BASE_THREAT もそのまま返す)。
        if not is_reach and n_open == 0 and len(self.state.river[seat]) == 0:
            return self.params.get('BASE_THREAT', 0.0), f'{seat_name}: 序盤・情報なし (脅威ゼロ)'

        # 門前ダマテンの場合は、警戒されにくいためダマテン警戒係数を掛けて減衰させる
        # ただし高ダマテン率プレイヤーはダマテンでも積極的にアガりに来るため、減衰率を緩和する
        if not is_reach and n_open == 0:
            base_dama = self.params.get('THREAT_DAMA_SCALE', 0.15)
            pstats = self.state.player_stats.get(str(seat), {})
            p_damaten = pstats.get("damaten_rate", self.params.get('OPPONENT_DEFAULT_DAMATEN_RATE', 0.15))
            default_damaten = self.params.get('OPPONENT_DEFAULT_DAMATEN_RATE', 0.15)
            # デフォルト値と同じなら従来通りの減衰、高いほど減衰緩和（最大1.0）
            dama_scale = min(1.0, base_dama * (p_damaten / max(default_damaten, 0.01)))
            value = value * dama_scale

        reason = f"{seat_name}: {reason_detail} (打点:{A}, 向聴:{S}, 有効枚:{U:.1f}) = {value:.2f}"
        return value, reason

    def _is_betaori(self, seat: int) -> bool:
        """
        @title 他家のベタオリ（オリ）状態判定
        @description 直近の捨牌の安全度とツモ切り率から、他家が降りているかを判定します。
        @param {int} seat - 対象プレイヤーの座席インデックス
        @returns {bool} ベタオリ状態であれば True
        """
        # Why: 自身がリーチしている場合は、アガリを目指して全ツッパ中（またはツモ切り）であり、オリではないため即座に False を返す
        if self.state.reach_states[seat].is_reach:
            return False

        # Why: 自分以外のリーチ者を対象とし、自身（seat）に対する自己参照バグを防ぐため i != seat とする。また、自分がリーチしている場合に他家が自分に対して降りている場合も考慮するため、my_seat を除外しない
        reach_seats = [i for i in range(4) if i != seat and self.state.reach_states[i].is_reach]
        river = self.state.river[seat]
        # Why: 捨牌が3枚未満の序盤ではオリ判定を行わないための安全ガード値 3
        if len(river) < 3:
            return False
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        from str_converter import tile_to_id, is_honor
        betaori_count = 0
        
        # Why: 直近5枚の捨牌（5は分析対象とする直近手数）の安全性をチェックする
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
                
        # Why: 直近5枚（またはそれ以下）のうち、ツモ切りまたは現物安全牌を捨てた割合を計算
        recent = min(5, len(river) - max(0, len(river) - 5))
        if recent == 0:
            return False
        # Why: 80%以上（0.8）が安牌またはツモ切りであれば、オリていると判定する
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

    def estimate_deal_in_rate(self) -> float:
        """
        @title 放銃率推定
        @description 自分の捨牌・ドラ表示牌・見えてる牌から、自分のツモ牌が
                    他家の和了牌になる確率を推定する。
                    1. 各牌の残り枚数を見る
                    2. 自分の捨牌に含まれている牌 (字牌・中張牌) は安全度が高い
                    3. 見えてない牌 (ノベリスク?) は危険度が高い
                    4. 相手のリーチ状態は脅威度を上げる
        @returns {float} 推定放銃率 (0.0〜1.0, 1 ツモあたりの確率)
        """
        if self._deal_in_rate_cache is not None:
            return self._deal_in_rate_cache

        from str_converter import tile_to_id
        visible = self._get_visible_counts()
        # 残り枚数
        remaining = [max(0, 4 - visible[i]) for i in range(34)]
        total_remaining = sum(remaining)
        if total_remaining == 0:
            self._deal_in_rate_cache = 0.0
            return 0.0

        # 各牌の危険度
        # - 字牌 (id 27-33): 中程度
        # - 端牌 (id 0, 8, 9, 17, 18, 26): 中
        # - 中張牌 (id 1-7, 10-16, 19-25): 高
        # さらに ドラ/裏ドラ 候補は超高
        danger = [0.0] * 34
        for i in range(34):
            if visible[i] >= 4:
                continue  # 0 枚残りなのでスキップ
            base_danger = 0.10
            if 27 <= i <= 33:
                base_danger = 0.08  # 字牌
            elif i % 9 == 0 or i % 9 == 8:
                base_danger = 0.06  # 端牌
            else:
                base_danger = 0.12  # 中張牌

            # ドラ表示牌ボーナス
            try:
                for d in self.state.actual_doras:
                    if tile_to_id(d) == i:
                        base_danger *= 1.5
            except Exception:
                pass
            danger[i] = base_danger

        # 自分と他家の合計危険度
        total_danger = sum(danger[i] * remaining[i] for i in range(34) if remaining[i] > 0)
        # 1 ツモあたりの放銃率 (概算): total_danger / total_remaining
        base_deal_in = total_danger / max(1, total_remaining)
        # リーチしている相手がいれば脅威UP
        n_reach = sum(1 for s in range(4) if s != self.state.my_seat and self.state.reach_states[s].is_reach)
        if n_reach >= 1:
            # リーチ中は待ちが絞られているので放銃率UP
            base_deal_in *= 1.5 + 0.3 * (n_reach - 1)
        # 副露している相手が多いほど待ちが広いので放銃率UP
        n_open = sum(1 for s in range(4) if s != self.state.my_seat for m in self.state.melds[s] if m.is_open)
        if n_open >= 1:
            base_deal_in *= 1.0 + 0.1 * n_open

        # 巡目が浅い (序盤) なら放銃率低め
        tsumo = (self.state.tsumo_count - 1) // 4 + 1
        if tsumo <= 6:
            base_deal_in *= 0.7
        elif tsumo <= 12:
            base_deal_in *= 1.0
        else:
            base_deal_in *= 1.2

        # 自分の手牌の安全度 (字牌・端牌多めなら放銃率低め)
        hand = self.state.my_hand
        honor_count = sum(1 for t in hand if 27 <= tile_to_id(t) <= 33)
        edge_count = sum(1 for t in hand if tile_to_id(t) % 9 in (0, 8))
        if honor_count + edge_count >= 5:
            base_deal_in *= 0.85

        res = max(0.0, min(0.5, base_deal_in))  # 0.5 で頭打ち
        self._deal_in_rate_cache = res
        return res

    def estimate_win_rate(self) -> float:
        """
        @title 和了率推定
        @description 自分の受け入れ枚数・待ちの質・巡目から和了率を推定する。
        @returns {float} 推定和了率 (0.0〜1.0, 残り巡目で和了する確率)
        """
        if self._win_rate_cache is not None:
            return self._win_rate_cache

        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_meld_count)

        if shanten <= 0:
            # テンパイ: 残り巡目で和了する確率
            wait_tiles = self._wait_tiles_for_tenpai() if hasattr(self, '_wait_tiles_for_tenpai') else None
            if not wait_tiles:
                # 受け入れ枚数を再計算
                wait_tiles = []
                visible = self._get_visible_counts()
                for tid in range(34):
                    if hand_counts[tid] >= 4:
                        continue
                    test = list(hand_counts)
                    test[tid] += 1
                    if open_meld_count == 0:
                        ns = ShantenCalculator.calculate_closed_effective(test)
                    else:
                        ns = ShantenCalculator.calculate_open(test, open_meld_count)
                    if ns >= 0:
                        continue
                    wait_tiles.append(tid)

            visible = self._get_visible_counts()
            total_remaining = sum(max(0, 4 - visible[t]) for t in wait_tiles)
            left_tiles = max(1, self.state.left_tile_count)
            # 1 ツモで和了確率
            one_draw = total_remaining / (4 * 13)  # 概算: 残り牌に対する受け入れ
            # 残り巡数 (1 局最大 18 巡 = 70 牌)
            max_draws = max(0, left_tiles)
            # 1 ツモで和了しない確率
            not_win_one = max(0.0, 1.0 - one_draw)
            res = 1.0 - (not_win_one ** max_draws)
        else:
            # 1 巡前に向聴数が下がる確率 (概算)
            avg_improve = 1.0 / (shanten * 4 + 4)
            tsumo = (self.state.tsumo_count - 1) // 4 + 1
            left_tiles = max(0, self.state.left_tile_count)
            # 数巡後にテンパイする確率
            res = avg_improve * left_tiles / 14.0  # 概算

        res = max(0.0, min(0.95, res))
        self._win_rate_cache = res
        return res

    def estimate_win_score(self) -> int:
        """
        @title 和了打点推定
        @description 自分の手牌の打点を推定 (符 + 飜数 × ベース)
        @returns {int} 推定打点 (親ロン 3900-32000 程度)
        """
        if self._win_score_cache is not None:
            return self._win_score_cache
        try:
            from hand_value import estimate_han_advanced, estimate_win_score
            han = estimate_han_advanced(
                self.state.my_hand, self.state.my_melds, self.state.doras,
                is_open=any(m.is_open for m in self.state.my_melds),
                has_reach=any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat),
                is_ippatsu=False, is_tsumo=False,
                seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju
            )
            han = max(han, 1)
            is_dealer = self.state.my_seat == 0
            score = estimate_win_score(han, 30, is_dealer)
        except Exception:
            score = 8000  # デフォルト mangan
        self._win_score_cache = score
        return score

    def calculate_push_fold_ev(self) -> Tuple[float, float, float]:
        """
        @title 押し/オリ EV 計算
        @description 押す場合とオリる場合の EV を比較し、押し寄り度 (push_lean, -1.0〜+1.0) を返す。
                    push_lean > 0 なら押す、< 0 ならオリる。
                    push_ev: 押した場合の EV
                    fold_ev: オリった場合の EV
        @returns {Tuple[float, float, float]} (push_ev, fold_ev, push_lean)
        """
        win_rate = self.estimate_win_rate()
        win_score = self.estimate_win_score()
        deal_in_rate = self.estimate_deal_in_rate()
        # 放銃時の失点 (他家による)
        # ロンはロンされた点数、ツモはロン+α
        loss_score = max(1000, win_score - 2000)  # 自分より少し低い

        push_ev = win_rate * win_score - deal_in_rate * loss_score
        # オリEV: 放銃を避けると、放銃確率分だけ得する
        fold_ev = 0 - deal_in_rate * loss_score * 0.3  # 完全オリれば放銃率は下がるが残り
        # 比較
        push_lean = (push_ev - fold_ev) / max(1, win_score)
        return push_ev, fold_ev, max(-1.0, min(1.0, push_lean))

    def compute_base_attack(self) -> float:
        """
        @title 基礎攻撃度の算出
        @description 自家的シャンテン数や手牌ブロック数、役満可能性から基礎攻撃度を算出します。
                  副露（鳴き）で確定済みの飜数も考慮します（既に2飜あるなら攻め継続の判断材料）。
        @returns {float} 基礎攻撃度 (0.0〜1.0)
        """
        if self._base_attack_cache is not None:
            return self._base_attack_cache
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        if shanten <= -1:
            han = self._estimate_han()
            if han >= 5:
                res = self.params.get('BASE_ATTACK_TENPAI_HIGH', 1.0)
            else:
                res = self.params.get('BASE_ATTACK_TENPAI_LOW', 0.7)
            self._base_attack_cache = res
            return res
        if shanten == 0:
            res = self.params.get('BASE_ATTACK_TENPAI_LOW', 0.7)
            self._base_attack_cache = res
            return res
        if shanten == 1:
            base_val = self.params.get('BASE_ATTACK_1SHANTEN', 0.4)
            blocks = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
            block_factor = max(0.0, min(1.0, (blocks - 4) / 3.0))
            han = self._estimate_han()
            score_factor = min(1.0, max(0.0, (han - 1) / 4.0))
            speed_score = block_factor / (shanten + 1.0)
            quality_boost = score_factor * speed_score * 0.15
            res = max(0.01, min(base_val + quality_boost, base_val * 1.3))
            # 副露の確定飜数ブースト
            res = self._apply_open_meld_boost(res, open_meld_count, shanten)
            self._base_attack_cache = res
            return res
        max_shanten = self.params.get('BASE_ATTACK_MAX_SHANTEN', 6)
        if shanten >= 2:
            if shanten > max_shanten:
                self._base_attack_cache = 0.0
                return 0.0

            default_val = 0.4 * (0.5 ** (shanten - 1))
            param_key = f'BASE_ATTACK_{shanten}SHANTEN'
            base_val = self.params.get(param_key, default_val)

            blocks = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
            block_factor = max(0.0, min(1.0, (blocks - 4) / 3.0))

            han = self._estimate_han()
            score_factor = min(1.0, max(0.0, (han - 1) / 4.0))
            speed_score = block_factor / (shanten + 1.0)
            quality_boost = score_factor * speed_score * 0.3

            base_res = max(0.01, min(base_val * block_factor + quality_boost, base_val * 2))

            # 染め手/四喜和ブースト: 字牌が大量に手牌にあれば染め手/四喜和狙い。
            honor_count = sum(hand_counts[i] for i in range(27, 34))
            honitsu_th = self.params.get('HONITSU_BOOST_THRESH', 7)
            shusuushi_th = self.params.get('SHUSUUSHI_BOOST_THRESH', 8)
            yaku_boost = 0.0
            if honor_count >= honitsu_th:
                yaku_boost = min(0.25, 0.05 * (honor_count - honitsu_th + 1))
            wind_count = sum(hand_counts[i] for i in range(27, 31))
            if wind_count >= shusuushi_th:
                yaku_boost = min(0.4, yaku_boost + 0.05 * (wind_count - shusuushi_th + 1))
            base_res = min(1.0, base_res + yaku_boost)

            # 副露の確定飜数ブースト
            base_res = self._apply_open_meld_boost(base_res, open_meld_count, shanten)
            self._base_attack_cache = base_res
            return base_res

        # 役満攻撃ブースト
        yakuman_boost = self._yakuman_attack_boost()
        if yakuman_boost > 0:
            res = min(1.0, yakuman_boost)
            self._base_attack_cache = res
            return res

        self._base_attack_cache = 0.0
        return 0.0

    def _apply_open_meld_boost(self, base_res: float, open_meld_count: int, shanten: int) -> float:
        # Why: 副露で確定済みの飜数（役牌・三元牌など）は「もう確保した打点」。
        #      手牌が遠い状態でも、攻め継続の手がかりとして基礎攻撃度に加算する。
        #      例: 2向聴で副露2飜確定 → base_attack を底上げして「危険度勝負」判定を出しやすくする。
        if open_meld_count == 0:
            return base_res
        # 副露1組ごとに +0.15（最大 0.45 まで）
        meld_boost = min(0.45, 0.15 * open_meld_count)
        # シャンテン数が多いほどブーストを控えめに（遠い手は加点しても仕方ない）
        if shanten >= 2:
            meld_boost *= 0.6
        return min(1.0, base_res + meld_boost)

    def _yakuman_attack_boost(self) -> float:
        """
        @title 役満攻撃ブースト
        @description 役満進行度が高い場合、攻撃度を引き上げる。
                  他家が脅威の場合はブーストしない。
        @returns {float} 攻撃ブースト値（0.0〜1.0）
        """
        if self._yakuman_attack_boost_cache is not None:
            return self._yakuman_attack_boost_cache
        from yakuman_evaluator import YakumanEvaluator

        # パラメータ読み込み
        yakuman_cfg = self.params.get('yakuman_strategy', {})
        min_shanten = yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2)
        defense_threshold = yakuman_cfg.get('YAKUMAN_ATTACK_BOOST_DEFENSE_THRESHOLD', 0.5)

        # 他家脅威度チェック: 高い場合はブーストしない
        # 注意: compute_opponent_threat()は循環呼び出しを避けるため直接呼ばない
        threat, _ = self._max_threat_with_reason()
        if threat > defense_threshold:
            self._yakuman_attack_boost_cache = 0.0
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

        res = min(1.0, max_boost)
        self._yakuman_attack_boost_cache = res
        return res

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
        """
        @title 押し引きスコアの計算
        @description 基礎攻撃度と他家脅威度のバランス、および順位などの補正を加えて総合的な押し引きスコアを計算します。
        @returns {float} 押し引きスコア (0.0〜1.0)
        """
        if self._push_score_cache is not None:
            return self._push_score_cache
        a_base = self.compute_base_attack()
        t_max = self.compute_opponent_threat_with_reach_boost()
        if t_max <= 0.0:
            hand_counts = self.state.my_hand_counts()
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            if open_meld_count == 0:
                shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
            else:
                shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
            if shanten >= 3:
                res = max(a_base, 0.3)
                self._push_score_cache = res
                return res
            self._push_score_cache = 1.0
            return 1.0
        push_score = a_base * (1.0 - t_max)
        # --- 人読み: リーチ押し引き補正 ---
        push_score = self._apply_player_stats_riichi_adjust(push_score)
        push_score = self._apply_position_override(push_score)
        # 人間例外: 4位(ラス回避)+テンパイは押す
        # ただし2リーチ以上はオリる
        n_reach = sum(1 for s in range(4) if s != self.state.my_seat and self.state.reach_states[s].is_reach)
        if n_reach >= 1:
            hand_counts = self.state.my_hand_counts()
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_meld_count)
            rank = self.state.my_score_rank()
            if rank == 3 and shanten <= 0:
                if n_reach >= 2:
                    push_score = min(push_score, 0.02)
                else:
                    push_score = max(push_score, 0.75)
            elif rank == 3 and shanten == 1:
                if n_reach >= 2:
                    push_score = min(push_score, 0.02)
                else:
                    push_score = max(push_score, 0.4)
            else:
                # 人間データ分析: 1-リーチ+1シャンテン+非4位で人間は53%オリる
                # 終盤の position override (1-シャンテン max 0.5) を抑制
                if shanten >= 1:
                    reach_penalty = self.params.get('REACH_PENALTY_NON4', 0.35) * n_reach
                    push_score = max(0.0, push_score - reach_penalty)
        res = max(0.0, min(1.0, push_score))
        self._push_score_cache = res
        return res

    def compute_opponent_threat_with_reach_boost(self) -> float:
        """
        @title 対家リーチ脅威度をブーストした最大脅威度
        @description 対家にリーチ者がいる場合、脅威度をブーストして
                    ファジィ推論が「高脅威」側(Y低/X高)に倒れるようにする。
                    人間はリーチ時に97%オリる → ファジィの X軸を「高」側に
                    強く振る → 「完全撤退」「回し打ち」「危険度勝負」のいずれかが選択される。
        @returns {float} ブースト済み最大脅威度 (0.0〜1.0)
        """
        t_max = self.compute_opponent_threat()
        n_reach = sum(1 for s in range(4) if s != self.state.my_seat and self.state.reach_states[s].is_reach)
        if n_reach >= 1:
            # 1リーチ: X軸高(0.65)に持っていく
            # 2リーチ+: より強く(0.85)
            if n_reach >= 2:
                boosted = max(t_max, 0.85)
            else:
                boosted = max(t_max, 0.70)
            return min(1.0, boosted)
        return t_max

    def _apply_player_stats_riichi_adjust(self, push_score: float) -> float:
        player_stats = self.state.player_stats or {}
        adjust = 0.0
        for s in range(4):
            if s == self.state.my_seat:
                continue
            if not self.state.reach_states[s].is_reach:
                continue
            pstats = player_stats.get(str(s), {})
            deal_in_rate = pstats.get("deal_in_rate", self.params.get('OPPONENT_DEFAULT_DEAL_IN_RATE', 0.12))
            riichi_rate = pstats.get("riichi_rate", self.params.get('OPPONENT_DEFAULT_RIICHI_RATE', 0.20))
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

    def tile_class_push_bias(self, tile: str) -> float:
        """
        @title 牌分類による押し/オリバイアス
        @description 天鳳人間ログから導かれたルール:
                  字牌を切る = 押す判断(自分の弱い牌を処分しつつ安全に進める)
                  中張牌を切る = オリる判断(安全牌を通す)
                  端牌を切る = 中間(状況次第)
                  人間データ: 字牌切りの100%が押す、中張切りの100%がオリる。
                  染め手進行中は字牌切り傾向がさらに強まる(3-4シャン 41-46%)。
        @param {str} tile - 切る牌
        @returns {float} 押しバイアス(正=押し寄り、負=オリ寄り)
        """
        from str_converter import tile_to_id as t2id
        is_honor_tile = is_honor(t2id(tile))
        is_terminal_tile = tile[0] in ('1', '9')

        # 染め手進行中(主力色7枚以上 + 3-4シャンテン): 字牌切りバイアスを強化
        # 人間は字牌を切って染め手を積極的に完成させる
        dye_bonus_active = False
        try:
            hand = self.state.my_hand
            if hand:
                counts = hand_to_counts(hand)
                suits_count = [sum(counts[i:i+9]) for i in (0, 9, 18)]
                max_suit = max(suits_count)
                open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
                if open_meld_count == 0:
                    sh = ShantenCalculator.calculate_closed_effective(counts)
                else:
                    sh = ShantenCalculator.calculate_open(counts, open_meld_count)
                if max_suit >= 7 and sh >= 3:
                    dye_bonus_active = True
        except Exception:
            pass

        if is_honor_tile:
            base_bias = self.params.get('PUSH_SAFE_TILES_BONUS', 0.3)
            if dye_bonus_active:
                # 染め手進行中: 字牌を切る = 手を進めつつオリる (中間押しの強化)
                base_bias = self.params.get('DYE_HONOR_PUSH_BONUS', 0.45)
            return base_bias
        elif is_terminal_tile:
            return self.params.get('TERMINAL_TILE_PUSH_BONUS', 0.15)
        else:
            return -self.params.get('FOLD_SAFE_TILES_BONUS', 0.3)

    def is_high_hand_value_first_turn(self) -> bool:
        base_attack = self.compute_base_attack()
        y_low, y_med, y_high = self.fuzzy_engine.get_y_membership(base_attack)
        return y_med > y_low or y_high > y_low

    def is_orya_ori_mode(self) -> bool:
        return self.compute_push_score() <= 0.05

    def is_zenchi_mode(self) -> bool:
        if not self.state.is_last_round():
            return False
        return self.state.my_score_rank() == 3

    def is_meld_open_allowed(self) -> bool:
        # Why: 「完全撤退」「撤退準備」の極度の守備フェーズでは、副露を完全に禁止します。
        #      「スリム化」では手を進める余地があるため、副露は許可する（玉座の間スタッツでは
        #      副露率 31-33% が望ましいため、様子見でも鳴けるようにする）。
        mode = self.get_strategy_mode()
        if mode in ("完全撤退", "撤退準備"):
            return False

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
        """
        @title 戦略モードの取得(ファジィ推論ベース)
        @description 押し引きスコア、攻撃度、脅威度から決定される最終的な戦略モードを返します。
                  人間は「牌タイプ選択」と「モード選択」を統合的に行うため、
                  ここではファジィマトリクスでモードを決定し、牌選択レベルは
                  evaluator.tile_class_push_bias() で別途調整する。
                  対家リーチ時は脅威度をブーストしてファジィで「高脅威」側を強制する。
        @returns {str} 戦略モード（例: '全力攻撃', '完全撤退' など）
        """
        if self._strategy_mode_cache is not None:
            return self._strategy_mode_cache

        # 前方全押し(全ツッパ)モード: 終盤4位+残り僅か → 例外
        if self.is_zenchi_mode():
            self._strategy_mode_cache = "全力攻撃"
            return "全力攻撃"

        push = self.compute_push_score()

        # 人間例外: 4位+テンパイ → 押す(対家1リーチのみ)
        n_reach = sum(1 for s in range(4) if s != self.state.my_seat and self.state.reach_states[s].is_reach)
        if n_reach >= 1:
            hand_counts = self.state.my_hand_counts()
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_meld_count)
            rank = self.state.my_score_rank()
            if rank == 3 and shanten <= 0 and n_reach < 2:
                # 4位テンパイ + 1リーチのみ → 全力攻撃(押す)
                self._strategy_mode_cache = "全力攻撃"
                return "全力攻撃"
            elif rank == 3 and shanten == 1 and n_reach < 2:
                # 4位1シャンテン + 1リーチのみ → 押し気味
                self._strategy_mode_cache = "押し気味"
                return "押し気味"

        # ベース攻撃度 + 脅威度(リーチ時はブースト済み)でファジィ評価
        base_attack = self.compute_base_attack()
        max_threat = self.compute_opponent_threat_with_reach_boost()

        # Why (revert): 位置戦略を全て削除。gene_0 と相性が悪い。
        # 4位 + リーチ時の特殊処理 (is_zenchi_mode / 人間例外) はそのまま有効。

        # ファジィ推論: X軸 = 脅威度(リーチ時0.70+), Y軸 = 攻撃度
        mode, _ = self.fuzzy_engine.evaluate_strategy(base_attack, max_threat)

        # push_score が極端に低い場合(オリ寄り)、ファジィの結果を「完全撤退」に上書き
        # 人間は 0.05 以下で「オリ判断」を示す
        # Why: 4向聴など攻撃度が低い状況では BASE_ATTACK が 0.04 程度になり、脅威が低くても
        # オリ閾値を下回ってしまう。脅威がないのに完全撤退になると手効率が破綻するため、
        # 脅威が一定以上ある時のみ「完全撤退」を強制する。
        # ただし、テンパイ手 (shanten <= 0) はもう待つだけなのでオリる選択肢がない。
        # 危険度勝負で押し (待ちを当てる) のが正しい。
        betaori_th = self.params.get('MODE_BETAORI_THRESHOLD', 0.05)
        betaori_threat_th = self.params.get('MODE_BETAORI_THREAT_THRESHOLD', 0.3)
        hand_counts_for_shanten = self.state.my_hand_counts()
        open_meld_count_for_shanten = sum(1 for m in self.state.my_melds if m.is_open)
        current_shanten = ShantenCalculator.calculate_closed_effective(hand_counts_for_shanten) if open_meld_count_for_shanten == 0 else ShantenCalculator.calculate_open(hand_counts_for_shanten, open_meld_count_for_shanten)
        if push <= betaori_th and max_threat >= betaori_threat_th and current_shanten > 0:
            mode = "完全撤退"

        # push_score が低い(= 0.25以下)場合は「撤退準備」を維持(ファジィの結果より優先)
        # ただし脅威が極めて低い(=序盤で何も動いていない)場合は回し打ちに留める
        # テンパイ手は 危険度勝負 を維持 (オリてもアガリがないので)
        retreat_th = self.params.get('MODE_RETREAT_PREP_THRESHOLD', 0.25)
        retreat_threat_th = self.params.get('MODE_RETREAT_THREAT_THRESHOLD', 0.15)
        if push <= retreat_th and mode not in ("完全撤退", "撤退準備") and current_shanten > 0:
            if max_threat >= retreat_threat_th:
                mode = "撤退準備"
            # else: ファジィの結果（回し打ち/スリム化など）を維持

        self._strategy_mode_cache = mode
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
            "fuzzy_scores": {k: round(v, 3) for k, v in scores.items()},
            # Why: フロントエンド側でマトリクスの境界位置とドット描画位置の双方に
            # 同じ閾値を使うことで、視覚的な整合性（境界 = ファジィ遷移点）を保証する。
            # MED-HIGH 境界は membership function の交点（MED=HIGH となる点）を解析的に解いた値。
            # これによりドットが必ず active セル内に収まる。
            "fuzzy_thresholds": self.fuzzy_engine.get_cell_boundaries()
        }
