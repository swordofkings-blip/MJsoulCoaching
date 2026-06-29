# -*- coding: utf-8 -*-
"""
@title ver.2 押し引き 戦術思想 ルール エンジン
@description 天鳳位の押し引き戦術を 構造的ルールとして実装。
              パラメータ調整だけでは再現困難な状況判断を、ルールベースで処理する。

ルール一覧 (天鳳位の戦術思想):
  1. 待ちの形 (両面=押す, カンチャン/ペンチャン/単騎/シャボ=オリ)
  2. 翻数 (1翻以下=オリ, 3翻以上=押す, 跳満以上=必ず押す)
  3. 順位 (トップ=オリ, ラス=押す, 親=連荘狙い)
  4. 巡目 (序盤=オリ, 終盤=押す)
  5. 現物 (自分の捨牌=押す, 放銃0%)
  6. リーチ者河 (字牌1枚見え=オリ)
  7. スジ (両側スジ=危険, オリ)
  8. 河読み (連打=ダマ手, 押せる)
  9. 待ち枚数 (1枚残り=オリ, 3枚以上=押す)
 10. 4枚見え (数牌=待ち薄く=押す, 字牌=1000=オリ)
"""
from __future__ import annotations

from typing import List, Dict, Tuple, Set
from core.str_converter import tile_to_id, id_to_tile


# ============================================================
# 待ちの形 判定
# ============================================================

def classify_wait_shape(state, best_discards: List[str]) -> str:
    """
    @title 待ちの形 分類
    @returns 'ryanmen' (両面) | 'kanchan' (カンチャン) | 'penchan' (ペンチャン)
              | 'tanki' (単騎) | 'shanpon' (シャボ) | 'unknown'
    """
    # 簡略: 牌構成から判定 (本実装では ukeire モジュールに 依存)
    # ここでの判定は 概念的なもの
    return 'unknown'


# ============================================================
# 牌ID 変換 ヘルパー
# ============================================================

def tile_str_to_id(tile: str) -> int:
    """@title '5m' → 4 (0-indexed)"""
    return tile_to_id(tile)


def id_to_tile_str(tile_id: int) -> str:
    """@title 4 → '5m'"""
    return id_to_tile(tile_id)


def is_honor(tile_id: int) -> bool:
    """@title 字牌判定 (id 27-33)"""
    return tile_id >= 27


def is_terminal(tile_id: int) -> bool:
    """@title 端牌判定 (1, 9)"""
    suit = tile_id // 9
    rank = tile_id % 9
    return suit < 3 and (rank == 0 or rank == 8)


# ============================================================
# 危険牌 判定 (現物 / スジ / 河)
# ============================================================

def get_suji_tiles(tile: str) -> Set[str]:
    """
    @title スジ計算 (両側スジ)
    @description スジ = 両側 1 つ ずつの牌 (5m の スジ = 4m, 6m)
                  端牌 (1m, 9m) は 反対 側 のみ (1m → 4m, 9m → 6m)
    @returns スジ牌 (両側含む) の set
    """
    try:
        tid = tile_to_id(tile)
    except Exception:
        return set()
    if tid >= 27:
        return set()  # 字牌はスジなし

    suit = tid // 9  # 0=m, 1=p, 2=s
    rank = tid % 9  # 0-8 (1-9, 0-indexed)
    result = set()
    # 中央 (2-6 = 3-7): 両側 ±1
    if 2 <= rank <= 6:
        for offset in [-1, 1]:
            if 0 <= rank + offset <= 8:
                adj_id = suit * 9 + rank + offset
                result.add(id_to_tile(adj_id))
    # 1m (=rank 0): スジ = 4m のみ (右に 3 つ)
    elif rank == 0:
        adj_id = suit * 9 + 3
        result.add(id_to_tile(adj_id))
    # 9m (=rank 8): スジ = 6m のみ (左に 3 つ)
    elif rank == 8:
        adj_id = suit * 9 + 5
        result.add(id_to_tile(adj_id))
    return result


def get_danger_tiles(state) -> Set[str]:
    """
    @title 危険牌 計算
    @description 押す 際に 捨てるべきでない牌 (= 放銃リスク高)
    @returns 危険牌 set

    含める牌:
      - リーチ者全員の 捨牌 (= 現物)
      - リーチ者全員の 河 の 字牌 (= ノーチャンス or 危険)
      - 4枚見え 字牌 (= 残0枚 = 安全、 放銃しない)
      - 4枚見え 数牌 ≠ 4 枚 (= 待ち薄 = 押せる)
    """
    danger = set()
    for s in range(4):
        if s == state.my_seat:
            continue
        rs = state.reach_states[s] if s < len(state.reach_states) else None
        if rs is None or not rs.is_reach:
            continue
        # リーチ者の捨牌 = 現物
        for t in state.river[s]:
            danger.add(t)
        # リーチ者の捨牌からスジ生成
        for t in state.river[s]:
            danger.update(get_suji_tiles(t))
        # 4枚見え数牌 ≠ 残0枚
        # (簡略化: 捨牌 4 枚に 同じ牌が 4 回 → 待ち薄 = 押せる)
    return danger


