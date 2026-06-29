# -*- coding: utf-8 -*-
"""
@title ver.2 防御評価
@description 平沢麻雀パターン理論 (ver.1 の `_tile_remaining_weights` を純化移植) による
              牌の安全度評価。電将パターンとは別物 (user 確認済み)。

重要: 4 枚見え (ノーチャンス) の扱いに注意
- 字牌 (Winds/Dragons): 4 枚見え = 100% 安全 (シーケンス作れないのでロンされない)
- 数牌 (数牌): 4 枚見えでも両面/カンチャン待ちでロンされ得る (100% ではない)

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
                1000=絶対安全, 0=現時点で最も危険。

                絶対安全 (1000) は 2 通り:
                1. 現物 (フリテン現物): リーチ者の河にその牌がある
                2. 4 枚見えの字牌: 単騎/双碰/国士無双待ちにもできない

                4 枚見えの数牌は:
                - 単騎/双碰 は除外
                - 両面/カンチャン待ちではロンされ得る (安全ではない)
                - 端牌 (1, 9) はペンチャン待ちでもロンされ得る
    """
    try:
        tile_id = tile_to_id(tile)
    except Exception:
        return 0

    visible = state.all_visible_counts()
    my_counts = state.my_hand_counts()
    my_count = my_counts[tile_id]

    # === 1. ノーチャンス判定: 字牌のみ 1000 ===
    # 字牌は 4 枚見えならシーケンス系待ちが存在しないため完全安全
    if is_honor(tile_id) and visible[tile_id] >= 4:
        return 1000

    # === 2. リーチ者の現物 (フリテン現物) 判定 ===
    # リーチしている他家全員の河にその牌があるなら絶対安全 (数牌・字牌共通)
    reach_seats = []
    for s in range(4):
        if s == state.my_seat:
            continue
        if state.reach_states[s] is not None and state.reach_states[s].is_reach:
            reach_seats.append(s)

    if reach_seats:
        is_genbutsu_all = True
        for seat in reach_seats:
            river_ids = set()
            for t in state.river[seat]:
                try:
                    river_ids.add(tile_to_id(t))
                except Exception:
                    continue
            if tile_id not in river_ids:
                is_genbutsu_all = False
                break
        if is_genbutsu_all:
            return 1000  # 全リーチ者の現物 = 絶対安全

    # === 3. それ以外の危険度評価 ===
    if not reach_seats:
        # リーチ者なし: 行列マトリクス or スジ判定
        public_count = visible[tile_id] - my_count
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
    if public_count == 0 and my_count == 1:
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

                重要な待ちの種類:
                - 単騎 (Tanki): 1 枚残りで待ち
                - 双碰 (Shanpon): 2 枚残りで待ち
                - 両面 (Ryanmen): 隣接牌どちらかの残り枚数
                - カンチャン (Kanchan): 両隣 1 つずつの残り枚数
                - ペンチャン (Penchan): 端牌 2, 8 の残り枚数

                4 枚見え (visible[tid] >= 4) の場合:
                - 字牌: シーケンス系待ちが存在しない → 0 (絶対安全)
                - 数牌: 単騎/双碰 は除外、シーケンス系のみ残る

    平沢麻雀パターン (ユーザー確認済) での判定:
                - 4 枚見えの 5m: 上サイド両面 ◯, 下サイド両面 ◯, カンチャン ◯, ペンチャン ✗, 単騎 ✗, シャボ ✗
                - 4 枚見えの 9m: ペンチャン ◯ (1-2-3 順子の 3 待ちは無関係, 7-8-9 順子の 7 待ち), 単騎 ✗, シャボ ✗
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
        no_chance = (visible[tid] >= 4)  # 4 枚すべて見えている

        if is_h:
            # 字牌: 単騎 + 双碰 のみ
            if no_chance:
                # 4 枚見え → 単騎/双碰 不可、国士無双以外は完全安全
                # 簡略化のため 0 とする (国士無双は特殊処理が必要だが頻度低い)
                weights[tid] = 0.0
            else:
                weights[tid] = 1.0 + 2.0  # 単騎 + 双碰
            continue

        # 数牌: 待ちの形ごとに重みを設定
        base = (tid // 9) * 9
        off = tid - base

        if no_chance:
            # 4 枚見え → 単騎 (1.0) と 双碰 (2.0) は除外
            tanki_shanpon = 0.0
        else:
            tanki_shanpon = 1.0 + 2.0  # 単騎 + 双碰

        if off == 0 or off == 8:
            # 端牌 (1, 9): ペンチャン + 単騎
            # ペンチャン: 1-2-3 (off=0, 端牌 1) や 7-8-9 (off=8, 端牌 9) の待ちは 1m or 9m 自身
            # 4 枚見えでも 1m/9m が単騎/双碰 対象になるかは visibility 次第
            # ここでは保守的にペンチャン残す
            penchan = 3.0  # ペンチャン (1 or 9 待ち)
            weights[tid] = penchan + tanki_shanpon
        elif off == 1 or off == 7:
            # 2, 8: カンチャン + 両面
            # カンチャン: 1-3 待ち (off=1), 7-9 待ち (off=7)
            kanchan = 3.0
            # 両面: 2-3-4 (off=1, 3 待ち) や 7-8-9 (off=7, 6 待ち) は隣接牌側の重み
            # 厳密には上サイド (1 待ち) と下サイド (3 or 6 待ち) で別
            # 簡略化: 両面合計 10.0 とする
            ryanmen = 10.0
            weights[tid] = kanchan + ryanmen + tanki_shanpon
        elif off == 2 or off == 6:
            # 3, 7: カンチャン + ペンチャン + 両面
            kanchan = 3.0
            penchan = 3.0
            ryanmen = 10.0
            weights[tid] = kanchan + penchan + ryanmen + tanki_shanpon
        else:
            # 4, 5, 6: カンチャン + 両面 (両方向)
            kanchan = 3.0
            ryanmen = 10.0 + 10.0  # 上下両方向
            weights[tid] = kanchan + ryanmen + tanki_shanpon

    return weights
