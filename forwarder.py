# -*- coding: utf-8 -*-
"""
@title 雀魂WebSocket中継サーバー
@description ブラウザ上のユーザースクリプトから転送されたパケットデータを受信し、liqi.pyで解析して表示します。また、牌譜シミュレーターのWebサーバーとしても機能します。
"""

import base64
import json
import traceback
import glob
import os
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from google.protobuf.json_format import MessageToDict
from liqi import LiqiProto
from game_state import GameState, Meld, ReachState
from evaluator import Evaluator
from str_converter import validate_tiles

try:
    from proto import liqi_pb2 as pb
except ImportError:
    import liqi_pb2 as pb

# 雀魂のWebSocketデータを解析するためのパーサークラスを初期化
liqi_parser = LiqiProto()

def decode_wrapped_protobuf(raw_bytes):
    """
    @title 入れ子Protobufデコーダー
    @description 雀魂特有の「[クラス名] ＋ [バイナリデータ]」の二重構造バイナリを再帰的に剥がしてパースします。
    @param {bytes} raw_bytes - 入力バイナリ
    @returns {tuple} (クラス名, デコードされた辞書データ, 内包バイナリ) または (None, None, 元バイナリ)
    """
    try:
        from liqi import fromProtobuf
        blocks = fromProtobuf(raw_bytes)
        if len(blocks) >= 2 and blocks[0]['type'] == 'string' and blocks[1]['type'] == 'string':
            class_name = blocks[0]['data'].decode('utf-8')
            # クラス名のプレフィックスをトリムしてpbモジュール内での適合クラス名を取得
            pure_name = class_name.lstrip('.').replace('lq.', '')
            payload = blocks[1]['data']
            
            # 対応するメッセージクラスが定義されていればデシリアライズを実行
            if hasattr(pb, pure_name):
                msg = getattr(pb, pure_name)()
                msg.ParseFromString(payload)
                dict_obj = MessageToDict(msg)
                return pure_name, dict_obj, payload
            else:
                return pure_name, {"raw_base64": base64.b64encode(payload).decode('utf-8')}, payload
    except Exception:
        # パース失敗時は元のバイナリを返す
        pass
    return None, None, raw_bytes

def deep_decode(data):
    """
    @title 再帰的Protobufデコーダー
    @description 辞書やリストなどのデータ構造を走査し、値が「クラス名＋Protobuf」のBase64文字列である部分を自動的にデコードしてJSONオブジェクトに置換します。
    @param {any} data - 入力データ（辞書、リスト、またはプリミティブ値）
    @returns {any} デコード・置換済みのデータ
    """
    if isinstance(data, dict):
        new_dict = {}
        for k, v in data.items():
            if isinstance(v, str):
                # 文字列の長さが極端に短い場合はBase64ではないと判断しスルーする
                # ハードコードされた数値 10 は、最小限のProtobufクラスヘッダー＋データ長を考慮して無駄なパースを避けるための閾値です
                if len(v) > 10:
                    try:
                        raw_bytes = base64.b64decode(v)
                        pure_name, decoded_dict, _ = decode_wrapped_protobuf(raw_bytes)
                        if pure_name and decoded_dict is not None:
                            # デコードに成功した場合は、さらにその内部も再帰的にデコードして格納する
                            new_dict[k] = {
                                "class_name": pure_name,
                                "data": deep_decode(decoded_dict)
                            }
                            continue
                    except Exception:
                        # デコード失敗時は単なる文字列として扱うため、後続の処理にフォールバックする
                        pass
            new_dict[k] = deep_decode(v)
        return new_dict
    elif isinstance(data, list):
        return [deep_decode(item) for item in data]
    else:
        return data

