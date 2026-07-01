# -*- coding: utf-8 -*-
"""
@title 戦術LLM トークナイズ前処理スクリプト
@description 牌譜データを解析し、戦術モード予測Transformer用の
             トークン系列に変換する。

入力トークン形式:
  [Persona: <nickname>] [Stats: wr=0.25 dir=0.15 mr=0.35 rr=0.22 dmr=0.30 awp=5200 adp=3800]
  [Score: 25000] [Shanten: 1] -> [1m 2m 3m 4z 5z 6s 7s 8s 9s 1p 1p 2p 3p]

出力:
  - tokenized_data.json: { "examples": [ { "tokens": [...], "label": <mode_id> } ] }
  - vocab.json: { "token_str": token_id, ... }

Why: ルールベース (core/strategy_v2.py) とニューラルモデルの両方を併用する
     ハイブリッド構成を取るため、牌譜データから学習可能な形式に変換する必要がある。
"""
from __future__ import annotations
import json
import os
import re
import sys
from typing import Dict, List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.shanten_v2 import ShantenCalculatorV2
from core.str_converter import hand_to_counts
from core.strategy_v2 import get_mode, Mode
from tools.build_stats_db import load_stats_db, _tenhou_tile_to_str, TENHOU_XML_DIR


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
OUTPUT_TOKENIZED = os.path.join(DATA_DIR, 'tokenized_data.json')
OUTPUT_VOCAB = os.path.join(DATA_DIR, 'vocab.json')

# 全34種の正規化牌表記（赤5は通常5に正規化する）
# Why: 赤5と通常5は戦術的意味が異なるが、トークン数を抑えるため同一視する。
ALL_TILES_NORMALIZED = [
    f'{n}{s}'
    for s in ('m', 'p', 's')
    for n in range(1, 10)
] + [f'{n}z' for n in range(1, 8)]

# モード名一覧（Mode enum → index のマッピング）
MODE_NAMES = [m.name for m in Mode]
MODE_NAME_TO_ID = {name: i for i, name in enumerate(MODE_NAMES)}


