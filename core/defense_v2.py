# -*- coding: utf-8 -*-
"""
@title ver.2 防御評価
@description 平沢麻雀パターン理論 (ver.1 の `_tile_remaining_weights` を純化移植) による
              牌の安全度評価。電将パターンとは別物 (user 確認済み)。
@returns 0-1000 (高い程安全)
"""
from __future__ import annotations
from typing import List

from str_converter import (
    tile_to_id,
    is_honor,
    suji_safe_tiles,
)


def safety_score(state, tile: str) -> int:
    """
    @title 平沢麻雀パターンによる安全度スコア
    @description リーチ者への放銃リスクを 0-1000 で評価。
                1000=現物 (絶対安全), 0=現時点で最も危険。
    """
    try:
        tile_id = tile_to_id(tile)
    except Exception:
        return 0

    visible = state.all_visible_counts()
    my_counts = state.my_hand_counts()
    my_count = my_counts[tile_id]
    public_count = visible[tile_id] - my_count  # 相手視点での見えている枚数

    # === 現物 (絶対安全) ===
    if public_count >= 4 - my_count:
        return 1000

    # === リーチ者を探す ===
    reach_seats = []
    for s in range(4):
        if s == state.my_seat:
            continue
        if state.reach_states[s].is_reach:
            reach_seats.append(s)

    if not reach_seats:
        return _non_reach_safety(state, tile_id, my_count, public_count)

    # リーチ者あり: 待ち重みを計算
    weights = _tile_remaining_weights(state, reach_seats, visible, my_counts)
    total = sum(weights)
    if total == 0:
        return 1000  # 全部 0 重み = 安全

    danger = weights[tile_id] / total
    score = int(1000 * (1.0 - danger))
    return max(0, min(1000, score))


def _non_reach_safety(state, tile_id: int, my_count: int, public_count: int) -> int:
    """
    @title リーチ者なし時の安全度
    @description 字牌は行列ベース、他は基本的な危険度で評価
    """
    if is_honor(tile_id):
        # 行列マトリクスで評価
        if public_count == 0 and my_count == 1:
            return 700  # 単騎のみ → 比較的危険
        if public_count == 1 and my_count == 1:
            return 500
        if public_count == 2 and my_count == 1:
            return 300
        if public_count >= 3 and my_count == 1:
            return 100
        if public_count == 0 and my_count == 2:
            return 200
        if public_count == 1 and my_count == 2:
            return 100
        return 50

    # 数牌: スジチェック
    visible = state.all_visible_counts()
    if public_count == 0 and my_count == 1:
        # 孤立牌
        return 600
    if public_count == 1 and my_count == 1:
        return 400
    if public_count >= 2 and my_count == 1:
        return 200
    if public_count == 0 and my_count == 2:
        return 300
    return 150


def _tile_remaining_weights(state, reach_seats: List[int], visible: List[int], my_counts: List[int]) -> List[float]:
    """
    @title 平沢麻雀パターン: 各牌の「待ち重み」算出
    @description リーチ者の待ちとして残りうる牌の重みを牌種ごとに算出。
                重み = 待ちの形ごとの残り枚数。
    """
    weights = [1.0] * 34  # 初期値 1.0 (現物のみ後で 0.0 に)

    # 現物 (フリテン含む) は重み 0
    for seat in reach_seats:
        genbutsu = set()
        for t in state.river[seat]:
            try:
                genbutsu.add(tile_to_id(t))
            except Exception:
                continue
        for tid in range(34):
            if tid in genbutsu:
                weights[tid] = 0.0

    for tid in range(34):
        if weights[tid] == 0.0:
            continue  # 現物はスキップ

        is_h = is_honor(tid)
        if is_h:
            # 字牌: 単騎 + 双碰
            if visible[tid] - my_counts[tid] < 4:
                weights[tid] = 1.0 + 2.0  # 単騎 + 双碰
            continue

        base = (tid // 9) * 9
        off = tid - base

        if off == 0 or off == 8:
            # 端牌: ペンチャン + 単騎
            weights[tid] = 3.0 + 1.0
        elif off == 1 or off == 7:
            # 2, 8: カンチャン + 両面
            weights[tid] = 3.0 + 10.0
        elif off == 2 or off == 6:
            # 3, 7: カンチャン + ペンチャン + 両面
            weights[tid] = 3.0 + 3.0 + 10.0
        else:
            # 4, 5, 6: カンチャン + 両面 (両方向)
            weights[tid] = 3.0 + 10.0 + 10.0

    return weights
