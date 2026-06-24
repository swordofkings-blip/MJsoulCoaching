# -*- coding: utf-8 -*-
"""
@title 局面判断ヘルパー
@description 牌譜再生 (record_evaluator.py) と API ハンドラ (forwarder.py) の両方から
呼ばれる局面判断ロジック。九種九牌・四風子連打・鳴き禁止理由などの判定を共通化する。

Why:
  牌譜の事前計算化 (eval.json への格納) にあたり、forwarder.py に定義されていた
  ヘルパー関数を共通モジュールに分離。record_evaluator.py から import して使う。
"""
from __future__ import annotations
from typing import TYPE_CHECKING

from core.str_converter import hand_to_counts, tile_to_id

if TYPE_CHECKING:
    from core.game_state import GameState
    from core.evaluator import Evaluator


_YAOCHU_IDS = [0, 8, 9, 17, 18, 26] + list(range(27, 34))


def build_kyushu_kyuhai_data(state: "GameState") -> dict:
    """
    @title 九種九牌判定
    @description 手牌が九種九牌 (么九牌9種以上) に該当するか判定する。
    @param {GameState} state - 現在の局面
    @returns {dict} {can_declare, recommend_declare, reason}
    """
    result = {
        "can_declare": False,
        "recommend_declare": False,
        "reason": ""
    }
    if not state.my_hand:
        return result
    counts = hand_to_counts(state.my_hand)
    yaochu_types = sum(1 for i in _YAOCHU_IDS if counts[i] >= 1)
    yaochu_total = sum(counts[i] for i in _YAOCHU_IDS)
    if yaochu_types == 9 and yaochu_total == 9:
        result["can_declare"] = True
        result["recommend_declare"] = True
        result["reason"] = "9種9牌のため流局を推奨します。"
    elif yaochu_types == 10 and yaochu_total == 10:
        result["can_declare"] = True
        if state.my_score_rank() == 3:
            result["recommend_declare"] = False
            result["reason"] = "10種10牌ですが、現在ラスのため国士無双を狙うことを推奨します。"
        else:
            result["recommend_declare"] = True
            result["reason"] = "10種10牌のため流局を推奨します。"
    elif yaochu_types == 10 and yaochu_total >= 11:
        result["can_declare"] = True
        result["recommend_declare"] = False
        result["reason"] = "10種11牌以上（対子あり）のため国士無双を狙うことを推奨します。"
    elif yaochu_types >= 11:
        result["can_declare"] = True
        result["recommend_declare"] = False
        result["reason"] = "11種以上の么九牌のため国士無双を狙うことを推奨します。"
    return result


def build_sufutsusenru_data(state: "GameState", evaluator: "Evaluator") -> dict:
    """
    @title 四風子連打判定
    @description 第一巡で全員風牌を捨てる状況 (四風子連打) が可能か判定する。
    @param {GameState} state - 現在の局面
    @param {Evaluator} evaluator - 評価器 (戦略モード判定用)
    @returns {dict} {is_possible, recommend_discard, wind_tile, reason}
    """
    result = {
        "is_possible": False,
        "recommend_discard": False,
        "wind_tile": None,
        "reason": ""
    }
    wind_possible, wind_tile = state.is_first_turn_wind_limit_possible()
    if not wind_possible or wind_tile is None:
        return result
    result["is_possible"] = True
    result["wind_tile"] = wind_tile
    if evaluator.strategy.is_high_hand_value_first_turn():
        result["recommend_discard"] = False
        mode = evaluator.strategy.get_strategy_mode()
        result["reason"] = f"手牌価値が高いため、四風子連打を回避しアガリを目指すことを推奨します（手牌評価: {mode}）。"
    else:
        result["recommend_discard"] = True
        result["reason"] = "手牌価値が低いため、四風子連打による流局を狙うことを推奨します。"
    return result


def get_meld_forbidden_reason(
    evaluator: "Evaluator",
    type_: int,
    tiles: list,
    from_seat: int,
    state: "GameState",
    params: dict,
) -> str:
    """
    @title 鳴き禁止の具体的理由を返す
    @description should_call_meld() が False を返した具体的な理由を判定する。
    @param {Evaluator} evaluator - 評価器
    @param {int} type_ - 副露種別 (0=チー, 1=ポン, 2=大明槓, 3=暗槓)
    @param {list} tiles - 牌 (文字列)
    @param {int} from_seat - 鳴き対象牌の出所
    @param {GameState} state - 現在の局面
    @param {dict} params - 設定パラメータ
    @returns {str} 鳴き禁止理由
    """
    try:
        hand = state.my_hand
        if not tiles:
            return "牌が指定されていません"
        tile_str = tiles[0] if tiles else ""
        open_meld_count = sum(1 for m in state.my_melds if m.is_open)
        my_seat = state.my_seat
        seat_names = ['東', '南', '西', '北']
        my_wind_id = (my_seat - state.ju) % 4
        my_wind_name = seat_names[my_wind_id]

        if type_ == 1:
            tile_id = tile_to_id(tile_str) if tile_str else 0
            if 27 <= tile_id <= 30:
                wind_id = tile_id - 27
                if wind_id != my_wind_id:
                    wind_name = seat_names[wind_id]
                    return f"オタ風 ({wind_name}) のためポンしません"

        if type_ == 0 and state.tsumo_count <= 4:
            return f"序盤 (ツモ{state.tsumo_count}巡) のためチーは見送ります"

        if open_meld_count >= 1 and state.tsumo_count <= 6:
            return f"序盤に副露済みのため、鳴きを増やしません"

        if type_ == 1 and state.tsumo_count <= 5:
            return f"序盤 (ツモ{state.tsumo_count}巡) のためポンを控えます"

        mode = evaluator.strategy.get_strategy_mode()
        if mode in ('ベタオリ', '安全第一', 'オリ'):
            return f"防御姿勢 ({mode}) のため鳴きません"

        shanten_estimate = 99
        try:
            from core.hand_value import estimate_shanten
            shanten_estimate = estimate_shanten(hand, open_meld_count)
        except Exception:
            pass
        if shanten_estimate >= 2:
            return f"{shanten_estimate}向聴と遠い手のため鳴きません"

        return "鳴き推奨条件を満たしません"
    except Exception as e:
        return f"鳴き判断エラー: {e}"


def normalize_hand_red_five(hand):
    """Convert red 5 tiles (0m/0p/0s) to regular 5 (5m/5p/5s) for matching."""
    return ['5' + t[1:] if t and t[0] == '0' else t for t in hand]
