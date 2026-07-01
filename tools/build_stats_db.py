# -*- coding: utf-8 -*-
"""
@title プレイヤースタッツ集計スクリプト
@description data/ 以下の牌譜 (record_*_trimmed.json) および
              天鳳 XML (mjlog) を解析し、プレイヤーごとの主要5大指標
              （和了率、放銃率、副露率、立直率、ダマ率、平均打点、平均銃点）を
              集計して stats_db.json に出力する。

Why: 戦術LLMの条件付き入力（ペルソナ）として使用するため。
     プレイヤーの打ち筋を数値化することで、パーソナライズドな戦術モード予測が可能になる。

出力形式 (stats_db.json):
{
  "players": {
    "69375101": {
      "nickname": "earth527",
      "account_id": 69375101,
      "total_hands": 100,
      "win_rate": 0.25,
      "deal_in_rate": 0.15,
      "meld_rate": 0.35,
      "riichi_rate": 0.22,
      "damaten_rate": 0.30,
      "avg_win_points": 5200.0,
      "avg_deal_in_points": 3800.0,
      "last_updated": "2026-07-01T12:00:00"
    }
  }
}
"""
from __future__ import annotations
import hashlib
import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Dict, List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))


DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data')
# stats_db.json の出力先
STATS_DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'stats_db.json')


# 牌譜ファイルのマッチングパターン（data/ 直下の record_*_trimmed.json のみ対象）
# Why: _eval.json は評価情報を含みアクション構造が異なるため除外する。
RECORD_GLOB_PATTERN = 'record_*_trimmed.json'

# 天鳳 XML (mjlog) のデフォルトディレクトリ
TENHOU_XML_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    '..', '..', '雀魂ラッパー_拡散AI', 'data', 'raw', 'tenhou_xml',
)

# 天鳳 0-135 牌ID → 内部 34種ID 変換用オフセット
# Why: 天鳳は0-135の一貫IDを使用し、各牌種4枚ずつ格納。
#       0-35=萬子, 36-71=筒子, 72-107=索子, 108-135=字牌。
#       赤5は特定ID(16,52,88)に割り当てられている。
_TENHOU_OFFSETS = [0, 36, 72, 108]
_AKA_DORA_IDS = {16: '0m', 52: '0p', 88: '0s'}


def _tenhou_tile_to_str(val: int) -> str:
    """@title 天鳳ID (0-135) → 内部牌表記変換
    @param {int} val - 天鳳牌ID (0-135)
    @returns {str} 内部牌表記 (例: "1m", "5p", "1z")
    """
    if val in _AKA_DORA_IDS:
        return _AKA_DORA_IDS[val]
    for si, off in enumerate(_TENHOU_OFFSETS):
        if val < off + 36:
            num = (val - off) // 4 + 1
            return f"{num}{'mps'[si]}" if si < 3 else f"{num}z"
    return f"?{val}"


def get_deterministic_id(name: str) -> int:
    """
    @title 決定論的プレイヤーID生成
    @description プロセス間でハッシュ値が変わらないよう MD5 を使用する。
    Why: Python の組み込み hash() はプロセス起動ごとにシードが変わるため、
         同じ名前でも実行ごとに異なるIDになる。stats_db と tokenizer で
         同一プレイヤーを参照できなくなるバグを修正する。
    @param {str} name - プレイヤー名
    @returns {int} 0〜0x7FFFFFFF の一意な整数ID
    """
    return int(hashlib.md5(name.encode('utf-8')).hexdigest(), 16) & 0x7FFFFFFF


def _tenhou_id_to_internal(val: int) -> int:
    """@title 天鳳ID → 34種ID変換
    @param {int} val - 天鳳牌ID (0-135)
    @returns {int} 34種ID (0-33)
    """
    for si, off in enumerate(_TENHOU_OFFSETS):
        if val < off + 36:
            return (val - off) // 4 + (0 if si < 3 else 27)
    return 0