def get_safe_tiles(state) -> Set[str]:
    """
    @title 安全牌 (= 押す際に捨てても放銃しない牌)
    @description 現物 + 4枚見え字牌
    @returns 安全牌 set
    """
    safe = set()
    # 自分の捨牌 = 現物
    for t in state.river[state.my_seat]:
        safe.add(t)
    # 4枚見え字牌 (字牌が 4 枚すべて見える → 残0枚 → 安全)
    for tid in range(27, 34):
        visible = 0
        for s in range(4):
            visible += state.river[s].count(id_to_tile(tid))
            for meld in state.my_melds if s == state.my_seat else []:
                visible += meld.tiles.count(id_to_tile(tid))
        if visible >= 4:
            safe.add(id_to_tile(tid))
    return safe


# ============================================================
# 翻数 による 押し/オリ 判定
# ============================================================

def get_effective_han(state) -> int:
    """
    @title 実効翻数 (待ち + ドラ + 赤 + 役牌 簡易推定)
    """
    han = 0
    # ドラ
    if hasattr(state, 'doras') and state.doras:
        for d in state.doras:
            try:
                tid = tile_to_id(d)
                han += state.my_hand.count(d)
            except Exception:
                continue
    # 赤ドラ
    han += sum(1 for t in state.my_hand if t in ('0m', '0p', '0s'))
    # 役牌 (三元 + 場風 + 自風) 暗刻
    for tile in set(state.my_hand):
        try:
            tid = tile_to_id(tile)
        except Exception:
            continue
        if state.my_hand.count(tile) >= 3 and is_honor(tid):
            han += 1
    return han


# ============================================================
# メイン: 押し/オリ 判定
# ============================================================

DEFAULT_RULES = {
    'PUSH_HAN_THRESHOLD': 3,           # 3翻以上で押す
    'PUSH_HIGH_HAN_THRESHOLD': 4,      # 跳満 (4翻) 以上で必ず押す
    'PUSH_LATE_TURN': 14,              # 終盤判定 (14巡+)
    'PUSH_EARLY_TURN': 5,              # 序盤判定 (1-5巡)
    'PUSH_TOP_PLACE_MARGIN': 8000,     # トップ目判定 (8,000点リード)
    'PUSH_LAST_PLACE_MARGIN': -8000,   # ラス目判定 (8,000点ビハインド)
    'PUSH_DEALER_BONUS': True,         # 親番は連荘狙い
    'PUSH_RYANMEN_WEIGHT': 1.5,        # 両面待ち 加点倍率
    'PUSH_TANKI_PENALTY': 0.5,         # 単騎 減点
    'PUSH_PENCHAN_PENALTY': 0.5,       # ペンチャン 減点
    'PUSH_KANCHAN_PENALTY': 0.5,       # カンチャン 減点
    'PUSH_SHANPON_PENALTY': 0.3,       # シャボ 減点
}