def trim_game_record(data):
    """
    @title 牌譜データ軽量化（トリミング）関数
    @description ユーザー装飾品、振聴フラグ、牌山データ、時間情報などの不要なメタデータを再帰的に削除します。
    @param {any} data - 入力データ（辞書、リスト、またはプリミティブ値）
    @returns {any} トリミング済みのデータ
    """
    if isinstance(data, dict):
        new_dict = {}
        # 不要なメタデータキーを削除対象として指定
        # これらは雀魂のProtobufスキーマ内の特定の項目名です
        strip_keys = {'zhenting', 'paishan', 'passed', 'timeuse', 'timeAdd', 'timeFixed', 'views'}
        for k, v in data.items():
            if k in strip_keys:
                continue
            new_dict[k] = trim_game_record(v)
        return new_dict
    elif isinstance(data, list):
        return [trim_game_record(item) for item in data]
    else:
        return data

def save_game_record(data_dict):
    """
    @title 牌譜データ保存関数
    @description 牌譜全体のラッパーバイナリを剥がし、各局のデータを全自動でデコードして綺麗にJSON保存します。
    @param {dict} data_dict - デコードされたResGameRecord of Lobbyの辞書データ
    """
    if not data_dict:
        return

    head = data_dict.get('head', {})
    uuid = head.get('uuid', 'unknown_uuid')

    # dataフィールド（巨大Base64）を取得
    base64_data = data_dict.get('data', '')
    if not base64_data:
        print("[Info] 牌譜のdataフィールドが空です。")
        return

    # Base64を復号
    raw_data = base64.b64decode(base64_data)

    # 1段目のラッパー（GameDetailRecords）を剥がす
    pure_name, detail_dict, unpacked_detail_bytes = decode_wrapped_protobuf(raw_data)
    
    # 局ごとの詳細データを格納する配列
    decoded_rounds = []

    # 正常にGameDetailRecordsを取り出せた場合、内部のrecordsリスト（各局バイナリ）を走査
    if pure_name == 'GameDetailRecords' and detail_dict:
        # 各局データをさらにデコード（2段目のラッパーを剥がす）
        records_list = detail_dict.get('records', [])
        for idx, record_item in enumerate(records_list):
            try:
                # bytes型あるいはBase64文字列からバイナリを取得
                if isinstance(record_item, str):
                    round_bytes = base64.b64decode(record_item)
                else:
                    round_bytes = record_item

                # 2段目のラッパー（GameRoundDetail等）を剥がす
                round_class, round_dict, _ = decode_wrapped_protobuf(round_bytes)
                
                if round_class and round_dict:
                    # アクションリストなどがあれば、その中のActionPrototype等も更に個別展開が狙えますが、
                    # 主要な局情報(GameRoundDetail等)はこの段階で綺麗にJson展開されます。
                    decoded_rounds.append({
                        "round_index": idx,
                        "class_name": round_class,
                        "data": round_dict
                    })
                else:
                    decoded_rounds.append({
                        "round_index": idx,
                        "class_name": round_class or "Unknown",
                        "raw_base64": base64.b64encode(round_bytes).decode('utf-8')
                    })
            except Exception as e:
                print(f"[Warning] 局 {idx} の詳細デコード中にエラーが発生しました: {e}")
    else:
        print(f"[Warning] GameDetailRecordsラッパーのアンラップに失敗しました (取得クラス: {pure_name})")
        # 1段目のアンラップが失敗した場合は、そのままの解析結果を表示用に入れる
        detail_dict = detail_dict or {"raw_base64_original": base64_data}

    # 3段目の入れ子データ（actions内のresultなど）をすべて再帰的に展開して保存する
    output_data = {
        "head": head,
        "detail_records": deep_decode(detail_dict),
        "decoded_rounds": deep_decode(decoded_rounds)
    }

    # data フォルダが存在することを確認
    os.makedirs('data', exist_ok=True)

    # 元の巨大デコード版を保存
    filename = os.path.join('data', f"record_{uuid}.json")
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 保存成功をコンソールに目立たせて表示
    # ハードコードされた数値 80 は、区切り線の長さをコンソールの標準的な幅に合わせるために指定されたものです
    print("=" * 80)
    print(f"[Success] 元の牌譜データをJSON保存しました: {filename}")

    # トリミングした軽量版データを生成し、別ファイルとして保存
    trimmed_data = trim_game_record(output_data)
    trimmed_filename = os.path.join('data', f"record_{uuid}_trimmed.json")
    with open(trimmed_filename, 'w', encoding='utf-8') as f:
        json.dump(trimmed_data, f, ensure_ascii=False, indent=2)

    print(f"[Success] 軽量化された牌譜データをJSON保存しました: {trimmed_filename}")
    print("=" * 80)