class TacticalTokenizer:
    """
    @title 戦術トークナイザ
    @description 牌譜から抽出した局面情報をTransformer入力用のトークン系列に変換する。
                 語彙は自動構築される。
    """

    SPECIAL_TOKENS = [
        '[PAD]', '[UNK]', '[CLS]', '[SEP]',
        '[PERSONA]', '[STATS]', '[SCORE]', '[SHANTEN]',
        '[ARROW]', '[HAND]',
    ]

    # 特殊記号トークン
    SYMBOL_TOKENS = ['=', '(', ')', '.', '-', '>']

    def __init__(self):
        self.vocab: Dict[str, int] = {}
        self.inv_vocab: Dict[int, str] = {}
        self._build_base_vocab()

    def _build_base_vocab(self):
        """特殊トークン + 牌 + 記号で基本語彙を構築"""
        idx = 0
        for tok in self.SPECIAL_TOKENS:
            self.vocab[tok] = idx
            self.inv_vocab[idx] = tok
            idx += 1

        # 牌トークン (34種)
        for tile in ALL_TILES_NORMALIZED:
            if tile not in self.vocab:
                self.vocab[tile] = idx
                self.inv_vocab[idx] = tile
                idx += 1

        # 数字トークン (0-9, 10-99999 は桁ごと)
        for n in list(range(10)):
            s = str(n)
            self.vocab[s] = idx
            self.inv_vocab[idx] = s
            idx += 1

        # 統計キートークン
        for key in ['wr', 'dir', 'mr', 'rr', 'dmr', 'awp', 'adp', 'score', 'shanten']:
            self.vocab[key] = idx
            self.inv_vocab[idx] = key
            idx += 1

        # 記号トークン
        for sym in self.SYMBOL_TOKENS:
            self.vocab[sym] = idx
            self.inv_vocab[idx] = sym
            idx += 1

        # モード名トークン
        for mode_name in MODE_NAMES:
            self.vocab[mode_name] = idx
            self.inv_vocab[idx] = mode_name
            idx += 1

        # 共通の名前文字を追加 (ひらがな・カタカナ・アルファベット)
        for ch in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZあいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをんがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽアイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲンガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ':
            if ch not in self.vocab:
                self.vocab[ch] = idx
                self.inv_vocab[idx] = ch
                idx += 1

        self._vocab_size = idx

    @property
    def vocab_size(self) -> int:
        return self._vocab_size

    def encode_string(self, text: str) -> List[int]:
        """
        @title 文字列をトークンID列にエンコード
        @description 文字単位のフォールバック付きで既知トークンにマッチさせる。
                    数字は連続する数字列を1トークンとして扱う。
        @param {str} text - 入力文字列
        @returns {List[int]} トークンID列
        """
        tokens = []
        i = 0
        while i < len(text):
            # 最長一致で既知トークンを探す
            matched = False
            # 数字列のマッチ
            if text[i].isdigit():
                j = i
                while j < len(text) and text[j].isdigit():
                    j += 1
                num_str = text[i:j]
                # 桁ごとに分割 (語彙にない大きな数字への対応)
                for ch in num_str:
                    if ch in self.vocab:
                        tokens.append(self.vocab[ch])
                    else:
                        tokens.append(self.vocab['[UNK]'])
                i = j
                matched = True
                continue

            # 牌トークンマッチ (例: 1m, 5p, 7z)
            if i + 2 <= len(text) and text[i:i+2] in self.vocab:
                tokens.append(self.vocab[text[i:i+2]])
                i += 2
                matched = True
                continue

            # 1文字トークンマッチ
            if text[i] in self.vocab:
                tokens.append(self.vocab[text[i]])
                i += 1
                matched = True
                continue

            # UNK
            tokens.append(self.vocab['[UNK]'])
            i += 1

        return tokens

    def decode_tokens(self, token_ids: List[int]) -> str:
        """@title トークンID列を文字列にデコード"""
        return ''.join(self.inv_vocab.get(tid, '[?]') for tid in token_ids)

    # 牌譜屋準拠スタッツのキー一覧（stats_features の順序と一致させる）
    STATS_FEATURE_KEYS = [
        'win_rate', 'deal_in_rate', 'tsumo_rate', 'damaten_rate',
        'meld_rate', 'riichi_rate', 'avg_win_points', 'avg_deal_in_points',
        'avg_win_turn', 'avg_placement',
        'riichi_win_rate', 'riichi_deal_in_rate', 'riichi_exhaustive_rate',
        'open_win_rate', 'deal_in_when_open_rate',
        'bust_rate', 'exhaustive_rate', 'tenpai_rate_in_exh',
        'point_efficiency', 'loss_from_deal_in', 'adj_efficiency',
    ]

    def build_example(self, persona_name: str, stats: dict, score: int,
                      shanten: int, hand_tiles: List[str], label_mode: Mode) -> dict:
        """
        @title 学習サンプルの構築
        @description 局面情報からトークン系列・スタッツベクトル・ラベルを生成する。
        @param {str} persona_name - プレイヤー名
        @param {dict} stats - プレイヤースタッツ辞書 (21項目)
        @param {int} score - 現在の持ち点
        @param {int} shanten - シャンテン数
        @param {List[str]} hand_tiles - 手牌リスト
        @param {Mode} label_mode - 正解ラベル（戦術モード）
        @returns {dict} { "tokens": [...], "stats_vec": [...], "label": <mode_id>, "text": <元テキスト> }
        """
        # スタッツベクトル (21次元float)
        stats_vec = [stats.get(k, 0.0) for k in self.STATS_FEATURE_KEYS]

        # 手牌の正規化（赤5→通常5）
        hand_norm = [
            ('5' + t[1]) if (t[0] == '0' and len(t) >= 2) else t
            for t in hand_tiles
        ]
        hand_str = ' '.join(hand_norm)

        # トークン系列の構文テキスト（スタッツはベクトルで別途渡すのでテキストには含めない）
        text = (
            f'[PERSONA] {persona_name} '
            f'[SCORE] {score} '
            f'[SHANTEN] {shanten} '
            f'[ARROW] [HAND] {hand_str}'
        )

        tokens = self.simple_tokenize(text)
        label_id = MODE_NAME_TO_ID.get(label_mode.name, 0)

        return {
            'tokens': tokens,
            'stats_vec': stats_vec,
            'label': label_id,
            'text': text,
        }

    def simple_tokenize(self, text: str) -> List[int]:
        """
        @title 簡易トークナイズ
        @description スペース区切りで分けた後、各部分を encode_string する。
        """
        ids: List[int] = [self.vocab.get('[CLS]', 0)]
        parts = text.split()
        for i, part in enumerate(parts):
            if i > 0:
                ids.append(self.vocab.get(' ', self.vocab['[UNK]']))
            ids.extend(self.encode_string(part))
        ids.append(self.vocab.get('[SEP]', 0))
        return ids


def normalize_tile(tile: str) -> str:
    """赤5 (0m/0p/0s) を通常5に正規化"""
    if tile and tile[0] == '0' and len(tile) >= 2 and tile[1] in ('m', 'p', 's'):
        return '5' + tile[1]
    return tile


