# -*- coding: utf-8 -*-
"""
@title 立直判断 重み 自動最適化 (人間挙動再現)
@description 天鳳DB の人間立直判断を目標に、ver.2 riichi_v2 の重みを自動調整
"""
import sys
import os
import sqlite3
import time
import json
import random

sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.game_state import GameState, ReachState, Meld
from core.riichi_v2 import (
    score_riichi, is_tenpai_closed, should_riichi, get_weights,
    DEFAULT_WEIGHTS
)


DB = r'C:\Users\Daikichi\Documents\code-workspace\雀魂ラッパー_拡散AI\data\raw\tenhou_logs.db'


def replay_actions(actions, target_seat):
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
            elif class_name == 'RecordDealTile':
                seat = data.get('seat')
                tile = data.get('tile')
                state.tsumo_count += 1
                if seat == target_seat and tile:
                    state.my_hand.append(tile)
            elif class_name == 'RecordDiscardTile':
                seat = data.get('seat')
                tile = data.get('tile')
                if seat == target_seat and tile:
                    if tile in state.my_hand:
                        state.my_hand.remove(tile)
            elif class_name == 'RecordReach':
                seat = data.get('seat')
                if seat is not None and 0 <= seat < 4:
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


def collect_riichi_decisions(n_logs=200, target_seat=0):
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
            for i, action in enumerate(actions):
                ar = action.get('result', {})
                cn = ar.get('class_name', '')
                ad = ar.get('data', {})
                seat = ad.get('seat')
                if cn == 'RecordDiscardTile' and seat == target_seat:
                    state = replay_actions(actions[:i+1], target_seat)
                    if is_tenpai_closed(state):
                        is_reach = bool(ad.get('isLiqi', False))
                        decisions.append((state, is_reach))
        except Exception:
            continue
    return decisions


def evaluate_weights(decisions, weights):
    """@title 人間立直判断 19% 立直率 + Recall 19% + Specificity 81% 目標"""
    tp = fp = fn = tn = 0
    for state, is_human_reach in decisions:
        # 評価用にweights差し替え
        from core.riichi_v2 import score_riichi as _score_riichi
        # 簡易: should_riichi の代わりに score を直接評価
        score, _ = _score_riichi(state, weights)
        # threshold = 0 (人間 19% 立直 目標なら 0 付近)
        ai_reach = score > 0
        if is_human_reach and ai_reach: tp += 1
        elif is_human_reach and not ai_reach: fn += 1
        elif not is_human_reach and ai_reach: fp += 1
        else: tn += 1
    total = tp + fp + fn + tn
    if total == 0:
        return 0.0, 0, 0, 0, 0
    recall = tp / max(1, tp + fn)
    specificity = tn / max(1, tn + fp)
    return recall * 100, specificity * 100, tp, fp, fn, tn


def main():
    print("天鳳 DB から 人間立直判断を抽出...")
    decisions = collect_riichi_decisions(n_logs=200)
    n_reach = sum(1 for _, r in decisions if r)
    n_dama = sum(1 for _, r in decisions if not r)
    print(f"判定事例: {len(decisions)} (人間リーチ: {n_reach} = {n_reach/len(decisions)*100:.1f}%, 人間ダマ: {n_dama} = {n_dama/len(decisions)*100:.1f}%)")

    # ベースライン
    print("\n=== ベースライン (現在 重み) ===")
    r, s, tp, fp, fn, tn = evaluate_weights(decisions, {})
    print(f"Recall: {r:.1f}%, Specificity: {s:.1f}%")
    print(f"TP={tp}, FP={fp}, FN={fn}, TN={tn}")

    # 重み スイープ: BASE を 変化 させて 人間 16% 立直 率 に 合わせる
    print("\n=== BASE スイープ (人間 16% 立直率 目標) ===")
    print(f"{'BASE':>8} | {'Recall':>8} | {'Spec':>8} | {'立直率':>8}")
    print("-" * 50)
    best_base = None
    best_distance = float('inf')
    for base in range(-300, 101, 25):
        w = dict(DEFAULT_WEIGHTS)
        w['RIICHI_W_BASE_SCORE'] = float(base)
        r, s, tp, fp, fn, tn = evaluate_weights(decisions, w)
        riichi_rate = (tp + fp) / max(1, tp + fp + fn + tn) * 100
        # 人間 16% 立直率 との 距離
        target_recall = 16.0
        target_spec = 84.0
        distance = abs(r - target_recall) + abs(s - target_spec)
        if distance < best_distance:
            best_distance = distance
            best_base = base
        print(f"{base:>8} | {r:>7.1f}% | {s:>7.1f}% | {riichi_rate:>7.1f}%")
    print(f"\n最適 BASE: {best_base} (距離: {best_distance:.1f})")

    # 最適 BASE で 全 重み 評価
    print(f"\n=== 最適 BASE = {best_base} ===")
    w = dict(DEFAULT_WEIGHTS)
    w['RIICHI_W_BASE_SCORE'] = float(best_base)
    r, s, tp, fp, fn, tn = evaluate_weights(decisions, w)
    print(f"Recall: {r:.1f}%, Specificity: {s:.1f}%")
    print(f"TP={tp}, FP={fp}, FN={fn}, TN={tn}")
    print(f"\n=== 推奨重み (config へ 統合) ===")
    print("RIICHI_W_BASE_SCORE:", w['RIICHI_W_BASE_SCORE'])


if __name__ == "__main__":
    main()
