# -*- coding: utf-8 -*-
"""
@title ver.2 戦術決定モジュール
@description ルールベース（オーラスラス・ドラ3強気等）と TacticalTransformer モデル推論を併用し、
              現在の局面（手牌・スタッツ・場況）に応じた最適な戦術モードを決定します。
"""
from __future__ import annotations
import json
import os
import warnings
from enum import Enum
from typing import List, Optional

from core.shanten_v2 import ShantenCalculatorV2
from core.chiitoitsu_v2 import chiitoitsu_mode_applicable
from core.yakuman_v2 import get_active_yakuman


class Mode(Enum):
    RIICHI_ATTACK = "RIICHI_ATTACK"      # 門前立直アタック
    OPEN_ATTACK = "OPEN_ATTACK"          # 副露鳴きアタック
    DAMA_ATTACK = "DAMA_ATTACK"          # 門前ダマテンアタック
    URGENT_ATTACK = "URGENT_ATTACK"      # 全力押し切り
    BALANCED = "BALANCED"                # 通常進行
    DEFEND = "DEFEND"                    # 回し打ち
    FOLD = "FOLD"                        # 完全撤退
    HONITSU_DEFEND = "HONITSU_DEFEND"    # 混一色防御進行
    CHANTA_DEFEND = "CHANTA_DEFEND"      # チャンタ防御進行
    CHIITOITSU = "CHIITOITSU"            # 七対子
    YAKUMAN = "YAKUMAN"                  # 役満
    KOKUSHI = "KOKUSHI"                  # 国士無双


# ──────────────────────────────────────────────
# TacticalTransformer モデル推論 (lazy load)
# ──────────────────────────────────────────────
_MODEL = None
_VOCAB = None
_STATS_DB = None
_DEVICE = None
_MODEL_LOADED = False

_STATS_FEATURE_KEYS = [
    'win_rate', 'deal_in_rate', 'tsumo_rate', 'damaten_rate',
    'meld_rate', 'riichi_rate', 'avg_win_points', 'avg_deal_in_points',
    'avg_win_turn', 'avg_placement',
    'riichi_win_rate', 'riichi_deal_in_rate', 'riichi_exhaustive_rate',
    'open_win_rate', 'deal_in_when_open_rate',
    'bust_rate', 'exhaustive_rate', 'tenpai_rate_in_exh',
    'point_efficiency', 'loss_from_deal_in', 'adj_efficiency',
]

_DEFAULT_STATS_DICT = {
    'win_rate': 0.25, 'deal_in_rate': 0.15, 'tsumo_rate': 0.0,
    'damaten_rate': 0.35, 'meld_rate': 0.20, 'riichi_rate': 0.18,
    'avg_win_points': 5000.0, 'avg_deal_in_points': 4000.0,
    'avg_win_turn': 0.0, 'avg_placement': 2.5,
    'riichi_win_rate': 0.0, 'riichi_deal_in_rate': 0.0,
    'riichi_exhaustive_rate': 0.0, 'open_win_rate': 0.0,
    'deal_in_when_open_rate': 0.0, 'bust_rate': 0.0,
    'exhaustive_rate': 0.0, 'tenpai_rate_in_exh': 0.0,
    'point_efficiency': 0.0, 'loss_from_deal_in': 0.0,
    'adj_efficiency': 0.0,
}

_DEFAULT_STATS_VECTOR = [_DEFAULT_STATS_DICT[k] for k in _STATS_FEATURE_KEYS]


def _resolve_rel(path: str) -> str:
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', path)


