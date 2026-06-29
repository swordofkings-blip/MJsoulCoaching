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
# 1.② リーチによる 打点上昇幅
# ============================================================

def calc_riichi_benefit(state, han: int) -> float:
    """
    @title リーチによる打点上昇幅
    @description 1,000点 → 2,600点 (2.6倍) vs 8,000 → 8,000 (0倍) の 差
                  役なし (0翻) の場合、リーチ = 役 確定 + 1 翻 で 利益 極めて大
    @param han: 推定翻数 (役 + ドラ)
    @returns 利益度 (-100 〜 +200, 高いほどリーチ価値あり)
    """
    # 基本点 (子): ハン数 → 基本点
    base_points = {
        0: 0,     # 役なし = ロン和了 不可、 リーチ 必須
        1: 1000,
        2: 2000,
        3: 4000,  # 満貫
        4: 8000,  # 跳満
        5: 8000,
        6: 12000, # 倍満
        7: 12000,
        8: 16000, # 三倍満
        9: 16000,
        10: 16000,
        11: 24000, # 役満
        12: 24000,
        13: 32000, # 2 役満
    }
    bp = base_points.get(min(han, 13), 0)
    # リーチ (1 翻 + 立直棒 1000 点)
    if han == 0:
        # 役なし → リーチで 最低 1 翻 (= 1000 点) 確定 + 立直棒
        # 利益 極めて大 (和了可能になる)
        return 200
    riichi_bp = base_points.get(min(han + 1, 13), 8000) + 1000
    if bp == 0:
        return 0
    benefit = (riichi_bp - bp) / bp * 100
    return benefit


# ============================================================
# 1.④ 手替わりの種類と有効枚数
# ============================================================

def calc_tenpai_change_potential(state) -> float:
    """
    @title 手替わり 種類と有効枚数 ポテンシャル
    @description 1 巡 待つことで 両面 / 三色 / 一気通貫 などに 変化 する 牌 が 山に 何枚 残って いるか
    @returns ポテンシャル値 (0-100, 高いほど 手替わり 期待 大)
    """
    # 簡略: 山 残り 数 によって 評価
    if not hasattr(state, 'left_tile_count'):
        return 0
    if state.left_tile_count < 20:
        return 0  # 山 枯渇 → 手替わり 期待 なし
    # 山 多い ほど 期待 大 (最大 70 枚 = 100)
    potential = min(100, state.left_tile_count * 1.5)
    return potential


# ============================================================
# 1.⑤ 手替わり 打点爆発力
# ============================================================

def calc_score_explosion_potential(state, han: int) -> float:
    """
    @title 手替わり 打点爆発力
    @description 平和 (1,000 点) → 満貫 (8,000 点) 化け する ポテンシャル
    @returns 爆発力 (0-100, 高いほど 1 巡 で 化け する 可能性)
    """
    if han <= 1:
        # 1 翻以下 → 爆発 ポテンシャル 高い (満貫まで化ける)
        return 80
    elif han <= 2:
        return 50
    elif han <= 3:
        return 30
    else:
        return 10  # 既に高い


# ============================================================
# 1.⑥ 裏ドラ・赤ドラ 期待値
# ============================================================

def calc_ura_aka_expectation(state) -> float:
    """
    @title 裏ドラ・赤ドラ 期待値
    @description 手牌に 暗刻 (アンコ) / 順子 多い → 裏ドラ / 赤ドラ 乗りやすい
    @returns 期待値 (0-100, 高いほど 裏ドラ / 赤ドラ 乗りやすい)
    """
    exp = 0
    # 暗刻 +20
    for t in set(state.my_hand):
        if state.my_hand.count(t) >= 3:
            exp += 20
    # 順子 +10 (重複カウント防止: 使用済み牌を 0 にする)
    counts = {}
    for t in state.my_hand:
        if t[-1] in ('m', 'p', 's'):
            try:
                tid = tile_to_id(t)
                suit = tid // 9
                rank = tid % 9
                counts.setdefault(suit, [0]*9)[rank] += 1
            except Exception:
                continue
    for suit, ranks in counts.items():
        # コピーで 操作
        r = list(ranks)
        for _ in range(4):  # 1 面子 につき 1 順子
            found = False
            for i in range(7):
                if r[i] >= 1 and r[i+1] >= 1 and r[i+2] >= 1:
                    r[i] -= 1
                    r[i+1] -= 1
                    r[i+2] -= 1
                    exp += 10
                    found = True
                    break
            if not found:
                break
    return min(100, exp)


