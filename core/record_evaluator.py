# -*- coding: utf-8 -*-
"""
牌譜再生 + AI 評価モジュール

trimmed JSON 形式の牌譜を 1 アクションずつ再生し、
各打牌・立直・副露の判断ポイントで AI に評価させ、
実際の打牌との一致度を S~C でスコアリングする。

主な API:
  - evaluate_record(record_dict) -> dict
      牌譜を最初から最後まで再生し、各プレイヤーの平均マッチスコア (0-100) を返す。
"""
from __future__ import annotations
import os
import sys
import json
import copy
from typing import Dict, List, Optional, Tuple, Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.game_state import GameState, Meld, ReachState
from core.evaluator import Evaluator
from core.decision_helpers import (
    build_kyushu_kyuhai_data as _build_kyushu_kyuhai_data,
    build_sufutsusenru_data as _build_sufutsusenru_data,
)


def _load_params() -> dict:
    """config/config_parameters.json を読み込む (フォールバックで空 dict)"""
    candidates = [
        os.path.join(_HERE, '..', 'config', 'config_parameters.json'),
        os.path.join(os.path.dirname(_HERE), 'config', 'config_parameters.json'),
    ]
    for c in candidates:
        if os.path.exists(c):
            try:
                with open(c, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
    return {}


def _grade_from_score(score: float) -> str:
    """平均マッチスコア (0-100) を S~C 評価に変換"""
    if score >= 90:
        return 'S'
    if score >= 80:
        return 'A'
    if score >= 70:
        return 'B'
    if score >= 60:
        return 'C'
    if score >= 50:
        return 'D'
    return 'E'


class RecordReplayer:
    """
    牌譜を再生しながら各プレイヤーの状態を追跡し、
    各判断ポイントで AI 評価を行うクラス。
    """

    def __init__(self, record: dict, params: Optional[dict] = None):
        self.record = record
        self.params = params or _load_params()
        # 各プレイヤーの状態 (4人分)
        # state_by_seat[seat] = { 'hand': [], 'discards': [], 'melds': [], 'tsumo': None, 'score': 25000, 'reach': False, 'riichi_turn': -1 }
        self.state_by_seat: Dict[int, dict] = {
            s: {
                'hand': [],
                'discards': [],
                'melds': [],
                'tsumo': None,
                'score': 25000,
                'reach': False,
                'riichi_turn': -1,
            } for s in range(4)
        }
        self.doras: List[str] = []
        self.left_tile_count: int = 70
        self.tsumo_count: int = 0
        self.chang: int = 0
        self.ju: int = 0
        self.ben: int = 0
        self.liqibang: int = 0
        self.active_seat: int = 0
        # 評価結果: list of {seat, decision_type, actual, ai_recommended, match_score, ...}
        self.evaluations: List[dict] = []
        # 牌譜一覧/シミュレーター用の事前計算表示データ: {action_idx: {recommended, near_tiles, ...}}
        self.precomputed_displays: Dict[str, dict] = {}
        # 副露判断の事前計算データ: {action_idx: {candidates: [...], recommended: ...}}
        self.precomputed_meld_decisions: Dict[str, dict] = {}
        # 特殊判断 (立直/暗槓/九種九牌/四風子連打) の事前計算データ
        self.precomputed_special_decisions: Dict[str, dict] = {}

    def replay(self) -> Dict[str, dict]:
        """牌譜を最初から最後まで再生し、各プレイヤーの評価結果を集計する"""
        actions = self.record.get('detail_records', {}).get('actions', [])
        for action_idx, action in enumerate(actions):
            t = action.get('type')
            if t == 1:
                self._handle_server_action(action, action_idx)
            elif t == 2:
                self._handle_user_input(action, action_idx)
        # 集計
        scores_by_seat: Dict[int, List[float]] = {s: [] for s in range(4)}
        for ev in self.evaluations:
            s = ev['seat']
            scores_by_seat[s].append(ev['match_score'])
        grades: Dict[str, dict] = {}
        for s in range(4):
            scores = scores_by_seat[s]
            if scores:
                avg = sum(scores) / len(scores)
                grades[str(s)] = {
                    'avg_score': round(avg, 1),
                    'grade': _grade_from_score(avg),
                    'count': len(scores),
                }
            else:
                grades[str(s)] = {'avg_score': 0.0, 'grade': 'E', 'count': 0}
        # Why: 牌譜一覧/シミュレーターでの表示高速化のため、グレードと事前計算表示データを
        # 同じ eval.json に格納する。actions キーは action_idx → 表示データ のマッピング。
        # precomputed_meld_decisions / precomputed_special_decisions はシミュレーターが
        # forwarder.py に問い合わせる代わりに eval.json から直接取得できるようにする。
        return {
            'grades': grades,
            'actions': self.precomputed_displays,
            'precomputed_meld_decisions': self.precomputed_meld_decisions,
            'precomputed_special_decisions': self.precomputed_special_decisions,
        }

    def _handle_server_action(self, action: dict, action_idx: int = -1):
        """type 1: サーバー側アクション (RecordNewRound, RecordDealTile, RecordDiscardTile, RecordChiPengGang, RecordAnGangAddGang)"""
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})

        if class_name == 'RecordNewRound':
            self._init_round(data)
        elif class_name == 'RecordDealTile':
            self._deal_tile(data)
        elif class_name == 'RecordDiscardTile':
            self._discard_tile(data)
            # Why: 打牌直後の局面で副露判断 (他家 3 名の chi/pon/kan 候補) と
            # 特殊判断 (打牌者の立直/九種九牌/四風子連打/暗槓) を事前計算。
            # シミュレーターが forwarder.py に問い合わせる代わりに eval.json から直接取得できる。
            if action_idx >= 0:
                self._precompute_after_discard(data, action_idx)
        elif class_name == 'RecordChiPengGang':
            self._chi_peng_gang(data)
        elif class_name == 'RecordAnGangAddGang':
            self._an_gang_add_gang(data)
        elif class_name == 'RecordNoTile':
            # 流局処理 (次の局へ)
            pass

    def _handle_user_input(self, action: dict, action_idx: int = -1):
        """type 2: ユーザー入力 (打牌、立直、副露など)"""
        ui = action.get('userInput', {})
        seat = ui.get('seat')
        ui_type = ui.get('type')
        operation = ui.get('operation', {})

        # 牌を切る: userInput.type=2, operation.type=1, operation.tile
        if ui_type == 2 and operation.get('type') == 1 and 'tile' in operation:
            actual_tile = operation.get('tile')
            if actual_tile:
                match, display_data = self._evaluate_discard(seat, actual_tile, return_display=True)
                self.evaluations.append({
                    'seat': seat,
                    'decision_type': 'discard',
                    'actual': actual_tile,
                    'match_score': match,
                })
                # Why: 牌譜一覧/シミュレーターでの表示高速化のため、表示用データを事前計算して保存。
                if display_data and action_idx >= 0:
                    self.precomputed_displays[str(action_idx)] = display_data
        # 副露判断: userInput.type=3 (cpg) - 現状はスキップ (複雑なので後で実装)
        # 立直/カンの判断: userInput.type=5 など - スキップ

    def _init_round(self, data: dict):
        """RecordNewRound: 新規局の開始"""
        self.chang = data.get('chang', 0)
        self.ju = data.get('ju', 0)
        self.ben = data.get('ben', 0)
        self.liqibang = data.get('liqibang', 0)
        scores = data.get('scores', [25000] * 4)
        self.doras = data.get('doras', [])
        self.left_tile_count = data.get('leftTileCount', 70)
        self.tsumo_count = 0

        # 各プレイヤーの状態をリセット
        for s in range(4):
            self.state_by_seat[s] = {
                'hand': list(data.get(f'tiles{s}', [])),
                'discards': [],
                'melds': [],
                'tsumo': None,
                'score': scores[s] if s < len(scores) else 25000,
                'reach': False,
                'riichi_turn': -1,
            }
        self.active_seat = data.get('operation', {}).get('seat', 0)

    def _deal_tile(self, data: dict):
        """RecordDealTile: 牌を自摸る"""
        seat = data.get('seat')
        tile = data.get('tile')
        self.left_tile_count = data.get('leftTileCount', self.left_tile_count - 1)
        self.tsumo_count += 1
        if seat is not None and tile:
            self.state_by_seat[seat]['tsumo'] = tile
            self.state_by_seat[seat]['hand'].append(tile)
            self.active_seat = seat

    def _discard_tile(self, data: dict):
        """RecordDiscardTile: 牌を捨てる"""
        seat = data.get('seat')
        tile = data.get('tile')
        is_liqi = data.get('isLiqi', False)
        if seat is not None and tile:
            hand = self.state_by_seat[seat]['hand']
            # 牌を手から削除 (0m/5m の両対応)
            if tile in hand:
                hand.remove(tile)
            elif tile == '0m' and '5m' in hand:
                hand.remove('5m')
            elif tile == '5m' and '0m' in hand:
                hand.remove('0m')
            elif tile == '0p' and '5p' in hand:
                hand.remove('5p')
            elif tile == '5p' and '0p' in hand:
                hand.remove('0p')
            elif tile == '0s' and '5s' in hand:
                hand.remove('5s')
            elif tile == '5s' and '0s' in hand:
                hand.remove('0s')
            self.state_by_seat[seat]['tsumo'] = None
            self.state_by_seat[seat]['discards'].append({
                'tile': tile,
                'isLiqi': is_liqi,
                'moqie': data.get('moqie', False),
            })
            if is_liqi:
                self.state_by_seat[seat]['reach'] = True
                self.state_by_seat[seat]['riichi_turn'] = self.tsumo_count
            self.active_seat = (seat + 1) % 4

    def _chi_peng_gang(self, data: dict):
        """RecordChiPengGang: チー・ポン・カン (副露)"""
        seat = data.get('seat')
        tiles = data.get('tiles', [])
        froms = data.get('froms', [])
        type_code = data.get('type', 1)
        if seat is None:
            return
        # 自家の牌を削除
        hand = self.state_by_seat[seat]['hand']
        for i, t in enumerate(tiles):
            if froms[i] == seat:
                if t in hand:
                    hand.remove(t)
                # 0m/5m 対応
                elif t == '0m' and '5m' in hand:
                    hand.remove('5m')
                elif t == '5m' and '0m' in hand:
                    hand.remove('0m')
        # 副露を追加
        self.state_by_seat[seat]['melds'].append({
            'type': 'minggang' if type_code == 2 else 'cpg',
            'tiles': list(tiles),
            'froms': list(froms),
        })
        self.state_by_seat[seat]['tsumo'] = None
        self.active_seat = seat

    def _an_gang_add_gang(self, data: dict):
        """RecordAnGangAddGang: 暗槓・加槓"""
        seat = data.get('seat')
        tile = data.get('tiles')
        type_code = data.get('type', 3)
        if seat is None or not tile:
            return
        hand = self.state_by_seat[seat]['hand']
        if type_code == 3:
            # 暗槓: 4枚を手から削除
            for _ in range(4):
                if tile in hand:
                    hand.remove(tile)
                elif tile == '0m' and '5m' in hand:
                    hand.remove('5m')
                elif tile == '5m' and '0m' in hand:
                    hand.remove('0m')
            self.state_by_seat[seat]['melds'].append({
                'type': 'ankan',
                'tiles': [tile] * 4,
                'froms': [seat] * 4,
            })
        else:
            # 加槓: 1枚を手から削除
            if tile in hand:
                hand.remove(tile)
            elif tile == '0m' and '5m' in hand:
                hand.remove('5m')
            for m in self.state_by_seat[seat]['melds']:
                if m.get('type') == 'cpg' and tile in m.get('tiles', []):
                    m['type'] = 'kakan'
                    m['tiles'].append(tile)
                    break
        self.state_by_seat[seat]['tsumo'] = None
        self.active_seat = seat

    def _build_state_for_seat(self, seat: int) -> GameState:
        """指定された席から見た GameState インスタンスを構築"""
        state = GameState()
        state.my_hand = list(self.state_by_seat[seat]['hand'])
        state.my_melds = [Meld(
            type=(2 if m['type'] == 'minggang' else 1 if m['type'] == 'cpg' else 1),
            tiles=list(m['tiles']),
            froms=list(m['froms']),
        ) for m in self.state_by_seat[seat]['melds']]
        state.my_seat = seat
        state.ju = self.ju
        state.chang = self.chang
        state.ben = self.ben
        state.liqibang = self.liqibang
        state.doras = list(self.doras)
        state.tsumo_count = self.tsumo_count
        state.last_self_drawn = self.state_by_seat[seat]['tsumo']
        state.left_tile_count = self.left_tile_count
        state.dealer_seat = 0  # 簡略化
        state.scores = [self.state_by_seat[s]['score'] for s in range(4)]
        state.reach_states = [ReachState() for _ in range(4)]
        for s in range(4):
            state.reach_states[s].is_reach = self.state_by_seat[s]['reach']
            if self.state_by_seat[s]['reach']:
                state.reach_states[s].reach_turn = self.state_by_seat[s]['riichi_turn']
        # 河
        state.river = [[] for _ in range(4)]
        for s in range(4):
            for d in self.state_by_seat[s]['discards']:
                state.river[s].append(d['tile'])
        # 副露
        state.melds = [[] for _ in range(4)]
        for s in range(4):
            for m in self.state_by_seat[s]['melds']:
                state.melds[s].append(Meld(
                    type=(2 if m['type'] == 'minggang' else 1 if m['type'] == 'cpg' else 1),
                    tiles=list(m['tiles']),
                    froms=list(m['froms']),
                ))
        return state

    def _evaluate_discard(self, seat: int, actual_tile: str, return_display: bool = False):
        """AI に打牌を評価させ、実際の打牌との一致度 (0-100) を返す。
        比率スコアリング: 1位を 100点、最悪手を 0点として線形補間。
        例: 1位=1000, 2位=950, 3位=500, 最悪=-500
            → 2位 = (950-(-500))/(1000-(-500)) * 100 = 96.7 点
            → 3位 = (500-(-500))/(1000-(-500)) * 100 = 66.7 点

        return_display=True の場合は (match_score, display_data) を返す。
        display_data には推奨打牌・候補評価・戦略詳細など UI 表示用データを含める。
        """
        try:
            state = self._build_state_for_seat(seat)
            evaluator = Evaluator(state, self.params)
            # 重複なし牌を列挙
            unique_tiles = list(dict.fromkeys(state.my_hand))
            if not unique_tiles:
                return (0.0, None) if return_display else 0.0
            evals = []
            for tile in unique_tiles:
                try:
                    score = evaluator.evaluate_tile(tile)
                    evals.append((tile, score))
                except Exception:
                    evals.append((tile, -99999))
            # スコア順にソート (降順)
            evals.sort(key=lambda x: -x[1])
            if not evals:
                return (0.0, None) if return_display else 0.0
            # 1位のスコアと最悪手のスコアを取得
            best_score = evals[0][1]
            worst_score = evals[-1][1]
            # 1位と最悪手が同じ場合は全員 100 点
            if best_score == worst_score:
                match = 100.0
            else:
                # 実際の打牌のスコアを探す
                actual_score = None
                for t, s in evals:
                    if t == actual_tile:
                        actual_score = s
                        break
                if actual_score is None:
                    match = 0.0
                else:
                    # 比率スコアリング: (actual - worst) / (best - worst) * 100
                    match = (actual_score - worst_score) / (best_score - worst_score) * 100.0
            match = max(0.0, min(100.0, match))

            display_data = None
            if return_display:
                try:
                    strategy_details = evaluator.strategy.get_strategy_details()
                    # Why: 牌譜一覧/シミュレーターでの即時表示のため、推奨打牌と候補評価を
                    # eval_tile の結果から構築（evaluate_state() を呼ばずに済む）。
                    recommended_tile = evals[0][0]
                    near_tiles = [t for t, _ in evals[:6]]
                    # evaluations 候補リスト (上位N件)
                    evaluations = []
                    for tile, score in evals[:8]:
                        evaluations.append({
                            'tile': tile,
                            'score': round(score, 1),
                        })
                    display_data = {
                        'seat': seat,
                        'recommended': recommended_tile,
                        'near_tiles': near_tiles,
                        'evaluations': evaluations,
                        'push_score': round(float(evaluator.strategy.compute_push_score()), 3),
                        'strategy_details': strategy_details,
                        # 軽量な推奨理由（クライアントで詳細展開はしない。フル理由は /api/evaluate 経由）
                        'reason': f"「{recommended_tile}」を推奨 (スコア {evals[0][1]:.0f}・手牌価値 {strategy_details.get('base_attack', 0):.2f}・場の脅威 {strategy_details.get('max_threat', 0):.2f})",
                    }
                except Exception as e:
                    print(f"[Warning] display data build failed: {e}")
            return (match, display_data) if return_display else match
        except Exception as e:
            print(f"[Warning] _evaluate_discard failed (seat={seat}, tile={actual_tile}): {e}")
            return (0.0, None) if return_display else 0.0

    # ------------------------------------------------------------------
    # 副露・特殊判断の事前計算
    # ------------------------------------------------------------------

    def _precompute_after_discard(self, data: dict, action_idx: int):
        """
        @title 打牌後の副露・特殊判断の事前計算
        @description RecordDiscardTile の直後に実行され、以下のデータを self に格納する:
          - precomputed_meld_decisions[action_idx] = {other_seat: {candidates, ...}}
            打牌牌を他家 (3名) がチー/ポン/カン可能かの判断
          - precomputed_special_decisions[action_idx] = {should_riichi, riichi_reason,
            kyushu_kyuhai, sufutsusenru, ankan_candidates}
            打牌者の立直/九種九牌/四風子連打/暗槓判断
        @param {dict} data - RecordDiscardTile の data フィールド
        @param {int} action_idx - 牌譜アクションインデックス
        """
        discard_seat = data.get('seat')
        discard_tile = data.get('tile')
        if discard_seat is None or not discard_tile:
            return

        # 1. 他家 (3名) の副露判断
        meld_decisions: Dict[str, dict] = {}
        for other_seat in range(4):
            if other_seat == discard_seat:
                continue
            try:
                state = self._build_state_for_seat(other_seat)
                candidates = self._compute_meld_candidates(state, discard_tile, discard_seat)
                if candidates:
                    meld_decisions[str(other_seat)] = {
                        'candidates': candidates,
                        'discarded_tile': discard_tile,
                        'discarded_from': discard_seat,
                    }
            except Exception as e:
                print(f"[Warning] meld precompute failed (seat={other_seat}, action={action_idx}): {e}")
        if meld_decisions:
            self.precomputed_meld_decisions[str(action_idx)] = meld_decisions

        # 2. 打牌者の特殊判断 (立直/九種九牌/四風子連打/暗槓)
        try:
            # 打牌前の状態: 捨てた牌を手牌に戻す
            pre_discard_state = self._build_state_for_seat(discard_seat)
            if discard_tile not in pre_discard_state.my_hand:
                pre_discard_state.my_hand.append(discard_tile)
            pre_discard_state.last_self_drawn = discard_tile
            # ドラ表示牌 → ドラ牌変換
            from core.str_converter import dora_indicator_to_dora
            pre_discard_state.doras = [
                dora_indicator_to_dora(d) if self._is_dora_indicator(d) else d
                for d in pre_discard_state.doras
            ]
            special = self._compute_special_decisions(pre_discard_state, discard_tile)
            if special:
                self.precomputed_special_decisions[str(action_idx)] = special
        except Exception as e:
            print(f"[Warning] special precompute failed (seat={discard_seat}, action={action_idx}): {e}")

    @staticmethod
    def _is_dora_indicator(tile: str) -> bool:
        """ドラ表示牌のフォーマット (0m, 0p, 0s はドラ表示牌として扱う)"""
        if not tile or not isinstance(tile, str) or len(tile) < 2:
            return False
        # 0m/0p/0s は表示牌、5z/6z/7z は常にドラ牌
        return tile.startswith('0') and tile[1] in ('m', 'p', 's')

    def _compute_meld_candidates(self, state: GameState, discard_tile: str, from_seat: int) -> List[dict]:
        """
        @title 副露候補の評価
        @description 指定された状態で、打牌 discard_tile に対して可能な副露 (チー/ポン/大明槓) と
        スキップを評価し、各候補の best_discard/best_score/forbidden/reason を返す。
        @param {GameState} state - 他家から見た局面
        @param {str} discard_tile - 捨牌
        @param {int} from_seat - 捨牌者
        @returns {list} 副露候補のリスト
        """
        try:
            from core.decision_helpers import normalize_hand_red_five
            from core.decision_helpers import get_meld_forbidden_reason
        except ImportError:
            from core.decision_helpers import normalize_hand_red_five
            get_meld_forbidden_reason = None

        # ドラ表示牌 → ドラ牌変換 (state.doras が変換済みでない場合)
        if any(self._is_dora_indicator(d) for d in state.doras):
            from core.str_converter import dora_indicator_to_dora
            state.doras = [dora_indicator_to_dora(d) for d in state.doras]

        # 赤5を統一
        hand_normalized = normalize_hand_red_five(list(state.my_hand))

        candidates: List[dict] = []

        # スキップ (常に候補)
        try:
            ev = Evaluator(state, self.params)
            skip_eval = self._evaluate_state_for_skip(ev, state)
            candidates.append({
                'type': 'skip',
                'label': 'スキップ',
                'best_discard': skip_eval.get('best_tile'),
                'best_score': skip_eval.get('best_score', 0),
                'shanten': skip_eval.get('shanten', 99),
                'forbidden': False,
                'reason': skip_eval.get('reason', ''),
            })
        except Exception:
            pass

        # ポン可能か
        hand_counts = {}
        for t in hand_normalized:
            hand_counts[t] = hand_counts.get(t, 0) + 1
        if hand_counts.get(discard_tile, 0) >= 2:
            pon_tiles = [discard_tile] * 3
            froms = [from_seat] * 3
            cand = self._eval_meld_candidate(state, 'pon', pon_tiles, froms, get_meld_forbidden_reason)
            if cand:
                candidates.append(cand)

        # チー可能か (同数牌 または 連続牌)
        chi_candidates = self._find_chi_candidates(hand_normalized, discard_tile)
        for chi_tiles in chi_candidates:
            froms = [state.my_seat, state.my_seat, from_seat]
            cand = self._eval_meld_candidate(state, 'chi', chi_tiles, froms, get_meld_forbidden_reason)
            if cand:
                candidates.append(cand)

        # 大明槓可能か
        if hand_counts.get(discard_tile, 0) >= 3:
            kan_tiles = [discard_tile] * 4
            froms = [from_seat] * 4
            cand = self._eval_meld_candidate(state, 'daiminkan', kan_tiles, froms, get_meld_forbidden_reason)
            if cand:
                candidates.append(cand)

        return candidates

    def _eval_meld_candidate(
        self,
        state: GameState,
        ctype: str,
        tiles: list,
        froms: list,
        get_meld_forbidden_reason,
    ) -> Optional[dict]:
        """単一副露候補を評価"""
        try:
            type_map = {'pon': 1, 'chi': 0, 'daiminkan': 2, 'ankan': 3, 'kakan': 2}
            meld_type = type_map.get(ctype, 1)
            # 鳴き禁止チェック
            if get_meld_forbidden_reason is not None:
                try:
                    check_ev = Evaluator(state, self.params)
                    meld_tile_strs = [str(t) for t in tiles]
                    if not check_ev.should_call_meld(meld_type, meld_tile_strs, froms[0] if froms else state.my_seat):
                        forbidden_reason = get_meld_forbidden_reason(
                            check_ev, meld_type, meld_tile_strs,
                            froms[0] if froms else state.my_seat, state, self.params
                        )
                        return {
                            'type': ctype,
                            'label': self._meld_label(ctype, tiles),
                            'tiles': list(tiles),
                            'best_discard': None,
                            'best_score': -99999,
                            'shanten': 99,
                            'forbidden': True,
                            'forbidden_reason': forbidden_reason,
                            'reason': f"❌ {forbidden_reason}",
                        }
                except Exception:
                    pass

            # 副露適用後の状態で評価
            new_state = copy.deepcopy(state)
            # 消費牌を削除 (赤5対応)
            hand_counts = {}
            for t in new_state.my_hand:
                hand_counts[t] = hand_counts.get(t, 0) + 1
            for t in tiles:
                if t == '0m' and hand_counts.get('0m', 0) > 0:
                    hand_counts['0m'] -= 1
                elif t == '0p' and hand_counts.get('0p', 0) > 0:
                    hand_counts['0p'] -= 1
                elif t == '0s' and hand_counts.get('0s', 0) > 0:
                    hand_counts['0s'] -= 1
                elif t == '5m' and hand_counts.get('0m', 0) > 0:
                    hand_counts['0m'] -= 1
                elif t == '5p' and hand_counts.get('0p', 0) > 0:
                    hand_counts['0p'] -= 1
                elif t == '5s' and hand_counts.get('0s', 0) > 0:
                    hand_counts['0s'] -= 1
                elif hand_counts.get(t, 0) > 0:
                    hand_counts[t] -= 1
            new_hand = []
            for tile, cnt in hand_counts.items():
                new_hand.extend([tile] * cnt)
            new_state.my_hand = new_hand
            # 副露追加
            new_state.my_melds.append(Meld(
                type=meld_type, tiles=list(tiles), froms=list(froms), tile_states=[]
            ))

            ev = Evaluator(new_state, self.params)
            unique_tiles = list(dict.fromkeys(new_state.my_hand))
            best_score = float('-inf')
            best_tile = None
            best_entry = None
            for tile in unique_tiles:
                entry = self._evaluate_tile_for_state(ev, tile)
                if entry and entry.get('score', float('-inf')) > best_score:
                    best_score = entry['score']
                    best_tile = tile
                    best_entry = entry
            if best_entry is None:
                return None
            return {
                'type': ctype,
                'label': self._meld_label(ctype, tiles),
                'tiles': list(tiles),
                'best_discard': best_tile,
                'best_score': best_score,
                'shanten': best_entry.get('shanten', 99),
                'forbidden': False,
                'reason': self._build_meld_reason_text(ctype, best_entry, new_state),
            }
        except Exception as e:
            print(f"[Warning] _eval_meld_candidate failed ({ctype}): {e}")
            return None

    def _find_chi_candidates(self, hand: list, discard_tile: str) -> List[list]:
        """チー候補 (2牌+捨て牌) を列挙"""
        candidates: List[list] = []
        if not discard_tile or len(discard_tile) < 2:
            return candidates
        suit = discard_tile[1]
        if suit not in ('m', 'p', 's'):
            return candidates
        try:
            num = int(discard_tile[0])
        except ValueError:
            return candidates
        hand_counts = {}
        for t in hand:
            hand_counts[t] = hand_counts.get(t, 0) + 1
        for delta in (-2, -1, 1, 2):
            mid = num + delta
            third = num + 2 * delta
            if not (1 <= mid <= 9 and 1 <= third <= 9):
                continue
            a = f'{min(num, mid, third)}{suit}'
            b = f'{sorted([num, mid, third])[1]}{suit}'
            c = f'{max(num, mid, third)}{suit}'
            # 自分の手牌から a, b を取り、c は捨て牌 (discard_tile)
            need = []
            for x in (a, b):
                if x == discard_tile:
                    continue
                need.append(x)
            if len(need) != 2:
                continue
            if need[0] == need[1]:
                if hand_counts.get(need[0], 0) >= 2:
                    candidates.append([need[0], need[1], discard_tile])
            else:
                if hand_counts.get(need[0], 0) >= 1 and hand_counts.get(need[1], 0) >= 1:
                    candidates.append([need[0], need[1], discard_tile])
        return candidates

    @staticmethod
    def _meld_label(ctype: str, tiles: list) -> str:
        labels = {'pon': 'ポン', 'chi': 'チー', 'daiminkan': '大明槓', 'ankan': '暗槓', 'kakan': '加槓'}
        prefix = labels.get(ctype, ctype)
        tile_str = '・'.join(tiles) if tiles else ''
        return f"{prefix} ({tile_str})" if tile_str else prefix

    def _evaluate_state_for_skip(self, evaluator: 'Evaluator', state: GameState) -> dict:
        """スキップ時の最善打牌を評価"""
        hand = state.my_hand
        unique_tiles = list(dict.fromkeys(hand))
        best_score = float('-inf')
        best_tile = None
        best_entry = None
        for tile in unique_tiles:
            entry = self._evaluate_tile_for_state(evaluator, tile)
            if entry and entry.get('score', float('-inf')) > best_score:
                best_score = entry['score']
                best_tile = tile
                best_entry = entry
        return {
            'best_tile': best_tile,
            'best_score': best_score,
            'shanten': best_entry.get('shanten', 99) if best_entry else 99,
            'reason': '',
        }

    def _evaluate_tile_for_state(self, evaluator: 'Evaluator', tile: str) -> Optional[dict]:
        """打牌候補を評価 (Evaluator.evaluate_tile のラッパー)"""
        try:
            score = evaluator.evaluate_tile(tile)
            shanten = 99
            try:
                shanten = evaluator.shanten_after_discard(tile)
            except Exception:
                pass
            return {'score': score, 'shanten': shanten}
        except Exception:
            return None

    @staticmethod
    def _build_meld_reason_text(ctype: str, best_entry: dict, new_state: GameState) -> str:
        """副露判断の理由を生成"""
        if not best_entry:
            return ""
        shanten = best_entry.get('shanten', 99)
        shanten_text = "テンパイ" if shanten == 0 else f"{shanten}向聴" if shanten > 0 else "和了"
        type_text = {'pon': 'ポン', 'chi': 'チー', 'daiminkan': '大明槓', 'ankan': '暗槓', 'kakan': '加槓'}.get(ctype, ctype)
        best_tile = best_entry.get('tile') or ''
        return f"{type_text}後「{best_tile}」切りで{shanten_text} (スコア {best_entry.get('score', 0):.0f})"

    def _compute_special_decisions(self, state: GameState, discard_tile: str) -> dict:
        """
        @title 特殊判断を計算
        @description 立直/九種九牌/四風子連打/暗槓の各判断を計算して dict で返す。
        @param {GameState} state - 局面 (打牌前)
        @param {str} discard_tile - 捨牌
        @returns {dict} 特殊判断データ
        """
        result: dict = {}
        try:
            ev = Evaluator(state, self.params)

            # 立直判断
            try:
                riichi_details = ev.get_riichi_decision_details()
                result['should_riichi'] = riichi_details.get('should_riichi')
                result['riichi_reason'] = riichi_details.get('reason', '')
            except Exception as e:
                result['riichi_reason'] = f"立直判定エラー: {e}"

            # 九種九牌
            try:
                result['kyushu_kyuhai'] = _build_kyushu_kyuhai_data(state)
            except Exception:
                pass

            # 四風子連打
            try:
                result['sufutsusenru'] = _build_sufutsusenru_data(state, ev)
            except Exception:
                pass

            # 暗槓可能牌
            try:
                result['ankan_candidates'] = self._find_ankan_candidates(state.my_hand)
            except Exception:
                pass

            # 加槓可能牌
            try:
                result['kakan_candidates'] = self._find_kakan_candidates(state)
            except Exception:
                pass
        except Exception as e:
            print(f"[Warning] _compute_special_decisions failed: {e}")
        return result

    @staticmethod
    def _find_ankan_candidates(hand: list) -> List[str]:
        """手牌内の暗槓候補 (4枚) を列挙"""
        counts: Dict[str, int] = {}
        for t in hand:
            counts[t] = counts.get(t, 0) + 1
        return [t for t, c in counts.items() if c == 4]

    @staticmethod
    def _find_kakan_candidates(state: GameState) -> List[str]:
        """加槓候補 (既にポンしている牌が手牌にある) を列挙"""
        candidates: List[str] = []
        for meld in state.my_melds:
            if meld.type == 1 and meld.tiles:  # ポン
                pon_tile = meld.tiles[0]
                if state.my_hand.count(pon_tile) >= 1:
                    candidates.append(pon_tile)
        return candidates


def evaluate_record(record: dict, params: Optional[dict] = None) -> Dict[int, dict]:
    """
    牌譜を評価し、各プレイヤーのマッチスコアと S~C 評価を返す。
    Returns: { seat: { 'avg_score': float, 'grade': str, 'count': int } }
    """
    replayer = RecordReplayer(record, params)
    return replayer.replay()