def evaluate_state(payload: dict) -> dict:
    """
    @title 局面評価エントリポイント
    @description シミュレーターから送信された局面JSONをGameStateに復元し、Evaluatorで全手牌候補を評価して推奨打牌・戦略パラメータ・各牌の思考根拠を返す。
    @param {dict} payload - リクエストボディ。手牌・河・鳴き・ドラ・点数・巡目・立直情報を含む。
    @returns {dict} レスポンスJSON (recommended, strategy_details, evaluations, summary)
    """
    state = _restore_game_state(payload)

    my_seat = state.my_seat
    hand = list(state.my_hand)

    if len(hand) % 3 != 2 or len(hand) < 2:
        return {
            "status": "not_your_turn",
            "recommended": None,
            "push_score": 0.0,
            "strategy_details": None,
            "evaluations": [],
            "summary": {"hand_size": len(hand), "tsumo_count": state.tsumo_count}
        }

    evaluator = Evaluator(state)
    strategy_details = evaluator.strategy.get_strategy_details()
    push_score = float(evaluator.strategy.compute_push_score())

    unique_tiles = list(dict.fromkeys(hand))
    evaluations = []
    for tile in unique_tiles:
        ev_entry = _build_evaluation_entry(evaluator, tile)
        evaluations.append(ev_entry)

    evaluations.sort(key=lambda x: (-x["score"], x["tile"]))
    recommended = evaluations[0]["tile"] if evaluations else None

    if recommended is not None:
        rec_entry = next((e for e in evaluations if e["tile"] == recommended), None)
        if rec_entry is not None:
            rec_entry["reason"] = _build_decision_reason(rec_entry, strategy_details, evaluator)

    return {
        "status": "ok",
        "recommended": recommended,
        "push_score": round(push_score, 3),
        "strategy_details": strategy_details,
        "evaluations": evaluations,
        "summary": {
            "hand_size": len(hand),
            "tsumo_count": state.tsumo_count,
            "my_seat": my_seat,
            "open_meld_count": sum(1 for m in state.my_melds if m.is_open),
        }
    }


def _build_evaluation_entry(evaluator: 'Evaluator', tile: str) -> dict:
    """
    @title 個別牌評価エントリ生成
    @description ある牌について、攻撃/防御/シャンテン/有効牌/ボーナス/理由を含む評価辞書を組み立てる。
    @param {Evaluator} evaluator - 初期化済みのEvaluator
    @param {str} tile - 評価対象の牌文字列
    @returns {dict} 1牌分の評価データ
    """
    try:
        score = float(evaluator.evaluate_tile(tile))
        attack = float(evaluator.attack.attack_score_for_tile(tile))
        defense = float(evaluator.defense.defense_score_for_tile(tile))
        shanten = int(evaluator.attack.shanten_after_discard(tile))
        ukeire, _ = evaluator.attack.ukeire_for_discard(tile)
    except Exception:
        score = 0.0
        attack = 0.0
        defense = 0.0
        shanten = 99
        ukeire = 0

    keiten_bonus = int(evaluator._get_keiten_bonus(tile))
    safety_desc = _safety_description(defense, evaluator)
    attack_desc = _attack_description(shanten, ukeire)

    return {
        "tile": tile,
        "score": round(score, 2),
        "attack": round(attack, 2),
        "defense": round(defense, 2),
        "shanten": shanten,
        "ukeire": int(ukeire),
        "safety_desc": safety_desc,
        "attack_desc": attack_desc,
        "keiten_bonus": keiten_bonus,
        "reason": "",
    }