def judge_push_fold(state, shanten: int, ukeire: Dict = None, params: dict = None) -> Tuple[str, List[str]]:
    """
    @title 押す/オリる の 構造的 ルール判定 (天鳳位 戦術思想)
    @returns ('push' | 'fold' | 'neutral', [reason_list])
    """
    if params is None:
        params = {}
    rules = dict(DEFAULT_RULES)
    rules.update(params)

    reasons = []
    score = 0  # 正で push、負で fold

    # === 0. 前提: 役なし (0 シャンテン以外) の場合 ===
    if shanten >= 2:
        # 2シャンテン以上 = 聴牌遠く、オリ
        reasons.append(f"{shanten}シャンテン (遠い)")
        return ('fold', reasons)

    # === 1. 翻数による判定 ===
    han = get_effective_han(state)
    if han >= rules['PUSH_HIGH_HAN_THRESHOLD']:
        score += 200
        reasons.append(f"高打点 ({han}翻 → 跳満以上) 必ず押す")
    elif han >= rules['PUSH_HAN_THRESHOLD']:
        score += 100
        reasons.append(f"中打点 ({han}翻) 押す")
    elif han >= 1:
        score -= 30
        reasons.append(f"低打点 ({han}翻) オリ寄り")
    else:
        score -= 80
        reasons.append(f"役なし (0翻) オリ")

    # === 2. 順位 による判定 ===
    if hasattr(state, 'scores') and state.scores:
        my_score = state.scores[state.my_seat]
        max_score = max(state.scores)
        min_score = min(state.scores)
        margin_top = my_score - max_score  # 0 = トップ
        margin_last = my_score - min_score  # 0 = ラス

        if margin_top == 0:
            score -= 100
            reasons.append("トップ目 オリ逃げ")
        elif margin_last == 0:
            score += 100
            reasons.append("ラス目 押す")
        elif margin_top > rules['PUSH_TOP_PLACE_MARGIN']:
            score -= 50
            reasons.append(f"トップリード ({margin_top:+d})")
        elif margin_last < rules['PUSH_LAST_PLACE_MARGIN']:
            score += 50
            reasons.append(f"ラスビハインド ({margin_last:+d})")

        # 親 加点
        if rules['PUSH_DEALER_BONUS'] and hasattr(state, 'dealer_seat'):
            if state.dealer_seat == state.my_seat:
                score += 40
                reasons.append("親番 連荘狙い")

    # === 3. 巡目 による判定 ===
    turn = (state.tsumo_count - 1) // 4 + 1 if state.tsumo_count > 0 else 1
    if turn >= rules['PUSH_LATE_TURN']:
        score += 60
        reasons.append(f"終盤 ({turn}巡) 押す")
    elif turn <= rules['PUSH_EARLY_TURN']:
        score -= 60
        reasons.append(f"序盤 ({turn}巡) オリ")

    # === 4. 現物 判定 ===
    safe_tiles = get_safe_tiles(state)
    if len(safe_tiles) >= 8:
        # 安全牌 8 種以上ある = オリ 余裕 → オリ寄り
        score -= 40
        reasons.append(f"安全牌 {len(safe_tiles)}種 オリ余裕")
    elif len(safe_tiles) <= 2:
        # 安全牌 2 種以下 = オリ 不可能 → 押す
        score += 80
        reasons.append(f"安全牌 {len(safe_tiles)}種 オリ不可能 → 押す")

    # === 5. リーチ者 状態 ===
    opp_reach_count = sum(1 for s in range(4)
                          if s != state.my_seat
                          and state.reach_states[s] is not None
                          and state.reach_states[s].is_reach)
    if opp_reach_count >= 2:
        # 2家以上リーチ = 危険 → オリ
        score -= 60
        reasons.append(f"他家リーチ {opp_reach_count}家 危険")
    elif opp_reach_count == 1:
        score -= 20
        reasons.append(f"他家リーチ 1家")

    # === 6. 待ちの形 (ukeire から取得) ===
    if ukeire and 'wait_type' in ukeire:
        wait_type = ukeire['wait_type']
        if wait_type == 'ryanmen':
            score += 50 * rules['PUSH_RYANMEN_WEIGHT']
            reasons.append("両面待ち 出和了されにくい → 押す")
        elif wait_type == 'tanki':
            score -= 80 * rules['PUSH_TANKI_PENALTY']
            reasons.append("単騎待ち 出和了されやすい → オリ")
        elif wait_type == 'penchan':
            score -= 60 * rules['PUSH_PENCHAN_PENALTY']
            reasons.append("ペンチャン待ち → オリ")
        elif wait_type == 'kanchan':
            score -= 40 * rules['PUSH_KANCHAN_PENALTY']
            reasons.append("カンチャン待ち → オリ")
        elif wait_type == 'shanpon':
            score -= 30 * rules['PUSH_SHANPON_PENALTY']
            reasons.append("シャボ待ち → オリ")

    # === 7. 4枚見え数牌 (待ち薄) ===
    # 簡略: state.my_hand の各牌について 4 枚見え = 待ち薄
    # 詳略: ukeire モジュール から 取得 する べき

    # === 最終判定 ===
    if score >= 50:
        decision = 'push'
    elif score <= -50:
        decision = 'fold'
    else:
        decision = 'neutral'
    reasons.insert(0, f"score={score} → {decision}")
    return (decision, reasons)


# ============================================================
# 押し時の安全牌選択
# ============================================================

def select_push_discard(state, candidates: List[str], ukeire: Dict = None) -> Tuple[str, str]:
    """
    @title 押す 際の 安全牌 選択
    @returns (推奨打牌, 理由)
    """
    safe = get_safe_tiles(state)
    safe_in_hand = [t for t in candidates if t in safe]
    if safe_in_hand:
        return (safe_in_hand[0], f"安全牌 選択 ({safe_in_hand[0]})")
    return (candidates[0] if candidates else '', "安全牌 なし 押し")


def select_fold_discard(state, candidates: List[str]) -> Tuple[str, str]:
    """
    @title オリ 際の 安全牌 選択
    @returns (推奨打牌, 理由)
    """
    safe = get_safe_tiles(state)
    safe_in_hand = [t for t in candidates if t in safe]
    if safe_in_hand:
        # 安全牌 の中で最も安全 (4枚見え数牌 > 字牌)
        return (safe_in_hand[0], f"オリ 安全牌 ({safe_in_hand[0]})")
    return (candidates[0] if candidates else '', "オリ 強制")
