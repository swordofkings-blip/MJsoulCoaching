# -*- coding: utf-8 -*-
"""
役満ボーナスのテストスクリプト
各役満の1〜3向聴・テンパイ状態で、スコアが正しく反映されるか確認する。
"""
import json
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from game_state import GameState, Meld
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator
from str_converter import tile_to_id


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

    print("=" * 60)
    print("  役満ボーナス テスト")
    print("=" * 60)

    results_all = []

    # ============================================================
    # 1. 国士無双 (Kokushi)
    # ============================================================
    # テンパイ: 13種揃え + 対子
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z','7z']
    s = make_state(h)
    results_all.append(("国士無双 テンパイ", evaluate_hand(s, params, "国士無双 テンパイ（13種+対子中）")))

    # 1向聴: 12種（1種欠け）
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m']
    s = make_state(h)
    results_all.append(("国士無双 1向聴", evaluate_hand(s, params, "国士無双 1向聴（7z中 欠け）")))

    # 2向聴: 11種（2種欠け）
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','2m','3m','4m']
    s = make_state(h)
    results_all.append(("国士無双 2向聴", evaluate_hand(s, params, "国士無双 2向聴（6z7z 欠け）")))

    # 3向聴: 10種（3種欠け）
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    s = make_state(h)
    results_all.append(("国士無双 3向聴", evaluate_hand(s, params, "国士無双 3向聴（3z4z7z 欠け）")))

    # ============================================================
    # 2. 四暗刻 (Suuankou)
    # ============================================================
    # テンパイ: 暗刻3組+対子+単騎待ち
    h = ['1m','1m','1m','9p','9p','9p','1s','1s','1s','1z','1z','7z','7z','7z']
    s = make_state(h)
    results_all.append(("四暗刻 テンパイ", evaluate_hand(s, params, "四暗刻 テンパイ（3暗刻+東対子→中単騎待ち）")))

    # 1向聴: 暗刻2組+対子2組
    h = ['1m','1m','1m','9p','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z']
    s = make_state(h)
    results_all.append(("四暗刻 1向聴", evaluate_hand(s, params, "四暗刻 1向聴（2暗刻+2対子）")))

    # 2向聴: 暗刻1組+対子3組
    h = ['1m','1m','1m','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z','5z']
    s = make_state(h)
    results_all.append(("四暗刻 2向聴", evaluate_hand(s, params, "四暗刻 2向聴（1暗刻+3対子+単騎）")))

    # 3向聴: 対子4組
    h = ['1m','1m','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z','5z','5z']
    s = make_state(h)
    results_all.append(("四暗刻 3向聴", evaluate_hand(s, params, "四暗刻 3向聴（4対子）")))

    # ============================================================
    # 3. 大三元 (Daisangen)
    # ============================================================
    # テンパイ: 白・發・中 刻子 + 1面子 + 1雀頭
    h = ['5z','5z','5z','6z','6z','6z','7z','7z','7z','1m','1m','1m','9p','9p']
    s = make_state(h)
    results_all.append(("大三元 テンパイ", evaluate_hand(s, params, "大三元 テンパイ（三元牌刻子3組+1面子+雀頭）")))

    # 1向聴: 白・發刻子 + 中対子 + 1面子 + 1雀頭
    h = ['5z','5z','5z','6z','6z','6z','7z','7z','1m','1m','1m','9p','9p','9p']
    s = make_state(h)
    results_all.append(("大三元 1向聴", evaluate_hand(s, params, "大三元 1向聴（2三元刻子+中対子+2面子）")))

    # 2向聴: 白刻子 + 發・中対子
    h = ['5z','5z','5z','6z','6z','7z','7z','1m','1m','1m','9p','9p','9p','1s']
    s = make_state(h)
    results_all.append(("大三元 2向聴", evaluate_hand(s, params, "大三元 2向聴（1三元刻子+2三元対子+面子）")))

    # 3向聴: 三元牌3対子
    h = ['5z','5z','6z','6z','7z','7z','1m','1m','1m','9p','9p','9p','1s','1s']
    s = make_state(h)
    results_all.append(("大三元 3向聴", evaluate_hand(s, params, "大三元 3向聴（3三元対子+2面子）")))

    # ============================================================
    # 4. 字一色 (Tsuuiisou)
    # ============================================================
    # テンパイ: 全字牌
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','5z']
    s = make_state(h)
    results_all.append(("字一色 テンパイ", evaluate_hand(s, params, "字一色 テンパイ（全字牌・3面子+雀頭+1対子）")))

    # 1向聴: 字一色寄り
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','6z']
    s = make_state(h)
    results_all.append(("字一色 1向聴", evaluate_hand(s, params, "字一色 1向聴（3面子+2対子）")))

    # 2向聴: 字牌多め
    h = ['1z','1z','1z','2z','2z','3z','3z','4z','4z','5z','5z','6z','7z','1m']
    s = make_state(h)
    results_all.append(("字一色 2向聴", evaluate_hand(s, params, "字一色 2向聴（1面子+4対子+数牌1枚）")))

    # 3向聴: 字牌+数牌混在
    h = ['1z','1z','2z','2z','3z','3z','4z','4z','5z','5z','6z','7z','1m','9p']
    s = make_state(h)
    results_all.append(("字一色 3向聴", evaluate_hand(s, params, "字一色 3向3向聴（5対子+数牌2枚）")))

    # ============================================================
    # 5. 清老頭 (Chinroutou)
    # ============================================================
    # テンパイ: 全老頭牌
    h = ['1m','1m','1m','9m','9m','9m','1p','1p','1p','9p','9p','9s','9s','9s']
    s = make_state(h)
    results_all.append(("清老頭 テンパイ", evaluate_hand(s, params, "清老頭 テンパイ（全老頭牌4面子+雀頭）")))

    # 1向聴: 老頭牌寄り
    h = ['1m','1m','1m','9m','9m','9m','1p','1p','1p','9p','9p','1s','1s','9s']
    s = make_state(h)
    results_all.append(("清老頭 1向聴", evaluate_hand(s, params, "清老頭 1向聴（4面子+1雀頭+1対子）")))

    # 2向聴: 老頭牌多め
    h = ['1m','1m','9m','9m','1p','1p','9p','9p','1s','1s','9s','9s','1m','9m']
    s = make_state(h)
    results_all.append(("清老頭 2向聴", evaluate_hand(s, params, "清老頭 2向2向向2向聴（6対子）")))

    # 3向聴: 老頭牌+中張牌
    h = ['1m','1m','9m','9m','1p','1p','9p','1s','1s','9s','5m','5p','5s','2m']
    s = make_state(h)
    results_all.append(("清老頭 3向聴", evaluate_hand(s, params, "清老頭 3向聴（老頭牌+中張牌混在）")))

    # ============================================================
    # 6. 九蓮宝燈 (Chuuren)
    # ============================================================
    # テンパイ: 1112345678999 + 1牌
    h = ['1m','1m','1m','2m','3m','4m','5m','6m','7m','8m','9m','9m','9m','5m']
    s = make_state(h)
    results_all.append(("九蓮宝燈 テンパイ", evaluate_hand(s, params, "九蓮宝燈 テンパイ（1112345678999+5m）")))

    # 1向聴: 111234567899 + 2牌
    h = ['1m','1m','1m','2m','3m','4m','5m','6m','7m','8m','9m','9m','5p','5p']
    s = make_state(h)
    results_all.append(("九蓮宝燈 1向聴", evaluate_hand(s, params, "九蓮宝燈 1向聴（111234567899+2対子）")))

    # 2向聴: 1112345678 + 3牌
    h = ['1m','1m','1m','2m','3m','4m','5m','6m','7m','8m','9m','5p','5p','6p']
    s = make_state(h)
    results_all.append(("九蓮宝燈 2向聴", evaluate_hand(s, params, "九蓮宝燈 2向聴（1112345678+9牌）")))

    # 3向聴: 11123456 + 4牌
    h = ['1m','1m','1m','2m','3m','4m','5m','6m','7m','5p','5p','6p','6p','7p']
    s = make_state(h)
    results_all.append(("九蓮宝燈 3向聴", evaluate_hand(s, params, "九蓮宝燈 3向聴（11123456+6牌）")))

    # ============================================================
    # 7. 大四喜 (Daisuushii)
    # ============================================================
    # テンパイ: 東南西北 刻子
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','4z','5z','5z']
    s = make_state(h)
    results_all.append(("大四喜 テンパイ", evaluate_hand(s, params, "大四喜 テンパイ（4風牌刻子+雀頭）")))

    # 1向聴: 3風牌刻子+1風牌対子
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','5z']
    s = make_state(h)
    results_all.append(("大四喜 1向聴", evaluate_hand(s, params, "大四喜 1向聴（3風牌刻子+1風牌対子+面子）")))

    # 2向聴: 2風牌刻子+2風牌対子
    h = ['1z','1z','1z','2z','2z','2z','3z','3z','4z','4z','5z','5z','5z','1m']
    s = make_state(h)
    results_all.append(("大四喜 2向聴", evaluate_hand(s, params, "大四喜 2向聴（2風牌刻子+2風牌対子）")))

    # 3向聴: 1風牌刻子+3風牌対子
    h = ['1z','1z','1z','2z','2z','3z','3z','4z','4z','5z','5z','1m','1m','9p']
    s = make_state(h)
    results_all.append(("大四喜 3向聴", evaluate_hand(s, params, "大四喜 3向聴（1風牌刻子+3風牌対子）")))

    # ============================================================
    # 8. 緑一色 (Ryuuiisou)
    # ============================================================
    # テンパイ: 2s3s4s6s8s白發のみ
    h = ['2s','2s','2s','3s','3s','3s','4s','4s','4s','6s','6s','8s','8s','5z']
    s = make_state(h)
    results_all.append(("緑一色 テンパイ", evaluate_hand(s, params, "緑一色 テンパイ（緑一色牌のみ4面子+雀頭）")))

    # 1向聴: 緑一色寄り
    h = ['2s','2s','2s','3s','3s','3s','4s','4s','6s','6s','8s','8s','5z','5z']
    s = make_state(h)
    results_all.append(("緑一色 1向聴", evaluate_hand(s, params, "緑一色 1向聴（3面子+2対子）")))

    # 2向聴: 緑一色+1枚余分
    h = ['2s','2s','3s','3s','4s','4s','6s','6s','8s','8s','5z','5z','6z','6z']
    s = make_state(h)
    results_all.append(("緑一色 2向聴", evaluate_hand(s, params, "緑一色 2向2向聴（5対子）")))

    # 3向聴: 緑一色+中張牌
    h = ['2s','2s','3s','3s','4s','6s','8s','5z','5z','6z','6z','5m','5p','5s']
    s = make_state(h)
    results_all.append(("緑一色 3向聴", evaluate_hand(s, params, "緑一色 3向聴（緑一色候補+中張牌）")))

    # ============================================================
    # 点差シナリオテスト
    # ============================================================
    print("\n" + "=" * 60)
    print("  点差シナリオテスト")
    print("=" * 60)

    # トップと20000点差（倍満超）→ 3向聴でも役満ボーナスが乗るか
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores_behind = [10000, 45000, 25000, 25000]  # 自身10000点、トップ45000点（差35000）
    s = make_state(h, scores=scores_behind)
    results_all.append(("国士無双 3向聴（点差35000）", evaluate_hand(s, params, "国士無双 3向聴（点差35000点）")))

    # トップと15000点差（倍満以下）→ 3向聴でも役満ボーナスが乗るか
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores_close = [20000, 35000, 25000, 25000]  # 自身20000点、トップ35000点（差15000）
    s = make_state(h, scores=scores_close)
    results_all.append(("国士無双 3向聴（点差15000）", evaluate_hand(s, params, "国士無双 3向聴（点差15000点）")))

    # トップ目（差なし）→ 3向聴では役満ボーナスが乗らないか
    h = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']
    scores_top = [45000, 10000, 25000, 25000]  # 自身45000点でトップ
    s = make_state(h, scores=scores_top)
    results_all.append(("国士無双 3向聴（トップ目）", evaluate_hand(s, params, "国士無双 3向聴（トップ目）")))

    # 四暗刻 3向聴 + 点差大
    h = ['1m','1m','9p','9p','1s','1s','1z','1z','7z','7z','6z','6z','5z','5z']
    s = make_state(h, scores=scores_behind)
    results_all.append(("四暗刻 3向聴（点差35000）", evaluate_hand(s, params, "四暗刻 3向聴（点差35000点）")))

    # 大三元 3向聴 + 点差大
    h = ['5z','5z','6z','6z','7z','7z','1m','1m','1m','9p','9p','9p','1s','1s']
    s = make_state(h, scores=scores_behind)
    results_all.append(("大三元 3向聴（点差35000）", evaluate_hand(s, params, "大三元 3向聴（点差35000点）")))

    # ============================================================
    # まとめ
    # ============================================================
    print("\n" + "=" * 60)
    print("  サマリー: 役満ボーナスが適用されているか確認")
    print("=" * 60)
    ok_count = 0
    ng_count = 0
    for label, scored in results_all:
        has_bonus = any('役満' in b for _, _, b in scored)
        best_tile = scored[0][0] if scored else '-'
        best_score = scored[0][1] if scored else 0
        status = "OK" if has_bonus else "NG"
        if has_bonus:
            ok_count += 1
        else:
            ng_count += 1
        print(f"  [{status}] {label:<40} → 最良打: {best_tile} (score={best_score:.1f})")

    print(f"\n  結果: OK={ok_count}, NG={ng_count}")
    return ng_count == 0


if __name__ == '__main__':
    success = main()
    sys.exit(0 if success else 1)