# ============================================================
# 2.② 死に牌 数
# ============================================================

def count_dead_tiles(state, wait_tiles: List[str]) -> int:
    """
    @title 死に牌 数 (河 / ドラ表示牌 に すでに 見えている 待ち牌)
    @param wait_tiles: 待ち牌 リスト
    @returns 死に牌 総数
    """
    if not wait_tiles:
        return 0
    visible = {}
    for t in wait_tiles:
        visible[t] = 0
    # 河
    for s in range(4):
        for t in state.river[s]:
            if t in visible:
                visible[t] += 1
    # ドラ表示牌
    if hasattr(state, 'doras') and state.doras:
        for d in state.doras:
            if d in visible:
                visible[d] += 1
    return sum(visible.values())


# ============================================================
# 2.③ 他家 出やすさ (スジ / 壁 / 字牌)
# ============================================================

def calc_pickup_ease(state, wait_tiles: List[str]) -> float:
    """
    @title 他家 出やすさ
    @description 待ち牌 が 他家 から ツモ切られ やすいか
                  字牌 (出やすい) > 数牌端牌 > 中央数牌 (出にくい)
    @returns 出やすさ (0-100, 高いほど 出やすい)
    """
    if not wait_tiles:
        return 50
    ease_sum = 0
    for t in wait_tiles:
        try:
            tid = tile_to_id(t)
        except Exception:
            continue
        if tid >= 27:
            # 字牌 = 出やすい (他家 オリ 際 ツモ切り)
            ease_sum += 70
        elif tid % 9 == 0 or tid % 9 == 8:
            # 端牌 = やや出やすい
            ease_sum += 50
        else:
            # 中央数牌 = 出にくい
            ease_sum += 30
    return ease_sum / len(wait_tiles)


# ============================================================
# 2.④ 待ち牌 が ドラ・赤ドラ
# ============================================================

def is_wait_dora_aka(state, wait_tiles: List[str]) -> bool:
    """
    @title 待ち牌 が ドラ・赤ドラ
    @description 待ち牌 が ドラ (ドラ表示牌の次) または 赤ドラ なら 他家 絶対 手放さない
    @returns True = ドラ待ち (出にくい)
    """
    from core.str_converter import dora_indicator_to_dora
    if not wait_tiles:
        return False
    for t in wait_tiles:
        # 赤ドラ
        if t in ('0m', '0p', '0s'):
            return True
        # ドラ (state.doras は ドラ表示牌 なので ドラ牌 に 変換)
        if hasattr(state, 'doras') and state.doras:
            for indicator in state.doras:
                try:
                    dora = dora_indicator_to_dora(indicator)
                    if t == dora:
                        return True
                except Exception:
                    continue
    return False


# ============================================================
# 3.② 残り ツモ 回数
# ============================================================

def remaining_tsumo_count(state) -> int:
    """
    @title 残り ツモ 回数
    @description 自分 が 引ける 牌 の 残り 回数 (流局 まで)
                  山 0 枚 なら 0 返す
    @returns 残り ツモ 回数
    """
    if not hasattr(state, 'left_tile_count'):
        return 0
    if state.left_tile_count <= 0:
        return 0
    return state.left_tile_count // 4 + 1


