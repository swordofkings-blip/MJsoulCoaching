# -*- coding: utf-8 -*-
"""
@title ver.2 立直判断 vs 天鳳人間判断 一致率テスト
@description 天鳳ログから人間立直判断を正解データとして抽出、ver.2 riichi_v2 との一致率を測定。
              雀魂牌譜では不足する人間判断データを補完する。

抽出パターン:
  1. RecordReach → 人間が立直 (正解: 立直)
  2. RecordDiscardTile (リーチしていない) → 人間がダマテン → 立直 しない (正解: 立直 しない)
  3. 人間がツモった後にリーチせず打牌 → ダマテン を選択
"""
from __future__ import annotations

import sys
import os
import sqlite3
import time
import json

sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.game_state import GameState, ReachState, Meld
from core.riichi_v2 import should_riichi, score_riichi, is_tenpai_closed
from core.shanten_v2 import ShantenCalculatorV2
from str_converter import hand_to_counts


DB = r'C:\Users\Daikichi\Documents\code-workspace\雀魂ラッパー_拡散AI\data\raw\tenhou_logs.db'


def replay_actions(actions: list, target_seat: int) -> GameState:
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
                    # 自分の捨牌なら手牌から削除
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
                    # 副露牌 3 枚 を 削除 (froms は 含まない)
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
                    meld.is_open = (meld_type == 2)  # 大明槓
                    if not hasattr(state, 'my_melds') or state.my_melds is None:
                        state.my_melds = []
                    state.my_melds.append(meld)
        except Exception as e:
            continue
    return state


def extract_riichi_decisions(actions: list) -> list:
    """
    @title 牌譜から立直判断事例を抽出
    @returns [(state, is_human_riichi), ...]
              is_human_riichi: 人間がリーチしたか (True/False)
              0 待ち (winning) で isLiqi=True 捨牌 → リーチ = 正解 True
              0 待ち (winning) で isLiqi=False 捨牌 → ダマテン = 正解 False
    """
    decisions = []
    target_seat = 0  # 簡略: 仮親視点

    for i, action in enumerate(actions):
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})
        seat = data.get('seat')

        if class_name == 'RecordDiscardTile' and seat == target_seat:
            # 捨牌局面で state 再生してリーチ判定
            state = replay_actions(actions[:i+1], target_seat)
            if is_tenpai_closed(state):
                # 人間がリーチしたか = isLiqi=True 捨牌
                is_reach = bool(data.get('isLiqi', False))
                decisions.append((state, is_reach))

    return decisions


def main():
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute("SELECT id, log FROM logs WHERE is_processed=1 AND was_error=0 LIMIT 200")
    rows = cur.fetchall()
    conn.close()
    print(f"DB から {len(rows)} 牌譜取得")

    tp = 0  # True Positive: 人間立直 → AI 立直
    fp = 0  # False Positive: 人間ダマ → AI 立直
    fn = 0  # False Negative: 人間立直 → AI ダマ
    tn = 0  # True Negative: 人間ダマ → AI ダマ

    processed = 0
    t0 = time.time()
    for log_id, log_blob in rows:
        try:
            result = tenhou_blob_to_actions(log_blob)
            if isinstance(result, tuple):
                head, n_rounds = result
                actions = head.get('detail_records', {}).get('actions', [])
            else:
                actions = result
            decisions = extract_riichi_decisions(actions)
            if processed < 3:
                print(f'{log_id[:30]}: actions={len(actions)} decisions={len(decisions)}', flush=True)
                discards = [a for a in actions if a.get('result', {}).get('class_name') == 'RecordDiscardTile']
                reaches = [a for a in actions if a.get('result', {}).get('class_name') == 'RecordReach']
                print(f'  捨牌={len(discards)}, 立直={len(reaches)}', flush=True)
            for state, is_human_reach in decisions:
                if not is_tenpai_closed(state):
                    continue
                ai_decision = should_riichi(state, {})
                if is_human_reach and ai_decision:
                    tp += 1
                elif is_human_reach and not ai_decision:
                    fn += 1
                elif not is_human_reach and ai_decision:
                    fp += 1
                else:
                    tn += 1
            processed += 1
            if processed % 50 == 0:
                elapsed = time.time() - t0
                print(f"... {processed} 牌譜処理 ({elapsed:.1f}s, decisions={len(decisions)})")
        except Exception as e:
            continue

    elapsed = time.time() - t0
    total = tp + fp + fn + tn
    if total == 0:
        print("判定事例 0")
        return

    recall = tp / max(1, tp + fn) * 100
    specificity = tn / max(1, tn + fp) * 100
    accuracy = (tp + tn) / total * 100
    precision = tp / max(1, tp + fp) * 100
    print(f"\n=== 立直判断 一致率テスト (天鳳人間判断 vs ver.2 riichi_v2) ===")
    print(f"判定事例: {total} (人間リーチ: {tp+fn}, 人間ダマ: {tn+fp})")
    print(f"TP: {tp}, FP: {fp}, FN: {fn}, TN: {tn}")
    print(f"Recall (リーチ感度): {recall:.1f}%")
    print(f"Specificity (ダマ特異度): {specificity:.1f}%")
    print(f"Precision (適合率): {precision:.1f}%")
    print(f"Accuracy (正解率): {accuracy:.1f}%")
    print(f"経過: {elapsed:.1f}s ({processed} 牌譜)")


if __name__ == "__main__":
    main()
