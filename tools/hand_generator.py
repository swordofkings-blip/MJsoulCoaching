# -*- coding: utf-8 -*-
"""
@title 麻雀 牌構成自動生成ツール
@description テストケース作成用の 14 枚麻雀牌を自動生成。
              制約 (シャンテン数、面子数、字牌数など) を指定して現実的な手牌を作る。
"""
from __future__ import annotations
import argparse
import random
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, '.')
from core.str_converter import hand_to_counts
from core.shanten_v2 import ShantenCalculatorV2


def generate_hand(n: int = 14, seed: Optional[int] = None,
                 target_shanten: Optional[int] = None,
                 target_melds: Optional[int] = None,
                 target_pairs: Optional[int] = None,
                 target_honor_count: Optional[int] = None,
                 min_red_five: int = 0,
                 must_include: Optional[List[str]] = None,
                 max_attempts: int = 10000) -> List[str]:
    """
    @title 牌構成生成
    @param n: 枚数 (デフォルト 14)
    @param seed: 乱数シード
    @param target_shanten: 目標シャンテン数 (None = 制約なし)
    @param target_melds: 目標面子数 (0-4, None = 制約なし)
    @param target_pairs: 目標雀頭候補数 (None = 制約なし)
    @param target_honor_count: 目標字牌数 (0-14, None = 制約なし)
    @param min_red_five: 最低赤 5 枚数 (0-4)
    @param must_include: 必ず含める牌 (例: ['5m', '5m', '5m'] でドラ 3 確定)
    @param max_attempts: 最大試行回数
    @returns 牌リスト
    """
    rng = random.Random(seed)

    for attempt in range(max_attempts):
        counts = [0] * 34
        # 必須牌を先に配置
        if must_include:
            for t in must_include:
                try:
                    tid = tile_to_id(t)
                    if counts[tid] < 4:
                        counts[tid] += 1
                    else:
                        break  # 4 枚超 = 不正
                except Exception:
                    break
            else:
                # 赤 5 を配置
                for _ in range(min_red_five):
                    suit = rng.randint(0, 2)
                    if counts[suit * 9 + 4] < 4:
                        counts[suit * 9 + 4] += 1
                # 残りをランダム
                remaining = n - sum(counts)
                for _ in range(remaining):
                    t = rng.randint(0, 33)
                    if counts[t] < 4:
                        counts[t] += 1
        else:
            # 赤 5 を配置
            for _ in range(min_red_five):
                suit = rng.randint(0, 2)
                counts[suit * 9 + 4] += 1
            # 残りをランダム
            remaining = n - sum(counts)
            for _ in range(remaining):
                t = rng.randint(0, 33)
                if counts[t] < 4:
                    counts[t] += 1

        from str_converter import id_to_tile
        hand = []
        for i, c in enumerate(counts):
            for _ in range(c):
                hand.append(id_to_tile(i))

        if target_shanten is not None:
            sh = ShantenCalculatorV2.calculate_closed_effective(counts)
            if sh != target_shanten:
                continue
        if target_melds is not None:
            _, melds, _, _ = ShantenCalculatorV2.explain_hand_structure(counts, 0)
            if melds != target_melds:
                continue
        if target_pairs is not None:
            _, _, pairs, _ = ShantenCalculatorV2.explain_hand_structure(counts, 0)
            if pairs != target_pairs:
                continue
        if target_honor_count is not None:
            honor = sum(counts[27:34])
            if honor != target_honor_count:
                continue
        return hand

    raise ValueError(f"制約を満たす手牌が {max_attempts} 試行で見つかりませんでした")


def tile_to_id(tile: str) -> int:
    """@title tile ('1m') を id (0-33) に変換"""
    if tile.startswith('0'):
        suit_letter = tile[1]
        rank = 4  # 赤 5
    else:
        suit_letter = tile[1]
        rank = int(tile[0]) - 1
    suit_map = {'m': 0, 'p': 1, 's': 2, 'z': 3}
    return suit_map[suit_letter] * 9 + rank


def display_hand(hand: List[str]) -> None:
    """@title 牌構成をプレビュー表示"""
    counts = hand_to_counts(hand)
    n = len(hand)
    sh = ShantenCalculatorV2.calculate_closed_effective(counts)
    _, melds, pairs, taatsu = ShantenCalculatorV2.explain_hand_structure(counts, 0)
    honor = sum(counts[27:34])
    red5 = sum(1 for t in hand if t.startswith('0'))
    print(f'  手牌 ({n} 枚): {sorted(hand)}')
    print(f'  シャンテン数: {sh} (面子 {melds} 雀頭候補 {pairs} 塔子 {taatsu})')
    print(f'  字牌: {honor} 枚, 赤 5: {red5} 枚')
    if sh == 0:
        print(f'  ★ テンパイ')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=14, help='枚数')
    p.add_argument('--count', type=int, default=1, help='生成数')
    p.add_argument('--seed', type=int, default=None, help='乱数シード')
    p.add_argument('--shanten', type=int, default=None, help='目標シャンテン数 (-1=和了, 0=テンパイ)')
    p.add_argument('--melds', type=int, default=None, help='目標面子数 (0-4)')
    p.add_argument('--pairs', type=int, default=None, help='目標雀頭候補数')
    p.add_argument('--honor', type=int, default=None, help='目標字牌数 (0-14)')
    p.add_argument('--red5', type=int, default=0, help='最低赤 5 枚数 (0-4)')
    p.add_argument('--must-include', type=str, default=None, help='必須牌 (カンマ区切り)')
    p.add_argument('--no-display', action='store_true', help='プレビュー非表示')
    args = p.parse_args()

    must_include = args.must_include.split(',') if args.must_include else None
    seed = args.seed if args.seed is not None else 0
    for i in range(args.count):
        if not args.no_display and args.count > 1:
            print(f'--- 牌譜 {i+1} ---')
        hand = generate_hand(
            n=args.n,
            seed=seed + i,
            target_shanten=args.shanten,
            target_melds=args.melds,
            target_pairs=args.pairs,
            target_honor_count=args.honor,
            min_red_five=args.red5,
            must_include=must_include,
        )
        if not args.no_display:
            display_hand(hand)


if __name__ == '__main__':
    main()