def _safety_description(defense: float, evaluator: 'Evaluator') -> str:
    """
    @title 安全度の日本語説明生成
    @description 防御スコアから、現物・スジ・字牌・無筋のいずれに該当するかを判定して日本語ラベルを返す。
    @param {float} defense - 防御評価スコア
    @param {Evaluator} evaluator - Evaluatorインスタンス（戦略モード参照用）
    @returns {str} 安全度分類の日本語ラベル
    """
    from evaluator import SCORE_GENBUTSU, SCORE_SUJI, SCORE_HONOR, SCORE_MUSUJI
    if defense >= SCORE_GENBUTSU:
        return "現物 (安全度: 極高)"
    if defense >= SCORE_SUJI:
        return "スジ (安全度: 高)"
    if defense >= SCORE_HONOR:
        return "字牌/生牌 (安全度: 中)"
    if defense > 0:
        return "準安全 (安全度: 低)"
    return "無筋 (危険)"


def _attack_description(shanten: int, ukeire: int) -> str:
    """
    @title 攻撃評価の日本語説明生成
    @description シャンテン数と有効牌枚数から、手効率の状態を日本語で表現する。
    @param {int} shanten - 打牌後のシャンテン数
    @param {int} ukeire - 有効牌枚数
    @returns {str} 手効率の日本語ラベル
    """
    if shanten <= -1:
        return f"和了形 (聴牌済・有効牌 {ukeire} 枚でアガリ可能)"
    if shanten == 0:
        return f"テンパイ維持 (有効牌: {ukeire}枚)"
    if ukeire == 0:
        return f"向聴維持 (有効牌: 0枚・手詰まり)"
    if shanten == 1:
        return f"1向聴へ前進 (有効牌: {ukeire}枚)"
    return f"{shanten}向聴 (有効牌: {ukeire}枚)"


def _build_decision_reason(rec_entry: dict, strategy_details: dict, evaluator: 'Evaluator') -> str:
    """
    @title 推奨打牌の決定理由生成
    @description 戦略モードと推奨牌の安全度・手効率から、なぜその牌が選ばれたかを日本語で要約する。
    @param {dict} rec_entry - 推奨牌の評価エントリ
    @param {dict} strategy_details - 戦略パラメータ辞書
    @param {Evaluator} evaluator - Evaluatorインスタンス
    @returns {str} 推奨理由の日本語テキスト
    """
    mode = strategy_details.get("mode", "")
    push = strategy_details.get("push_score", 0.0)
    threat = strategy_details.get("max_threat", 0.0)
    tile = rec_entry["tile"]
    shanten = rec_entry["shanten"]
    ukeire = rec_entry["ukeire"]
    defense = rec_entry["defense"]
    attack = rec_entry["attack"]
    safety_desc = rec_entry["safety_desc"]
    attack_desc = rec_entry["attack_desc"]
    keiten_bonus = rec_entry.get("keiten_bonus", 0)

    parts = []
    if mode.startswith("ベタオリ"):
        if defense >= 1000:
            parts.append(f"他家リーチ・面前等の脅威が高いため、ベタオリ（完全防御）モードで安全牌を最優先。")
            parts.append(f"「{tile}」は{safety_desc}（守備点: {defense:.0f}）でロスのない打牌。")
        else:
            parts.append(f"完全防御局面だが、現物がないため無筋の中から相対的にリスクの低い牌を選択。")
            parts.append(f"「{tile}」は守備点 {defense:.0f}、手効率 {attack_desc} の妥協打牌。")
    elif mode.startswith("ゼンツ"):
        parts.append(f"オーラス・ラス目のためゼンツ（全ツモ・全当たり狙い）。")
        parts.append(f"「{tile}」の手効率 {attack_desc} を評価して採用。")
    elif push >= 0.5:
        parts.append(f"押し気味（PushScore={push:.2f}）で {attack_desc} を選択。")
        parts.append(f"「{tile}」の攻撃評価 {attack:.0f} が最大。")
    else:
        parts.append(f"{mode} にて {attack_desc}（有効牌 {ukeire}枚）と{safety_desc}を総合評価。")
        parts.append(f"「{tile}」が総合スコア最高。")

    if keiten_bonus > 0:
        parts.append(f"終盤の形テンボーナス +{keiten_bonus} 点を加算。")
    return "".join(parts)


