# -*- coding: utf-8 -*-
"""
@title 人間押し引き判断 一致率テスト + 重み自動最適化
@description 天鳳DBから人間押し引き判断事例を抽出、ver.2 push_fold_v2 との一致率を測定。
              その後、重みを自動スイープして人間挙動との一致率を最大化。

抽出パターン:
  - 押し: 1シャンテン or テンパイ で 5巡以上 連続 捨牌 (= 攻め続行)
  - オリ: 1シャンテン or テンパイ で 流局 まで 行く (= 攻め諦め)
"""
from __future__ import annotations

import sys
import os
import sqlite3
import time
import json
import random
import copy

sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.game_state import GameState, ReachState, Meld
from core.push_fold_v2 import (
    judge_push_fold, get_safe_tiles, DEFAULT_RULES,
    get_suji_tiles,
)
from core.shanten_v2 import ShantenCalculatorV2
from str_converter import hand_to_counts


DB = r'C:\Users\Daikichi\Documents\code-workspace\雀魂ラッパー_拡散AI\data\raw\tenhou_logs.db'


def replay_actions(actions, target_seat):
    """牌譜を target_seat から見た GameState として再生"""
    state = GameState()
    state.my_seat = target_seat
    state.reach_states = [ReachState() for _ in range(4)]
    state.scores = [25000, 25000, 25000, 25000]
    for action in actions:
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})
        try:
            if class_name == 'RecordNewRound':
                state.my_hand = []
                state.my_melds = []
                state.doras = list(data.get('doras', []))
                state.scores = list(data.get('scores', [25000]*4))
                state.left_tile_count = data.get('leftTileCount', 70)
                state.my_hand = list(data.get(f'tiles{target_seat}', []))
                state.chang = data.get('chang', 0)
                state.ju = data.get('ju', 0)
                state.tsumo_count = 0
                state.dealer_seat = data.get('ju', 0)
                state.river = [[] for _ in range(4)]
            elif class_name == 'RecordDealTile':
                seat = data.get('seat')
                tile = data.get('tile')
                state.tsumo_count += 1
                if seat == target_seat and tile:
                    state.my_hand.append(tile)
            elif class_name == 'RecordDiscardTile':
                seat = data.get('seat')
                tile = data.get('tile')
                if seat == target_seat and tile and tile in state.my_hand:
                    state.my_hand.remove(tile)
                if seat is not None and 0 <= seat < 4:
                    if len(state.river) < 4:
                        state.river = [[] for _ in range(4)]
                    if len(state.river[seat]) < 30:
                        state.river[seat].append(tile)
                # リーチ判定
                is_liqi = data.get('isLiqi', False)
                if is_liqi and 0 <= seat < 4:
                    state.reach_states[seat].is_reach = True
                    state.reach_states[seat].reach_turn = state.tsumo_count
            elif class_name == 'RecordChiPengGang':
                seat = data.get('seat')
                if seat == target_seat:
                    meld_type = data.get('type')
                    tiles = data.get('tiles', [])
                    from_who = data.get('from')
                    for t in tiles[:3]:
                        if t in state.my_hand:
                            state.my_hand.remove(t)
                    meld = Meld()
                    meld.type = meld_type
                    meld.tiles = tiles
                    meld.froms = [from_who] if from_who is not None else []
                    meld.is_open = True
                    if not hasattr(state, 'my_melds') or state.my_melds is None:
                        state.my_melds = []
                    state.my_melds.append(meld)
            elif class_name == 'RecordAnGangAddGang':
                seat = data.get('seat')
                if seat == target_seat:
                    meld_type = data.get('type')
                    tiles = data.get('tiles', [])
                    for t in tiles[:4]:
                        if t in state.my_hand:
                            state.my_hand.remove(t)
                    meld = Meld()
                    meld.type = meld_type
                    meld.tiles = tiles
                    meld.froms = []
                    meld.is_open = (meld_type == 2)
                    if not hasattr(state, 'my_melds') or state.my_melds is None:
                        state.my_melds = []
                    state.my_melds.append(meld)
        except Exception:
            continue
    return state


def collect_push_fold_decisions(n_logs=200, target_seat=0):
    """
    @title 人間押し引き判断 事例 抽出
    @returns [(state, shanten, is_human_push, score), ...]
              is_human_push: True = 押し (5巡連続捨牌), False = オリ (流局)
    """
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, log FROM logs WHERE is_processed=1 AND was_error=0 LIMIT ?", (n_logs,))
    rows = cur.fetchall()
    conn.close()

    decisions = []
    for log_id, log_blob in rows:
        try:
            result = tenhou_blob_to_actions(log_blob)
            if isinstance(result, tuple):
                head, _ = result
                actions = head.get('detail_records', {}).get('actions', [])
            else:
                actions = result
            # 各局で 人間 の 押す/オリ を 判定
            cur_round = []
            for action in actions:
                ar = action.get('result', {})
                cn = ar.get('class_name', '')
                ad = ar.get('data', {})
                if cn == 'RecordNewRound':
                    cur_round = [action]
                elif cn == 'RecordNoTile':
                    # 流局 = オリ判定
                    # 局終了直前 (1シャンテン or テンパイ) で抽出
                    for i, a in enumerate(cur_round):
                        ar2 = a.get('result', {})
                        cn2 = ar2.get('class_name', '')
                        if cn2 == 'RecordDiscardTile' and ar2.get('data', {}).get('seat') == target_seat:
                            state = replay_actions(cur_round[:i+1], target_seat)
                            counts = hand_to_counts(state.my_hand)
                            sh = ShantenCalculatorV2.calculate_open(
                                counts, sum(1 for m in state.my_melds if m.is_open))
                            if 0 <= sh <= 1:
                                decisions.append((state, sh, False))  # オリ
                    cur_round = []
                elif cn in ('RecordHule', 'RecordRonAgari', 'RecordTsumoAgari'):
                    # 和了 = 押し判定 (テンパイ or 1シャンテン で 局 終了)
                    for i, a in enumerate(cur_round):
                        ar2 = a.get('result', {})
                        cn2 = ar2.get('class_name', '')
                        if cn2 == 'RecordDiscardTile' and ar2.get('data', {}).get('seat') == target_seat:
                            state = replay_actions(cur_round[:i+1], target_seat)
                            counts = hand_to_counts(state.my_hand)
                            sh = ShantenCalculatorV2.calculate_open(
                                counts, sum(1 for m in state.my_melds if m.is_open))
                            if 0 <= sh <= 1:
                                decisions.append((state, sh, True))  # 押し
                    cur_round = []
                else:
                    cur_round.append(action)
        except Exception:
            continue
    return decisions


