# -*- coding: utf-8 -*-
"""役満ロジックv2の動作確認テスト"""
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


def evaluate_hand(state, params, label):
    evaluator = Evaluator(state, params=params)
    hand = state.my_hand
    unique_tiles = list(dict.fromkeys(hand))

    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"  手牌: {' '.join(hand)}")
    print(f"{'='*60}")

    # 役満評価の確認
    yak_eval = YakumanEvaluator(state)
    results = yak_eval.evaluate_all()
    for name, r in results.items():
        if r.progress > 0:
            print(f"  [{name}] progress={r.progress:.2f} shanten={r.shanten} possible={r.is_possible}")

    # 副露封印モードの確認
    seal = yak_eval.should_seal_melds()
    if seal:
        print(f"  [副露封印モード: ON]")

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
    for tile, score, bonus_str in scored:
        print(f"  {tile:<6} {score:>8.1f}  {bonus_str}")

    return scored


def main():
    params = load_params()
    results_all = []

    print("=" * 60)
    print("  役満ロジックv2 動作確認テスト")
    print("=" * 60)

    # ============================================================
    # テスト1: 国士無双1向聴（牌貢献度判定テスト）
    # ============================================================
    # 12種揃え（東欠け）、中張牌2mが手牌にある
    # → 中張牌にはボーナスが乗らないはず
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m']
    s = make_state(h)
    results_all.append(("国士無双1向聴: 牌貢献度判定", evaluate_hand(s, params, "国士無双1向聴（7z欠け・中張牌2mあり）")))

    # ============================================================
    # テスト2: 四暗刻2向聴（門前チェック）
    # ============================================================
    # 暗刻2組+対子3組
    h = ['1m','1m','1m','9p','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z']
    s = make_state(h)
    results_all.append(("四暗刻2向聴: 門前", evaluate_hand(s, params, "四暗刻2向聴（門前・暗刻2組+対子2組）")))

    # ============================================================
    # テスト3: 四暗刻2向聴（副露あり→無効化）
    # ============================================================
    # 副露あり的情况下、四暗刻は成立しない
    meld1 = Meld(type=0, tiles=['2p','2p','2p'], froms=[1], tile_states=[0,0,0])
    h = ['1m','1m','1m','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z']
    s = make_state(h, melds=[meld1])
    results_all.append(("四暗刻2向聴: 副露あり", evaluate_hand(s, params, "四暗刻2向聴（副露あり→四暗刻無効）")))

    # ============================================================
    # テスト4: 大三元1向聴（priority factorテスト）
    # ============================================================
    # 白・發刻子+中対子
    h = ['5z','5z','5z','6z','6z','6z','7z','7z','1m','1m','1m','9p','9p','9p']
    s = make_state(h)
    results_all.append(("大三元1向聴: priority", evaluate_hand(s, params, "大三元1向聴（2三元刻子+中対子）")))

    # ============================================================
    # テスト5: 四暗刻1向聴 vs 大三元2向聴（複合テスト）
    # ============================================================
    # 四暗刻の方が進行度が高いので、四暗刻に振るはず
    h = ['1m','1m','1m','9p','9p','9p','5z','5z','5z','7z','7z','1s','1s','1s']
    s = make_state(h)
    results_all.append(("四暗刻1向聴 vs 大三元1向聴", evaluate_hand(s, params, "四暗刻1向聴+大三元1向聴（複合）")))

    # ============================================================
    # テスト6: 点差大的場合3向聴でもボーナス
    # ============================================================
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores_behind = [5000, 45000, 25000, 25000]  # 点差40000
    s = make_state(h, scores=scores_behind)
    results_all.append(("国士無双3向聴: 点差大", evaluate_hand(s, params, "国士無双3向聴（点差40000）")))

    # ============================================================
    # テスト7: 副露封印モードテスト
    # ============================================================
    # 国士無双1向聴で門前を維持すべき
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m']
    s = make_state(h)
    yak_eval = YakumanEvaluator(s)
    seal = yak_eval.should_seal_melds()
    results_all.append(("副露封印モード", [("封印ON" if seal else "封印OFF", 0, "")]))

    # ============================================================
    # まとめ
    # ============================================================
    print("\n" + "=" * 60)
    print("  サマリー")
    print("=" * 60)
    for label, scored in results_all:
        if scored and scored[0][0] in ('封印ON', '封印OFF'):
            print(f"  {label}: {scored[0][0]}")
        else:
            has_bonus = any('役満' in b for _, _, b in scored) if scored else False
            best_tile = scored[0][0] if scored else '-'
            best_score = scored[0][1] if scored else 0
            status = "OK" if has_bonus else "NG"
            print(f"  [{status}] {label:<40} → 最良打: {best_tile} (score={best_score:.1f})")


if __name__ == '__main__':
    main()