# ============================================================
# 3.③ ハイテイ チェック
# ============================================================

def is_near_haitei(state) -> bool:
    """
    @title ハイテイ (海底牌) 近い か
    @description 残り 4 ツモ以内 = ハイテイ 近い
    @returns True = ハイテイ 近い
    """
    if not hasattr(state, 'left_tile_count'):
        return False
    return state.left_tile_count <= 4


# ============================================================
# 4.② 高打点 仕掛け チェック
# ============================================================

def count_opp_high_danger(state) -> int:
    """
    @title 他家 高打点 仕掛け 数 (ドラポン / 染め手)
    @description 他家 が ドラ を ポン している / 染め手 明らかな 数
                  (state.doras は ドラ表示牌 なので ドラ牌 に 変換 する 必要 が ある)
    @returns 高打点 仕掛け 数
    """
    from core.str_converter import dora_indicator_to_dora
    count = 0
    # ドラ牌 list 取得
    actual_doras = []
    if hasattr(state, 'doras') and state.doras:
        for indicator in state.doras:
            try:
                actual_doras.append(dora_indicator_to_dora(indicator))
            except Exception:
                continue
    if not actual_doras:
        return 0
    for s in range(4):
        if s == state.my_seat:
            continue
        melds_s = state.melds[s] if hasattr(state, 'melds') and s < len(state.melds) and state.melds else []
        for meld in melds_s:
            if getattr(meld, 'is_open', False):
                # ドラ牌 を 含んで いるか
                for t in meld.tiles:
                    if t in actual_doras:
                        count += 1
                        break
    return count


# ============================================================
# 4.③ リーチ宣言牌 危険度
# ============================================================

def is_declare_tile_dangerous(state, declare_tile: str) -> bool:
    """
    @title リーチ宣言牌 の 危険度
    @description 宣言牌 が ロン牌 に なる リスク
                  字牌 > 数牌端牌 > 中央数牌
    @returns True = 危険
    """
    try:
        tid = tile_to_id(declare_tile)
    except Exception:
        return False
    if tid >= 27:
        # 字牌 = やや危険 (他家 手牌に ある 可能性 高)
        return True
    elif tid % 9 == 0 or tid % 9 == 8:
        # 端牌 = 中
        return True
    return False


# ============================================================
# 4.④ 他家 ベタ降り チェック
# ============================================================

def is_opp_full_fold(state) -> bool:
    """
    @title 他家 ベタ降り (全員 慎重)
    @description 3 家 すべて リーチ していない + 河 が 少 ない = ベタ降り
    @returns True = ベタ降り
    """
    reach_count = sum(1 for s in range(4)
                      if s != state.my_seat
                      and state.reach_states[s] is not None
                      and state.reach_states[s].is_reach)
    # リーチ 0 人 + 河 少 = ベタ降り
    if reach_count == 0:
        total_river = sum(len(state.river[s]) for s in range(4) if s != state.my_seat)
        if total_river < 20:
            return True
    return False


# ============================================================
# 5.② オーラス / 局数 チェック
# ============================================================

def is_orasu(state) -> bool:
    """
    @title オーラス か
    @description 南 4 局 (東風) / 南 8 局 (半荘) = オーラス
    @returns True = オーラス
    """
    if not hasattr(state, 'chang') or not hasattr(state, 'ju'):
        return False
    # 東風: 南 4 局 = ju=3, chang=3
    # 半荘: 南 8 局 = ju=3, chang=7
    return (state.ju == 3 and state.chang >= 3)


# ============================================================
# 5.④ 供託リーチ棒 数
# ============================================================

def get_honba_count(state) -> int:
    """
    @title 供託 本場 (= 供託リーチ棒 数)
    @returns 供託 本場
    """
    if hasattr(state, 'chang'):
        return state.chang
    return 0


# ============================================================
# 5.③ ターゲット 点差 チェック
# ============================================================