def _replay_round_for_seat(
    actions: List[dict],
    target_seat: int,
    seat_to_account: Dict[int, dict],
) -> List[dict]:
    """
    @title 指定席の局再生（スナップショット＋未来行動記録）
    @description 牌譜アクション列を4席すべての状態を追跡しながら再生し、
                 各ツモ局面のスナップショットとその直後のプレイヤー行動を記録する。
                 これにより未来情報ルックアヘッドでの戦術モード逆算が可能になる。
    """
    snapshots: List[dict] = []

    # 4席分の状態を同時に追跡
    states = [
        {'hand': [], 'river': [], 'melds': [], 'melds_count': 0,
         'riichi': False, 'tsumo_count': 0}
        for _ in range(4)
    ]
    scores = [25000] * 4
    doras = []
    last_snapshot_idx = -1

    def _push_snapshot(seat):
        nonlocal last_snapshot_idx
        s = states[seat]
        hand_counts = hand_to_counts(s['hand'])
        open_melds = s['melds']
        if len(open_melds) == 0:
            shanten = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
        else:
            shanten = ShantenCalculatorV2.calculate_open(hand_counts, len(open_melds))

        snapshots.append({
            'hand': list(s['hand']),
            'melds': list(s['melds']),
            'melds_count': s['melds_count'],
            'scores': list(scores),
            'score': scores[seat],
            'doras': list(doras),
            'tsumo_count': s['tsumo_count'],
            'seat': seat,
            'reach_states': [states[s2]['riichi'] for s2 in range(4)],
            'river': [list(states[s2]['river']) for s2 in range(4)],
            'shanten': shanten,
            'discard_tile': None,
            'is_reach_declaration': False,
            'is_meld_declaration': False,
        })
        last_snapshot_idx = len(snapshots) - 1

    def _backfill(seat, key, value):
        """直近のスナップショットに未来行動を書き戻す"""
        for i in range(len(snapshots) - 1, -1, -1):
            if snapshots[i]['seat'] == seat and snapshots[i][key] is None or key in ('is_reach_declaration', 'is_meld_declaration'):
                if snapshots[i][key] is False:  # 未設定の場合のみ
                    snapshots[i][key] = value
                break

    for action in actions:
        t = action.get('type')

        if t == 1:
            result = action.get('result', {})
            class_name = result.get('class_name', '')
            data = result.get('data', {})

            if class_name == 'RecordNewRound':
                for seat in range(4):
                    hand_key = f'tiles{seat}'
                    states[seat] = {
                        'hand': [normalize_tile(t) for t in data.get(hand_key, [])],
                        'river': [],
                        'melds': [],
                        'melds_count': 0,
                        'riichi': False,
                        'tsumo_count': 0,
                    }
                scores = list(data.get('scores', [25000] * 4))
                doras = [normalize_tile(d) for d in data.get('doras', [])]

            elif class_name == 'RecordDealTile':
                seat = data.get('seat')
                tile = data.get('tile')
                if seat is not None:
                    states[seat]['tsumo_count'] += 1
                    if tile:
                        states[seat]['hand'].append(normalize_tile(tile))
                    if seat == target_seat:
                        _push_snapshot(seat)

            elif class_name == 'RecordDiscardTile':
                seat = data.get('seat')
                tile = data.get('tile')
                is_liqi = data.get('isLiqi', False)
                if seat is not None and tile:
                    norm = normalize_tile(tile)
                    if norm in states[seat]['hand']:
                        states[seat]['hand'].remove(norm)
                    states[seat]['river'].append(norm)
                    if is_liqi:
                        states[seat]['riichi'] = True
                        # リーチ宣言を直近スナップショットに記録
                        if seat == target_seat:
                            _backfill(seat, 'is_reach_declaration', True)

            elif class_name == 'RecordChiPengGang':
                seat = data.get('seat')
                tiles = data.get('tiles', [])
                froms = data.get('froms', [])
                if seat is not None:
                    # 自分の手牌から削除
                    for ti, fr in zip(tiles, froms):
                        if fr == seat:
                            norm = normalize_tile(ti)
                            if norm in states[seat]['hand']:
                                states[seat]['hand'].remove(norm)
                    # チー/ポン/大明槓なので1種の副露
                    states[seat]['melds'].append([normalize_tile(t) for t in tiles])
                    states[seat]['melds_count'] += 1
                    # 副露を直近スナップショットに記録
                    if seat == target_seat:
                        _backfill(seat, 'is_meld_declaration', True)

            elif class_name == 'RecordAnGangAddGang':
                seat = data.get('seat')
                tile = data.get('tiles', '')
                if seat is not None and tile:
                    norm = normalize_tile(tile)
                    # 暗槓: 4枚削除
                    for _ in range(4):
                        if norm in states[seat]['hand']:
                            states[seat]['hand'].remove(norm)
                    # 加槓: 1枚削除（既存の副露に追加）
                    states[seat]['melds'].append([norm])
                    states[seat]['melds_count'] += 1

            elif class_name == 'RecordHule':
                if 'scores' in data:
                    scores = list(data['scores'])

        elif t == 2:
            ui = action.get('userInput', {})
            ui_type = ui.get('type')
            seat = ui.get('seat')
            if ui_type == 5 and seat is not None:
                states[seat]['riichi'] = True
                if seat == target_seat:
                    _backfill(seat, 'is_reach_declaration', True)

    return snapshots


def extract_training_examples_from_record(
    record: dict,
    tokenizer: TacticalTokenizer,
    stats_db: Dict[str, dict],
    account_id_map: Dict[int, str],
) -> List[dict]:
    """
    @title 牌譜からの学習サンプル抽出（未来ルックアヘッドラベリング版）
    @description 牌譜を全プレイヤー視点で再生し、ルックアヘッド逆算した戦術モードを
                 正解ラベルとして学習サンプルを生成する。
    Why: ルールベース get_mode() ではなく、プレイヤーの実際の行動履歴から
         戦術意図を逆算することで、ルールの焼き増しではない真の学習を可能にする。
    """
    samples: List[dict] = []

    accounts = record.get('head', {}).get('accounts', [])
    seat_to_account = {}
    for acc in accounts:
        seat_to_account[acc['seat']] = acc

    actions = record.get('detail_records', {}).get('actions', [])

    for seat in range(4):
        if seat not in seat_to_account:
            continue
        # 局再生 → スナップショット
        snapshots = _replay_round_for_seat(actions, seat, seat_to_account)
        if not snapshots:
            continue

        # 未来ルックアヘッドでモード逆算
        modes = _determine_round_modes(snapshots, seat)

        # 各スナップショットに逆算モードをラベルとして付与
        for snap, mode in zip(snapshots, modes):
            sample = _build_sample_at_tsumo(
                snap, tokenizer, stats_db, seat_to_account,
                label_mode=mode,
            )
            if sample:
                samples.append(sample)

    return samples