def evaluate_push_fold(decisions, params):
    """
    @title 押し引き 一致率 評価
    @returns dict with recall, specificity, accuracy
    """
    tp = fp = fn = tn = 0
    for state, shanten, is_human_push in decisions:
        decision, _ = judge_push_fold(state, shanten, ukeire=None, params=params)
        # AI の 押し = 'push' or 'neutral' (中立=押す寄り), オリ = 'fold'
        # 人間挙動 と 一致 判定
        ai_push = decision in ('push', 'neutral')
        if is_human_push and ai_push: tp += 1
        elif is_human_push and not ai_push: fn += 1
        elif not is_human_push and ai_push: fp += 1
        else: tn += 1
    total = tp + fp + fn + tn
    if total == 0:
        return {'recall': 0, 'specificity': 0, 'accuracy': 0, 'tp': 0, 'fp': 0, 'fn': 0, 'tn': 0}
    return {
        'recall': tp / max(1, tp + fn) * 100,
        'specificity': tn / max(1, tn + fp) * 100,
        'accuracy': (tp + tn) / total * 100,
        'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn,
    }


def main():
    print("天鳳 DB から 人間押し引き判断を抽出...")
    decisions = collect_push_fold_decisions(n_logs=200)
    n_push = sum(1 for _, _, p in decisions if p)
    n_fold = sum(1 for _, _, p in decisions if not p)
    print(f"判定事例: {len(decisions)} (人間押し: {n_push} = {n_push/max(1,len(decisions))*100:.1f}%, 人間オリ: {n_fold} = {n_fold/max(1,len(decisions))*100:.1f}%)")

    # ベースライン
    print("\n=== ベースライン (現在 重み) ===")
    res = evaluate_push_fold(decisions, {})
    print(f"Recall: {res['recall']:.1f}%, Specificity: {res['specificity']:.1f}%, Accuracy: {res['accuracy']:.1f}%")
    print(f"TP={res['tp']}, FP={res['fp']}, FN={res['fn']}, TN={res['tn']}")

    # 重み スイープ: 配分 比率 (手牌 vs 場況)
    print("\n=== 配分 比率 スイープ (手牌 w × 場況 w) ===")
    print(f"{'hand_w':>8} | {'sit_w':>8} | {'Recall':>8} | {'Spec':>8} | {'Acc':>8}")
    print("-" * 60)
    best = None
    best_acc = 0
    for hand_w in [1.0, 0.7, 0.5, 0.3]:
        for sit_w in [1.0, 1.3, 1.5, 1.8, 2.0]:
            w = dict(DEFAULT_RULES)
            w['_HAND_WEIGHT'] = hand_w
            w['_SITUATION_WEIGHT'] = sit_w
            res = evaluate_push_fold(decisions, w)
            if res['accuracy'] > best_acc:
                best_acc = res['accuracy']
                best = (hand_w, sit_w)
            print(f"{hand_w:>8.2f} | {sit_w:>8.2f} | {res['recall']:>7.1f}% | {res['specificity']:>7.1f}% | {res['accuracy']:>7.1f}%")
    print(f"\n最適 配分: hand={best[0]}, sit={best[1]} (Accuracy: {best_acc:.1f}%)")

    # 最適 配分 で ベース バイアス スイープ
    print(f"\n=== 最適 配分 + ベース バイアス スイープ (hand={best[0]}, sit={best[1]}) ===")
    print(f"{'BASE':>8} | {'Recall':>8} | {'Spec':>8} | {'Acc':>8}")
    print("-" * 50)
    best_base = None
    best_base_acc = 0
    for base in range(-100, 101, 25):
        w = dict(DEFAULT_RULES)
        w['_HAND_WEIGHT'] = best[0]
        w['_SITUATION_WEIGHT'] = best[1]
        w['_BASE_BIAS'] = float(base)
        res = evaluate_push_fold(decisions, w)
        if res['accuracy'] > best_base_acc:
            best_base_acc = res['accuracy']
            best_base = base
        print(f"{base:>8} | {res['recall']:>7.1f}% | {res['specificity']:>7.1f}% | {res['accuracy']:>7.1f}%")
    print(f"\n最適 配分+BASE: hand={best[0]}, sit={best[1]}, BASE={best_base} (Accuracy: {best_base_acc:.1f}%)")


if __name__ == "__main__":
    main()