def _ensure_loaded():
    global _MODEL, _VOCAB, _STATS_DB, _DEVICE, _MODEL_LOADED
    if _MODEL_LOADED:
        return

    vpath = _resolve_rel('data/vocab.json')
    if os.path.exists(vpath):
        try:
            with open(vpath, 'r', encoding='utf-8') as f:
                _VOCAB = json.load(f)
        except Exception:
            _VOCAB = None

    dbpath = _resolve_rel('data/stats_db.json')
    if os.path.exists(dbpath):
        try:
            with open(dbpath, 'r', encoding='utf-8') as f:
                _STATS_DB = json.load(f).get('players', {})
        except Exception:
            _STATS_DB = {}

    if _VOCAB is None:
        return

    try:
        import torch
    except ImportError:
        return

    ckpt = _resolve_rel('models/tactical_llm_best.pt')
    if not os.path.exists(ckpt):
        ckpt = _resolve_rel('models/tactical_llm_final.pt')
    if not os.path.exists(ckpt):
        return

    try:
        from core.tactical_llm import build_model
        vsz = _VOCAB.get('vocab_size', 271)
        ncls = len(_VOCAB.get('mode_names', [m.name for m in Mode]))
        _DEVICE = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        model = build_model(vocab_size=vsz, num_classes=ncls, dropout=0.0,
                            num_stats_features=len(_STATS_FEATURE_KEYS))
        warnings.filterwarnings('ignore', message='.*weights_only.*')
        state_dict = torch.load(ckpt, map_location=_DEVICE)
        saved_max_seq = state_dict.get('pos_encoder.pe', torch.zeros(256, 1, 64)).shape[0]
        model = build_model(vocab_size=vsz, num_classes=ncls, dropout=0.0,
                            max_seq_len=saved_max_seq,
                            num_stats_features=len(_STATS_FEATURE_KEYS))
        model.load_state_dict(state_dict, strict=False)
        model.to(_DEVICE)
        model.eval()
        _MODEL = model
        _MODEL_LOADED = True
    except Exception:
        _MODEL_LOADED = False


def _tokenize_state(state, shanten: int, player_name: str) -> List[int]:
    vocab = _VOCAB['vocab']
    unk = vocab.get('[UNK]', 1)
    score = state.scores[state.my_seat]
    hand_norm = [
        ('5' + t[1]) if (t[0] == '0' and len(t) >= 2) else t
        for t in state.my_hand
    ]
    ids = [vocab.get('[CLS]', 2)]

    def _sp():
        ids.append(unk)

    def _add(s: str):
        i = 0
        while i < len(s):
            if s[i].isdigit():
                j = i
                while j < len(s) and s[j].isdigit():
                    j += 1
                for ch in s[i:j]:
                    ids.append(vocab.get(ch, unk))
                i = j
                continue
            if i + 2 <= len(s) and s[i:i+2] in vocab:
                ids.append(vocab[s[i:i+2]])
                i += 2
                continue
            ids.append(vocab.get(s[i], unk))
            i += 1

    _add('[PERSONA]'); _sp(); _add(player_name); _sp()
    _add('[SCORE]'); _sp(); _add(str(score)); _sp()
    _add('[SHANTEN]'); _sp(); _add(str(shanten)); _sp()
    _add('[ARROW]'); _sp()
    _add('[HAND]')
    for t in hand_norm:
        _sp(); ids.append(vocab.get(t, unk))
    ids.append(vocab.get('[SEP]', 3))
    return ids


def _get_stats_vector(player_name: str) -> List[float]:
    if _STATS_DB and player_name:
        for pdata in _STATS_DB.values():
            if pdata.get('nickname', '') == player_name:
                return [pdata.get(k, 0.0) for k in _STATS_FEATURE_KEYS]
    return list(_DEFAULT_STATS_VECTOR)


def _predict_with_model(state, shanten: int, player_name: str):
    if not _MODEL_LOADED:
        return None
    try:
        import torch
        tok = _tokenize_state(state, shanten, player_name)
        sv = _get_stats_vector(player_name)
        x = torch.tensor(tok, dtype=torch.long).view(-1, 1).to(_DEVICE)
        sf = torch.tensor([sv], dtype=torch.float32).to(_DEVICE)
        with torch.no_grad():
            cid = _MODEL.forward(x, stats_features=sf).argmax(dim=-1).item()
        modes = _VOCAB.get('mode_names', [])
        return Mode[modes[cid]] if 0 <= cid < len(modes) else None
    except Exception:
        return None