class PlayerStatsTracker:
    """
    @title プレイヤースタッツ追跡
    @description 牌譜のアクション列を順次処理し、各プレイヤーの統計情報を蓄積する。
    """

    def __init__(self):
        # accountId -> stats dict
        self.players: Dict[int, dict] = {}

    def _ensure_player(self, account_id: int, nickname: str) -> dict:
        if account_id not in self.players:
            self.players[account_id] = {
                'account_id': account_id,
                'nickname': nickname,
                # 基本
                'num_games': 0,          # 参加した対局数
                'total_hands': 0,        # 総局数
                'total_wins': 0,         # 和了回数
                'tsumo_wins': 0,         # ツモ和了回数
                'open_wins': 0,          # 副露あり和了
                'total_deal_ins': 0,     # 放銃回数
                'total_melds': 0,        # 副露回数 (延べ)
                'total_hands_with_meld': 0,  # 副露した局数
                'total_riichi': 0,       # 立直回数
                'wins_with_riichi': 0,   # 立直和了回数
                'win_points': [],        # 和了点一覧
                'deal_in_points': [],    # 放銃点一覧
                'win_turns': [],         # 和了巡目一覧
                # 立直関連
                'riichi_dealins': 0,     # 立直中の放銃回数
                'riichi_exhaustive': 0,  # 立直流局回数
                # 放銃関連
                'deal_in_when_open': 0,  # 副露中の放銃回数
                # 流局関連
                'exhaustive_count': 0,   # 流局した局数
                'exhaustive_tenpai': 0,  # 流局時テンパイ回数
                # 対局関連
                'placements': [],        # 順位一覧 (0=トップ)
                'sum_final_score': 0,    # 最終スコア合計
                'busted_count': 0,       # トビ回数
                'renchan_count': 0,      # 連荘回数
            }
        return self.players[account_id]

    def process_record(self, record: dict):
        """
        @title 牌譜1件を処理

        アクション種別:
        - type=1, RecordNewRound: 新局開始。各プレイヤーの手牌を初期化。
        - type=1, RecordDealTile: ツモ。hand_count を増やす。
        - type=1, RecordDiscardTile: 打牌。isLiqi=True で立直を検出。
        - type=1, RecordChiPengGang: 副露。melds をカウント。
        - type=1, RecordAnGangAddGang: 暗槓/加槓。
        - type=1, RecordHule: 和了。winner + deal-in seats を特定。
        - type=2, userInput.type=5: 立直宣言（初回のリーチ意思表示）。
        """
        accounts_info = {}
        for acc in record.get('head', {}).get('accounts', []):
            seat = acc.get('seat')
            if seat is None:
                continue
            a_id = acc.get('accountId', 0)
            accounts_info[seat] = {
                'seat': seat,
                'account_id': a_id,
                'nickname': acc.get('nickname', f'player_{a_id}'),
            }
        # JSON1件=1対局
        for seat_info in accounts_info.values():
            stats = self._ensure_player(seat_info['account_id'], seat_info['nickname'])
            stats['num_games'] += 1

        # 局ごとの状態: seat -> { 'riichi': bool, 'melds_in_hand': bool, 'is_playing': bool }
        round_state: Dict[int, dict] = {}

        actions = record.get('detail_records', {}).get('actions', [])
        for action in actions:
            t = action.get('type')

            if t == 1:
                self._handle_server_action(action, accounts_info, round_state)
            elif t == 2:
                self._handle_user_input(action, accounts_info, round_state)

    def _handle_server_action(self, action: dict, accounts_info: dict, round_state: dict):
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})

        if class_name == 'RecordNewRound':
            # 新局: 全プレイヤーの情報をリセット
            round_state.clear()
            for seat in range(4):
                if seat in accounts_info:
                    account_id = accounts_info[seat]['account_id']
                    stats = self._ensure_player(account_id, accounts_info[seat]['nickname'])
                    stats['total_hands'] += 1
                    round_state[seat] = {
                        'riichi': False,
                        'has_meld': False,
                        'is_playing': True,
                    }

        elif class_name == 'RecordDealTile':
            seat = data.get('seat')
            if seat is not None and seat in round_state:
                round_state[seat]['is_playing'] = True

        elif class_name == 'RecordDiscardTile':
            seat = data.get('seat')
            is_liqi = data.get('isLiqi', False)
            if seat is not None and seat in round_state:
                if is_liqi and not round_state[seat]['riichi']:
                    round_state[seat]['riichi'] = True
                    account_id = accounts_info[seat]['account_id']
                    if account_id in self.players:
                        self.players[account_id]['total_riichi'] += 1

        elif class_name == 'RecordChiPengGang':
            seat = data.get('seat')
            if seat is not None and seat in round_state:
                round_state[seat]['has_meld'] = True
                account_id = accounts_info[seat]['account_id']
                if account_id in self.players:
                    self.players[account_id]['total_melds'] += 1

        elif class_name == 'RecordAnGangAddGang':
            seat = data.get('seat')
            if seat is not None and seat in round_state:
                round_state[seat]['has_meld'] = True
                account_id = accounts_info[seat]['account_id']
                if account_id in self.players:
                    self.players[account_id]['total_melds'] += 1

        elif class_name == 'RecordHule':
            hules = data.get('hules', [])
            delta_scores = data.get('deltaScores', [0, 0, 0, 0])
            for hule in hules:
                winner_seat = hule.get('seat')
                is_zimo = hule.get('zimo', False)
                winner_riichi = hule.get('liqi', False)
                point_sum = hule.get('pointSum', 0)
                dadian = hule.get('dadian', 0)

                # 和了者 (pointSum は供託を含む総合得点、dadian は打点上)
                if winner_seat is not None and winner_seat in accounts_info:
                    account_id = accounts_info[winner_seat]['account_id']
                    if account_id in self.players:
                        self.players[account_id]['total_wins'] += 1
                        if is_zimo:
                            self.players[account_id]['tsumo_wins'] += 1
                        if winner_riichi:
                            self.players[account_id]['wins_with_riichi'] += 1
                        # pointSum が0の場合は dadian を代用
                        win_pts = point_sum if point_sum > 0 else dadian
                        self.players[account_id]['win_points'].append(win_pts)
                        # 和了巡目
                        self.players[account_id]['win_turns'].append(
                            getattr(self, '_current_turn', 0)
                        )

                # 放銃者: deltaScores で和了者以外でマイナスの席 (ツモの場合は3人全員)
                if is_zimo:
                    # ツモ和了: 和了者以外の3人が支払い
                    for seat in range(4):
                        if seat != winner_seat and seat in accounts_info and delta_scores and seat < len(delta_scores):
                            if delta_scores[seat] < 0:
                                account_id = accounts_info[seat]['account_id']
                                if account_id in self.players:
                                    self.players[account_id]['total_deal_ins'] += 1
                                    self.players[account_id]['deal_in_points'].append(abs(delta_scores[seat]))
                else:
                    # ロン和了: 放銃者1人
                    for seat in range(4):
                        if seat != winner_seat and seat in accounts_info and delta_scores and seat < len(delta_scores):
                            if delta_scores[seat] < 0:
                                account_id = accounts_info[seat]['account_id']
                                if account_id in self.players:
                                    self.players[account_id]['total_deal_ins'] += 1
                                    self.players[account_id]['deal_in_points'].append(abs(delta_scores[seat]))
                                break  # ロンは1人だけ

            # 副露があった局のカウント (各プレイヤーごと)
            for seat, st in round_state.items():
                if st['has_meld'] and seat in accounts_info:
                    account_id = accounts_info[seat]['account_id']
                    if account_id in self.players:
                        self.players[account_id]['total_hands_with_meld'] += 1

    def _handle_user_input(self, action: dict, accounts_info: dict, round_state: dict):
        """
        @title ユーザー入力の処理
        @description type=5 は局開始時のリーチ確認・立直意思表示。
                     type=2 は打牌。打牌時に立直フラグが既に立っている場合はリーチ後の打牌。
        """
        ui = action.get('userInput', {})
        seat = ui.get('seat')
        ui_type = ui.get('type')

        if seat is None or seat not in round_state:
            return

        if ui_type == 5 and not round_state[seat]['riichi']:
            # リーチ宣言 (userInput.type=5)
            round_state[seat]['riichi'] = True
            account_id = accounts_info[seat]['account_id']
            if account_id in self.players:
                self.players[account_id]['total_riichi'] += 1

    def _player_key(self, name: str, account_id: int = 0) -> int:
        """@title プレイヤー識別キー生成
        @description 雀魂は accountId、天鳳は名前のハッシュをキーとする。
        @param {str} name - プレイヤー名
        @param {int} account_id - 雀魂アカウントID (0=未指定)
        @returns {int} 識別キー
        """
        if account_id != 0:
            return account_id
        # Why: 天鳳にはアカウントIDが無いため、名前の MD5 ハッシュをID代わりにする。
        #      組み込み hash() はプロセスごとにシードが変わるため使えない。
        return get_deterministic_id(name)

    def process_tenhou_xml(self, xml_path: str):
        """@title 天鳳XML (mjlog) 1件を処理
        @description 天鳳のXML牌譜をパースし、各プレイヤーのスタッツを蓄積する。
        @param {str} xml_path - .xml ファイルの絶対パス
        """
        tree = ET.parse(xml_path)
        root = tree.getroot()

        # --- プレイヤー情報の取得 (UN タグ) ---
        un_elem = root.find('.//UN')
        if un_elem is None:
            return
        player_names = []
        player_keys = []
        # 対局の最終スコア (placement 算出用)
        final_scores: List[int] = [25000] * 4

        for i in range(4):
            raw = un_elem.get(f'n{i}', '')
            name = urllib.parse.unquote(raw)
            player_names.append(name)
            key = self._player_key(name)
            player_keys.append(key)
            stats = self._ensure_player(key, name)
            stats['num_games'] += 1  # このXML=1対局

        # --- 局ごとの状態追跡 ---
        round_state: Dict[int, dict] = {}
        # 天鳳の honba 追跡
        global_honba = 0
        global_riichi_sticks = 0

        for elem in root:
            tag = elem.tag

            if tag == 'INIT':
                seed_str = elem.get('seed', '0,0,0,0,0,0')
                parts = [int(p) for p in seed_str.split(',')]
                # seed: 継続回数, 局数, 本場, リーチ棒, 供託, ドラ表示牌
                chang = parts[0]
                ju = parts[1]
                honba = parts[2]
                global_honba = honba
                # riichi_sticks は REACH タグで管理
                dora_id = parts[5]
                dora_tile = _tenhou_tile_to_str(dora_id)

                ten_str = elem.get('ten', '250,250,250,250')
                scores = [int(x) * 100 for x in ten_str.split(',')]

                # 手牌初期化
                hands = {}
                for i in range(4):
                    hai_str = elem.get(f'hai{i}', '')
                    if hai_str:
                        hands[i] = [_tenhou_tile_to_str(int(x)) for x in hai_str.split(',') if x.strip()]
                    else:
                        hands[i] = []

                # 局状態リセット
                round_state.clear()
                for seat in range(4):
                    stats = self._ensure_player(player_keys[seat], player_names[seat])
                    stats['total_hands'] += 1
                    round_state[seat] = {
                        'hand': list(hands[seat]),
                        'riichi': False,
                        'has_meld': False,
                        'riichi_step': 0,  # 0=なし, 1=宣言, 2=成立
                        'tsumo_count': 0,  # その局のツモ回数
                    }

            elif tag == 'REACH' and round_state:
                who = int(elem.get('who', '0'))
                step = int(elem.get('step', '1'))
                if who in round_state:
                    if step == 1:
                        round_state[who]['riichi_step'] = 1
                    elif step == 2:
                        round_state[who]['riichi_step'] = 2
                        round_state[who]['riichi'] = True
                        self.players[player_keys[who]]['total_riichi'] += 1

            elif tag == 'N' and round_state:
                who = int(elem.get('who', '0'))
                m_val = int(elem.get('m', '0'))
                called_val = m_val & 0x1F
                source_rel = (m_val >> 5) & 0x3
                meld_type = (m_val >> 7) & 0x3
                if meld_type == 3:
                    # 暗槓: 手牌から4枚削除
                    tile_str = _tenhou_tile_to_str(called_val)
                    if who in round_state:
                        for _ in range(4):
                            if tile_str in round_state[who]['hand']:
                                round_state[who]['hand'].remove(tile_str)
                        round_state[who]['has_meld'] = True
                        self.players[player_keys[who]]['total_melds'] += 1
                elif meld_type in (0, 1, 2):
                    # チー(0)/ポン(1)/大明槓(2)
                    discarder = (who + source_rel) % 4 if meld_type != 0 else (who + 3) % 4
                    tile_str = _tenhou_tile_to_str(called_val)
                    # 手牌から明示的な削除（正確な枚数は build_meld_params 相当の処理が必要だが、
                    # スタッツ集計では副露した事実と自分の手牌枚数減少のみ追跡すれば十分）
                    if meld_type == 0:  # チー: 2枚削除
                        if who in round_state:
                            removed = 0
                            for h in list(round_state[who]['hand']):
                                if removed >= 2:
                                    break
                                round_state[who]['hand'].remove(h)
                                removed += 1
                    elif meld_type == 1:  # ポン: 2枚削除
                        if who in round_state:
                            for _ in range(2):
                                if tile_str in round_state[who]['hand']:
                                    round_state[who]['hand'].remove(tile_str)
                    elif meld_type == 2:  # 大明槓: 3枚削除
                        if who in round_state:
                            for _ in range(3):
                                if tile_str in round_state[who]['hand']:
                                    round_state[who]['hand'].remove(tile_str)
                    if who in round_state:
                        round_state[who]['has_meld'] = True
                        self.players[player_keys[who]]['total_melds'] += 1

            elif tag == 'DORA' and round_state:
                dora_id = int(elem.get('hai', '0'))

            elif tag == 'AGARI' and round_state:
                who = int(elem.get('who', '0'))
                from_who = int(elem.get('fromWho', '0'))
                ten_str = elem.get('ten', '0,0,0')
                ten_parts = [int(x) for x in ten_str.split(',')]
                # ten: 符, 打点, 制限フラグ
                points = ten_parts[1]

                # sc (score change): old0,delta0,old1,delta1,old2,delta2,old3,delta3
                # Why: 天鳳のscは (旧スコア, 変化量) の4組。席順は暗黙的に0-3。
                sc_str = elem.get('sc', '')
                delta_scores = [0] * 4
                if sc_str:
                    sc_parts = sc_str.split(',')
                    for i in range(0, len(sc_parts), 2):
                        delta = int(sc_parts[i + 1])
                        seat_idx = i // 2
                        if seat_idx < 4:
                            # delta は100点単位（例: -10 = -1000点）
                            delta_scores[seat_idx] = delta * 100

                # 和了の記録
                if who < len(player_keys):
                    win_pts = points
                    winner_riichi = round_state.get(who, {}).get('riichi', False)
                    winner_has_meld = round_state.get(who, {}).get('has_meld', False)
                    winner_turn = round_state.get(who, {}).get('tsumo_count', 0)

                    self.players[player_keys[who]]['total_wins'] += 1
                    if from_who == who:
                        self.players[player_keys[who]]['tsumo_wins'] += 1
                    if winner_riichi:
                        self.players[player_keys[who]]['wins_with_riichi'] += 1
                    if winner_has_meld:
                        self.players[player_keys[who]]['open_wins'] += 1
                    self.players[player_keys[who]]['win_points'].append(win_pts)
                    self.players[player_keys[who]]['win_turns'].append(winner_turn)

                # スコア更新（飛び検出 + 最終スコア用）
                for seat in range(4):
                    if seat < len(delta_scores) and seat < len(player_keys):
                        old_score = int(sc_parts[seat * 2]) if sc_str else 250
                        new_score = old_score * 100 + delta_scores[seat]
                        final_scores[seat] = new_score
                        if new_score < 0:
                            self.players[player_keys[seat]]['busted_count'] += 1

                # 放銃の記録
                if from_who != who:
                    # ロン: 放銃者1名
                    if from_who < len(delta_scores):
                        deal_in_pts = abs(delta_scores[from_who])
                        if deal_in_pts > 0 and from_who < len(player_keys):
                            self.players[player_keys[from_who]]['total_deal_ins'] += 1
                            self.players[player_keys[from_who]]['deal_in_points'].append(deal_in_pts)
                            # 立直中/副露中の放銃
                            if round_state.get(from_who, {}).get('riichi', False):
                                self.players[player_keys[from_who]]['riichi_dealins'] += 1
                            if round_state.get(from_who, {}).get('has_meld', False):
                                self.players[player_keys[from_who]]['deal_in_when_open'] += 1
                else:
                    # ツモ: 和了者以外の3名
                    for seat in range(4):
                        if seat != who and seat < len(delta_scores) and delta_scores[seat] < 0:
                            deal_in_pts = abs(delta_scores[seat])
                            if deal_in_pts > 0 and seat < len(player_keys):
                                self.players[player_keys[seat]]['total_deal_ins'] += 1
                                self.players[player_keys[seat]]['deal_in_points'].append(deal_in_pts)
                                # 立直中/副露中の放銃
                                if round_state.get(seat, {}).get('riichi', False):
                                    self.players[player_keys[seat]]['riichi_dealins'] += 1
                                if round_state.get(seat, {}).get('has_meld', False):
                                    self.players[player_keys[seat]]['deal_in_when_open'] += 1

                # 副露ハンドのカウント
                for seat, st in round_state.items():
                    if st['has_meld'] and seat < len(player_keys):
                        self.players[player_keys[seat]]['total_hands_with_meld'] += 1

            elif tag == 'RYUUKYOKU' and round_state:
                # 流局カウント
                # Why: 天鳳のRYUUKYOKUにはhai0-3が含まれ、テンパイの席だけ手牌が入る。
                #      haiがある=テンパイ、haiがない=ノーテン。
                for seat in range(4):
                    if seat in round_state and seat < len(player_keys):
                        self.players[player_keys[seat]]['exhaustive_count'] += 1
                        has_hai = elem.get(f'hai{seat}') is not None
                        if has_hai:
                            self.players[player_keys[seat]]['exhaustive_tenpai'] += 1
                # 副露ハンドのカウント（流局時も副露は記録）
                for seat, st in round_state.items():
                    if st['has_meld'] and seat < len(player_keys):
                        self.players[player_keys[seat]]['total_hands_with_meld'] += 1
                # スコア更新（飛び検出用）
                sc_str_ryu = elem.get('sc', '')
                if sc_str_ryu:
                    sc_parts_ryu = sc_str_ryu.split(',')
                    for i in range(0, len(sc_parts_ryu), 2):
                        delta = int(sc_parts_ryu[i + 1])
                        seat_idx = i // 2
                        if seat_idx < 4 and seat_idx < len(player_keys):
                            old_score = int(sc_parts_ryu[i])
                            new_score = old_score * 100 + delta * 100
                            final_scores[seat_idx] = new_score
                            if new_score < 0:
                                self.players[player_keys[seat_idx]]['busted_count'] += 1

            elif tag in ('TAIKYOKU', 'START'):
                pass  # 対局開始タグ、スキップ

            else:
                # Draw/Discard タグの処理
                # DRAW: T/U/V/W + 数字
                # DISCARD: D/E/F/G + 数字
                if tag and len(tag) >= 2 and tag[0] in 'TUVWDEFG':
                    try:
                        tile_val = int(tag[1:])
                    except ValueError:
                        continue
                    tile_str = _tenhou_tile_to_str(tile_val)
                    who_char = tag[0]
                    if who_char in 'TUVW':
                        seat = 'TUVW'.index(who_char)
                        if seat in round_state:
                            round_state[seat]['hand'].append(tile_str)
                            round_state[seat]['tsumo_count'] += 1
                    elif who_char in 'DEFG':
                        seat = 'DEFG'.index(who_char)
                        if seat in round_state and tile_str in round_state[seat]['hand']:
                            round_state[seat]['hand'].remove(tile_str)

        # --- 対局終了処理: 順位・合計スコア ---
        ordered = sorted(
            [(final_scores[s], s) for s in range(4) if s < len(player_keys)],
            reverse=True,
        )
        for rank, (score, seat) in enumerate(ordered):
            if seat < len(player_keys):
                self.players[player_keys[seat]]['placements'].append(rank)
                self.players[player_keys[seat]]['sum_final_score'] += score

    def compute_stats(self) -> Dict[str, dict]:
        """
        @title 集計結果の計算
        @description 各プレイヤーの生データから牌譜屋準拠の統計指標を算出する。
        @returns {dict} stats_db.json 形式の players dict
        """
        result = {}
        for account_id, data in self.players.items():
            g = data['num_games']
            h = data['total_hands']
            w = data['total_wins']
            tsumo_w = data['tsumo_wins']
            di = data['total_deal_ins']
            riichi = data['total_riichi']
            w_riichi = data['wins_with_riichi']
            meld_h = data['total_hands_with_meld']
            open_w = data['open_wins']
            melds = data['total_melds']
            win_pts = data['win_points']
            deal_pts = data['deal_in_points']
            win_turns = data['win_turns']
            placements = data['placements']
            riichi_di = data['riichi_dealins']
            di_open = data['deal_in_when_open']
            exh = data['exhaustive_count']
            exh_tenpai = data['exhaustive_tenpai']
            busted = data['busted_count']
            sum_final = data['sum_final_score']
            riichi_exh = data['riichi_exhaustive']

            # --- 基本 ---
            win_rate = w / h if h > 0 else 0.0
            deal_in_rate = di / h if h > 0 else 0.0
            tsumo_rate = tsumo_w / w if w > 0 else 0.0
            # 牌譜屋準拠: 黙聴率 = ダマ和了 / 門前和了
            closed_wins = w - open_w
            damaten_wins = w - w_riichi - open_w
            damaten_rate = damaten_wins / closed_wins if closed_wins > 0 else 0.0
            meld_rate = meld_h / h if h > 0 else 0.0
            riichi_rate = riichi / h if h > 0 else 0.0
            avg_win_pts = sum(win_pts) / len(win_pts) if win_pts else 0.0
            avg_deal_pts = sum(deal_pts) / len(deal_pts) if deal_pts else 0.0
            avg_win_turn = sum(win_turns) / len(win_turns) if win_turns else 0.0

            # --- 立直関連 ---
            riichi_win_rate = w_riichi / riichi if riichi > 0 else 0.0
            riichi_deal_in_rate = riichi_di / riichi if riichi > 0 else 0.0
            riichi_exhaustive_rate = riichi_exh / riichi if riichi > 0 else 0.0

            # --- 副露関連 ---
            open_win_rate = open_w / meld_h if meld_h > 0 else 0.0
            deal_in_when_open_rate = di_open / di if di > 0 else 0.0

            # --- 対局関連 ---
            avg_placement = sum(placements) / len(placements) if placements else 2.5
            bust_rate = busted / g if g > 0 else 0.0
            exhaustive_rate = exh / h if h > 0 else 0.0
            tenpai_rate_in_exh = exh_tenpai / exh if exh > 0 else 0.0

            # --- 派生指標 ---
            point_efficiency = win_rate * avg_win_pts
            loss_from_deal_in = deal_in_rate * avg_deal_pts
            adj_efficiency = point_efficiency - loss_from_deal_in
            # 局収支: (平均最終スコア - 25000) * 対局数 / 総局数
            round_balance = ((sum_final / max(g, 1)) - 25000) * g / max(h, 1) if h > 0 else 0.0

            result[str(account_id)] = {
                'nickname': data['nickname'],
                'account_id': account_id,
                # 生データ
                'total_hands': h,
                'total_games': g,
                # 基本
                'win_rate': round(win_rate, 4),
                'deal_in_rate': round(deal_in_rate, 4),
                'tsumo_rate': round(tsumo_rate, 4),
                'damaten_rate': round(damaten_rate, 4),
                'meld_rate': round(meld_rate, 4),
                'riichi_rate': round(riichi_rate, 4),
                'avg_win_points': round(avg_win_pts, 1),
                'avg_deal_in_points': round(avg_deal_pts, 1),
                'avg_win_turn': round(avg_win_turn, 2),
                'avg_placement': round(avg_placement + 1, 2),  # 1-4表示に
                # 立直
                'riichi_win_rate': round(riichi_win_rate, 4),
                'riichi_deal_in_rate': round(riichi_deal_in_rate, 4),
                'riichi_exhaustive_rate': round(riichi_exhaustive_rate, 4),
                # 副露
                'open_win_rate': round(open_win_rate, 4),
                'deal_in_when_open_rate': round(deal_in_when_open_rate, 4),
                # 対局
                'bust_rate': round(bust_rate, 4),
                'exhaustive_rate': round(exhaustive_rate, 4),
                'tenpai_rate_in_exh': round(tenpai_rate_in_exh, 4),
                # 派生
                'point_efficiency': round(point_efficiency, 1),
                'loss_from_deal_in': round(loss_from_deal_in, 1),
                'adj_efficiency': round(adj_efficiency, 1),
                'round_balance': round(round_balance, 1),
            }
        return result


