# -*- coding: utf-8 -*-
"""
@title ver.2 役満モード
@description 役満進行中の特殊タプル。
              国士無双は特殊、他の役満はグループ化 (字牌系/幺九系/一色系)。
"""
from __future__ import annotations
from typing import Tuple, Optional

from core.shanten_v2 import ShantenCalculatorV2
from str_converter import (
    tile_to_id,
    is_honor,
    is_terminal,
    SANGEN_IDS,
    KAZE_IDS,
)


# 役満種類
YAKUMAN_TYPES = {
    'kokushi': '国士無双',
    'suuankou': '四暗刻',
    'daisuushii': '大四喜',
    'shousuushii': '小四喜',
    'daisangen': '大三元',
    'tsuuiisou': '字一色',
    'chinroutou': '清老頭',
    'ryuuiisou': '緑一色',
    'chuuren': '九蓮宝燈',
    'suukantsu': '四槓子',
}

# グループ化:
# - kokushi: 特殊 (幺九牌絶対残し)
# - 字牌系: daisuushii, shousuushii, daisangen, tsuuiisou (風牌・三元牌)
# - 幺九系: chinroutou, chuuren (端牌)
# - 一色系: ryuuiisou (緑一色: 2345678 + 發 の特殊牌)
# - 暗刻系: suuankou (暗刻)
# - 槓子系: suukantsu (槓子)


def detect_yakumans(state) -> dict:
    """
    @title 役満候補の検出
    @description 各役満の進行度を判定。
                役満の種類ごとにシャンテン数や完成確率を返す。
    @returns {yakuman_type: {'possible': bool, 'shanten': int, 'progress': float}}
    """
    results = {}
    hand_counts = state.my_hand_counts()
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)

    # 国士無双
    yao = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
    unique = sum(1 for i in yao if hand_counts[i] >= 1)
    has_pair = any(hand_counts[i] >= 2 for i in yao)
    if unique >= 10:
        shanten = 13 - unique - (1 if has_pair else 0)
        results['kokushi'] = {
            'possible': True,
            'shanten': shanten,
            'progress': max(0, min(1, (13 - shanten) / 13.0)),
        }

    # 大四喜 / 小四喜
    wind_count = sum(hand_counts[i] for i in range(27, 31))
    if wind_count >= 8:
        results['daisuushii'] = {'possible': True, 'shanten': 0, 'progress': 0.8}
    elif wind_count >= 5:
        results['shousuushii'] = {'possible': True, 'shanten': 1, 'progress': 0.5}

    # 大三元
    sangen_count = sum(hand_counts[i] for i in SANGEN_IDS)
    if sangen_count >= 8:
        results['daisangen'] = {'possible': True, 'shanten': 0, 'progress': 0.8}

    # 字一色
    if open_meld_count == 0:
        all_honor = all(
            is_honor(tile_to_id(t))
            for t in state.my_hand
        )
        if all_honor and len(state.my_hand) >= 14:
            results['tsuuiisou'] = {'possible': True, 'shanten': 0, 'progress': 0.7}

    # 清老頭
    all_terminal = all(
        is_terminal(tile_to_id(t)) or is_honor(tile_to_id(t))
        for t in state.my_hand
    )
    all_terminal_pure = all(
        is_terminal(tile_to_id(t)) for t in state.my_hand
    )
    if all_terminal_pure and len(state.my_hand) >= 14:
        results['chinroutou'] = {'possible': True, 'shanten': 0, 'progress': 0.7}

    return results


def get_active_yakuman(state) -> Optional[str]:
    """
    @title 現在進行中の役満を取得
    @description 進行度が最も高い役満を返す
    @returns yakuman_type (str) or None
    """
    detected = detect_yakumans(state)
    if not detected:
        return None
    best_type = None
    best_progress = -1
    for yakuman_type, info in detected.items():
        if info['progress'] > best_progress:
            best_progress = info['progress']
            best_type = yakuman_type
    return best_type


def yakuman_tuple(state, tile: str, yakuman_type: str) -> Tuple:
    """
    @title 役満モードのタプル
    @description 役満進行度に応じて特殊タプルを返す。
    """
    from core.tactical_rank_v2 import tactical_discard_rank
    from core.defense_v2 import safety_score

    hand_counts = list(state.my_hand_counts())
    discard_id = tile_to_id(tile)
    if 0 <= discard_id < 34:
        hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    shanten = ShantenCalculatorV2.calculate_closed(hand_counts) if open_meld_count == 0 else ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

    # 受け入れ計算
    visible = state.all_visible_counts()
    my_counts = state.my_hand_counts()
    good = 0
    bad = 0
    for tid in range(34):
        if hand_counts[tid] >= 4:
            continue
        test = list(hand_counts)
        test[tid] += 1
        if open_meld_count == 0:
            ns = ShantenCalculatorV2.calculate_closed(test)
        else:
            ns = ShantenCalculatorV2.calculate_open(test, open_meld_count)
        if ns >= shanten:
            continue
        remaining = 4 - visible[tid]
        if remaining <= 0:
            continue
        good += remaining
    ukeire = good + bad

    # 役満別特殊ランク
    yakuman_garbage = _yakuman_garbage_rank(state, tile_id, yakuman_type)
    dora_loss = _dora_loss(state, discard_id)
    saf = safety_score(state, tile)

    detected = detect_yakumans(state)
    progress = detected.get(yakuman_type, {}).get('progress', 0)

    return (shanten, -ukeire, -int(progress * 100), yakuman_garbage, dora_loss, -saf)


def _yakuman_garbage_rank(state, tile_id: int, yakuman_type: str) -> int:
    """
    @title 役満の特殊ゴミ度
    @description 役満ごとに守るべき牌を判定し、ガーベッジランクを返す。
                0=真っ先に切る, 9=絶対残す
    """
    if yakuman_type == 'kokushi':
        return 9 if (is_honor(tile_id) or is_terminal(tile_id)) else 0

    if yakuman_type in ('daisuushii', 'shousuushii'):
        return 9 if tile_id in KAZE_IDS else 0

    if yakuman_type == 'daisangen':
        return 9 if tile_id in SANGEN_IDS else 0

    if yakuman_type == 'tsuuiisou':
        return 9 if is_honor(tile_id) else 0

    if yakuman_type == 'chinroutou':
        return 9 if is_terminal(tile_id) else 0

    if yakuman_type == 'ryuuiisou':
        # 緑一色: 2345678 + 発 (字牌)
        ryuu = [19, 20, 21, 22, 23, 24, 25, 23, 32]
        return 9 if (is_honor(tile_id) or tile_id in ryuu) else 0

    if yakuman_type == 'suuankou':
        # 暗刻
        return 9 if state.my_hand_counts()[tile_id] >= 2 else 0

    if yakuman_type == 'chuuren':
        # 九蓮宝燈: 1 色の 1-9 (端含む)
        if not is_honor(tile_id) and is_terminal(tile_id):
            return 9
        return 5

    if yakuman_type == 'suukantsu':
        return 0  # 槓子は 4 組できるなら OK

    return 0


def _dora_loss(state, tid: int) -> int:
    """@title ドラ表示牌を捨てる際の損失"""
    loss = 0
    for d in state.doras:
        try:
            if tile_to_id(d) == tid:
                loss += 1
        except Exception:
            pass
    return loss
