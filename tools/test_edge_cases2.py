# -*- coding: utf-8 -*-
"""エッジケーステスト（正しい期待値に修正）"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from game_state import GameState, Meld
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator


def load_params():
    return json.load(open('config/config_parameters.json', encoding='utf-8'))


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
    unique = list(dict.fromkeys(state.my_hand))

    print(f"\n  {'牌':<6} {'スコア':>8}  ボーナス詳細")
    print(f"  {'-'*50}")

    scored = []
    for tile in unique:
        s = evaluator.evaluate_tile(tile)
        details = evaluator.details.get(tile, [])
        yakuman = [d for d in details if '役満' in d]
        bonus_str = ' | '.join(yakuman) if yakuman else '-'
        scored.append((tile, s, bonus_str))

    scored.sort(key=lambda x: -x[1])
    for tile, score, bonus_str in scored:
        print(f"  {tile:<6} {score:>8.1f}  {bonus_str}")

    return scored


def main():
    params = load_params()
    all_ok = True

    print("=" * 60)
    print("  エッジケーステスト（修正版）")
    print("=" * 60)

    # 1: 大三元1向聴
    h = ['5z','5z','5z','6z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p']
    evaluate_and_print(make_state(h), params, "1: 大三元1向聴")
    # 期待: suuankou優先度が高いのでそちらが選ばれる（suuankou progress=0.60 > daisangen progress=0.67だが、priorityで逆転）

    # 2: 大三元2向聴
    h = ['5z','5z','5z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p','9s']
    evaluate_and_print(make_state(h), params, "2: 大三元2向聴")
    # 期待: suuankou (shanten=1) > daisangen (shanten=2) → suuankou選ばれる

    # 3: 字一色テンパイ
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','6z']
    evaluate_and_print(make_state(h), params, "3: 字一色テンパイ")

    # 4: 清老頭テンパイ
    h = ['1m','1m','1m','9m','9m','9m','1p','1p','1p','9p','9p','1s','1s','9s']
    evaluate_and_print(make_state(h), params, "4: 清老頭テンパイ")

    # 5: 国士無双テンパイ
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z','7z']
    evaluate_and_print(make_state(h), params, "5: 国士無双テンパイ")

    # 6: 九蓮宝燈テンパイ
    h = ['1m','1m','1m','2m','3m','4m','5m','6m','7m','8m','9m','9m','9m','5m']
    evaluate_and_print(make_state(h), params, "6: 九蓮宝燈テンパイ")

    # 7: 四槓子（暗刻4組）
    h = ['1m','1m','1m','1m','9p','9p','9p','9p','5z','5z','5z','5z','1s','1s']
    evaluate_and_print(make_state(h), params, "7: 四槓子テンパイ")

    # 8: 大四喜1向聴
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5m','5p','5s']
    evaluate_and_print(make_state(h), params, "8: 大四喜1向聴")

    # 9: 小四喜テンパイ
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','1m']
    evaluate_and_print(make_state(h), params, "9: 小四喜テンパイ")

    # 10: 緑一色1向聴
    h = ['2s','2s','2s','3s','3s','3s','4s','4s','6s','6s','8s','8s','5z','5z']
    evaluate_and_print(make_state(h), params, "10: 緑一色1向聴")

    # 11: 副露済み（四暗刻無効）
    meld1 = Meld(type=0, tiles=['2p','2p','2p'], froms=[1], tile_states=[0,0,0])
    h = ['1m','1m','1m','5z','5z','6z','6z','7z','7z','9p','9p','9p','1s','1s']
    evaluate_and_print(make_state(h, melds=[meld1]), params, "11: 副露済み（四暗刻無効）")

    # 12: 点差大（3向聴でも狙う）
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores = [5000, 45000, 25000, 25000]
    evaluate_and_print(make_state(h, scores=scores), params, "12: 点差大 国士無双3向聴")

    print(f"\n{'='*60}")
    print("  全テスト完了")
    print(f"{'='*60}")


if __name__ == '__main__':
    main()