def _restore_game_state(payload: dict) -> GameState:
    """
    @title GameState復元ヘルパー
    @description リクエストJSONからGameStateを組み立てる。欠損フィールドにはデフォルト値を入れて寛容に動作させる。
    @param {dict} payload - クライアント送信JSON
    @returns {GameState} 復元されたGameStateインスタンス
    """
    state = GameState()
    state.my_seat = int(payload.get("my_seat", 0))
    state.chang = int(payload.get("chang", 0))
    state.ju = int(payload.get("ju", 0))
    state.ben = int(payload.get("ben", 0))
    state.liqibang = int(payload.get("liqibang", 0))
    state.left_tile_count = int(payload.get("left_tile_count", 70))
    state.tsumo_count = int(payload.get("tsumo_count", 0))
    state.scores = list(payload.get("scores", [25000, 25000, 25000, 25000]))
    state.doras = list(payload.get("doras", []))

    hand = payload.get("hand", [])
    if not validate_tiles(hand):
        raise ValueError("hand contains invalid tile strings")
    state.my_hand = list(hand)

    raw_river = payload.get("river", [[], [], [], []])
    state.river = [list(r) for r in raw_river] + [[] for _ in range(4 - len(raw_river))]
    state.river = state.river[:4]

    raw_moqie = payload.get("river_moqie", [[], [], [], []])
    state.river_moqie = [list(r) for r in raw_moqie] + [[] for _ in range(4 - len(raw_moqie))]
    state.river_moqie = state.river_moqie[:4]
    for seat_idx in range(4):
        if len(state.river_moqie[seat_idx]) < len(state.river[seat_idx]):
            state.river_moqie[seat_idx] = [False] * len(state.river[seat_idx])

    raw_melds = payload.get("melds", [[], [], [], []])
    state.melds = []
    for seat_idx in range(4):
        seat_melds = raw_melds[seat_idx] if seat_idx < len(raw_melds) else []
        converted = []
        for m in seat_melds:
            if isinstance(m, dict):
                converted.append(Meld(
                    type=int(m.get("type", 0)),
                    tiles=list(m.get("tiles", [])),
                    froms=list(m.get("froms", [])),
                    tile_states=list(m.get("tile_states", [])),
                ))
            elif isinstance(m, list):
                converted.append(Meld(type=0, tiles=list(m), froms=[]))
        state.melds.append(converted)
    state.my_melds = list(state.melds[state.my_seat])

    raw_reach = payload.get("reach_states", [])
    for i in range(4):
        rs = ReachState()
        if i < len(raw_reach) and isinstance(raw_reach[i], dict):
            rs.is_reach = bool(raw_reach[i].get("is_reach", False))
            rs.reach_turn = int(raw_reach[i].get("reach_turn", -1))
            rs.is_ippatsu = bool(raw_reach[i].get("is_ippatsu", False))
        state.reach_states[i] = rs

    state.last_discard_seat = int(payload.get("last_discard_seat", -1))
    state.last_discard_tile = payload.get("last_discard_tile", None)
    return state


class FlowMsgMock:
    """
    @title WebSocketメッセージモッククラス
    @description liqi.pyのparseメソッドが要求するflow_msgオブジェクトの構造を模倣します。
    """
    def __init__(self, content: bytes, from_client: bool):
        self.content = content
        self.from_client = from_client

