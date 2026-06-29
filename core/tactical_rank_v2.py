# -*- coding: utf-8 -*-
"""
@title ver.2 戦術的切りやすさランク
@description 牌の「切りやすさ」を 0-99 の整数で評価する。
              麻雀セオリーを 1 つの巨大な if-else 関数として言語化。
              0=真っ先に切る、99=絶対残す。

設計方針:
- 各 if ブロックが麻雀セオリーの 1 ルール (上から順に評価)
- 同じランク内では +1 単位で枝番を表現
- 新しいセオリー概念を挟むときは中間に +1 単位の if ブロックを追加
- 0-9: 字牌 (安全性重視)
- 10-29: 端牌 (1, 9)
- 30-39: 2, 8 牌
- 40-49: 中張孤立
- 50-59: 雀頭候補
- 60-69: 暗刻/槓子
- 70-79: ドラ・赤5
- 80-89: 役満進行中
- 90-99: 絶対残す
"""
from __future__ import annotations

from str_converter import (
    tile_to_id,
    id_to_tile,
    is_honor,
    is_red_five,
    is_terminal,
    HONOR_IDS,
)

# 三元牌: 白 (31), 發 (32), 中 (33)
SANGEN_IDS = (31, 32, 33)
# 風牌: 東 (27), 南 (28), 西 (29), 北 (30)
KAZE_IDS = (27, 28, 29, 30)


def tactical_discard_rank(state, tile: str) -> int:
    """
    @title 戦術的切りやすさランク (0-99)
    @description 牌の「切りやすさ」を 0-99 の整数で評価。
                麻雀セオリーを if-else 連鎖で完全に言語化。
                0=真っ先に切る、99=絶対残す。

    @param state - GameState
    @param tile - 評価対象の牌 ('1m', '5z' など)
    @returns int (0-99)
    """
    try:
        tile_id = tile_to_id(tile)
    except Exception:
        return 50

    if not (0 <= tile_id < 34):
        return 50

    is_red = is_red_five(tile)
    is_h = is_honor(tile_id)
    is_term = is_terminal(tile_id)

    visible = state.all_visible_counts()
    my_counts = state.my_hand_counts()
    my_count = my_counts[tile_id]
    public_count = visible[tile_id] - my_count  # 相手視点での見えている枚数

    is_dora = _is_dora(state, tile_id)
    is_yakuhai = _is_yakuhai(state, tile_id)
    is_28 = (not is_term) and (not is_h) and (tile_id % 9 in (1, 7))

    # === 段 1: 3 枚以上 (暗刻) は絶対残す (rank 99) ===
    if my_count >= 3:
        if is_dora:
            return 99  # ドラ暗刻は絶対残す
        return 95  # 暗刻も基本残す

    # === 段 2: 2 枚 (雀頭) ===
    if my_count == 2:
        # ドラ雀頭 (rank 75)
        if is_dora:
            return 75
        # ドラでない雀頭
        if is_h:
            return 55  # 字牌の雀頭 (役牌以外は切る)
        elif is_term:
            return 52  # 端牌の雀頭
        elif is_28:
            return 51  # 28 雀頭
        else:
            return 50  # 中張雀頭

    # === 段 3: 1 枚 (ここから先、孤立 or 搭子) ===

    # === 段 3-1: 字牌 ===
    if is_h:
        # ドラ字牌 (rank 78)
        if is_dora:
            return 78
        # 役牌 (rank 55-65)
        if is_yakuhai:
            # 全 4 枚見え (= 残 0 枚) → 刻子が作れない (rank 4)
            if public_count + my_count >= 4:
                return 4
            # 残あり → 刻子狙いなので残す (rank 60)
            return 60
        # 客風 (オタ風)
        # 2 枚以上見え → 真っ先に切る (rank 0)
        if public_count >= 2:
            return 0
        # 1 枚見え → 早く切る (rank 1)
        if public_count == 1:
            return 1
        # 生牌 → 重なるリスクあり (rank 2)
        return 2

    # === 段 3-2: ドラ・赤ドラ ===
    if is_dora:
        return 85
    if is_red:
        return 80

    # === 段 3-3: 端牌 (1, 9) ===
    if is_term:
        # ドラ隣接 (両面変化あり) → 残す (rank 35)
        if _is_adjacent_to_dora(state, tile_id):
            return 35
        # 孤立端牌 → 真っ先に切る (rank 10)
        if not _has_adjacent_tiles(state, my_counts, tile_id):
            return 10
        # 端牌でも隣接あり → 搭子扱い (rank 50)
        return 50

    # === 段 3-4: 2, 8 牌 ===
    if is_28:
        # ドラ隣接 (rank 38)
        if _is_adjacent_to_dora(state, tile_id):
            return 38
        # 孤立 28 → 切る (rank 20)
        if not _has_adjacent_tiles(state, my_counts, tile_id):
            return 20
        # 28 でも隣接あり → 搭子扱い (rank 45)
        return 45

    # === 段 3-5: 中張牌 (3-7) ===
    # ドラ隣接 (rank 40)
    if _is_adjacent_to_dora(state, tile_id):
        return 40
    # 孤立中張 → 残す価値あり (rank 30)
    if not _has_adjacent_tiles(state, my_counts, tile_id):
        return 30
    # 中張搭子 → 手作り核心 (rank 60)
    return 60


# ============================================================
# ヘルパー: 判定関数 (条件チェックのみ、ランク計算は含まない)
# ============================================================

def _is_dora(state, tile_id: int) -> bool:
    """
    @title ドラ表示牌と一致するか (赤ドラ含む)
    """
    for d in state.doras:
        try:
            if tile_to_id(d) == tile_id:
                return True
        except Exception:
            pass
    return False


def _is_yakuhai(state, tile_id: int) -> bool:
    """
    @title 役牌 (三元牌・自風・場風) かどうか
    """
    if tile_id in SANGEN_IDS:
        return True
    seat_wind = 27 + ((state.my_seat - state.ju) % 4)
    round_wind = 27 + (state.chang % 4)
    return tile_id in (seat_wind, round_wind)


def _has_adjacent_tiles(state, my_counts, tile_id: int) -> bool:
    """
    @title 手牌内に隣接牌 (両面・カンチャン・ペンチャン) があるか
    @description 切った牌の隣接位置 (左右 1, 2) に手牌内牌があるか
    """
    if tile_id >= 27:
        return False
    if tile_id < 0 or tile_id >= 34:
        return False

    if tile_id < 9:
        base = 0
    elif tile_id < 18:
        base = 9
    else:
        base = 18
    off = tile_id - base

    if my_counts[tile_id] >= 2:
        return True  # 雀頭扱い

    # 隣接牌 (左右 1 つ)
    for delta in (-1, 1):
        adj = off + delta
        if 0 <= adj <= 8:
            if my_counts[base + adj] >= 1:
                return True

    # 1 つ飛ばし (カンチャン)
    for delta in (-2, 2):
        adj = off + delta
        if 0 <= adj <= 8:
            if my_counts[base + adj] >= 1:
                return True

    return False


def _is_adjacent_to_dora(state, tile_id: int) -> bool:
    """
    @title ドラ表示牌の隣接牌 (±1) かどうか
    @description ドラの両隣 (例: ドラ 5m → 4m, 6m) は両面変化として残す価値あり
    """
    if tile_id >= 27:
        return False

    for d in state.doras:
        try:
            d_id = tile_to_id(d)
            if d_id >= 27:
                continue
            if abs(tile_id - d_id) == 1:
                return True
        except Exception:
            pass
    return False