def calc_target_point_diff(state) -> int:
    """
    @title ターゲット (2位) と の 点差
    @description 満貫 (8,000 点) ツモれば 捲れる / 直撃 必須 な 関係 か
    @returns ターゲット との 点差
    """
    if not hasattr(state, 'scores') or not state.scores:
        return 0
    my_score = state.scores[state.my_seat]
    others = [state.scores[s] for s in range(4) if s != state.my_seat]
    if not others:
        return 0
    sorted_others = sorted(others, reverse=True)
    higher = [s for s in sorted_others if s > my_score]
    if higher:
        return my_score - higher[0]  # 負 = ビハインド
    return 0


# ============================================================
# 6.③ トビ (持ち点 ゼロ) チェック (雀魂ルール 準拠)
# ============================================================

def get_tobi_risk(state) -> Tuple[int, str]:
    """
    @title トビ リスク レベル (雀魂ルール: 0点になるまで使ってOK)
    @description 雀魂ルールでは 0点になるまでリーチ棒等を使ってOK。
                  ただし 0点 終了 リスク は ある。
                  - 持ち点 >= 2,000点: リスク なし
                  - 持ち点 1,000-2,000点: リスク 中 (1本 なら OK、 2本 連続 出す と 危険)
                  - 持ち点 < 1,000点: リスク 大 (リーチ 棒 出す だけ で 0点 終了 リスク)
                  - 持ち点 0: 既に トビ
    @returns (risk_level 0-2, message)
    """
    if not hasattr(state, 'scores') or not state.scores:
        return (0, "")
    my_score = state.scores[state.my_seat]
    if my_score == 0:
        return (2, "既に トビ 終了 (持ち点 0)")
    elif my_score < 1000:
        return (2, f"トビ リスク 大 (持ち点 {my_score}, リーチ棒 1,000 で 0点 終了 リスク)")
    elif my_score < 2000:
        return (1, f"トビ リスク 中 (持ち点 {my_score}, リーチ 1本 OK だが 2本 連続 出す と 危険)")
    else:
        return (0, f"トビ リスク なし (持ち点 {my_score})")


