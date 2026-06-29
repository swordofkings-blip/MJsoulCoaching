# -*- coding: utf-8 -*-
"""
@title ver.1 vs ver.2 人間牌譜一致率テスト
@description 雀魂 (Majsoul) 牌譜で ver.1 と ver.2 の人間打牌一致率を測定。
              既存 RecordReplayer で牌譜を再生し、各打牌で両 AI の best_discard を比較。
              ver.2 が ver.1 を超えれば改善。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, Meld, ReachState
from core.evaluator import Evaluator
from core.evaluator_v2 import EvaluatorV2
from core.record_evaluator import RecordReplayer


def load_params(path: str) -> dict:
    if not path:
        return {}
    _base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    _paths = [path, os.path.join(_base, 'config', path), os.path.join(_base, path)]
    for _p in _paths:
        if os.path.exists(_p):
            with open(_p, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
    return {}


def process_record(record_path: str, params: dict, max_decisions: int = 0,
                   save_mismatches: bool = False, scoring: str = 'proportional') -> dict:
    """
    1 つの牌譜を ver.1 と ver.2 で再生し、各打牌の一致率を測定。
    人間打牌と AI の最良打牌が一致したかを見る。
    max_decisions: 0 = 全て、それ以外 = 制限 (デバッグ用)
    save_mismatches: 不一致ケースを保存
    scoring: 'strict' (完全一致) | 'proportional' (比率スコアリング 0-100)
    """
    with open(record_path, 'r', encoding='utf-8') as f:
        record = json.load(f)

    # 簡略化: actions を最初から再生して ver.1/ver.2 を評価
    replayer_v1 = RecordReplayer(record, params)
    replayer_v2 = RecordReplayer(record, params)

    # actions を逐次処理して人間打牌時に AI 一致を見る
    actions = record.get('detail_records', {}).get('actions', [])
    v1_eval = _walk_actions(actions, replayer_v1, params, use_v2=False,
                            max_decisions=max_decisions, save_mismatches=save_mismatches,
                            scoring=scoring)
    v2_eval = _walk_actions(actions, replayer_v2, params, use_v2=True,
                            max_decisions=max_decisions, save_mismatches=save_mismatches,
                            scoring=scoring)

    return {
        'file': os.path.basename(record_path),
        'v1_total': v1_eval['total'],
        'v1_exact': v1_eval['exact_match'],
        'v1_avg_match': v1_eval['avg_match'],
        'v2_total': v2_eval['total'],
        'v2_exact': v2_eval['exact_match'],
        'v2_avg_match': v2_eval['avg_match'],
        'v2_mismatches': v2_eval.get('mismatches', []),
    }


def _walk_actions(actions: list, replayer: RecordReplayer, params: dict, use_v2: bool,
                   max_decisions: int = 0, save_mismatches: bool = False,
                   scoring: str = 'strict') -> dict:
    """
    actions を逐次処理。
    RecordDiscardTile 直前に state を構築して AI の best_discard を呼び、人間打牌と比較。
    max_decisions: 0 = 全て
    save_mismatches: 不一致ケースを保存
    scoring: 'strict' (完全一致) | 'proportional' (比率スコアリング 0-100)
    """
    total = 0
    match_sum = 0.0
    exact_match = 0
    mismatches = []
    for action in actions:
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})

        if class_name == 'RecordNewRound':
            replayer._init_round(data)
        elif class_name == 'RecordDealTile':
            replayer._deal_tile(data)
        elif class_name == 'RecordDiscardTile':
            seat = data.get('seat')
            tile = data.get('tile')
            # 打牌直前の state を構築して AI に判断させる
            # (打牌前 = 14 枚、まだ手牌に tile が含まれる)
            try:
                state = replayer._build_state_for_seat(seat)
                if use_v2:
                    ai = EvaluatorV2(state, params)
                else:
                    ai = Evaluator(state, params)
                hand = list(state.my_hand)
                if hand and len(hand) == 14:
                    unique_tiles = list(dict.fromkeys(hand))
                    # 各牌のスコア/タプルを取得
                    if use_v2:
                        # ver.2: タプル比較 (min() 規約、小さいほど良い)
                        evals = []
                        for t in unique_tiles:
                            try:
                                tpl = ai.evaluate_tile(t)
                                evals.append((t, tpl))
                            except Exception:
                                evals.append((t, None))
                        evals.sort(key=lambda x: x[1])  # 昇順 (min が best)
                    else:
                        # ver.1: 単一スコア (大きいほど良い)
                        evals = []
                        for t in unique_tiles:
                            try:
                                score = ai.evaluate_tile(t)
                                evals.append((t, score))
                            except Exception:
                                evals.append((t, -99999))
                        evals.sort(key=lambda x: -x[1])  # 降順 (max が best)

                    if not evals:
                        pass
                    else:
                        chosen = evals[0][0]
                        total += 1
                        if chosen == tile:
                            exact_match += 1
                            match_sum += 100.0
                        elif scoring == 'proportional':
                            # 比率スコアリング (順位ベース): 人間の打牌が何位かを 0-100 で評価
                            # best (1位) = 100, worst (最下位) = 0, 線形補間
                            n = len(evals)
                            actual_pos = None
                            for k, (t, _) in enumerate(evals):
                                if t == tile:
                                    actual_pos = k
                                    break
                            if actual_pos is not None and n > 1:
                                # 1位が 100, 最下位が 0
                                match = (n - 1 - actual_pos) / (n - 1) * 100.0
                                match_sum += match
                            else:
                                match_sum += 0.0
                        if save_mismatches and chosen != tile and len(mismatches) < 30:
                            structure = ai.describe_hand_structure() if hasattr(ai, 'describe_hand_structure') else ''
                            mode = ai.get_mode().name if hasattr(ai, 'get_mode') else '?'
                            mismatches.append({
                                'hand': hand,
                                'actual': tile,
                                'ai': chosen,
                                'mode': mode,
                                'structure': structure,
                            })
            except Exception as e:
                pass
            # 人間打牌を適用
            replayer._discard_tile(data)
            if max_decisions > 0 and total >= max_decisions:
                break
        elif class_name == 'RecordChiPengGang':
            replayer._chi_peng_gang(data)
        elif class_name == 'RecordAnGangAddGang':
            replayer._an_gang_add_gang(data)
        # userInput はスキップ (AI は人間の打牌前に評価)

    return {
        'total': total,
        'exact_match': exact_match,
        'match_sum': match_sum,
        'avg_match': match_sum / total if total else 0.0,
        'mismatches': mismatches,
    }


def main(file_list: List[str], params_path: str, max_decisions: int = 0,
         save_mismatches: bool = False, out_path: str = None, scoring: str = 'proportional'):
    params = load_params(params_path)
    print(f"=== ver.1 vs ver.2 人間牌譜一致率テスト ===")
    print(f"  ファイル数: {len(file_list)}")
    print(f"  パラメータ: {params_path or '(default)'}")
    print(f"  max_decisions: {max_decisions or '(無制限)'}")
    print(f"  scoring: {scoring}")

    grand_v1_total = 0
    grand_v1_exact = 0
    grand_v1_match_sum = 0.0
    grand_v2_total = 0
    grand_v2_exact = 0
    grand_v2_match_sum = 0.0
    all_v2_mismatches = []
    t0 = time.time()
    for i, fp in enumerate(file_list):
        try:
            r = process_record(fp, params, max_decisions=max_decisions,
                               save_mismatches=save_mismatches, scoring=scoring)
            v1_pct = r['v1_avg_match']
            v2_pct = r['v2_avg_match']
            v1_strict = r['v1_exact'] / r['v1_total'] * 100 if r['v1_total'] else 0
            v2_strict = r['v2_exact'] / r['v2_total'] * 100 if r['v2_total'] else 0
            print(f"  [{i+1}/{len(file_list)}] {r['file']}: "
                  f"ver.1=完全一致 {r['v1_exact']}/{r['v1_total']} ({v1_strict:.1f}%) 比率 {v1_pct:.1f} | "
                  f"ver.2=完全一致 {r['v2_exact']}/{r['v2_total']} ({v2_strict:.1f}%) 比率 {v2_pct:.1f}")
            grand_v1_total += r['v1_total']
            grand_v1_exact += r['v1_exact']
            grand_v1_match_sum += r['v1_avg_match'] * r['v1_total']
            grand_v2_total += r['v2_total']
            grand_v2_exact += r['v2_exact']
            grand_v2_match_sum += r['v2_avg_match'] * r['v2_total']
            all_v2_mismatches.extend(r.get('v2_mismatches', []))
        except Exception as e:
            print(f"  [{i+1}/{len(file_list)}] {fp}: エラー ({type(e).__name__}: {e})")
            import traceback
            traceback.print_exc()

    print()
    print("=== 結果サマリ ===")
    if grand_v1_total:
        v1_pct = grand_v1_match_sum / grand_v1_total
        v1_strict = grand_v1_exact / grand_v1_total * 100
        print(f"  ver.1: 完全一致 {grand_v1_exact}/{grand_v1_total} ({v1_strict:.1f}%) | 比率スコア {v1_pct:.1f}")
    if grand_v2_total:
        v2_pct = grand_v2_match_sum / grand_v2_total
        v2_strict = grand_v2_exact / grand_v2_total * 100
        print(f"  ver.2: 完全一致 {grand_v2_exact}/{grand_v2_total} ({v2_strict:.1f}%) | 比率スコア {v2_pct:.1f}")
    if grand_v1_total and grand_v2_total:
        v1_pct = grand_v1_match_sum / grand_v1_total
        v2_pct = grand_v2_match_sum / grand_v2_total
        diff = v2_pct - v1_pct
        print(f"  比率スコア差分: ver.2 - ver.1 = {diff:+.1f}pt")
    print(f"  経過時間: {time.time() - t0:.1f}秒")

    if save_mismatches and all_v2_mismatches:
        if out_path is None:
            out_path = "v2_mismatches.json"
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(all_v2_mismatches, f, ensure_ascii=False, indent=2)
        print(f"\n  ver.2 不一致ケース {len(all_v2_mismatches)} 件を {out_path} に保存")
        # 不一致の内訳 (モード別)
        from collections import Counter
        mode_count = Counter(m['mode'] for m in all_v2_mismatches)
        print(f"  モード別不一致: {dict(mode_count)}")
        # 不一致のサンプル表示 (最初の 5 件)
        for i, m in enumerate(all_v2_mismatches[:5]):
            print(f"  例{i+1}: 手牌={m['hand']} 人間={m['actual']} ver.2={m['ai']} mode={m['mode']} 構造={m['structure']}")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", help="trimmed.json ファイル (複数可)")
    p.add_argument("--params", type=str, default="config/config_parameters.json")
    p.add_argument("--max-decisions", type=int, default=0, help="ファイルあたり判定数の上限 (デバッグ用)")
    p.add_argument("--save-mismatches", action="store_true", help="ver.2 不一致ケースを JSON 保存")
    p.add_argument("--out", type=str, default=None, help="不一致ケース保存先")
    p.add_argument("--scoring", choices=['strict', 'proportional'], default='proportional',
                   help="スコアリング方式 (strict=完全一致, proportional=比率スコア)")
    args = p.parse_args()
    main(args.files, args.params, args.max_decisions, args.save_mismatches, args.out, args.scoring)
