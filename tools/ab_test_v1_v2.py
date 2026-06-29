# -*- coding: utf-8 -*-
"""
@title ver.1 vs ver.2 A/B テスト
@description ランダム手牌で ver.1 と ver.2 の最良打牌一致率を測定。
              ver.2 の妥当性を早期に確認する (Akochan バトル前の sanity check)。
"""
from __future__ import annotations
import random
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, Meld, ReachState
from core.evaluator import Evaluator
from core.evaluator_v2 import EvaluatorV2
from str_converter import hand_to_counts


def random_14tile_hand(rng: random.Random) -> list:
    """ランダムな 14 枚手牌を生成 (現実的な構成: 4面子+1雀頭 or 進行中)"""
    # 山から 14 枚ランダム抽出 (同じ牌 4 枚まで)
    counts = [0] * 34
    while sum(counts) < 14:
        t = rng.randint(0, 33)
        if counts[t] < 4:
            counts[t] += 1
    # id → tile 文字列
    from str_converter import id_to_tile
    hand = []
    for i, c in enumerate(counts):
        for _ in range(c):
            hand.append(id_to_tile(i))
    return hand


def make_state_for(hand: list, doras: list = None) -> GameState:
    state = GameState()
    state.my_hand = list(hand)
    state.my_seat = 0
    state.chang = 0
    state.ju = 0
    state.tsumo_count = 8
    state.doras = doras or ['1m']
    # ReachState オブジェクトで初期化 (None だと ver.1 でクラッシュ)
    state.reach_states = [ReachState() for _ in range(4)]
    state.scores = [25000, 25000, 25000, 25000]
    state.left_tile_count = 70
    return state


def main(n: int = 1000, seed: int = 42):
    rng = random.Random(seed)
    agree = 0
    disagree = 0
    v2_error = 0
    v1_error = 0
    samples = []
    for i in range(n):
        hand = random_14tile_hand(rng)
        state1 = make_state_for(hand)
        state2 = make_state_for(hand)
        # ver.1
        try:
            ev1 = Evaluator(state1)
            d1 = ev1.best_discard(list(state1.my_hand))
        except Exception as e:
            v1_error += 1
            d1 = None
        # ver.2
        try:
            ev2 = EvaluatorV2(state2)
            d2 = ev2.best_discard(list(state2.my_hand))
        except Exception as e:
            v2_error += 1
            d2 = None
        if d1 == d2:
            agree += 1
        else:
            disagree += 1
            if len(samples) < 10:
                samples.append((hand, d1, d2))
    print(f"=== ver.1 vs ver.2 A/B テスト (n={n}) ===")
    print(f"  一致: {agree} ({agree/n*100:.1f}%)")
    print(f"  不一致: {disagree} ({disagree/n*100:.1f}%)")
    print(f"  ver.1 エラー: {v1_error}")
    print(f"  ver.2 エラー: {v2_error}")
    if samples:
        print("\n--- 不一致サンプル (最初の 10 件) ---")
        for hand, d1, d2 in samples:
            print(f"  手牌: {hand}  ver.1={d1}  ver.2={d2}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    main(n)