def get_riichi_sticks(state) -> int:
    """
    @title 場 の リーチ 棒 (= 供託 1000点棒) の 数
    @description 立直 が かかる ごと に +1 本 (= 1,000 点)
    @returns リーチ 棒 数
    """
    if not hasattr(state, 'reach_states'):
        return 0
    return sum(1 for rs in state.reach_states if rs is not None and rs.is_reach)


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
      - 4枚見え 数牌 ≠ 4 枚 (= 待ち薄、 安全 = 押せる側、 なので 含めない)
      - スジ (リーチ者の 捨牌 から 生成)
    注: リーチ者の捨牌 (= 現物) は 危険 で は なく 安全牌
    """
    danger = set()
    for s in range(4):
        if s == state.my_seat:
            continue
        rs = state.reach_states[s] if s < len(state.reach_states) else None
        if rs is None or not rs.is_reach:
            continue
        # リーチ者の捨牌からスジ生成
        for t in state.river[s]:
            danger.update(get_suji_tiles(t))
    return danger


def get_safe_tiles(state) -> Set[str]:
    """
    @title 安全牌 (= 押す際に捨てても放銃しない牌)
    @description リーチしている他家の捨牌 (現物) + 4枚見え字牌
                  注: 自分の捨牌は安全牌ではない (他家に自分がリーチ者になる)
    @returns 安全牌 set
    """
    safe = set()
    # リーチ者の捨牌 = 現物
    for s in range(4):
        if s == state.my_seat:
            continue
        rs = state.reach_states[s] if s < len(state.reach_states) else None
        if rs is None or not rs.is_reach:
            continue
        for t in state.river[s]:
            safe.add(t)
    # 4枚見え字牌 (字牌が 4 枚すべて見える → 残0枚 → 安全)
    for tid in range(27, 34):
        visible = 0
        for s in range(4):
            visible += state.river[s].count(id_to_tile(tid))
        # 自分の手牌・副露もカウント
        if hasattr(state, 'my_hand') and state.my_hand:
            visible += state.my_hand.count(id_to_tile(tid))
        if hasattr(state, 'my_melds') and state.my_melds:
            for meld in state.my_melds:
                visible += sum(1 for t in meld.tiles if tile_to_id(t) == tid)
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
    from core.str_converter import dora_indicator_to_dora
    han = 0
    # ドラ (state.doras は ドラ表示牌 → ドラ牌 に 変換 する 必要 が ある)
    if hasattr(state, 'doras') and state.doras:
        for indicator in state.doras:
            try:
                dora = dora_indicator_to_dora(indicator)
                han += state.my_hand.count(dora)
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
    @title 押す/オリる の 構造的 ルール判定 (天鳳位 戦術思想 25 項目)
    @returns ('push' | 'fold' | 'neutral', [reason_list])

    配分 比率 パラメータ:
      _HAND_WEIGHT: 手牌要素 (1-2 番目) の 重み
      _SITUATION_WEIGHT: 場況要素 (3-5 番目) の 重み
      デフォルト 1.0 / 1.0。 場況 依存 なら _SITUATION_WEIGHT を 1.5 など に する。
    """
    if params is None:
        params = {}
    rules = dict(DEFAULT_RULES)
    rules.update(params)

    hand_w = rules.get('_HAND_WEIGHT', 1.0)
    sit_w = rules.get('_SITUATION_WEIGHT', 1.0)

    reasons = []
    hand_score = 0
    sit_score = 0

    # ベース バイアス (チューニング 用)
    base_bias = rules.get('_BASE_BIAS', 0)
    sit_score += base_bias

    # === 0. 前提: 2シャンテン以上 = オリ ===
    if shanten >= 2:
        reasons.append(f"{shanten}シャンテン (遠い)")
        return ('fold', reasons)

    # 待ち牌 取得
    wait_tiles = ukeire.get('tiles', []) if ukeire else []

    # === 1. 確定打点 (1.①) ===
    han = get_effective_han(state)
    if han >= rules['PUSH_HIGH_HAN_THRESHOLD']:
        hand_score += 200
        reasons.append(f"高打点 ({han}翻 → 跳満以上) 必ず押す")
    elif han >= rules['PUSH_HAN_THRESHOLD']:
        hand_score += 100
        reasons.append(f"中打点 ({han}翻) 押す")
    elif han >= 1:
        hand_score -= 30
        reasons.append(f"低打点 ({han}翻) オリ寄り")
    else:
        hand_score -= 80
        reasons.append(f"役なし (1.③ 0翻) オリ")

    # === 1.② リーチ打点上昇幅 ===
    riichi_benefit = calc_riichi_benefit(state, han)
    if riichi_benefit >= 100:  # 2 倍以上
        hand_score += 60
        reasons.append(f"リーチ 打点上昇 大 ({riichi_benefit:.0f}%)")
    elif riichi_benefit >= 30:
        hand_score += 30
        reasons.append(f"リーチ 打点上昇 中 ({riichi_benefit:.0f}%)")
    else:
        hand_score -= 30
        reasons.append(f"リーチ 打点上昇 小 ({riichi_benefit:.0f}%)")

    # === 1.④ 手替わり 種類と有効枚数 ===
    tenpai_change = calc_tenpai_change_potential(state)
    hand_score += tenpai_change * 0.2  # 最大 +20
    if tenpai_change > 50:
        reasons.append(f"手替わり 期待 大 (山 {state.left_tile_count}枚)")

    # === 1.⑤ 手替わり 打点爆発力 ===
    score_exp = calc_score_explosion_potential(state, han)
    hand_score += score_exp * 0.3  # 最大 +30 (1 翻以下)
    if score_exp >= 50:
        reasons.append(f"打点 爆発力 大 (1.⑤)")

    # === 1.⑥ 裏ドラ・赤ドラ 期待値 ===
    ura_exp = calc_ura_aka_expectation(state)
    hand_score += ura_exp * 0.3  # 最大 +30
    if ura_exp >= 40:
        reasons.append(f"裏ドラ 乗り 良い (1.⑥)")

    # === 2.① 待ちの形 ===
    if ukeire and 'wait_type' in ukeire:
        wait_type = ukeire['wait_type']
        if wait_type == 'ryanmen':
            hand_score += 50 * rules['PUSH_RYANMEN_WEIGHT']
            reasons.append("両面待ち 出和了されにくい → 押す")
        elif wait_type == 'tanki':
            hand_score -= 80 * rules['PUSH_TANKI_PENALTY']
            reasons.append("単騎待ち 出和了されやすい → オリ")
        elif wait_type == 'penchan':
            hand_score -= 60 * rules['PUSH_PENCHAN_PENALTY']
            reasons.append("ペンチャン待ち → オリ")
        elif wait_type == 'kanchan':
            hand_score -= 40 * rules['PUSH_KANCHAN_PENALTY']
            reasons.append("カンチャン待ち → オリ")
        elif wait_type == 'shanpon':
            hand_score -= 30 * rules['PUSH_SHANPON_PENALTY']
            reasons.append("シャボ待ち → オリ")

    # === 2.② 死に牌 数 ===
    if wait_tiles:
        dead = count_dead_tiles(state, wait_tiles)
        if dead >= 3:
            hand_score -= 60
            reasons.append(f"死に牌 {dead}枚 多い (2.②)")
        elif dead >= 1:
            hand_score -= 20
            reasons.append(f"死に牌 {dead}枚 (2.②)")

    # === 2.③ 他家 出やすさ ===
    if wait_tiles:
        ease = calc_pickup_ease(state, wait_tiles)
        if ease >= 60:
            hand_score += 40
            reasons.append(f"他家 出やすい ({ease:.0f}%, 2.③)")
        elif ease <= 35:
            hand_score -= 40
            reasons.append(f"他家 出にくい ({ease:.0f}%, 2.③)")

    # === 2.④ 待ちドラ ===
    if is_wait_dora_aka(state, wait_tiles):
        hand_score -= 80
        reasons.append("待ち が ドラ・赤ドラ (2.④) 絶対手放さない")

    # === 3.① 巡目 ===
    turn = (state.tsumo_count - 1) // 4 + 1 if state.tsumo_count > 0 else 1
    if turn >= rules['PUSH_LATE_TURN']:
        sit_score += 60
        reasons.append(f"終盤 ({turn}巡) 押す")
    elif turn <= rules['PUSH_EARLY_TURN']:
        sit_score -= 60
        reasons.append(f"序盤 ({turn}巡) オリ")

    # === 3.② 残り ツモ 回数 ===
    rem_tsumo = remaining_tsumo_count(state)
    if rem_tsumo >= 10:
        sit_score += 20
        reasons.append(f"残り ツモ {rem_tsumo}回 余裕 (3.②)")
    elif rem_tsumo <= 4:
        sit_score -= 30
        reasons.append(f"残り ツモ {rem_tsumo}回 少ない (3.②)")

    # === 3.③ ハイテイ ===
    if is_near_haitei(state):
        sit_score -= 20
        reasons.append("ハイテイ 近い (3.③)")

    # === 4.① 先行リーチ ===
    opp_reach_count = sum(1 for s in range(4)
                          if s != state.my_seat
                          and state.reach_states[s] is not None
                          and state.reach_states[s].is_reach)
    if opp_reach_count >= 2:
        sit_score -= 60
        reasons.append(f"他家リーチ {opp_reach_count}家 危険 (4.①)")
    elif opp_reach_count == 1:
        sit_score -= 20
        reasons.append(f"他家リーチ 1家 (4.①)")

    # === 4.② 高打点 仕掛け ===
    high_danger = count_opp_high_danger(state)
    if high_danger >= 1:
        sit_score -= 40
        reasons.append(f"他家 高打点 仕掛け {high_danger}件 (4.②)")

    # === 4.④ 他家 ベタ降り ===
    if is_opp_full_fold(state):
        sit_score += 30
        reasons.append("他家 ベタ降り (4.④) ダマ有利")

    # === 5.① 順位 ===
    if hasattr(state, 'scores') and state.scores:
        my_score = state.scores[state.my_seat]
        max_score = max(state.scores)
        min_score = min(state.scores)
        margin_top = my_score - max_score
        margin_last = my_score - min_score

        if margin_top == 0:
            sit_score -= 100
            reasons.append("トップ目 オリ逃げ (5.①)")
        elif margin_last == 0:
            sit_score += 100
            reasons.append("ラス目 押す (5.①)")
        elif margin_top > rules['PUSH_TOP_PLACE_MARGIN']:
            sit_score -= 50
            reasons.append(f"トップリード ({margin_top:+d})")
        elif margin_last < rules['PUSH_LAST_PLACE_MARGIN']:
            sit_score += 50
            reasons.append(f"ラスビハインド ({margin_last:+d})")

        if rules['PUSH_DEALER_BONUS'] and hasattr(state, 'dealer_seat'):
            if state.dealer_seat == state.my_seat:
                sit_score += 40
                reasons.append("親番 連荘狙い (5.①)")

    # === 5.② オーラス / 局数 ===
    if is_orasu(state):
        sit_score += 20
        reasons.append("オーラス (5.②) 着順 確定 近い")

    # === 5.③ ターゲット 点差 ===
    target_diff = calc_target_point_diff(state)
    if target_diff < -3000:  # 3,000 点 ビハインド
        sit_score += 50
        reasons.append(f"2位 と {target_diff}点 ビハインド (5.③) 満貫ツモで捲り")
    elif target_diff < 0:
        sit_score += 20
        reasons.append(f"2位 と {target_diff}点 (5.③)")

    # === 5.④ 供託リーチ棒 ===
    honba = get_honba_count(state)
    if honba >= 3:
        sit_score += 50
        reasons.append(f"供託 {honba}本 価値大 (5.④) +{honba * 1000}点")
    elif honba >= 1:
        sit_score += 20
        reasons.append(f"供託 {honba}本 (5.④)")

    # === 6.③ トビ リスク (雀魂ルール: 0点まで使ってOK) ===
    tobi_level, tobi_msg = get_tobi_risk(state)
    if tobi_level == 2:
        sit_score -= 150
        reasons.append(f"トビ リスク 大 (6.③) {tobi_msg}")
    elif tobi_level == 1:
        sit_score -= 50
        reasons.append(f"トビ リスク 中 (6.③) {tobi_msg}")

    # === 4. 現物 判定 (押し/オリ 補助) ===
    safe_tiles = get_safe_tiles(state)
    if len(safe_tiles) >= 8:
        sit_score -= 40
        reasons.append(f"安全牌 {len(safe_tiles)}種 オリ余裕")
    elif len(safe_tiles) <= 2:
        sit_score += 80
        reasons.append(f"安全牌 {len(safe_tiles)}種 オリ不可能 → 押す")

    # === 配分 比率 適用 ===
    score = hand_score * hand_w + sit_score * sit_w

    # === 最終判定 ===
    if score >= 50:
        decision = 'push'
    elif score <= -50:
        decision = 'fold'
    else:
        decision = 'neutral'
    reasons.insert(0, f"hand={hand_score:.0f}*w={hand_w:.1f} + sit={sit_score:.0f}*w={sit_w:.1f} → total={score:.0f} → {decision}")
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
