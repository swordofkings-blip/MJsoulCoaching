# -*- coding: utf-8 -*-
"""
@title ver.2 シャンテン計算
@description ver.1 の ShantenCalculator を移植。
              スレッドローカルキャッシュ + lru_cache で性能維持。
"""
from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple, Set
import threading


class ShantenCalculatorV2:
    _thread_local = threading.local()

    @staticmethod
    def _get_cache() -> dict:
        if not hasattr(ShantenCalculatorV2._thread_local, 'cache'):
            ShantenCalculatorV2._thread_local.cache = {}
        return ShantenCalculatorV2._thread_local.cache

    @staticmethod
    def clear_cache():
        ShantenCalculatorV2._get_cache().clear()

    @staticmethod
    def calculate_standard(hand_counts: List[int]) -> int:
        key = (tuple(hand_counts), 's')
        cache = ShantenCalculatorV2._get_cache()
        if key in cache:
            return cache[key]
        result = ShantenCalculatorV2._suit_shanten(hand_counts, 0)
        cache[key] = result
        return result

    @staticmethod
    def calculate_closed(hand_counts: List[int]) -> int:
        key = (tuple(hand_counts), 'c')
        cache = ShantenCalculatorV2._get_cache()
        if key in cache:
            return cache[key]
        std = ShantenCalculatorV2._suit_shanten(hand_counts, 0)
        chiitoi = ShantenCalculatorV2._chiitoitsu_shanten(hand_counts)
        kokushi = ShantenCalculatorV2._kokushi_shanten(hand_counts)
        result = min(std, chiitoi, kokushi)
        cache[key] = result
        return result

    @staticmethod
    def calculate_open(hand_counts: List[int], open_meld_count: int) -> int:
        key = (tuple(hand_counts), open_meld_count)
        cache = ShantenCalculatorV2._get_cache()
        if key in cache:
            return cache[key]
        if open_meld_count >= 4:
            return -1
        result = ShantenCalculatorV2._suit_shanten(hand_counts, open_meld_count)
        cache[key] = result
        return result

    @staticmethod
    def calculate_closed_effective(hand_counts: List[int]) -> int:
        key = (tuple(hand_counts), 'ce')
        cache = ShantenCalculatorV2._get_cache()
        if key in cache:
            return cache[key]
        std = ShantenCalculatorV2._suit_shanten(hand_counts, 0)
        pairs = sum(1 for c in hand_counts if c >= 2)
        yaochu_indices = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        yaochu_types = sum(1 for i in yaochu_indices if hand_counts[i] >= 1)
        best = std
        if pairs >= 4:
            chiitoi = ShantenCalculatorV2._chiitoitsu_shanten(hand_counts)
            if chiitoi < best:
                best = chiitoi
        if yaochu_types >= 9:
            kokushi = ShantenCalculatorV2._kokushi_shanten(hand_counts)
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
        return ShantenCalculatorV2._suit_shanten_detail(counts, open_meld_count)[0]

    @staticmethod
    def _suit_shanten_detail(counts: List[int], open_meld_count: int) -> Tuple[int, int, int, int]:
        """
        @title 詳細シャンテン計算
        @description 面子手でのシャンテン数と、その時の最良分解 (面子, 対子, 塔子) を返す。
        @returns (shanten, total_melds, total_pairs, total_taatsu)
        """
        m_combs = ShantenCalculatorV2._solve_suit_combinations(tuple(counts[0:9]))
        p_combs = ShantenCalculatorV2._solve_suit_combinations(tuple(counts[9:18]))
        s_combs = ShantenCalculatorV2._solve_suit_combinations(tuple(counts[18:27]))
        h_combs = ShantenCalculatorV2._solve_honor_combinations(tuple(counts[27:34]))
        best_shanten = 8
        best_decomp = (0, 0, 0)
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
                        elif still_needed == 0 and total_taatsu == 0:
                            s = 1
                        else:
                            rem_blocks = total_taatsu + total_pairs
                            s = still_needed + max(0, still_needed - rem_blocks)
                        if s < best_shanten or (s == best_shanten and (total_pairs, total_taatsu, total_melds) > (best_decomp[1], best_decomp[2], best_decomp[0])):
                            best_shanten = s
                            best_decomp = (total_melds, total_pairs, total_taatsu)
        return (best_shanten, best_decomp[0], best_decomp[1], best_decomp[2])

    @staticmethod
    def explain_hand_structure(hand_counts: List[int], open_meld_count: int = 0) -> Tuple[int, int, int, int]:
        """
        @title 手牌構造の解説用分解
        @description 向聴数最小の分解 (面子, 対子, 塔子) を返す。
                    evaluator_v2.explain_discard のコーチング文生成や、
                    block_shortage 計算の精度向上に使う。
        @returns (shanten, melds, pairs, taatsu) - 面子は露張含む
        @note 既存 int 戻り値関数 (calculate_*) は維持、破壊なし。
        """
        key = (tuple(hand_counts), open_meld_count, 'explain')
        cache = ShantenCalculatorV2._get_cache()
        if key in cache:
            return cache[key]
        result = ShantenCalculatorV2._suit_shanten_detail(hand_counts, open_meld_count)
        cache[key] = result
        return result

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
