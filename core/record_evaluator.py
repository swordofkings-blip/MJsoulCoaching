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
from typing import Dict, List, Optional, Tuple, Any

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from core.game_state import GameState, Meld, ReachState
from core.evaluator_v2 import EvaluatorV2


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
        # 同じ eval.json に格納する。actions キーは action_idx → 表示データ のマッピングで
        # forwarder.py の evaluate_state() レスポンスと同じ構造 (recommended/near_tiles/
        # evaluations/strategy_details/should_riichi/riichi_reason/kyushu_kyuhai/
        # sufutsusenru/summary を含む)。
        # precomputed_meld_decisions はシミュレーターが /api/evaluate-meld の代わりに
        # eval.json から直接取得できるようにする。
        return {
            'grades': grades,
            'actions': self.precomputed_displays,
            'precomputed_meld_decisions': self.precomputed_meld_decisions,
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
        """
        @title ユーザー入力の処理
        @description type 2 のアクション (打牌決定) を処理し、実際の打牌と AI 推奨の一致度を計算する。
        表示データ (precomputed_displays) は _precompute_after_discard で RecordDiscardTile 時に
        既に保存済みなので、ここでは evaluations に評価スコアを追加するだけ。
        """
        ui = action.get('userInput', {})
        seat = ui.get('seat')
        ui_type = ui.get('type')
        operation = ui.get('operation', {})

        # 牌を切る: userInput.type=2, operation.type=1, operation.tile
        if ui_type == 2 and operation.get('type') == 1 and 'tile' in operation:
            actual_tile = operation.get('tile')
            if actual_tile:
                match = self._evaluate_discard(seat, actual_tile, return_display=False)
                self.evaluations.append({
                    'seat': seat,
                    'decision_type': 'discard',
                    'actual': actual_tile,
                    'match_score': match,
                })
        # 副露判断: userInput.type=3 (cpg) - 現状はスキップ
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
        """AI に打牌を評価させ、実際の打牌との一致度 (0-100) を返す (v2 7Dタプル版)。
        各打牌の 7D タプルを多層指数加重で 1 次元スカラー化し、比率マッピングする。
        """
        try:
            state = self._build_state_for_seat(seat)
            evaluator = EvaluatorV2(state, self.params)
            unique_tiles = list(dict.fromkeys(state.my_hand))
            if not unique_tiles:
                return (0.0, None) if return_display else 0.0
            evals = []
            for tile in unique_tiles:
                try:
                    tup = evaluator.evaluate_tile(tile)
                    score = sum(v * (100 ** (len(tup) - 1 - i)) for i, v in enumerate(tup))
                    evals.append((tile, score))
                except Exception:
                    evals.append((tile, -9999999999.0))
            evals.sort(key=lambda x: -x[1])
            if not evals:
                return (0.0, None) if return_display else 0.0
            best_score = evals[0][1]
            worst_score = evals[-1][1]
            if best_score == worst_score:
                match = 100.0
            else:
                actual_score = None
                for t, s in evals:
                    if t == actual_tile:
                        actual_score = s
                        break
                if actual_score is None:
                    match = 0.0
                else:
                    match = (actual_score - worst_score) / (best_score - worst_score) * 100.0
            match = max(0.0, min(100.0, match))

            display_data = None
            if return_display:
                try:
                    v2_mode = evaluator.get_mode()
                    from server.forwarder import MODE_V2_JP, TIER_NAMES_7D
                    mode_jp = MODE_V2_JP.get(v2_mode, v2_mode.value)
                    recommended_tile = evals[0][0]
                    near_tiles = [t for t, _ in evals[:6]]
                    evaluations = []
                    for tile, _ in evals[:8]:
                        try:
                            tup = evaluator.evaluate_tile(tile)
                            tup_list = [round(float(v), 2) for v in tup[:7]]
                        except Exception:
                            tup_list = []
                        evaluations.append({
                            'tile': tile,
                            'score': round(float(tup_list[0] if tup_list else 0), 1),
                            'tuple_values': tup_list,
                        })
                    display_data = {
                        'seat': seat,
                        'recommended': recommended_tile,
                        'near_tiles': near_tiles,
                        'evaluations': evaluations,
                        'push_score': 0.0,
                        'strategy_details': {
                            'v2_mode': v2_mode.value,
                            'v2_mode_jp': mode_jp,
                            'v2_tier_names': list(TIER_NAMES_7D),
                        },
                        'reason': f"「{recommended_tile}」を推奨 (v2 mode: {mode_jp})",
                    }
                except Exception as e:
                    print(f"[Warning] display data build failed: {e}")
            return (match, display_data) if return_display else match
        except Exception as e:
            print(f"[Warning] _evaluate_discard failed (seat={seat}, tile={actual_tile}): {e}")
            return (0.0, None) if return_display else 0.0

    # ------------------------------------------------------------------
    # 副露・特殊判断の事前計算 (forwarder.py の既存 API 関数を直接呼んで
    # フルレスポンスを保存する。独自実装はしない)
    # ------------------------------------------------------------------

    def _precompute_after_discard(self, data: dict, action_idx: int):
        """
        @title 打牌後の副露・特殊判断の事前計算
        @description RecordDiscardTile の直後に実行され、forwarder.py の evaluate_state() と
        evaluate_meld() を直接呼んでフルレスポンスを eval.json に保存する。
        シミュレーターは forwarder.py に問い合わせず eval.json から直接表示する。
        @param {dict} data - RecordDiscardTile の data フィールド
        @param {int} action_idx - 牌譜アクションインデックス
        """
        # Why: forwarder.py の既存 evaluate_state / evaluate_meld を直接呼ぶことで、
        # 独自実装のバグ (「鳴き禁止条件に該当する (具体的な理由は判定中)」) を回避し、
        # API 経由と完全同一の出力を eval.json に保存する。
        from server.forwarder import evaluate_state_v2, evaluate_meld_v2

        discard_seat = data.get('seat')
        discard_tile = data.get('tile')
        if discard_seat is None or not discard_tile:
            return

        # 1. 打牌者の局面評価 (v2)
        discarder_payload = self._build_payload_for_seat(
            discard_seat,
            include_discard_tile=discard_tile,
        )
        discarder_result = evaluate_state_v2(discarder_payload)
        if discarder_result.get('status') == 'ok':
            self.precomputed_displays[str(action_idx)] = discarder_result

        # 2. 他家 (3名) の副露判断 (v2)
        meld_decisions: Dict[str, dict] = {}
        for other_seat in range(4):
            if other_seat == discard_seat:
                continue
            try:
                other_payload = self._build_payload_for_seat(
                    other_seat,
                    include_discard_tile=None,
                )
                meld_candidates = self._build_meld_candidates_for_seat(
                    other_seat, discard_tile, discard_seat
                )
                if not meld_candidates or all(c.get('type') == 'skip' for c in meld_candidates):
                    continue
                other_payload['meld_candidates'] = meld_candidates
                meld_result = evaluate_meld_v2(other_payload)
                if meld_result.get('status') == 'ok' and meld_result.get('candidates'):
                    meld_decisions[str(other_seat)] = meld_result
            except Exception as e:
                print(f"[Warning] meld precompute failed (seat={other_seat}, action={action_idx}): {e}")
        if meld_decisions:
            self.precomputed_meld_decisions[str(action_idx)] = meld_decisions

    def _build_payload_for_seat(self, seat: int, include_discard_tile: Optional[str]) -> dict:
        """
        @title 局面ペイロードの構築
        @description 指定席から見た GameState ペイロードを構築し、evaluate_state / evaluate_meld に渡す。
        @param {int} seat - 自分の席
        @param {str|None} include_discard_tile - 手牌に含める牌 (打牌前の評価時に使用)
        @returns {dict} ペイロード
        """
        state = self._build_state_for_seat(seat)
        if include_discard_tile and include_discard_tile not in state.my_hand:
            state.my_hand = list(state.my_hand) + [include_discard_tile]
            state.last_self_drawn = include_discard_tile

        # ドラ表示牌 → ドラ牌変換
        from core.str_converter import dora_indicator_to_dora
        doras = []
        for d in state.doras:
            if d and d[0] == '0' and len(d) >= 2 and d[1] in ('m', 'p', 's'):
                doras.append(dora_indicator_to_dora(d))
            else:
                doras.append(d)

        # 副露データを dict 形式に変換
        melds_payload = [[] for _ in range(4)]
        for s in range(4):
            for m in state.melds[s]:
                melds_payload[s].append({
                    'type': m.type,
                    'tiles': list(m.tiles),
                    'froms': list(m.froms),
                    'tile_states': list(getattr(m, 'tile_states', [])),
                })

        # 立直状態を dict 形式に変換
        reach_states = []
        for rs in state.reach_states:
            reach_states.append({
                'is_reach': bool(getattr(rs, 'is_reach', False)),
                'reach_turn': int(getattr(rs, 'reach_turn', -1)),
                'is_ippatsu': bool(getattr(rs, 'is_ippatsu', False)),
            })

        return {
            'my_seat': int(seat),
            'chang': int(self.chang),
            'ju': int(self.ju),
            'ben': int(self.ben),
            'liqibang': int(self.liqibang),
            'left_tile_count': int(self.left_tile_count),
            'tsumo_count': int(self.tsumo_count),
            'scores': [int(self.state_by_seat[s]['score']) for s in range(4)],
            'doras': doras,
            'dealer_seat': int(self.ju),
            'hand': list(state.my_hand),
            'river': [list(state.river[s]) for s in range(4)],
            'river_moqie': [list(state.river_moqie[s]) if hasattr(state, 'river_moqie') and len(state.river_moqie) > s else [False] * len(state.river[s]) for s in range(4)],
            'melds': melds_payload,
            'reach_states': reach_states,
            'last_discard_seat': int(getattr(state, 'last_discard_seat', -1)),
            'last_discard_tile': getattr(state, 'last_discard_tile', None),
            'params': self.params,
        }

    def _build_meld_candidates_for_seat(self, seat: int, discard_tile: str, from_seat: int) -> list:
        """
        @title 副露候補リストの構築
        @description 他家から見たときの副露候補 (skip/pon/chi/daiminkan) を組み立てる。
        評価は evaluate_meld 側で実行される。
        @param {int} seat - 自分の席 (副露する側)
        @param {str} discard_tile - 捨牌
        @param {int} from_seat - 捨牌者
        @returns {list} 副露候補
        """
        # 赤5 (0m/0p/0s) を通常5 (5m/5p/5s) に正規化
        state = self._build_state_for_seat(seat)
        hand_normalized = [
            ('5' + t[1:]) if (t and t[0] == '0' and len(t) >= 2 and t[1] in ('m', 'p', 's')) else t
            for t in state.my_hand
        ]
        dt_base = discard_tile
        if dt_base and dt_base[0] == '0' and len(dt_base) >= 2 and dt_base[1] in ('m', 'p', 's'):
            dt_base = '5' + dt_base[1]

        hand_counts = {}
        for t in hand_normalized:
            hand_counts[t] = hand_counts.get(t, 0) + 1

        candidates: list = [{'type': 'skip', 'label': 'スキップ', 'tiles': [], 'froms': []}]

        # ポン可能
        if hand_counts.get(dt_base, 0) >= 2:
            candidates.append({
                'type': 'pon',
                'label': 'ポン',
                'tiles': [dt_base, dt_base, dt_base],
                'froms': [from_seat, seat, seat],
            })

        # チー可能 (下家の捨牌のみ)
        cs = (seat + 3) % 4
        if cs == from_seat and len(dt_base) >= 2 and dt_base[1] in ('m', 'p', 's'):
            try:
                n = int(dt_base[0])
                for a in range(max(1, n - 2), min(7, n) + 1):
                    if not (a <= n <= a + 2):
                        continue
                    con = [x for x in (a, a + 1, a + 2) if x != n]
                    ta = f'{con[0]}{dt_base[1]}'
                    tb = f'{con[1]}{dt_base[1]}'
                    if (hand_counts.get(ta, 0) >= 1 and hand_counts.get(tb, 0) >= 1):
                        candidates.append({
                            'type': 'chi',
                            'label': f'チー({ta}{tb})',
                            'tiles': [dt_base, ta, tb],
                            'froms': [from_seat, seat, seat],
                        })
                        break
            except ValueError:
                pass

        # 大明槓可能
        if hand_counts.get(dt_base, 0) >= 3:
            candidates.append({
                'type': 'daiminkan',
                'label': '大明槓',
                'tiles': [dt_base] * 4,
                'froms': [from_seat, seat, seat, seat],
            })

        return candidates



def evaluate_record(record: dict, params: Optional[dict] = None) -> Dict[int, dict]:
    """
    牌譜を評価し、各プレイヤーのマッチスコアと S~C 評価を返す。
    Returns: { seat: { 'avg_score': float, 'grade': str, 'count': int } }
    """
    replayer = RecordReplayer(record, params)
    return replayer.replay()