def _calculate_deal_in_prob(snap: dict, tile: str, target_seat: int) -> float:
    """
    @title 放銃確率推定（軽量版）
    @description スナップショットの情報のみから、指定牌を切った時の放銃確率を概算する。
                 リーチ者の現物=0%、スジ=2%、端牌=6-8%、中張無筋=12%がベース。
    Why: 重い GameState/StrategyManager に依存せず、スナップショットのみで計算できるようにする。
    @param {dict} snap - ツモ局面スナップショット
    @param {str} tile - 評価する牌
    @param {int} target_seat - 自分の席
    @returns {float} 放銃確率 (0.0-0.5)
    """
    from str_converter import tile_to_id, is_honor
    try:
        tid = tile_to_id(tile)
    except Exception:
        return 0.0

    reach_seats = [
        s for s in range(4)
        if s != target_seat and len(snap['reach_states']) > s and snap['reach_states'][s]
    ]
    if not reach_seats:
        return 0.0  # リーチ者がいなければ放銃確率0

    river = snap['river']
    visible = [0] * 34
    for s in range(4):
        for t in river[s]:
            visible[tile_to_id(t)] += 1
    for t in snap['hand']:
        visible[tile_to_id(t)] += 1
    for d in snap['doras']:
        visible[tile_to_id(d)] += 1

    # 現物チェック: 全リーチ者の河にあるなら絶対安全
    is_genbutsu_all = True
    for rs in reach_seats:
        river_ids = set()
        for t in river[rs]:
            try:
                river_ids.add(tile_to_id(t))
            except Exception:
                pass
        if tid not in river_ids:
            is_genbutsu_all = False
            break
    if is_genbutsu_all:
        return 0.0

    # 字牌4枚見えも絶対安全
    if is_honor(tid) and visible[tid] >= 4:
        return 0.0

    # 残り枚数による補正
    remaining = 4 - visible[tid]
    if remaining <= 0:
        return 0.0

    # 牌種別ベース危険度
    if is_honor(tid):
        base = 0.08
    elif tid % 9 == 0 or tid % 9 == 8:
        base = 0.06  # 端牌
    else:
        base = 0.12  # 中張牌

    # スジ割引: リーチ者がいる場合、スジ牌は危険度半減
    # ただし全リーチ者に対してスジでなければ割引なし
    all_suji = True
    for rs in reach_seats:
        is_suji_for_this = False
        for river_tile_str in river[rs]:
            try:
                river_tid = tile_to_id(river_tile_str)
                # スジ: 3離れた牌
                if not is_honor(river_tid) and not is_honor(tid):
                    same_suit = (tid // 9) == (river_tid // 9)
                    diff = abs((tid % 9) - (river_tid % 9))
                    if same_suit and diff == 3:
                        is_suji_for_this = True
                        break
            except Exception:
                pass
        if not is_suji_for_this:
            all_suji = False
            break
    if all_suji:
        base *= 0.3  # 全リーチ者にスジ → 危険度70%減

    # リーチ人数で補正
    n = len(reach_seats)
    if n >= 1:
        base *= 1.5 + 0.3 * (n - 1)

    return min(base, 0.5)


def _determine_round_modes(snapshots: List[dict], target_seat: int) -> List[Mode]:
    """
    @title 戦術モード逆算（未来ルックアヘッド）
    @description 局内の全スナップショットをスキャンし、強豪プレイヤーの実際の
                 打牌行動（リーチ・副露・切った牌の放銃確率・シャンテン数の変化）
                 から戦術モードを逆算する。
    Why: ルールベース get_mode() を教師にするとルールの焼き増しにしかならない。
         実際のプレイヤーの行動から「なぜこの判断をしたか」を推定することで、
         より人間らしい戦術判断を学習させる。
    """
    n = len(snapshots)
    if n == 0:
        return []

    # シャンテン数列
    shanten_list = [s['shanten'] for s in snapshots]

    # 切った牌の放銃確率
    dealin_probs = []
    for s in snapshots:
        dt = s.get('discard_tile')
        if dt:
            dealin_probs.append(_calculate_deal_in_prob(s, dt, target_seat))
        else:
            dealin_probs.append(None)

    # 脅威発生点の特定: 他家リーチ or 他家2副露以上
    threat_idx = n  # デフォルト=最後まで脅威なし
    for i, s in enumerate(snapshots):
        opp_reach = sum(1 for seat in range(4) if seat != target_seat and s['reach_states'][seat])
        if opp_reach > 0:
            threat_idx = i
            break
        # 他家の副露数集計
        # （スナップショットには target_seat の melds_count しかないため、
        #   river の長さ変化で他家の仕掛けを間接検出する簡易ロジック）
        if i > 0:
            prev_river_lens = [len(snapshots[i-1]['river'][seat]) for seat in range(4) if seat != target_seat]
            curr_river_lens = [len(s['river'][seat]) for seat in range(4) if seat != target_seat]
            if any(c - p >= 2 for c, p in zip(curr_river_lens, prev_river_lens)):
                threat_idx = i
                break

    # モード初期化: 脅威発生前はBALANCED、発生後はDEFEND
    modes = [Mode.BALANCED] * n

    # ── 脅威発生前 (i < threat_idx) ──
    # 手仕舞いの通常進行。シャンテン数が改善したらATTACKを部分的に付与
    for i in range(min(threat_idx, n)):
        if i > 0 and shanten_list[i] < shanten_list[i - 1]:
            modes[i] = Mode.ATTACK
        elif i > 0 and shanten_list[i] == shanten_list[i - 1]:
            modes[i] = Mode.BALANCED

    # ── 脅威発生後 (i >= threat_idx) ──
    for i in range(threat_idx, n):
        s = snapshots[i]
        dt = s.get('discard_tile')
        dp = dealin_probs[i] if i < len(dealin_probs) else None
        is_reach = s.get('is_reach_declaration', False)
        is_meld = s.get('is_meld_declaration', False)

        # 完全撤退 (FOLD) 判定:
        # シャンテンが維持or悪化 + 現物のみ連打（dp=0.0）
        if dp is not None and dp == 0.0:
            # この先、最後まで現物以外を一切切っていない & シャンテン改善なし
            is_folding = True
            for k in range(i, n):
                if dealin_probs[k] is not None and dealin_probs[k] > 0.0:
                    is_folding = False
                    break
                if shanten_list[k] < shanten_list[i]:
                    is_folding = False
                    break
            if is_folding:
                modes[i] = Mode.FOLD
                continue

        # 押し (ATTACK) 判定:
        # 放銃確率>=8%の危険牌を勝負 / 追っかけリーチ / シャンテン改善
        if dp is not None and dp >= 0.08:
            modes[i] = Mode.ATTACK
        elif is_reach or is_meld:
            modes[i] = Mode.ATTACK
        elif i > 0 and shanten_list[i] < shanten_list[i - 1]:
            modes[i] = Mode.ATTACK
        else:
            # 回し打ち (DEFEND): FOLDでもATTACKでもない
            modes[i] = Mode.DEFEND

    return modes


def _build_sample_at_tsumo(
    round_state: dict,
    tokenizer: TacticalTokenizer,
    stats_db: Dict[str, dict],
    seat_to_account: Optional[Dict[int, dict]] = None,
    player_names: Optional[List[str]] = None,
    label_mode: Optional[Mode] = None,
) -> Optional[dict]:
    """
    @title ツモ局面での学習サンプル生成
    @description スナップショットの局面情報からトークン系列を生成する。
                 ラベルは呼び出し元から指定された label_mode（ルックアヘッド逆算値）。
    @param {dict|None} seat_to_account - MJsoul用: seat→account情報
    @param {list|None} player_names - 天鳳用: 席順のプレイヤー名リスト
    @param {Mode|None} label_mode - ルックアヘッド逆算された正解モード
    """
    seat = round_state['seat']
    if seat < 0:
        return None

    # アカウント情報 (MJsoul or 天鳳)
    if seat_to_account is not None:
        acc_info = seat_to_account.get(seat, {})
        account_id = acc_info.get('accountId', 0)
        nickname = acc_info.get('nickname', 'unknown')
    elif player_names is not None and seat < len(player_names):
        nickname = player_names[seat]
        account_id = hash(nickname) & 0x7FFFFFFF
    else:
        nickname = 'unknown'
        account_id = 0

    # スタッツ
    player_stats = stats_db.get(str(account_id), None)
    if player_stats is None:
        player_stats = {
            'win_rate': 0.25, 'deal_in_rate': 0.15, 'meld_rate': 0.20,
            'riichi_rate': 0.18, 'damaten_rate': 0.35,
            'avg_win_points': 5000.0, 'avg_deal_in_points': 4000.0,
        }

    hand = round_state['hand']
    if not hand:
        return None

    hand_counts = hand_to_counts(hand)
    open_meld_count = len(round_state['melds'])
    if open_meld_count == 0:
        shanten = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
    else:
        shanten = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

    mode = label_mode if label_mode is not None else Mode.BALANCED

    return tokenizer.build_example(
        persona_name=nickname,
        stats=player_stats,
        score=round_state['score'],
        shanten=shanten,
        hand_tiles=hand,
        label_mode=mode,
    )


def replay_tenhou_xml_for_samples(
    xml_path: str,
    tokenizer: TacticalTokenizer,
    stats_db: Dict[str, dict],
    sample_interval: int = 1,
) -> List[dict]:
    """@title 天鳳XMLから学習サンプル抽出
    @description 天鳳XMLを全プレイヤー視点で再生し、ツモ局面のサンプルを生成する。
    @param {str} xml_path - XMLファイルパス
    @param {TacticalTokenizer} tokenizer - トークナイザ
    @param {dict} stats_db - プレイヤースタッツDB
    @returns {List[dict]} 学習サンプルリスト
    """
    import xml.etree.ElementTree as ET
    import urllib.parse
    import hashlib
    from core.game_state import Meld

    tree = ET.parse(xml_path)
    root = tree.getroot()

    # --- プレイヤー情報 ---
    un_elem = root.find('.//UN')
    if un_elem is None:
        return []
    player_names = []
    for i in range(4):
        raw = un_elem.get(f'n{i}', '')
        player_names.append(urllib.parse.unquote(raw))

    samples: List[dict] = []
    # 各席のサンプリングカウンタ
    sample_counters = [0] * 4

    # --- 4プレイヤー分の状態を同時に保持 ---
    states = [
        {'hand': [], 'riichi': False, 'has_meld': False, 'melds': [], 'melds_count': 0,
         'score': 25000, 'scores': [25000] * 4, 'tsumo_count': 0, 'seat': seat,
         'doras': [], 'reach_states': [False] * 4, 'river': []}
        for seat in range(4)
    ]

    # ラウンドごとのスナップショット（各プレイヤーごと）
    round_snapshots: Dict[int, List[dict]] = {s: [] for s in range(4)}
    # 最終ラウンドのスナップショットへの参照（backfill用）
    last_snap_idx = {s: -1 for s in range(4)}

    def _push_xml_snapshot(seat):
        s = states[seat]
        hand_counts = hand_to_counts(s['hand'])
        omc = len(s['melds'])
        sh = ShantenCalculatorV2.calculate_closed_effective(hand_counts) if omc == 0 else ShantenCalculatorV2.calculate_open(hand_counts, omc)
        round_snapshots[seat].append({
            'hand': list(s['hand']),
            'melds': list(s['melds']),
            'melds_count': s['melds_count'],
            'scores': list(s['scores']),
            'score': s['score'],
            'doras': list(s['doras']),
            'tsumo_count': s['tsumo_count'],
            'seat': seat,
            'reach_states': list(states[s2]['riichi'] for s2 in range(4)),
            'river': [list(states[s2]['river']) for s2 in range(4)],
            'shanten': sh,
            'discard_tile': None,
            'is_reach_declaration': False,
            'is_meld_declaration': False,
        })
        last_snap_idx[seat] = len(round_snapshots[seat]) - 1

    def _backfill_xml(seat, key, value):
        idx = last_snap_idx.get(seat, -1)
        if idx >= 0 and idx < len(round_snapshots[seat]):
            if not round_snapshots[seat][idx].get(key):
                round_snapshots[seat][idx][key] = value

    def _process_round():
        """蓄積されたラウンドのスナップショットを処理し、サンプルを生成"""
        for s in range(4):
            sn = round_snapshots[s]
            if not sn:
                continue
            modes = _determine_round_modes(sn, s)
            for snap, mode in zip(sn, modes):
                sample_counters[s] += 1
                if sample_counters[s] % sample_interval != 0:
                    continue
                sample = _build_sample_at_tsumo(
                    snap, tokenizer, stats_db,
                    player_names=player_names,
                    label_mode=mode,
                )
                if sample:
                    samples.append(sample)
        for s in range(4):
            round_snapshots[s].clear()

    for elem in root:
        tag = elem.tag

        if tag == 'INIT':
            _process_round()  # 前ラウンドを処理
            seed_str = elem.get('seed', '0,0,0,0,0,0')
            parts = [int(p) for p in seed_str.split(',')]
            dora_id = parts[5]
            dora_tile = _tenhou_tile_to_str(dora_id)
            ten_str = elem.get('ten', '250,250,250,250')
            scores = [int(x) * 100 for x in ten_str.split(',')]

            for seat in range(4):
                hai_str = elem.get(f'hai{seat}', '')
                hand = [_tenhou_tile_to_str(int(x)) for x in hai_str.split(',') if x.strip()] if hai_str else []
                states[seat]['hand'] = list(hand)
                states[seat]['river'] = []
                states[seat]['score'] = scores[seat]
                states[seat]['scores'] = list(scores)
                states[seat]['doras'] = [dora_tile]
                states[seat]['tsumo_count'] = 0
                states[seat]['riichi'] = False
                states[seat]['has_meld'] = False
                states[seat]['melds'] = []
                states[seat]['melds_count'] = 0
                states[seat]['reach_states'] = [False] * 4

        elif tag == 'REACH':
            who = int(elem.get('who', '0'))
            step = int(elem.get('step', '1'))
            if 0 <= who < 4:
                if step == 2:
                    states[who]['riichi'] = True
                    states[who]['reach_states'][who] = True
                    _backfill_xml(who, 'is_reach_declaration', True)

        elif tag == 'N':
            who = int(elem.get('who', '0'))
            m_val = int(elem.get('m', '0'))
            if who < 0 or who >= 4:
                continue
            called_val = m_val & 0x1F
            meld_type = (m_val >> 7) & 0x3

            if meld_type == 3:  # 暗槓
                tile_str = _tenhou_tile_to_str(called_val)
                for _ in range(4):
                    if tile_str in states[who]['hand']:
                        states[who]['hand'].remove(tile_str)
                states[who]['has_meld'] = True
                states[who]['melds'].append([tile_str])
                states[who]['melds_count'] += 1
            elif meld_type == 1:  # ポン
                tile_str = _tenhou_tile_to_str(called_val)
                for _ in range(2):
                    if tile_str in states[who]['hand']:
                        states[who]['hand'].remove(tile_str)
                states[who]['has_meld'] = True
                states[who]['melds'].append([tile_str])
                states[who]['melds_count'] += 1
                _backfill_xml(who, 'is_meld_declaration', True)
            elif meld_type == 2:  # 大明槓
                tile_str = _tenhou_tile_to_str(called_val)
                for _ in range(3):
                    if tile_str in states[who]['hand']:
                        states[who]['hand'].remove(tile_str)
                states[who]['has_meld'] = True
                states[who]['melds'].append([tile_str])
                states[who]['melds_count'] += 1
                _backfill_xml(who, 'is_meld_declaration', True)
            elif meld_type == 0:  # チー
                tile_str = _tenhou_tile_to_str(called_val)
                removed = 0
                for h in list(states[who]['hand']):
                    if removed >= 2:
                        break
                    states[who]['hand'].remove(h)
                    removed += 1
                states[who]['has_meld'] = True
                states[who]['melds'].append([tile_str])
                states[who]['melds_count'] += 1
                _backfill_xml(who, 'is_meld_declaration', True)

        elif tag in ('AGARI', 'RYUUKYOKU'):
            if 'sc' in elem.attrib:
                sc_str = elem.get('sc', '')
                if sc_str:
                    parts = sc_str.split(',')
                    for i in range(0, len(parts), 2):
                        delta = int(parts[i + 1])
                        seat_idx = i // 2
                        if seat_idx < 4:
                            states[seat_idx]['score'] += delta * 100
                            states[seat_idx]['scores'] = [states[s]['score'] for s in range(4)]

        elif tag == 'DORA':
            pass

        elif tag in ('TAIKYOKU', 'START', 'UN', 'GO'):
            pass

        else:
            # Draw: T/U/V/W + 数字
            if tag and len(tag) >= 2 and tag[0] in 'TUVW':
                try:
                    tile_val = int(tag[1:])
                except ValueError:
                    continue
                seat = 'TUVW'.index(tag[0])
                tile_str = _tenhou_tile_to_str(tile_val)
                if 0 <= seat < 4:
                    states[seat]['hand'].append(tile_str)
                    states[seat]['tsumo_count'] += 1
                    # ツモ直後のスナップショットを記録（後で一括処理）
                    if not states[seat]['riichi']:
                        _push_xml_snapshot(seat)

            # Discard: D/E/F/G + 数字
            elif tag and len(tag) >= 2 and tag[0] in 'DEFG':
                try:
                    tile_val = int(tag[1:])
                except ValueError:
                    continue
                seat = 'DEFG'.index(tag[0])
                tile_str = _tenhou_tile_to_str(tile_val)
                if 0 <= seat < 4 and tile_str in states[seat]['hand']:
                    states[seat]['hand'].remove(tile_str)
                    states[seat]['river'].append(tile_str)

    # 最終ラウンドを処理
    _process_round()

    return samples
                            'hand': list(states[seat]['hand']),
                            'melds': list(states[seat]['melds']),
                            'scores': list(states[seat]['scores']),
                            'score': states[seat]['score'],
                            'doras': list(states[seat]['doras']),
                            'tsumo_count': states[seat]['tsumo_count'],
                            'seat': seat,
                            'reach_states': list(states[seat]['reach_states']),
                        }
                        sample = _build_sample_at_tsumo(snap, tokenizer, stats_db, None, player_names)
                        if sample:
                            samples.append(sample)
            # Discard: D/E/F/G + 数字
            elif tag and len(tag) >= 2 and tag[0] in 'DEFG':
                try:
                    tile_val = int(tag[1:])
                except ValueError:
                    continue
                seat = 'DEFG'.index(tag[0])
                tile_str = _tenhou_tile_to_str(tile_val)
                if 0 <= seat < 4 and tile_str in states[seat]['hand']:
                    states[seat]['hand'].remove(tile_str)
                    states[seat]['river'].append(tile_str)

    return samples


