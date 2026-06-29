# -*- coding: utf-8 -*-
"""
@title ver.2 副露判断 (加減算モデル、22 要素)
@description 副露を 0/1 ではなく、22 要素の加重スコアで評価:
              meld_score = Σ(加点要素 × 重み) - Σ(減点要素 × 重み)
              meld_score > THRESHOLD なら鳴く。

要素カテゴリ:
  [基本スタッツ] 1-6
  [手役・染め手] 7-9
  [河・山] 10-12
  [状況・他家] 13-22

重みは config/config_parameters.json で調整可能。
"""
from __future__ import annotations
from typing import List, Tuple

from core.str_converter import tile_to_id, is_honor, hand_to_counts
from core.shanten_v2 import ShantenCalculatorV2


# デフォルト重み (config で上書き可能)
DEFAULT_WEIGHTS = {
    # [基本スタッツ] 1-6
    'MELD_W_SHANTEN_PROGRESS': 400.0,   # 1. シャンテン進行
    'MELD_W_UKEIRE': 8.0,              # 2. 受け入れ枚数
    'MELD_W_HAN_GAIN': 150.0,          # 3. 翻数期待値 (門前 vs 鳴き)
    'MELD_W_WAIT_QUALITY': 100.0,      # 4. 待ちの形 (両面 > 愚形)
    'MELD_W_DISCARD_RISK': 50.0,       # 5. 孤立牌放銃リスク
    'MELD_W_MELD_REMAINING': 300.0,    # 6. 残り副露可能回数
    # [手役・染め手] 7-9
    'MELD_W_YAKU_FIXED': 200.0,        # 7. 役の確定
    'MELD_W_YAKU_LOSS': 150.0,         # 8. 食い下がり・消滅
    'MELD_W_HONITSU_WARN': 100.0,      # 9. 染め手警戒度上昇
    # [河・山] 10-12
    'MELD_W_VISIBLE_COUNT': 30.0,      # 10. 鳴く牌の見え枚数
    'MELD_W_YAMA_REMAIN': 5.0,         # 11. 壁・スジ・ノーチャンス
    'MELD_W_KAMICHA_AFFINITY': 80.0,   # 12. 上家 affinity
    # [状況・他家] 13-22
    'MELD_W_TURN_EARLY_PENALTY': 80.0, # 13. 序盤
    'MELD_W_TSUMO_LEFT': 30.0,         # 14. 残りツモ
    'MELD_W_KYOHAKU_BONUS': 100.0,     # 15. 供託・本場
    'MELD_W_ROUND_POSITION': 80.0,     # 16. 残り局数
    'MELD_W_RANK_FACTOR': 100.0,       # 17. 自身の順位・点差
    'MELD_W_OPP_REACH': 200.0,         # 18. 他家リーチ
    'MELD_W_OPP_HIGH_HAN': 200.0,      # 19. 他家想定打点
    'MELD_W_SAFE_TILES_AFTER': 50.0,   # 20. 鳴き後の安牌残数
    'MELD_W_DEALER': 80.0,             # 21. 親番
    'MELD_W_OPP_STYLE': 60.0,          # 22. 他家スタイル
    # threshold と全体補正
    'MELD_THRESHOLD': 0.0,              # meld_score > 0 で鳴く
    'MELD_BASE_BIAS': 0.0,              # 基本バイアス (正で鳴き寄り)
}


def get_weights(params: dict) -> dict:
    """@title params から重みを取得 (未設定ならデフォルト)"""
    w = dict(DEFAULT_WEIGHTS)
    if params:
        for k in w:
            v = params.get(k)
            if v is not None:
                w[k] = float(v)
    return w


