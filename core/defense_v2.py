# -*- coding: utf-8 -*-
"""
@title ver.2 放銃警戒 & 安全度評価
@description 他家の仕掛け（リーチ、多副露、ドラポン）から放銃警戒度をリアルタイムに集計し、
              現物・スジ・無筋等の個別危険重みを合算して各牌の安全スコアを算出します。
"""
from __future__ import annotations
from typing import List

from str_converter import (
    tile_to_id,
    is_honor,
    suji_safe_tiles,
)


def is_dora_tile(state, tile_str: str) -> bool:
    """牌がドラまたは赤ドラか判定"""
    if tile_str and tile_str[0] == '0':
        return True
    from core.str_converter import dora_indicator_to_dora
    for d in state.doras:
        try:
            if dora_indicator_to_dora(d) == tile_str:
                return True
        except Exception:
            pass
    return False


def safety_score(state, tile: str) -> int:
    """
    @title 平沢麻雀パターンによる安全度スコア
    @description 他家放銃警戒度 (リーチ者・多副露者) への放銃リスクを 0-1000 で評価。
                1000=絶対安全, 0=現時点で最も危険。
    """
    try:
        tile_id = tile_to_id(tile)
    except Exception:
        return 0

    visible = state.all_visible_counts()
    my_counts = state.my_hand_counts()
    my_count = my_counts[tile_id]

    # === 1. ノーチャンス判定: 字牌のみ 1000 ===
    if is_honor(tile_id) and visible[tile_id] >= 4:
        return 1000

    # === 2. 他家放銃警戒度 (alert_seats) の判定 ===
    # リーチ者、および3副露以上、または2副露+ドラ鳴きの他家を警戒対象とする
    alert_seats = []
    for s in range(4):
        if s == state.my_seat:
            continue
        
        # 2-1. リーチしている他家
        if state.reach_states[s] is not None and state.reach_states[s].is_reach:
            alert_seats.append(s)
            continue
            
        # 2-2. 鳴き（副露）が多い他家のチェック
        open_meld_count = 0
        has_dora_in_melds = False
        for m in state.melds[s]:
            open_meld_count += 1
            for tile_str in getattr(m, 'tiles', []):
                if is_dora_tile(state, tile_str):
                    has_dora_in_melds = True

        # 3副露以上、または2副露かつドラを含んでいる場合は警戒対象とする
        if open_meld_count >= 3 or (open_meld_count >= 2 and has_dora_in_melds):
            alert_seats.append(s)

    # === 3. 警戒対象の現物判定 ===
    # 警戒対象全員にとって現物（絶対安全）であれば 1000 を返す
    if alert_seats:
        is_genbutsu_all = True
        for seat in alert_seats:
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
            return 1000  # 共通現物 = 絶対安全 (最優先で温存)

    # === 4. それ以外の危険度評価 ===
    if not alert_seats:
        public_count = visible[tile_id] - my_count
        return _non_reach_safety(state, tile_id, my_count, public_count)

    # 警戒対象あり: 各警戒対象に対する個別重みを合算して評価
    weights = _tile_remaining_weights(state, alert_seats, visible, my_counts)
    total = sum(weights)
    if total == 0:
        return 1000  # 全員に対して安全

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


def _tile_remaining_weights(state, alert_seats: List[int], visible: List[int], my_counts: List[int]) -> List[float]:
    """
    @title 平沢麻雀パターン: 各牌の「待ち重み」算出
    @description 各警戒対象に対する個別の待ち重みを算出し、それらの合計を返す。
                個別重み = 各警戒対象に対するロン待ち確率の指標。
    """
    total_weights = [0.0] * 34

    for seat in alert_seats:
        # この人単体に対する初期の重み
        seat_weights = [1.0] * 34

        # 現物 (フリテン含む) はこの人に対しては重み 0
        genbutsu = set()
        for t in state.river[seat]:
            try:
                genbutsu.add(tile_to_id(t))
            except Exception:
                continue
        for tid in range(34):
            if tid in genbutsu:
                seat_weights[tid] = 0.0

        for tid in range(34):
            if seat_weights[tid] == 0.0:
                continue

            is_h = is_honor(tid)
            no_chance = (visible[tid] >= 4)

            if is_h:
                # 字牌: 単騎 + 双碰 のみ
                if no_chance:
                    seat_weights[tid] = 0.0
                else:
                    seat_weights[tid] = 1.0 + 2.0
                continue

            # 数牌
            base = (tid // 9) * 9
            off = tid - base

            if no_chance:
                tanki_shanpon = 0.0
            else:
                tanki_shanpon = 1.0 + 2.0

            if off == 0 or off == 8:
                penchan = 3.0
                seat_weights[tid] = penchan + tanki_shanpon
            elif off == 1 or off == 7:
                kanchan = 3.0
                ryanmen = 10.0
                seat_weights[tid] = kanchan + ryanmen + tanki_shanpon
            elif off == 2 or off == 6:
                kanchan = 3.0
                penchan = 3.0
                ryanmen = 10.0
                seat_weights[tid] = kanchan + penchan + ryanmen + tanki_shanpon
            else:
                kanchan = 3.0
                ryanmen = 10.0 + 10.0
                seat_weights[tid] = kanchan + ryanmen + tanki_shanpon

        # ── 序盤捨て牌端安全度補正（この人の河の捨て牌に対してのみ適用） ──
        river_list = state.river[seat]
        for idx, discard_str in enumerate(river_list):
            try:
                discard_id = tile_to_id(discard_str)
            except Exception:
                continue
            if is_honor(discard_id):
                continue
            base = (discard_id // 9) * 9
            off = discard_id - base

            # A. 2切り→1, 8切り→9 (1〜5巡目、危険度70%減)
            if idx < 5:
                if off == 1:
                    target = base + 0
                    seat_weights[target] *= 0.3
                elif off == 7:
                    target = base + 8
                    seat_weights[target] *= 0.3

            # B, C. 3切り→1, 7切り→9, 1切り→2, 9切り→8 (1〜3巡目、危険度25%減)
            if idx < 3:
                if off == 2:
                    target = base + 0
                    seat_weights[target] *= 0.75
                elif off == 6:
                    target = base + 8
                    seat_weights[target] *= 0.75
                elif off == 0:
                    target = base + 1
                    seat_weights[target] *= 0.75
                elif off == 8:
                    target = base + 7
                    seat_weights[target] *= 0.75

        # この人に対する重みを全体の合計に加算
        for tid in range(34):
            total_weights[tid] += seat_weights[tid]

    return total_weights
