# -*- coding: utf-8 -*-
"""エッジケーステスト"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from game_state import GameState, Meld
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator


def load_params():
    config_path = os.path.join(os.path.dirname(__file__), '..', 'config', 'config_parameters.json')
    with open(config_path, encoding='utf-8') as f:
        return json.load(f)


def make_state(hand, scores=None, tsumo_count=5, melds=None):
    state = GameState()
    state.my_seat = 0
    state.my_hand = list(hand)
    state.scores = scores or [25000, 25000, 25000, 25000]
    state.tsumo_count = tsumo_count
    state.doras = ['1m']
    state.left_tile_count = 70 - tsumo_count * 4
    if melds:
        state.my_melds = melds
        state.melds[0] = melds
    return state


def evaluate_and_print(state, params, label):
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  手牌: {' '.join(state.my_hand)}")
    print(f"{'='*60}")

    yak_eval = YakumanEvaluator(state)
    results = yak_eval.evaluate_all()
    for name, r in results.items():
        if r.progress > 0:
            print(f"  [{name}] progress={r.progress:.2f} shanten={r.shanten} possible={r.is_possible}")

    seal = yak_eval.should_seal_melds()
    if seal:
        print(f"  [副露封印: ON]")

    evaluator = Evaluator(state, params=params)
    unique_tiles = list(dict.fromkeys(state.my_hand))

    print(f"\n  {'牌':<6} {'スコア':>8}  ボーナス詳細")
    print(f"  {'-'*50}")

    scored = []
    for tile in unique_tiles:
        score = evaluator.evaluate_tile(tile)
        details = evaluator.details.get(tile, [])
        yakuman_details = [d for d in details if '役満' in d]
        bonus_str = ' | '.join(yakuman_details) if yakuman_details else '-'
        scored.append((tile, score, bonus_str))

    scored.sort(key=lambda x: -x[1])
    for tile, score, bonus_str in scored[:5]:  # 上位5件のみ表示
        print(f"  {tile:<6} {score:>8.1f}  {bonus_str}")

    return scored


def main():
    params = load_params()

    print("=" * 60)
    print("  エッジケーステスト")
    print("=" * 60)

    # ============================================================
    # エッジケース1: 四暗刻2向聴 vs 大三元1向聴
    # ============================================================
    # 四暗刻: 暗刻1組(1m) + 対子2組(5z,6z) → 2向聴
    # 大三元: 白・發刻子 + 中対子 → 1向聴
    h = ['1m','1m','1m','5z','5z','6z','6z','7z','7z','1s','1s','9p','9p','9p']
    s = make_state(h)
    evaluate_and_print(s, params, "エッジケース1: 四暗刻2向聴 vs 大三元1向聴")

    # ============================================================
    # エッジケース2: 四暗刻1向聴 vs 大三元2向聴
    # ============================================================
    # 四暗刻: 暗刻2組(1m,9p) + 対子2組(5z,6z) → 1向聴
    # 大三元: 白刻子 + 發・中対子 → 2向聴
    h = ['1m','1m','1m','9p','9p','9p','5z','5z','6z','6z','7z','7z','1s','1s']
    s = make_state(h)
    evaluate_and_print(s, params, "エッジケース2: 四暗刻1向聴 vs 大三元2向聴")

    # ============================================================
    # エッジケース3: 副露済みで四暗刻無効
    # ============================================================
    # 副露あり → 四暗刻は門前限定なので無効
    meld1 = Meld(type=0, tiles=['2p','2p','2p'], froms=[1], tile_states=[0,0,0])
    h = ['1m','1m','1m','5z','5z','6z','6z','7z','7z','9p','9p','9p','1s','1s']
    s = make_state(h, melds=[meld1])
    evaluate_and_print(s, params, "エッジケース3: 副露済み（四暗刻無効）")

    # ============================================================
    # エッジケース4: 国士無双1向聴（門前封印）
    # ============================================================
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m']
    s = make_state(h)
    evaluate_and_print(s, params, "エッジケース4: 国士無双1向聴（門前封印）")

    # ============================================================
    # エッジケース5: 点差なし（通常進行優先）
    # ============================================================
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores_even = [25000, 25000, 25000, 25000]
    s = make_state(h, scores=scores_even)
    evaluate_and_print(s, params, "エッジケース5: 点差なし（通常進行優先）")

    # ============================================================
    # エッジケース6: 点差大（3向聴でも狙う）
    # ============================================================
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores_behind = [5000, 45000, 25000, 25000]
    s = make_state(h, scores=scores_behind)
    evaluate_and_print(s, params, "エッジケース6: 点差大（3向聴でも狙う）")

    # ============================================================
    # エッジケース7: 四槓子（最も困難）
    # ============================================================
    h = ['1m','1m','1m','1m','9p','9p','9p','9p','5z','5z','5z','5z','1s','1s']
    s = make_state(h)
    evaluate_and_print(s, params, "エッジケース7: 四槓子（4暗刻4組）")

    # ============================================================
    # エッジケース8: 字一色 vs 大三元（複合）
    # ============================================================
    h = ['1z','1z','1z','2z','2z','2z','5z','5z','5z','6z','6z','7z','7z','7z']
    s = make_state(h)
    evaluate_and_print(s, params, "エッジケース8: 字一色 vs 大三元（複合）")


if __name__ == '__main__':
    main()