def pad_sequences(sequences: List[List[int]], max_len: int, pad_token_id: int = 0) -> Tuple[List[List[int]], List[List[int]]]:
    """
    @title 系列のパディング
    @description 可変長トークン系列を指定長にパディングし、アテンションマスクも返す。
    @param {List[List[int]]} sequences - トークンID列のリスト
    @param {int} max_len - パディング後の長さ
    @param {int} pad_token_id - パディングトークンのID
    @returns {Tuple[List[List[int]], List[List[int]]]} (padded_sequences, attention_masks)
    """
    padded = []
    masks = []
    for seq in sequences:
        if len(seq) >= max_len:
            padded.append(seq[:max_len])
            masks.append([1] * max_len)
        else:
            padded.append(seq + [pad_token_id] * (max_len - len(seq)))
            masks.append([1] * len(seq) + [0] * (max_len - len(seq)))
    return padded, masks


def _save_numpy_batch(token_ids: List[List[int]], stats_vecs: List[List[float]],
                       labels: List[int], max_seq_len: int, pad_id: int,
                       output_dir: str, batch_idx: int):
    """@title バッチをnumpy形式で保存（スタッツベクトル含む）"""
    padded, masks = pad_sequences(token_ids, max_seq_len, pad_id)
    np.save(os.path.join(output_dir, f'input_ids_{batch_idx:04d}.npy'), np.array(padded, dtype=np.int32))
    np.save(os.path.join(output_dir, f'attn_masks_{batch_idx:04d}.npy'), np.array(masks, dtype=np.int8))
    np.save(os.path.join(output_dir, f'labels_{batch_idx:04d}.npy'), np.array(labels, dtype=np.int8))
    np.save(os.path.join(output_dir, f'stats_{batch_idx:04d}.npy'), np.array(stats_vecs, dtype=np.float32))