def find_record_files(data_dir: str) -> List[str]:
    """
    @title 牌譜ファイルの検索
    @description data/ フォルダから record_*_trimmed.json パターンに合致するファイルを列挙する。
    @param {str} data_dir - data ディレクトリ
    @returns {List[str]} ファイルパスのリスト
    """
    import glob as _glob
    pattern = os.path.join(data_dir, RECORD_GLOB_PATTERN)
    return sorted(_glob.glob(pattern))


def find_tenhou_xml_files(xml_dir: str = TENHOU_XML_DIR) -> List[str]:
    """@title 天鳳XMLファイルの検索
    @param {str} xml_dir - XMLディレクトリ
    @returns {List[str]} ファイルパスのリスト
    """
    import glob as _glob
    if not os.path.isdir(xml_dir):
        print(f"[find_tenhou_xml] ディレクトリが存在しません: {xml_dir}")
        return []
    return sorted(_glob.glob(os.path.join(xml_dir, '*.xml')) + _glob.glob(os.path.join(xml_dir, '*.mjlog')))


def build_stats_db(data_dir: str = DATA_DIR, output_path: str = STATS_DB_PATH,
                   tenhou_xml_dir: Optional[str] = TENHOU_XML_DIR):
    """
    @title スタッツDBの構築
    @description 全牌譜（MJ雀魂JSON + 天鳳XML）を解析してプレイヤースタッツを集計し、
                 stats_db.json に保存する。
    @param {str} data_dir - 雀魂牌譜ディレクトリ
    @param {str} output_path - 出力先パス
    @param {str|None} tenhou_xml_dir - 天鳳XMLディレクトリ (None=スキップ)
    """
    tracker = PlayerStatsTracker()
    total_records = 0

    # --- 雀魂JSONの処理 ---
    record_files = find_record_files(data_dir)
    for filepath in record_files:
        filename = os.path.basename(filepath)
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                record = json.load(f)
            tracker.process_record(record)
            total_records += 1
            print(f"[build_stats_db] JSON完了: {filename}")
        except Exception as e:
            print(f"[build_stats_db] JSONエラー ({filename}): {e}")
            continue

    # --- 天鳳XMLの処理 ---
    if tenhou_xml_dir:
        xml_files = find_tenhou_xml_files(tenhou_xml_dir)
        print(f"[build_stats_db] 天鳳XML {len(xml_files)} 件を処理中...")
        for filepath in xml_files:
            filename = os.path.basename(filepath)
            try:
                tracker.process_tenhou_xml(filepath)
                total_records += 1
                if total_records % 1000 == 0:
                    print(f"[build_stats_db] 進行中: {total_records} 件処理済...")
            except Exception as e:
                print(f"[build_stats_db] XMLエラー ({filename}): {e}")
                continue
        print(f"[build_stats_db] 天鳳XML処理完了: {len(xml_files)} 件")

    if total_records == 0:
        print("[build_stats_db] 処理可能な牌譜がありませんでした。")
        return

    stats = tracker.compute_stats()
    db = {
        'players': stats,
        'meta': {
            'total_records_processed': total_records,
            'total_players': len(stats),
            'last_updated': datetime.now(timezone.utc).isoformat(),
        },
    }

    os.makedirs(os.path.dirname(output_path) or '.', exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    print(f"[build_stats_db] 完了: {len(stats)} プレイヤーのスタッツを {output_path} に保存しました。")
    print(f"  内訳: JSON {len(record_files)} 件 + XML {len(xml_files) if tenhou_xml_dir and xml_files else 0} 件")


def load_stats_db(path: str = STATS_DB_PATH) -> Dict[str, dict]:
    """
    @title stats_db.json の読み込み
    @param {str} path - stats_db.json のパス
    @returns {dict} プレイヤースタッツ辞書 (空の場合は空 dict)
    """
    if os.path.exists(path):
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f).get('players', {})
    return {}


def get_player_stats(account_id: int, db: Optional[Dict[str, dict]] = None) -> Optional[dict]:
    """
    @title 特定プレイヤーのスタッツ取得
    @param {int} account_id - 雀魂アカウントID
    @param {dict|None} db - stats_db の players 辞書 (None の場合は自動読み込み)
    @returns {dict|None} プレイヤースタッツ、または None
    """
    if db is None:
        db = load_stats_db()
    return db.get(str(account_id))


if __name__ == '__main__':
    build_stats_db()