def _count_visible_dora(state) -> int:
    """
    @title 見えているドラ総数（赤ドラ含む）
    @description state.doras の各牌（ドラ表示牌）の見え枚数と、
                 赤5（0m, 0p, 0s）の見え枚数を合計する。
    Why: ドラが多く見えている＝他家のドラ持ちが少ない＝リーチ打点が低い。
         攻めて良い指標として使う。
    @param state - GameState（all_visible_counts, doras を参照）
    @returns {int} 見えているドラ総数
    """
    total = 0
    visible = state.all_visible_counts()
    # ドラ表示牌ごとの見え枚数を合計
    for d in state.doras:
        try:
            from str_converter import tile_to_id
            tid = tile_to_id(d)
            if 0 <= tid < 34:
                total += visible[tid]
        except Exception:
            pass
    # 赤ドラ（0m=4, 0p=13, 0s=22）の見え枚数も加算
    for aka_id in [4, 13, 22]:
        total += visible[aka_id]
    return total


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def get_mode(state, current_turn: int, is_last_round: bool,
             player_name: Optional[str] = None) -> Mode:
    my_counts = state.my_hand_counts()
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count == 0:
        shanten = ShantenCalculatorV2.calculate_closed_effective(my_counts)
    else:
        shanten = ShantenCalculatorV2.calculate_open(my_counts, open_meld_count)

    rank = _my_score_rank(state)
    is_tenpai = shanten <= 0
    n_reach = sum(
        1 for s in range(4)
        if s != state.my_seat
        and state.reach_states[s] is not None
        and state.reach_states[s].is_reach
    )

    # 1. 国士無双 (最優先ルール)
    yakuman = get_active_yakuman(state)
    if yakuman == 'kokushi':
        # 他家放銃警戒度の最大値を取得
        try:
            from core.hand_value_v2 import compute_full_5d
            h5 = compute_full_5d(state)
            max_threat = h5.get('b_risk_max', 0.0)
        except Exception:
            max_threat = 0.0
        is_last_rank4 = is_last_round and rank == 3
        is_tenpai = shanten <= 0
        if max_threat > 0.30 and not is_last_rank4 and not is_tenpai:
            from str_converter import tile_to_id, is_honor, is_terminal
            from core.defense_v2 import safety_score
            hand_ids = [tile_to_id(t) for t in state.my_hand]
            yaochu_ids = {0, 8, 9, 17, 18, 26} | set(range(27, 34))
            yaochu_counts = {}
            for tid in hand_ids:
                if tid in yaochu_ids:
                    yaochu_counts[tid] = yaochu_counts.get(tid, 0) + 1
            head_tid = None
            max_cnt = 1
            for tid, count in yaochu_counts.items():
                if count > max_cnt:
                    max_cnt = count
                    head_tid = tid
            keep_limits = {tid: 1 for tid in yaochu_counts}
            if head_tid is not None:
                keep_limits[head_tid] = 2
            current_keep = {}
            has_safe_garbage = False
            for tile in state.my_hand:
                tid = tile_to_id(tile)
                is_garbage = False
                if tid not in yaochu_ids:
                    is_garbage = True
                else:
                    current_keep[tid] = current_keep.get(tid, 0) + 1
                    if current_keep[tid] > keep_limits[tid]:
                        is_garbage = True
                if is_garbage:
                    saf = safety_score(state, tile)
                    if saf >= 600:
                        has_safe_garbage = True
                        break
            if not has_safe_garbage:
                return Mode.FOLD
        return Mode.KOKUSHI

    # 2. 役満 (最優先ルール)
    if yakuman is not None and yakuman != 'kokushi':
        return Mode.YAKUMAN

    # 3. 終盤 4 位 (最優先ルール)
    if is_last_round and rank == 3:
        return Mode.URGENT_ATTACK

    # 4. 七対子 (最優先ルール)
    if chiitoitsu_mode_applicable(state, current_turn):
        return Mode.CHIITOITSU

    # 4b. ドラ見え時の強気押し返し
    # Why: 自分からドラが大量に見えている＝他家のドラ持ちが少ない＝他家リーチの打点が低い。
    #      テンパイor一シャンテンならオリる理由がなく、強気に押す。
    visible_dora = _count_visible_dora(state)
    if visible_dora >= 3 and shanten <= 1:
        return Mode.OPEN_ATTACK if open_meld_count > 0 else Mode.RIICHI_ATTACK

    # 5. TacticalTransformer 推論
    _ensure_loaded()
    if _MODEL_LOADED:
        name = player_name or getattr(state, 'player_name', None) or 'player'
        predicted = _predict_with_model(state, shanten, name)
        if predicted is not None:
            return predicted

    # 6. フォールバック: 従来の if-else
    if n_reach >= 2 and not is_tenpai:
        return Mode.FOLD
    if n_reach >= 1 and not is_tenpai:
        return Mode.DEFEND
    if shanten <= 1:
        return Mode.RIICHI_ATTACK
    return Mode.BALANCED


def _my_score_rank(state) -> int:
    my_score = state.scores[state.my_seat]
    sorted_scores = sorted(state.scores, reverse=True)
    return sorted_scores.index(my_score)
