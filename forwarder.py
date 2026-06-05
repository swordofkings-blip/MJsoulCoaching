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

    # 元の巨大デコード版を保存
    filename = f"record_{uuid}.json"
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(output_data, f, ensure_ascii=False, indent=2)

    # 保存成功をコンソールに目立たせて表示
    # ハードコードされた数値 80 は、区切り線の長さをコンソールの標準的な幅に合わせるために指定されたものです
    print("=" * 80)
    print(f"[Success] 元の牌譜データをJSON保存しました: {filename}")

    # トリミングした軽量版データを生成し、別ファイルとして保存
    trimmed_data = trim_game_record(output_data)
    trimmed_filename = f"record_{uuid}_trimmed.json"
    with open(trimmed_filename, 'w', encoding='utf-8') as f:
        json.dump(trimmed_data, f, ensure_ascii=False, indent=2)

    print(f"[Success] 軽量化された牌譜データをJSON保存しました: {trimmed_filename}")
    print("=" * 80)

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

        elif path == '/api/records':
            # 保存されている trimmed 牌譜一覧をスキャンして返す
            try:
                records = []
                # 雀魂ラッパーフォルダ内のトリミング済みJSONを検索
                files = glob.glob("record_*_trimmed.json")
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

                filename = f"record_{uuid}_trimmed.json"
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

    def do_POST(self):
        """
        @title POSTパケットレシーバー
        @description 受信したパケットデータを復号し、liqi.pyを用いて解析結果を出力します。また、牌譜パケットを検知した場合はJSON保存を実行します。
        """
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