# ============================================================
# ヘルパー: 鳴きシミュレーション
# ============================================================
def simulate_meld(hand: List[str], call_type: int, tiles: List[str]) -> Tuple[List[str], int, int]:
    """
    @title 副露シミュレーション
    @returns (hand_after, shanten_after, melds_after)
    """
    try:
        hand_after = list(hand)
        if call_type == 1:  # ポン
            consumed = [tiles[0], tiles[0]]
        elif call_type == 0:  # チー
            consumed = list(tiles[1:]) if len(tiles) > 1 else []
        elif call_type == 2:  # 大明槓
            consumed = [tiles[0], tiles[0], tiles[0]]
        else:
            return hand_after, 8, 0
        for t in consumed:
            try:
                tid = tile_to_id(t)
            except Exception:
                continue
            for h in list(hand_after):
                try:
                    if tile_to_id(h) == tid:
                        hand_after.remove(h)
                        break
                except Exception:
                    continue
        counts = hand_to_counts(hand_after)
        sh = ShantenCalculatorV2.calculate_open(counts, 1)  # 1 副露
        return hand_after, sh, 1
    except Exception:
        return list(hand), 8, 1


# ============================================================
# 要素 1: シャンテン進行
# ============================================================
def score_shanten_progress(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 1. シャンテン進行の加点"""
    w = get_weights(params)
    hand = list(state.my_hand)
    counts_before = hand_to_counts(hand)
    open_meld_before = sum(1 for m in state.my_melds if m.is_open)
    sh_before = ShantenCalculatorV2.calculate_open(counts_before, open_meld_before) if open_meld_before else ShantenCalculatorV2.calculate_closed_effective(counts_before)
    _, sh_after, _ = simulate_meld(hand, call_type, tiles)
    diff = sh_before - sh_after
    score = w['MELD_W_SHANTEN_PROGRESS'] * diff
    return score, f"シャンテン進行 {sh_before}→{sh_after} ({diff:+d})"


# ============================================================
# 要素 2: 受け入れ枚数
# ============================================================
def score_ukeire(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 2. 受け入れ枚数の加点 (純粋枚数ベース近似)"""
    w = get_weights(params)
    hand_after, _, _ = simulate_meld(state.my_hand, call_type, tiles)
    counts = hand_to_counts(hand_after)
    # 簡易受け入れ計算: 面子/塔子/雀頭候補を足す
    # (詳細計算は ukeire_v2.count_ukeire を呼ぶ)
    from core.ukeire_v2 import count_ukeire
    ukeire_good, ukeire_bad = count_ukeire_after_meld(counts, state, hand_after)
    score = w['MELD_W_UKEIRE'] * (ukeire_good + 0.3 * ukeire_bad)
    return score, f"受け入れ {ukeire_good}+{ukeire_bad}枚"


def count_ukeire_after_meld(counts, state, hand_after) -> Tuple[int, int]:
    """@title 鳴いた後の受け入れ枚数 (良形/愚形)"""
    # 簡易計算: 各牌種について +1/+2/+3/+4 牌が見えたら枚数を加算
    # (詳細: ukeire_v2.count_ukeire を使う)
    try:
        from core.ukeire_v2 import count_ukeire
        return count_ukeire(state, 'meld_after')
    except Exception:
        return 8, 4


# ============================================================
# 要素 3: 翻数期待値 (門前 vs 鳴き)
# ============================================================
def score_han_gain(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 3. 門前 vs 鳴きの翻数期待値差
    @description 満貫 (8,000 点 = 4 翻) 以上なら加点大幅 UP、押し判断の核
    """
    w = get_weights(params)
    target_id = tile_to_id(tiles[0]) if tiles else -1
    SANGEN = {31, 32, 33}
    is_yakuhai_potential = False
    if call_type == 1 and 0 <= target_id <= 33:
        if target_id in SANGEN:
            is_yakuhai_potential = True
        else:
            seat_wind = 27 + ((state.my_seat - state.ju) % 4)
            round_wind = 27 + (state.chang % 4)
            if target_id in (seat_wind, round_wind):
                is_yakuhai_potential = True
    # チーでも手役 +1 翻 (順子確定) なら加点
    is_shuntsu = False
    if call_type == 0 and len(tiles) == 3:
        ids = sorted([tile_to_id(t) for t in tiles if t])
        if len(ids) == 3 and ids[0] + 1 == ids[1] and ids[1] + 1 == ids[2]:
            is_shuntsu = True
    if not is_yakuhai_potential and not is_shuntsu:
        return 0.0, "役牌確定なし"
    # 序盤 (6 巡以内) は 順子加点なし (面子の自由度維持)
    turn = (state.tsumo_count - 1) // 4 + 1
    # 役牌ポンで +1 翻 / チー順子で +0.3 翻
    if is_shuntsu and turn <= 6:
        return 0.0, f"序盤 ({turn} 巡) 順子加点なし"
    gain = 0.3 if is_shuntsu else 1.0
    # ドラなら追加
    dora_count = count_dora_tiles(state.my_hand + ([tiles[0]] if call_type in (1, 2) else []), state.doras)
    if dora_count >= 3:
        gain += 2.0  # ドラ 3 で +2
    elif dora_count >= 1:
        gain += 0.5 * dora_count
    # 満貫 (4 翻) 以上なら加点大幅 UP (押し判断)
    if gain >= 2.5:
        score = w['MELD_W_HAN_GAIN'] * gain * 1.5
    else:
        score = w['MELD_W_HAN_GAIN'] * gain
    return score, f"翻数期待 +{gain:.1f}翻"


def count_dora_tiles(hand: List[str], dora_indicators: List[str]) -> int:
    """@title 手牌内ドラ枚数"""
    n = 0
    dora_ids = set()
    for d in dora_indicators:
        try:
            dora_ids.add(tile_to_id(d))
        except Exception:
            pass
    for t in hand:
        try:
            if tile_to_id(t) in dora_ids:
                n += 1
        except Exception:
            pass
    return n


# ============================================================
# 要素 4: 待ちの形
# ============================================================
def score_wait_quality(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 4. 待ちの形 (テンパイ時 両面 > 愚形)"""
    w = get_weights(params)
    hand_after, sh_after, _ = simulate_meld(state.my_hand, call_type, tiles)
    if sh_after > 0:
        return 0.0, "テンパイ未到達"
    # テンパイ時: 両面多そうな手なら加点
    # 簡易判定: 手牌に塔子候補 (12 形とか) があれば加点
    score = w['MELD_W_WAIT_QUALITY'] * 0.5  # 仮で +0.5
    return score, "テンパイ到達 (待ち詳細判定は省略)"


# ============================================================
# 要素 5: 孤立牌放銃リスク
# ============================================================
def score_discard_risk(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 5. 孤立牌・不要牌の放銃リスク (減点)"""
    w = get_weights(params)
    if call_type != 0:  # チー以外は無関係
        return 0.0, "チー以外"
    consumed = list(tiles[1:])
    # consumed が他家にとって当たり牌の可能性
    risk = 0.0
    for t in consumed:
        try:
            tid = tile_to_id(t)
        except Exception:
            continue
        # 現物判定 (他家河にある = 0 リスク)
        safe = False
        for s in range(4):
            if s == state.my_seat:
                continue
            for r in state.river[s]:
                try:
                    if tile_to_id(r) == tid:
                        safe = True
                        break
                except Exception:
                    continue
            if safe:
                break
        if not safe:
            risk += 1.0
    score = -w['MELD_W_DISCARD_RISK'] * risk
    return score, f"放銃リスク {risk}枚"


# ============================================================
# 要素 6: 残り副露可能回数
# ============================================================
def score_meld_remaining(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 6. 残り副露可能回数 (3 副露目 = 守備力激減)"""
    w = get_weights(params)
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    new_count = open_meld_count + 1
    if new_count >= 4:
        return -9999.0, f"4 副露でこれ以上鳴けない"
    if new_count == 3:
        return -w['MELD_W_MELD_REMAINING'] * 0.7, "3 副露目 (守備力激減)"
    if new_count == 2:
        return -w['MELD_W_MELD_REMAINING'] * 0.2, "2 副露目 (守備力減)"
    return 0.0, f"残り {4 - new_count} 回"


# ============================================================
# 要素 7: 役の確定
# ============================================================
def score_yaku_fixed(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 7. 役の確定有無 (役牌/三元/タンヤオ)
    @description 通常のポンでも加点 (1 面子追加 = 価値あり)
    """
    w = get_weights(params)
    target_id = tile_to_id(tiles[0]) if tiles else -1
    SANGEN = {31, 32, 33}
    is_yakuhai = False
    is_otakaze = False
    if call_type == 1 and 0 <= target_id <= 33:
        if target_id in SANGEN:
            is_yakuhai = True
        else:
            seat_wind = 27 + ((state.my_seat - state.ju) % 4)
            round_wind = 27 + (state.chang % 4)
            if target_id in (seat_wind, round_wind):
                is_yakuhai = True
            elif 27 <= target_id <= 30:
                is_otakaze = True
    is_shuntsu_complete = False
    if call_type == 0 and len(tiles) == 3:
        ids = sorted([tile_to_id(t) for t in tiles if t])
        if len(ids) == 3 and ids[0] + 1 == ids[1] and ids[1] + 1 == ids[2]:
            is_shuntsu_complete = True
    if is_yakuhai:
        return w['MELD_W_YAKU_FIXED'], "役牌確定"
    if is_otakaze:
        return _score_otakaze_pon(state, target_id, params)
    if is_shuntsu_complete:
        return w['MELD_W_YAKU_FIXED'] * 0.3, "順子形成 (役未確定)"
    if call_type == 1:  # 通常のポン: 1 面子追加 = 価値あり
        return w['MELD_W_YAKU_FIXED'] * 0.4, "ポン 1 面子追加 (進行期待)"
    return 0.0, "役未確定"


def _score_otakaze_pon(state, target_id, params) -> Tuple[float, str]:
    """
    @title オタ風ポンの状況判断
    @description
        オタ風ポンも状況次第で OK:
        1. 染め手狙い: 手牌内字牌 >= 6 → 混一色狙い OK (加点)
        2. トイトイ狙い: 既 1 副露 + 対子複数 → トイトイ移行 OK (加点)
        3. 攻めてる最中: 4 巡目以降 + 1 向聴 + 副露牌が 4 枚目 → 仕方なく OK (微加点)
        4. それ以外: 基本禁止 (減点)
    """
    w = get_weights(params)
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    hand = list(state.my_hand)
    hand_counts = hand_to_counts(hand)
    # 手牌内字牌枚数
    honor_count = sum(hand_counts[i] for i in range(27, 34))
    # 手牌内対子数
    pair_count = sum(1 for c in hand_counts if c >= 2)
    # 副露牌が 4 枚目 (= 既 3 枚持っている) = 鳴かないとあがれない
    target_count = hand_counts[target_id] if 0 <= target_id < 34 else 0
    # 巡目
    turn = (state.tsumo_count - 1) // 4 + 1
    # シャンテン数
    sh = ShantenCalculatorV2.calculate_closed_effective(hand_counts)

    # 1. 染め手狙い: 字牌 >= 8 (過半数) のみ染め手狙い
    if honor_count >= 8:
        return w['MELD_W_YAKU_FIXED'] * 0.5, f"染め手狙い (字牌 {honor_count} 枚)"
    # 2. トイトイ狙い: 1 副露済み + 対子 2 個以上
    if open_meld_count >= 1 and pair_count >= 2:
        return w['MELD_W_YAKU_FIXED'] * 0.4, f"トイトイ狙い ({open_meld_count} 副露 + 対子 {pair_count})"
    # 3. 鳴かないとあがれない: 4 巡目以降 + 1 向聴 + 副露牌が 4 枚目
    if turn >= 4 and sh == 1 and target_count >= 3:
        return w['MELD_W_YAKU_FIXED'] * 0.2, f"仕方なく (巡目 {turn} + 1 向聴 + 牌 {target_count} 枚)"
    # 4. それ以外: 基本禁止
    return -w['MELD_W_YAKU_FIXED'] * 0.8, f"オタ風ポン禁止 (字牌 {honor_count} 枚 + 対子 {pair_count} 個)"


# ============================================================
# 要素 8: 食い下がり・消滅する役
# ============================================================
def score_yaku_loss(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 8. 食い下がり・消滅する役 (減点)
    @description チーは食い下がりが大きく、ポンはやや軽い
    """
    w = get_weights(params)
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    new_open = open_meld_count + 1
    if new_open == 0:
        return 0.0, "門前維持"
    loss = 0.0
    if call_type == 0:  # チー: 食い下がり大
        loss += 0.3  # 0.4 → 0.3 (軽量化)
    elif call_type == 1:  # ポン: 食い下がり中
        loss += 0.15  # 0.2 → 0.15 (軽量化)
    else:
        loss += 0.05
    score = -w['MELD_W_YAKU_LOSS'] * loss
    return score, f"門前役消滅 -{loss:.2f}"


# ============================================================
# 要素 9: 染め手警戒度上昇
# ============================================================
def score_honitsu_warning(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 9. 染め手警戒度上昇 (他家から警戒される)"""
    w = get_weights(params)
    target_id = tile_to_id(tiles[0]) if tiles else -1
    if not (0 <= target_id <= 26):  # 数牌以外
        return 0.0, "字牌 (染め手警戒低)"
    suit = target_id // 9
    # トイトイ移行中 (2 副露目以降の ポン) は染め手警戒なし
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if call_type == 1 and open_meld_count >= 1:
        # 既に副露済みで 2 副露目のポン → トイトイ狙い → 染め手警戒なし
        return 0.0, f"トイトイ移行中 ({open_meld_count} 副露目)"
    # 鳴いた色が明確になる = 染め手警戒
    if call_type == 1:  # ポン
        return -w['MELD_W_HONITSU_WARN'] * 0.6, f"ポン (他家警戒 {suit}色)"
    if call_type == 0:  # チー
        return -w['MELD_W_HONITSU_WARN'] * 0.3, f"チー (他家警戒 {suit}色)"
    return 0.0, ""


# ============================================================
# 要素 10: 鳴く牌の見え枚数
# ============================================================
def score_visible_count(state, tiles, params) -> Tuple[float, str]:
    """@title 10. 鳴く牌の見え枚数 (少ないほど安全)"""
    w = get_weights(params)
    if not tiles:
        return 0.0, ""
    target_id = tile_to_id(tiles[0]) if tiles[0] else -1
    if target_id < 0:
        return 0.0, ""
    visible = state.all_visible_counts()
    my_count = state.my_hand_counts()[target_id]
    public_count = visible[target_id] - my_count
    # 見え枚数多い → 山残り少ない → 待ち牌として弱い
    if public_count >= 3:
        return -w['MELD_W_VISIBLE_COUNT'] * 2, f"見え {public_count} 枚 (山僅か)"
    if public_count >= 2:
        return -w['MELD_W_VISIBLE_COUNT'] * 0.5, f"見え {public_count} 枚"
    if public_count == 0:
        return w['MELD_W_VISIBLE_COUNT'] * 0.5, f"生牌 ({public_count} 枚見え)"
    return 0.0, f"見え {public_count} 枚"


# ============================================================
# 要素 11: 壁・スジ・ノーチャンス
# ============================================================
def score_yama_remain(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 11. 自アガリ牌の山残り期待度 (近似)"""
    w = get_weights(params)
    target_id = tile_to_id(tiles[0]) if tiles else -1
    if target_id < 0:
        return 0.0, ""
    # 4 - visible = 山残り
    visible = state.all_visible_counts()
    public = visible[target_id] - state.my_hand_counts()[target_id]
    remain = max(0, 4 - visible[target_id])
    if remain == 0:
        return -w['MELD_W_YAMA_REMAIN'] * 5, "山 0 枚 (アガリ牌なし)"
    return w['MELD_W_YAMA_REMAIN'] * remain, f"山残り {remain} 枚"


# ============================================================
# 要素 12: 上家 affinity (チー限定)
# ============================================================
def score_kamicha_affinity(state, call_type, from_seat, params) -> Tuple[float, str]:
    """@title 12. 上家 affinity (チー限定)"""
    w = get_weights(params)
    if call_type != 0:
        return 0.0, "チー以外"
    # from_seat がカミチャ (自分の左 = my_seat + 3)
    kamicha = (state.my_seat + 3) % 4
    if from_seat != kamicha:
        return -w['MELD_W_KAMICHA_AFFINITY'] * 0.3, "下家/対面チー (依存度低)"
    return w['MELD_W_KAMICHA_AFFINITY'] * 0.5, "上家チー (継続チー期待)"


# ============================================================
# 要素 13: 巡目 (序盤減点)
# ============================================================
def score_turn_early(state, params) -> Tuple[float, str]:
    """@title 13. 巡目 (序盤は減点)"""
    w = get_weights(params)
    turn = (state.tsumo_count - 1) // 4 + 1
    if turn <= 3:
        return -w['MELD_W_TURN_EARLY_PENALTY'] * 1.5, f"序盤 {turn} 巡 (面子の自由度維持)"
    if turn <= 7:
        return -w['MELD_W_TURN_EARLY_PENALTY'] * 0.7, f"中盤序 {turn} 巡"
    if turn >= 14:
        return w['MELD_W_TURN_EARLY_PENALTY'] * 0.3, f"終盤 {turn} 巡 (加点効率)"
    return 0.0, f"{turn} 巡"


# ============================================================
# 要素 14: 残りツモ回数
# ============================================================
def score_tsumo_left(state, params) -> Tuple[float, str]:
    """@title 14. 残りツモ回数 (少ないとツモ期待低)"""
    w = get_weights(params)
    left = state.left_tile_count
    own_tsumo = left // 4 + 1
    if own_tsumo <= 2:
        return -w['MELD_W_TSUMO_LEFT'] * 1.5, f"残りツモ {own_tsumo} 回 (少)"
    if own_tsumo >= 8:
        return w['MELD_W_TSUMO_LEFT'] * 0.5, f"残りツモ {own_tsumo} 回 (多)"
    return 0.0, f"残りツモ {own_tsumo} 回"


# ============================================================
# 要素 15: 供託・本場
# ============================================================
def score_kyohaku(state, params) -> Tuple[float, str]:
    """@title 15. 供託 (リーチ棒) + 本場"""
    w = get_weights(params)
    bonus = 0
    if hasattr(state, 'liqibang'):
        bonus += state.liqibang * 1000
    if hasattr(state, 'ben'):
        bonus += state.ben * 300
    if bonus >= 4000:
        return w['MELD_W_KYOHAKU_BONUS'] * 1.0, f"供託+本場 {bonus}点 (加点魅力大)"
    if bonus >= 1500:
        return w['MELD_W_KYOHAKU_BONUS'] * 0.3, f"供託+本場 {bonus}点"
    return 0.0, f"供託+本場 {bonus}点"


# ============================================================
# 要素 13: 巡目 (序盤減点)
# ============================================================
def score_turn_early(state, params) -> Tuple[float, str]:
    """@title 13. 巡目 (序盤は減点)"""
    w = get_weights(params)
    turn = (state.tsumo_count - 1) // 4 + 1
    if turn <= 3:
        return -w['MELD_W_TURN_EARLY_PENALTY'] * 0.8, f"序盤 {turn} 巡 (面子の自由度維持)"
    if turn <= 7:
        return -w['MELD_W_TURN_EARLY_PENALTY'] * 0.3, f"中盤序 {turn} 巡"
    if turn >= 14:
        return w['MELD_W_TURN_EARLY_PENALTY'] * 0.3, f"終盤 {turn} 巡 (加点効率)"
    return 0.0, f"{turn} 巡"


# ============================================================
# 要素 16: 残り局数 (オーラス)
# ============================================================
def score_round_position(state, params) -> Tuple[float, str]:
    """@title 16. 残り局数 (オーラス)
    @description 人間はオーラスでも鳴く判断あり → 撤廃
    """
    w = get_weights(params)
    return 0.0, "状況依存なし"


# ============================================================
# 要素 17: 自身の順位・点差
# ============================================================
def score_rank(state, params) -> Tuple[float, str]:
    """@title 17. 自身の順位・点差 (ラス = 攻め、トップ = 慎重)"""
    w = get_weights(params)
    if not hasattr(state, 'scores'):
        return 0.0, "順位情報なし"
    my_score = state.scores[state.my_seat]
    sorted_scores = sorted(state.scores, reverse=True)
    my_rank = sorted_scores.index(my_score)
    if my_rank == 3:  # ラス
        return w['MELD_W_RANK_FACTOR'] * 0.5, "ラス目 (攻め必要)"
    return 0.0, f"{my_rank + 1} 位"


# ============================================================
# 要素 18: 他家リーチ
# ============================================================
def score_opp_reach(state, params) -> Tuple[float, str]:
    """@title 18. 他家リーチ (減点)
    @description リーチ者への押しは手役が満貫以上なら可
    """
    w = get_weights(params)
    n_reach = sum(
        1 for s in range(4)
        if s != state.my_seat
        and state.reach_states[s] is not None
        and state.reach_states[s].is_reach
    )
    if n_reach >= 2:
        return -w['MELD_W_OPP_REACH'] * 1.5, f"他家リーチ {n_reach} 人 (守備最優先)"
    if n_reach == 1:
        return -w['MELD_W_OPP_REACH'] * 0.4, f"他家リーチ {n_reach} 人"
    return 0.0, "他家リーチなし"


# ============================================================
# 要素 19: 他家想定打点
# ============================================================
def score_opp_high_han(state, params) -> Tuple[float, str]:
    """@title 19. 他家想定打点 (高打点気配で減点)"""
    w = get_weights(params)
    # 簡略: 河の状況でマンガン気配を判定
    # 詳細: ドラ表示牌、捨牌パターン、副露 etc.
    # ここでは暫定的に安全牌が少ない河 = 高打点気配
    safe_discard_count = 0
    for s in range(4):
        if s == state.my_seat:
            continue
        for r in state.river[s]:
            try:
                if is_honor(tile_to_id(r)):
                    safe_discard_count += 1
            except Exception:
                continue
    if safe_discard_count >= 6:
        return -w['MELD_W_OPP_HIGH_HAN'] * 0.8, "他家高打点気配 (字牌多)"
    return 0.0, "他家打点不明"


# ============================================================
# 要素 20: 鳴いた後の守備力
# ============================================================
def score_safe_tiles_after(state, call_type, tiles, params) -> Tuple[float, str]:
    """@title 20. 鳴いた後の守備力 (安牌残数 + 残り手牌枚数)
    @description
        - 残安牌 (字牌) 1 枚につき加点
        - 残り手牌 4 枚以下 = 守備力激減で減点
        - 残り手牌 1 枚 (裸単騎) = 致命的に減点
    """
    w = get_weights(params)
    hand_after, _, _ = simulate_meld(state.my_hand, call_type, tiles)
    n_remain = len(hand_after)
    safe = 0
    for t in hand_after:
        try:
            if is_honor(tile_to_id(t)):
                safe += 1
        except Exception:
            continue
    score = w['MELD_W_SAFE_TILES_AFTER'] * safe
    # 残り手牌枚数による守備力補正
    if n_remain <= 1:
        score -= w['MELD_W_SAFE_TILES_AFTER'] * 8  # 裸単騎 = 致命
    elif n_remain <= 2:
        score -= w['MELD_W_SAFE_TILES_AFTER'] * 4  # 2 枚手 = 激減
    elif n_remain <= 3:
        score -= w['MELD_W_SAFE_TILES_AFTER'] * 2  # 3 枚手 = 減
    elif n_remain <= 4:
        score -= w['MELD_W_SAFE_TILES_AFTER'] * 0.5  # 4 枚手 = やや減
    return score, f"安牌 {safe} 枚 + 残り {n_remain} 枚手"


# ============================================================
# 要素 21: 親番
# ============================================================
def score_dealer(state, params) -> Tuple[float, str]:
    """@title 21. 親番 (加点)"""
    w = get_weights(params)
    if hasattr(state, 'dealer_seat') and state.dealer_seat == state.my_seat:
        return w['MELD_W_DEALER'] * 0.5, "親番 (連荘狙い)"
    return 0.0, "子番"


# ============================================================
# 要素 22: 他家プレイスタイル
# ============================================================
def score_opp_style(state, params) -> Tuple[float, str]:
    """@title 22. 他家プレイスタイル (AI スタッツ保持時のみ)"""
    w = get_weights(params)
    # 簡略: 他家の河の字牌率が高い = オリるタイプ
    opp_honor_rate = 0.0
    opp_count = 0
    for s in range(4):
        if s == state.my_seat:
            continue
        for r in state.river[s]:
            opp_count += 1
            try:
                if is_honor(tile_to_id(r)):
                    opp_honor_rate += 1
            except Exception:
                continue
    if opp_count == 0:
        return 0.0, "情報不足"
    rate = opp_honor_rate / opp_count
    if rate >= 0.4:
        return w['MELD_W_OPP_STYLE'] * 0.5, "他家オリ傾向 (鳴き牽制有効)"
    return 0.0, f"他家字牌率 {rate:.0%}"


# ============================================================
# 統合
# ============================================================
SCORERS = [
    ('1.シャンテン進行', score_shanten_progress, ('state', 'call_type', 'tiles', 'params')),
    ('2.受け入れ枚数', score_ukeire, ('state', 'call_type', 'tiles', 'params')),
    ('3.翻数期待値', score_han_gain, ('state', 'call_type', 'tiles', 'params')),
    ('4.待ちの形', score_wait_quality, ('state', 'call_type', 'tiles', 'params')),
    ('5.孤立牌放銃', score_discard_risk, ('state', 'call_type', 'tiles', 'params')),
    ('6.副露残数', score_meld_remaining, ('state', 'call_type', 'tiles', 'params')),
    ('7.役確定', score_yaku_fixed, ('state', 'call_type', 'tiles', 'params')),
    ('8.門前役消滅', score_yaku_loss, ('state', 'call_type', 'tiles', 'params')),
    ('9.染め手警戒', score_honitsu_warning, ('call_type', 'tiles', 'params')),
    ('10.見え枚数', score_visible_count, ('state', 'tiles', 'params')),
    ('11.山残り', score_yama_remain, ('state', 'call_type', 'tiles', 'params')),
    ('12.上家affinity', score_kamicha_affinity, ('state', 'call_type', 'from_seat', 'params')),
    ('13.巡目', score_turn_early, ('state', 'params')),
    ('14.残りツモ', score_tsumo_left, ('state', 'params')),
    ('15.供託本場', score_kyohaku, ('state', 'params')),
    ('16.残り局数', score_round_position, ('state', 'params')),
    ('17.順位点差', score_rank, ('state', 'params')),
    ('18.他家リーチ', score_opp_reach, ('state', 'params')),
    ('19.他家打点', score_opp_high_han, ('state', 'params')),
    ('20.安牌残数', score_safe_tiles_after, ('state', 'call_type', 'tiles', 'params')),
    ('21.親番', score_dealer, ('state', 'params')),
    ('22.他家スタイル', score_opp_style, ('state', 'params')),
]


def score_meld(state, call_type: int, tiles: List[str], from_seat: int, params: dict) -> Tuple[float, List[Tuple[str, float, str]]]:
    """
    @title 22 要素の加重スコア合計
    @returns (total_score, [(name, value, reason), ...])
    """
    w = get_weights(params)
    total = w.get('MELD_BASE_BIAS', 0.0)
    breakdown = []
    for name, scorer, sig in SCORERS:
        try:
            args = {p: eval(p, {'state': state, 'call_type': call_type, 'tiles': tiles, 'from_seat': from_seat, 'params': params}) for p in sig}
            value, reason = scorer(**args)
        except Exception as e:
            value, reason = 0.0, f"err: {type(e).__name__}"
        total += value
        breakdown.append((name, value, reason))
    return total, breakdown


def should_call_meld(state, call_type: int, tiles: List[str], from_seat: int, params: dict) -> Tuple[bool, str]:
    """
    @title 副露すべきか (ver.2 加減算モデル)
    @returns (鳴くべきか, 理由文字列)
    """
    w = get_weights(params)
    total, breakdown = score_meld(state, call_type, tiles, from_seat, params)
    threshold = w['MELD_THRESHOLD']
    decision = total > threshold
    # 主要な要素を 3 つまで表示
    top_items = sorted(breakdown, key=lambda x: -abs(x[1]))[:3]
    reason_parts = [f"{n}({v:+.0f})" for n, v, _ in top_items]
    reason = f"meld_score={total:+.0f} {' > ' if decision else ' <= '}threshold={threshold} | top: " + " ".join(reason_parts)
    return decision, reason