class PacketHandler(BaseHTTPRequestHandler):
    """
    @title パケットHTTP要求ハンドラー
    @description ブラウザからのCORSリクエストおよびPOST転送パケットを処理し、GET要求に対してWeb UIとAPIをサーブします。
    """

    def _set_cors_headers(self):
        """
        @title CORSヘッダー設定
        @description ブラウザの異なるドメイン（雀魂公式）からのPOST要求を許可するためのCORSヘッダーを追加します。
        """
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        # Private Network Access (PNA) ポリシーにより、ローカルホストへのアクセスが制限されるのを防ぐためのヘッダー
        self.send_header("Access-Control-Allow-Private-Network", "true")

    def do_OPTIONS(self):
        """
        @title OPTIONSプリフライトハンドラー
        @description ブラウザが安全性の確認のために事前に行うOPTIONSリクエストに即座に成功を返します。
        """
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        """
        @title GET要求ハンドラー
        @description 牌譜一覧画面、シミュレーター画面、および各種APIエンドポイント（一覧取得・牌譜詳細取得）をサーブします。
        """
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path
        query = urllib.parse.parse_qs(parsed_path.query)

        if path == '/':
            # 牌譜一覧画面のHTMLを返す
            try:
                filepath = os.path.join(os.path.dirname(__file__), 'templates', 'index.html')
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error reading index.html: {e}")

        elif path == '/simulator':
            # シミュレーター画面のHTMLを返す
            try:
                filepath = os.path.join(os.path.dirname(__file__), 'templates', 'simulator.html')
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error reading simulator.html: {e}")

        elif path == '/majsoul_hook.user.js':
            # Tampermonkey自動インポート用のユーザースクリプトを返す
            try:
                filepath = os.path.join(os.path.dirname(__file__), 'majsoul_hook.js')
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"Error reading majsoul_hook.js: {e}")

        elif path == '/api/records':
            # 保存されている trimmed 牌譜一覧をスキャンして返す
            try:
                records = []
                # 雀魂ラッパーフォルダ内のトリミング済みJSONを検索
                files = glob.glob("data/record_*_trimmed.json")
                for filepath in files:
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        head = data.get('head', {})
                        uuid = head.get('uuid', 'unknown')
                        start_time = head.get('startTime', 0)
                        category = head.get('config', {}).get('category', 2) # デフォルト四人戦

                        # 各プレイヤーの最終スコアを取得
                        result_players = head.get('result', {}).get('players', [])
                        # ハードコードされた数値 25000 は、四人戦の初期点数として使われる一般的な数値です
                        scores_map = {p.get('seat'): p.get('partPoint1', 25000) for p in result_players}

                        players = []
                        for acc in head.get('accounts', []):
                            seat = acc.get('seat')
                            players.append({
                                'seat': seat,
                                'nickname': acc.get('nickname', 'Unknown'),
                                'score': scores_map.get(seat, 25000)
                            })

                        records.append({
                            'uuid': uuid,
                            'startTime': start_time,
                            'category': category,
                            'players': players
                        })
                    except Exception as fe:
                        print(f"[Warning] 牌譜一覧API用ファイルの読み込みに失敗しました ({filepath}): {fe}")

                # 対局開始時間で降順ソート
                records.sort(key=lambda x: x['startTime'], reverse=True)

                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(json.dumps(records, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"API Error: {e}")

        elif path == '/api/record':
            # 特定のuuidの trimmed 牌譜データを返す
            try:
                uuid = query.get('uuid', [None])[0]
                if not uuid:
                    self.send_error(400, "Missing uuid parameter")
                    return

                filename = os.path.join('data', f"record_{uuid}_trimmed.json")
                if not os.path.exists(filename):
                    self.send_error(404, f"Record not found: {filename}")
                    return

                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()

                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                self.send_error(500, f"API Error: {e}")
        else:
            self.send_response(404)
            self.end_headers()

    def _handle_evaluate(self, post_data: bytes):
        """
        @title /api/evaluate ハンドラー
        @description シミュレーターから送信された局面JSONをGameStateに復元し、Evaluatorで各牌を評価して推奨打牌付きで返却する。
        @param {bytes} post_data - HTTPリクエストボディ
        """
        try:
            payload = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            self._send_json({"status": "error", "message": f"Invalid JSON: {e}"}, status=400)
            return

        try:
            result = evaluate_state(payload)
            self._send_json(result)
        except Exception as e:
            traceback.print_exc()
            self._send_json({"status": "error", "message": str(e)}, status=500)

    def _send_json(self, obj, status: int = 200):
        """
        @title JSONレスポンス送信
        @description CORSヘッダー付きのJSONレスポンスを指定ステータスで送信する。
        @param {any} obj - 送信するJSON化可能オブジェクト
        @param {int} status - HTTPステータスコード
        """
        self.send_response(status)
        self._set_cors_headers()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.end_headers()
        self.wfile.write(json.dumps(obj, ensure_ascii=False).encode('utf-8'))

    def do_POST(self):
        """
        @title POSTパケットレシーバー
        @description 受信したパケットデータを復号し、liqi.pyを用いて解析結果を出力します。また、牌譜パケットを検知した場合はJSON保存を実行します。/api/evaluate では局面評価を返します。
        """
        if self.path == '/api/evaluate':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            self._handle_evaluate(post_data)
            return
        if self.path == '/packet':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            
            try:
                payload = json.loads(post_data.decode('utf-8'))
                from_client = payload.get('from_client', False)
                base64_data = payload.get('data', '')

                raw_bytes = base64.b64decode(base64_data)
                flow_msg = FlowMsgMock(raw_bytes, from_client)
                
                try:
                    result = liqi_parser.parse(flow_msg)

                    direction = "➡ [CLIENT -> SERVER]" if from_client else "⬅ [SERVER -> CLIENT]"
                    print(f"\n{direction} (ID: {result.get('id')})")
                    print(f"Method: {result.get('method')}")
                    print(f"Data: {json.dumps(result.get('data'), ensure_ascii=False, indent=2)}")
                    print("-" * 80)

                    msg_type_str = str(result.get('type'))
                    if result.get('method') == '.lq.Lobby.fetchGameRecord' and ('Res' in msg_type_str or '3' in msg_type_str):
                        save_game_record(result.get('data'))

                except AssertionError:
                    print(f"[Warning] パケットの到着順序が前後したか、初期パケットが欠落したため解析をスキップしました (Length: {len(raw_bytes)} bytes)")
                    
                    # 【フォールバック】アサーションエラーで解析がスキップされたが、巨大パケット（牌譜データ）であると推測される場合
                    # ハードコードされた数値 5000 は、最小限の牌譜詳細データサイズを想定したしきい値です。
                    if len(raw_bytes) > 5000 and not from_client:
                        try:
                            from liqi import fromProtobuf, MsgType
                            msg_type = MsgType(raw_bytes[0])
                            if msg_type == MsgType.Res or raw_bytes[0] == 3:
                                msg_block = fromProtobuf(raw_bytes[3:])
                                if len(msg_block) >= 2 and msg_block[1]['type'] == 'string':
                                    pb_bytes = msg_block[1]['data']
                                    res_record = pb.ResGameRecord()
                                    res_record.ParseFromString(pb_bytes)
                                    res_dict = MessageToDict(res_record)
                                    print("[Info] [Fallback] 巨大パケットから牌譜データ (ResGameRecord) の強制デコードを試みます。")
                                    save_game_record(res_dict)
                        except Exception as fe:
                            print(f"[Warning] 牌譜の強制デコード（フォールバック）に失敗しました: {fe}")

                except Exception as parse_error:
                    print(f"[Warning] パケット解析中にエラーが発生しました: {parse_error}")

                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success"}).encode('utf-8'))

            except Exception as e:
                print(f"[Error Processing HTTP Request]: {e}")
                traceback.print_exc()
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

def run(server_class=HTTPServer, handler_class=PacketHandler, port=8080):
    """
    @title サーバー起動関数
    @description HTTPサーバーを指定されたポートで待機起動します。
    @param {type} server_class - HTTPServer クラス
    @param {type} handler_class - 処理用のハンドラークラス
    @param {int} port - サーバー待機ポート (デフォルト: 8080)
    """
    server_address = ('', port)
    httpd = server_class(server_address, handler_class)
    # ハードコードされた数値 8080 は、ローカル開発サーバー用ポートとして一般的で重複を避けるために選定されたものです。
    print(f"Starting server on port {port}...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
        httpd.server_close()

if __name__ == '__main__':
    run()