def preprocess_all(data_dir: str = DATA_DIR, tokenized_path: str = OUTPUT_TOKENIZED,
                   vocab_path: str = OUTPUT_VOCAB,
                   tenhou_xml_dir: Optional[str] = TENHOU_XML_DIR):
    """
    @title 全牌譜の前処理
    @description 雀魂JSON + 天鳳XML から学習サンプルを抽出し、numpy配列として保存する。
    @param {str} data_dir - 雀魂JSONディレクトリ
    @param {str} tokenized_path - 出力先パス（.npy用ディレクトリの親）
    @param {str} vocab_path - 出力先 (vocab.json)
    @param {str|None} tenhou_xml_dir - 天鳳XMLディレクトリ (None=スキップ)
    """
    import glob
    import urllib.parse

    tokenizer = TacticalTokenizer()
    stats_db = load_stats_db()

    # 出力ディレクトリ設定
    output_dir = os.path.join(os.path.dirname(tokenized_path) or '.', 'tokenized_npy')
    os.makedirs(output_dir, exist_ok=True)

    # Why: 全サンプルをメモリに保持すると数GBになるため、100,000サンプルごとに
    #      numpy ファイルに書き出してメモリを節約する。
    #      numpyはメモリマップド読み書きが可能で、学習時に部分ロードできる。
    BATCH_SIZE = 100000
    buffer_tokens: List[List[int]] = []
    buffer_stats: List[List[float]] = []
    buffer_labels: List[int] = []
    batch_counter = 0
    total_samples = 0
    max_seq_len_observed = 0

    def _flush_buffer():
        nonlocal batch_counter, buffer_tokens, buffer_stats, buffer_labels, max_seq_len_observed
        if not buffer_tokens:
            return
        _save_numpy_batch(buffer_tokens, buffer_stats, buffer_labels, max_seq_len_observed,
                           tokenizer.vocab['[PAD]'], output_dir, batch_counter)
        print(f"[tokenize]  保存: batch_{batch_counter:04d} ({len(buffer_tokens)} サンプル)")
        batch_counter += 1
        buffer_tokens = []
        buffer_stats = []
        buffer_labels = []

    # --- 雀魂JSONの処理 ---
    record_files = sorted(glob.glob(os.path.join(data_dir, 'record_*_trimmed.json')))
    for filepath in record_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                record = json.load(f)
        except Exception as e:
            print(f"[tokenize] 読み込みエラー ({filename}): {e}")
            continue

        account_id_map = {}
        for acc in record.get('head', {}).get('accounts', []):
            account_id_map[acc['seat']] = acc.get('accountId', 0)

        try:
            samples = extract_training_examples_from_record(
                record, tokenizer, stats_db, account_id_map,
            )
            for s in samples:
                buffer_tokens.append(s['tokens'])
                buffer_stats.append(s['stats_vec'])
                buffer_labels.append(s['label'])
                max_seq_len_observed = max(max_seq_len_observed, len(s['tokens']))
                total_samples += 1
                if len(buffer_tokens) >= BATCH_SIZE:
                    _flush_buffer()
            print(f"[tokenize] JSON {filename}: {len(samples)} サンプル")
        except Exception as e:
            print(f"[tokenize] 抽出エラー ({filename}): {e}")
            continue

    # --- 天鳳XMLの処理 ---
    # Why: sample_interval=6 で全ツモの約16.7%をサンプリング。
    #      全件だと570万件超となり、学習時間・メモリともに非現実的なため。
    XML_SAMPLE_INTERVAL = 6
    if tenhou_xml_dir and os.path.isdir(tenhou_xml_dir):
        xml_files = sorted(glob.glob(os.path.join(tenhou_xml_dir, '*.xml')))
        processed = 0
        for filepath in xml_files:
            basename = os.path.basename(filepath)
            try:
                samples = replay_tenhou_xml_for_samples(
                    filepath, tokenizer, stats_db, sample_interval=XML_SAMPLE_INTERVAL,
                )
                for s in samples:
                    buffer_tokens.append(s['tokens'])
                    buffer_stats.append(s['stats_vec'])
                    buffer_labels.append(s['label'])
                    max_seq_len_observed = max(max_seq_len_observed, len(s['tokens']))
                    total_samples += 1
                    if len(buffer_tokens) >= BATCH_SIZE:
                        _flush_buffer()
                processed += 1
                if processed % 1000 == 0:
                    print(f"[tokenize] 天鳳XML 進行中: {processed}/{len(xml_files)}, "
                          f"サンプル累計: {total_samples}")
            except Exception as e:
                print(f"[tokenize] 天鳳XML エラー ({basename}): {e}")
                continue
        print(f"[tokenize] 天鳳XML 完了: {processed}/{len(xml_files)} ファイル")

    # 最終バッチをフラッシュ
    _flush_buffer()
    print(f"[tokenize] 合計 {total_samples} サンプル ({batch_counter} バッチ)")

    # 最大系列長を再計算
    max_seq_len = min(max_seq_len_observed + 4, 256)
    print(f"[tokenize] 最大系列長: {max_seq_len}")

    # メタデータを保存
    meta = {
        'num_examples': total_samples,
        'num_batches': batch_counter,
        'max_seq_len': max_seq_len,
        'vocab_size': tokenizer.vocab_size,
        'pad_token_id': tokenizer.vocab['[PAD]'],
        'mode_names': MODE_NAMES,
        'num_stats_features': len(TacticalTokenizer.STATS_FEATURE_KEYS),
        'stats_feature_keys': TacticalTokenizer.STATS_FEATURE_KEYS,
    }
    with open(os.path.join(output_dir, 'meta.json'), 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    print(f"[tokenize] メタデータを保存: {os.path.join(output_dir, 'meta.json')}")

    # 語彙を保存
    with open(vocab_path, 'w', encoding='utf-8') as f:
        json.dump({
            'vocab': tokenizer.vocab,
            'vocab_size': tokenizer.vocab_size,
            'mode_names': MODE_NAMES,
        }, f, ensure_ascii=False, indent=2)
    print(f"[tokenize] 語彙を保存: {vocab_path}")


if __name__ == '__main__':
    preprocess_all()
