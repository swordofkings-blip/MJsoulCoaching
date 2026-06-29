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


def process_record(record_path: str, params: dict) -> dict:
    """
    1 つの牌譜を ver.1 と ver.2 で再生し、各打牌の一致率を測定。
    人間打牌と AI の最良打牌が一致したかを見る。
    """
    with open(record_path, 'r', encoding='utf-8') as f:
        record = json.load(f)

    # 簡略化: actions を最初から再生して ver.1/ver.2 を評価
    replayer_v1 = RecordReplayer(record, params)
    replayer_v2 = RecordReplayer(record, params)

    # actions を逐次処理して人間打牌時に AI 一致を見る
    actions = record.get('detail_records', {}).get('actions', [])
    v1_eval = _walk_actions(actions, replayer_v1, params, use_v2=False)
    v2_eval = _walk_actions(actions, replayer_v2, params, use_v2=True)

    return {
        'file': os.path.basename(record_path),
        'v1_total': v1_eval['total'],
        'v1_match': v1_eval['match'],
        'v2_total': v2_eval['total'],
        'v2_match': v2_eval['match'],
    }


def _walk_actions(actions: list, replayer: RecordReplayer, params: dict, use_v2: bool) -> dict:
    """
    actions を逐次処理。
    RecordDiscardTile 直前に state を構築して AI の best_discard を呼び、人間打牌と比較。
    """
    total = 0
    match = 0
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
                    chosen = ai.best_discard(hand)
                    if chosen:
                        total += 1
                        if chosen == tile:
                            match += 1
            except Exception as e:
                pass
            # 人間打牌を適用
            replayer._discard_tile(data)
        elif class_name == 'RecordChiPengGang':
            replayer._chi_peng_gang(data)
        elif class_name == 'RecordAnGangAddGang':
            replayer._an_gang_add_gang(data)
        # userInput はスキップ (AI は人間の打牌前に評価)

    return {'total': total, 'match': match}


def main(file_list: List[str], params_path: str):
    params = load_params(params_path)
    print(f"=== ver.1 vs ver.2 人間牌譜一致率テスト ===")
    print(f"  ファイル数: {len(file_list)}")
    print(f"  パラメータ: {params_path or '(default)'}")

    grand_v1_total = 0
    grand_v1_match = 0
    grand_v2_total = 0
    grand_v2_match = 0
    t0 = time.time()
    for i, fp in enumerate(file_list):
        try:
            r = process_record(fp, params)
            v1_pct = r['v1_match'] / r['v1_total'] * 100 if r['v1_total'] else 0
            v2_pct = r['v2_match'] / r['v2_total'] * 100 if r['v2_total'] else 0
            print(f"  [{i+1}/{len(file_list)}] {r['file']}: "
                  f"ver.1={r['v1_match']}/{r['v1_total']} ({v1_pct:.1f}%) "
                  f"ver.2={r['v2_match']}/{r['v2_total']} ({v2_pct:.1f}%)")
            grand_v1_total += r['v1_total']
            grand_v1_match += r['v1_match']
            grand_v2_total += r['v2_total']
            grand_v2_match += r['v2_match']
        except Exception as e:
            print(f"  [{i+1}/{len(file_list)}] {fp}: エラー ({type(e).__name__}: {e})")
            import traceback
            traceback.print_exc()

    print()
    print("=== 結果サマリ ===")
    if grand_v1_total:
        print(f"  ver.1 合計: {grand_v1_match}/{grand_v1_total} ({grand_v1_match/grand_v1_total*100:.1f}%)")
    if grand_v2_total:
        print(f"  ver.2 合計: {grand_v2_match}/{grand_v2_total} ({grand_v2_match/grand_v2_total*100:.1f}%)")
    if grand_v1_total and grand_v2_total:
        diff = (grand_v2_match/grand_v2_total - grand_v1_match/grand_v1_total) * 100
        print(f"  差分: ver.2 - ver.1 = {diff:+.1f}pt")
    print(f"  経過時間: {time.time() - t0:.1f}秒")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("files", nargs="+", help="trimmed.json ファイル (複数可)")
    p.add_argument("--params", type=str, default="config/config_parameters.json")
    args = p.parse_args()
    main(args.files, args.params)
