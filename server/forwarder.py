# -*- coding: utf-8 -*-
"""
@title 雀魂WebSocket中継サーバー
@description ブラウザ上のユーザースクリプトから転送されたパケットデータを受信し、liqi.pyで解析して表示します。また、牌譜シミュレーターのWebサーバーとしても機能します。
"""

import base64
import json
import re
import traceback
import glob
import os
import sys
import subprocess
import urllib.parse
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from google.protobuf.json_format import MessageToDict

_FW_ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
sys.path.insert(0, _FW_ROOT)

from core.sapk_api import fetch_player_stats
from majsoul_wrapper.liqi import LiqiProto
from core.game_state import GameState, Meld, ReachState
from core.evaluator import Evaluator
from core.str_converter import validate_tiles, hand_to_counts
from majsoul_wrapper.proto import liqi_pb2 as pb

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
        from majsoul_wrapper.liqi import fromProtobuf
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

def _try_decode_record_fallback(raw_bytes):
    """
    @title 牌譜データ強制デコード (フォールバック)
    @description 牌譜レスポンスのパケットを、初期パケット欠落時でも
                強制的にデコードして保存する。
    @param {bytes} raw_bytes - パケット生バイト列
    """
    try:
        from majsoul_wrapper.liqi import fromProtobuf, MsgType
        # Type 3 = Res (レスポンス)
        print(f"[Fallback] First 8 bytes: {raw_bytes[:8].hex()}", flush=True)
        if raw_bytes[0] != 3 and not (hasattr(MsgType, 'Res') and raw_bytes[0] == MsgType.Res.value):
            print(f"[Fallback] First byte {raw_bytes[0]} is not 3 (Res). Skipping.", flush=True)
            return
        # Protobuf メッセージブロックを抽出
        msg_block = fromProtobuf(raw_bytes[3:])
        if len(msg_block) < 2 or msg_block[1]['type'] != 'string':
            print(f"[Fallback] msg_block length={len(msg_block)} or type mismatch. msg_block={msg_block[:3] if msg_block else 'empty'}", flush=True)
            return
        pb_bytes = msg_block[1]['data']
        # ResGameRecord としてデコード試行
        res_record = pb.ResGameRecord()
        res_record.ParseFromString(pb_bytes)
        res_dict = MessageToDict(res_record)
        # 牌譜データの実体があるか確認
        head = res_dict.get('head', {})
        if not head or 'uuid' not in head:
            print(f"[Fallback] No head or uuid in res_dict. keys={list(res_dict.keys())[:5]}", flush=True)
            return
        print("[Info] [Fallback] Decoded game record from raw packet.")
        save_game_record(res_dict)
    except Exception as fe:
        print(f"[Warning] Fallback decode failed: {fe}")


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

    # 牌譜屋APIからプレイヤーのスタッツを取得し seat 番号をキーに埋め込む
    accounts = head.get('accounts', [])
    player_stats = {}
    for acc in accounts:
        seat = acc.get('seat')
        nickname = acc.get('nickname', '')
        if seat is not None and nickname:
            stats = fetch_player_stats(nickname)
            player_stats[str(seat)] = stats
    if player_stats:
        head['player_stats'] = player_stats

    # 3段目の入れ子データ（actions内のresultなど）をすべて再帰的に展開して保存する
    output_data = {
        "head": head,
        "detail_records": deep_decode(detail_dict),
        "decoded_rounds": deep_decode(decoded_rounds)
    }

    # data フォルダが存在することを確認
    os.makedirs(os.path.join(_FW_ROOT, 'data'), exist_ok=True)

    # トリミングした軽量版データを生成し、別ファイルとして保存
    # Why: 元の生 JSON は保存容量が大きいが、シミュレーターは trimmed/eval しか使わないため
    #      元データは破棄してディスク容量を節約する。
    trimmed_data = trim_game_record(output_data)
    trimmed_filename = os.path.join(_FW_ROOT, 'data', f"record_{uuid}_trimmed.json")
    with open(trimmed_filename, 'w', encoding='utf-8') as f:
        json.dump(trimmed_data, f, ensure_ascii=False, indent=2)

    print(f"[Success] 軽量化された牌譜データをJSON保存しました: {trimmed_filename}")
    print("=" * 80)

    # 牌譜の AI 総合評価 (S~C 評価) をバックグラウンドで実行
    # Why: 各打牌を AI で再評価し、実際の打牌との一致度から S~C グレードを算出。
    # 計算に時間がかかるため、別スレッドで実行し結果をキャッシュする。
    _schedule_record_evaluation(uuid, trimmed_filename)


def _schedule_record_evaluation(uuid: str, trimmed_filename: str):
    """牌譜の AI 総合評価をバックグラウンドで実行し、結果をキャッシュする"""
    import threading
    eval_filename = os.path.join(_FW_ROOT, 'data', f"record_{uuid}_eval.json")

    # 既に評価結果があればスキップ
    if os.path.exists(eval_filename):
        return

    def _run():
        try:
            with open(trimmed_filename, 'r', encoding='utf-8') as f:
                record = json.load(f)
            from core.record_evaluator import evaluate_record
            result = evaluate_record(record)
            # キャッシュに保存
            with open(eval_filename, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f"[Success] 牌譜 {uuid} の AI 評価を保存しました: {eval_filename}")
        except Exception as e:
            print(f"[Warning] 牌譜 {uuid} の AI 評価に失敗しました: {e}")
            # 失敗マーカーを保存 (無限再試行を防ぐ)
            try:
                with open(eval_filename, 'w', encoding='utf-8') as f:
                    json.dump({}, f, ensure_ascii=False)
            except Exception:
                pass

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()

from collections import OrderedDict
_eval_cache = OrderedDict()
# Why: 牌譜の事前計算 (record_evaluator.py) では各アクションごとに異なる局面を評価するため、
# 64 件ではキャッシュがすぐに追い出される。2048 件に拡大してヒット率を上げる。
# 牌譜 1 件あたり 200-500 アクション程度なので、その大半をカバーできる。
_EVAL_CACHE_MAX = 2048

def _eval_cache_key(payload: dict) -> str:
    # 評価結果に影響する主要フィールドだけハッシュ化
    import hashlib
    key_data = {
        'hand': payload.get('hand', []),
        'melds': payload.get('melds', []),
        'river': payload.get('river', []),
        'doras': payload.get('doras', []),
        'tsumo_count': payload.get('tsumo_count', 0),
        'left_tile_count': payload.get('left_tile_count', 70),
        'scores': payload.get('scores', []),
        'my_seat': payload.get('my_seat', 0),
        'reach_states': payload.get('reach_states', []),
        'chang': payload.get('chang', 0),
        'ju': payload.get('ju', 0),
    }
    s = json.dumps(key_data, sort_keys=True, ensure_ascii=False)
    return hashlib.md5(s.encode('utf-8')).hexdigest()

def evaluate_state(payload: dict) -> dict:
    """
    @title 局面評価エントリポイント
    @description シミュレーターから送信された局面JSONをGameStateに復元し、Evaluatorで全手牌候補を評価して推奨打牌・戦略パラメータ・各牌の思考根拠を返す。
    @param {dict} payload - リクエストボディ。手牌・河・鳴き・ドラ・点数・巡目・立直情報を含む。
    @returns {dict} レスポンスJSON (recommended, strategy_details, evaluations, summary)
    """
    # Why: 同一局面の連続評価を省略して「次巡」連打時のサーバー負荷を削減。
    # params は結果に影響しないのでキーから除外（config 変更時のみ無効化される）。
    # LRU: アクセスされたエントリを最後に移動して、古いものから削除する。
    cache_key = _eval_cache_key(payload)
    if cache_key in _eval_cache:
        _eval_cache.move_to_end(cache_key)
        return _eval_cache[cache_key]
    state = _restore_game_state(payload)
    params = payload.get("params", None)
    if params is None:
        import json
        config_path = os.path.join(_FW_ROOT, 'config', 'config_parameters.json')
        if os.path.exists(config_path):
            with open(config_path, encoding='utf-8') as f:
                params = json.load(f)
        else:
            params = {}

    my_seat = state.my_seat
    hand = list(state.my_hand)

    # 手牌 + 副露牌の合計で打牌判断を判定（副露後・カン後は手牌が14枚未満になる）
    total_tiles = len(hand) + sum(len(m.tiles) for m in state.my_melds)
    if total_tiles < 13 or total_tiles > 15 or len(hand) < 1:
        return {
            "status": "not_your_turn",
            "recommended": None,
            "push_score": 0.0,
            "strategy_details": None,
            "evaluations": [],
            "summary": {"hand_size": len(hand), "tsumo_count": state.tsumo_count}
        }

    evaluator = Evaluator(state, params=params)
    strategy_details = evaluator.strategy.get_strategy_details()
    push_score = float(evaluator.strategy.compute_push_score())

    is_riichi_active = state.reach_states[my_seat].is_reach

    if is_riichi_active:
        # リーチ中の推奨は基本ツモ切り (last_self_drawn)
        recommended = state.last_self_drawn
    
    unique_tiles = list(dict.fromkeys(hand))
    evaluations = []
    for tile in unique_tiles:
        ev_entry = _build_evaluation_entry(evaluator, tile)
        evaluations.append(ev_entry)

    evaluations.sort(key=lambda x: (-x["score"], x["tile"]))
    
    if not is_riichi_active:
        recommended = evaluations[0]["tile"] if evaluations else None

    # テンパイ時の立直ダマ判定
    should_riichi = None
    riichi_reason = ""
    if not is_riichi_active and recommended:
        rec_shanten = evaluations[0]["shanten"] if evaluations else 99
        open_meld_count = sum(1 for m in state.my_melds if m.is_open)
        if rec_shanten == 0 and open_meld_count == 0:
            riichi_details = evaluator.get_riichi_decision_details()
            should_riichi = riichi_details["should_riichi"]
            riichi_reason = riichi_details["reason"]

    all_scores = [ev["score"] for ev in evaluations]
    max_score = max(all_scores) if all_scores else 0.0
    min_score = min(all_scores) if all_scores else 0.0
    near_tiles = []
    rating_threshold = params.get('MATCH_RATING_THRESHOLD', 90.0)
    min_range = params.get('MATCH_MIN_RANGE', 400.0)

    # 推奨牌のシャンテン数と防御スコアを取得
    rec_shanten = evaluations[0]["shanten"] if evaluations else 99
    rec_defense = evaluations[0]["defense"] if evaluations else -9999.0

    for ev in evaluations:
        score_range = max(max_score - min_score, min_range)
        diff = max(0.0, max_score - ev["score"])
        ratio = max(0.0, 1.0 - diff / score_range)
        ev["rating"] = round(100.0 * (ratio ** 2), 1)
        ev["blunder_score"] = round(diff, 2)
        ev["is_blunder"] = ev["blunder_score"] > 200
        ev["reason"] = _build_decision_reason(ev, strategy_details, evaluator, is_best=(ev["tile"] == recommended))
        if ev["tile"] != recommended:
            if ev["rating"] >= rating_threshold:
                if ev["defense"] <= rec_defense and ev["shanten"] > rec_shanten:
                    continue
                near_tiles.append(ev["tile"])

    kyushu_kyuhai_data = _build_kyushu_kyuhai_data(state)
    sufutsusenru_data = _build_sufutsusenru_data(state, evaluator)

    result = {
        "status": "ok",
        "recommended": recommended,
        "near_tiles": near_tiles,
        "push_score": round(push_score, 3),
        "strategy_details": strategy_details,
        "evaluations": evaluations,
        "is_riichi_active": is_riichi_active,
        "should_riichi": should_riichi,
        "riichi_reason": riichi_reason,
        "kyushu_kyuhai": kyushu_kyuhai_data,
        "sufutsusenru": sufutsusenru_data,
        "summary": {
            "hand_size": len(hand),
            "tsumo_count": state.tsumo_count,
            "my_seat": my_seat,
            "open_meld_count": sum(1 for m in state.my_melds if m.is_open),
        }
    }
    # キャッシュに書き込み（LRU: 古いものを削除）
    # Why: OrderedDict + move_to_end で LRU 風に動作。牌譜の事前計算で
    # 似た局面が連続して評価される場合にヒット率が上がる。
    if len(_eval_cache) >= _EVAL_CACHE_MAX:
        _eval_cache.popitem(last=False)
    _eval_cache[cache_key] = result
    return result


def _normalize_hand_red_five(hand):
    """Convert red 5 tiles (0m/0p/0s) to regular 5 (5m/5p/5s) for matching."""
    return ['5' + t[1:] if t and t[0] == '0' else t for t in hand]


def evaluate_meld(payload: dict) -> dict:
    """
    @title 副露判断評価
    @description 局面JSONと副露候補のリストを受け取り、各候補（スキップ含む）を評価して最善を返す。
    """
    state = _restore_game_state(payload)
    # Normalize red 5 tiles in hand so candidate tiles (e.g. "5p") match hand tiles (e.g. "0p")
    state.my_hand = _normalize_hand_red_five(state.my_hand)
    import json
    config_path = os.path.join(_FW_ROOT, 'config', 'config_parameters.json')
    if os.path.exists(config_path):
        with open(config_path, encoding='utf-8') as f:
            params = json.load(f)
    else:
        params = {}

    my_seat = state.my_seat
    candidates = payload.get("meld_candidates", [])
    # candidates: [{type: "pon"/"chi"/"daiminkan"/"ankan"/"kakan"/"skip", tiles: [...], froms: [...], consumed: [...]}]

    results = []
    for cand in candidates:
        if cand.get("type") == "skip":
            ev = Evaluator(state, params=params)
            hand = state.my_hand
            unique_tiles = list(dict.fromkeys(hand))
            best_score = float('-inf')
            best_tile = None
            best_eval = None
            for tile in unique_tiles:
                entry = _build_evaluation_entry(ev, tile)
                if entry["score"] > best_score:
                    best_score = entry["score"]
                    best_tile = tile
                    best_eval = entry
            results.append({
                "type": "skip",
                "label": "スキップ",
                "best_discard": best_tile,
                "best_score": best_score,
                "best_eval": best_eval,
                "shanten": best_eval["shanten"] if best_eval else 99,
                "reason": _build_meld_reason("skip", best_eval, state, state, None),
            })
            continue

        # Apply meld to a copy of state
        import copy
        st = copy.deepcopy(state)
        ctype = cand["type"]
        tiles = cand.get("tiles", [])
        froms = cand.get("froms", [])

        # Remove consumed tiles from hand
        for t in tiles:
            if t in st.my_hand:
                st.my_hand.remove(t)

        # Add meld
        if ctype == "pon":
            meld_type = 1
        elif ctype == "chi":
            meld_type = 0
        elif ctype in ("daiminkan", "kakan"):
            meld_type = 2
        elif ctype == "ankan":
            meld_type = 3
        else:
            continue

        # Why: should_call_meld() のオタ風ポン禁止・序盤チー禁止などの
        # 鳴き禁止条件をここで適用し、不適切な鳴きを除外する。
        # (AI のスコア比較では捕捉できない、ルールベースの判断)
        # Note: should_call_meld は tiles を文字列 ('3z') で受け取る仕様
        from core.game_state import Meld
        try:
            check_ev = Evaluator(state, params=params)
            # tiles が数値 ID の場合は文字列に変換
            meld_tile_strs = [str(t) if not isinstance(t, str) else t for t in tiles]
            can_meld = check_ev.should_call_meld(meld_type, meld_tile_strs, froms[0] if froms else state.my_seat)
            if not can_meld:
                # 鳴き禁止の具体的な理由を特定
                forbidden_reason = _get_meld_forbidden_reason(check_ev, meld_type, meld_tile_strs, froms[0] if froms else state.my_seat, state, params)
                # 鳴き禁止条件に該当: UI に表示するため flagged として返す (推奨からは除外)
                results.append({
                    "type": ctype,
                    "label": cand.get("label", ctype),
                    "tiles": tiles,
                    "best_discard": None,
                    "best_score": -99999,
                    "best_eval": None,
                    "shanten": 99,
                    "forbidden": True,
                    "forbidden_reason": forbidden_reason,
                    "reason": f"❌ {forbidden_reason}",
                })
                continue
        except Exception:
            pass  # 判定エラー時はスキップせず続行

        if ctype == "kakan":
            # 加槓: 既存のポンを槓に変更（新しい副露を追加しない）
            kakan_tile = list(tiles)[0] if tiles else None
            found_meld = False
            for m in st.my_melds:
                if m.type == 1 and m.tiles and m.tiles[0] == kakan_tile:
                    m.tiles.append(kakan_tile)
                    m.type = meld_type
                    found_meld = True
                    break
            if not found_meld:
                st.my_melds.append(Meld(type=meld_type, tiles=list(tiles), froms=list(froms), tile_states=[]))
        else:
            st.my_melds.append(Meld(type=meld_type, tiles=list(tiles), froms=list(froms), tile_states=[]))

        # Evaluate the resulting state
        ev = Evaluator(st, params=params)
        if ctype in ("kakan", "ankan"):
            # 加槓/暗槓後は嶺上牌が来るため、特定の切り牌を評価できない
            # 手牌のシャンテン数のみ表示
            shanten_after = 99
            if st.my_hand:
                from core.strategy_manager import ShantenCalculator
                from core.str_converter import hand_to_counts
                open_cnt = sum(1 for m in st.my_melds if m.is_open)
                cnts = hand_to_counts(st.my_hand)
                shanten_after = ShantenCalculator.calculate_open(cnts, open_cnt)

            # 人読み対応: should_ankan/should_kakan の判定でスコアを動的設定
            kan_allowed = False
            if ctype == "ankan":
                kan_allowed = ev.should_ankan()
            elif ctype == "kakan":
                kakan_tile = list(tiles)[0] if tiles else None
                if kakan_tile:
                    kan_allowed = ev.should_kakan(kakan_tile)

            if kan_allowed:
                # スキップの best_score を取得して槓を最優先
                skip_score = results[0]["best_score"] if results else 0
                kan_score = skip_score + 1
            else:
                kan_score = -9999
            results.append({
                "type": ctype,
                "label": cand.get("label", ctype),
                "tiles": tiles,
                "best_discard": None,
                "best_score": kan_score,
                "best_eval": None,
                "shanten": shanten_after,
                "reason": _build_meld_reason(ctype, None, state, st, cand),
            })
        else:
            hand = st.my_hand
            unique_tiles = list(dict.fromkeys(hand))
            best_score = float('-inf')
            best_tile = None
            best_eval = None
            for tile in unique_tiles:
                entry = _build_evaluation_entry(ev, tile)
                if entry["score"] > best_score:
                    best_score = entry["score"]
                    best_tile = tile
                    best_eval = entry

            results.append({
                "type": ctype,
                "label": cand.get("label", ctype),
                "tiles": tiles,
                "best_discard": best_tile,
                "best_score": best_score,
                "best_eval": best_eval,
                "shanten": best_eval["shanten"] if best_eval else 99,
                "reason": _build_meld_reason(ctype, best_eval, state, st, cand),
            })

    if not results:
        return {"status": "error", "message": "No candidates provided"}

    # Find the option with the highest best_score
    best = max(results, key=lambda x: x.get("best_score", 0)) if results else None

    return {
        "status": "ok",
        "candidates": results,
        "recommended": best["type"] if best else None,
    }


def _get_meld_forbidden_reason(evaluator, type_: int, tiles: list, from_seat: int, state, params) -> str:
    """
    @title 鳴き禁止の具体的理由を返す
    @description should_call_meld() が False を返した具体的な理由を判定する。
    牌譜の事前計算 (record_evaluator.py) で同一の判定を行い eval.json に保存する。
    """
    from str_converter import is_honor, tile_to_id

    if type_ == 1:  # ポン
        target_id = tile_to_id(tiles[0])
        if is_honor(target_id):
            seat_wind = 27 + ((state.my_seat - state.ju) % 4)
            round_wind = 27 + (state.chang % 4)
            if 27 <= target_id <= 30:  # 風牌
                if target_id != seat_wind and target_id != round_wind:
                    return f"オタ風ポン禁止 ({['東', '南', '西', '北'][target_id - 27]} は{['東', '南', '西', '北'][seat_wind - 27]}家の自風・{['東', '南', '西', '北'][round_wind - 27]}場の場風ではない)"
            # 三元牌 (白發中) はポンが許可されるはず
            if 31 <= target_id <= 33:
                return f"三元牌 ({['白', '發', '中'][target_id - 31]}) のポンは本来許可されます"
    if type_ == 0:  # チー
        early_disable = params.get('MELD_EARLY_TURN_DISABLE', 0)
        current_turn_meld = (state.tsumo_count - 1) // 4 + 1
        if early_disable > 0 and current_turn_meld <= early_disable:
            return f"序盤チー禁止 (現在{current_turn_meld}巡目 ≤ {early_disable}巡目までチー封印)"

    # 大明槓: should_daiminkan の判定
    if type_ == 2:
        try:
            if not evaluator.should_daiminkan(tiles, from_seat):
                # should_daiminkan の中身は複雑なため、ここでは代表理由を返す
                from_seat_name = ['東', '南', '西', '北'][from_seat] if 0 <= from_seat < 4 else f"席{from_seat}"
                return f"大明槓不成立 ({from_seat_name}家の捨牌で槓する条件を満たさず)"
        except Exception:
            pass

    # 副露数上限
    open_meld_count = sum(1 for m in state.my_melds if m.is_open)
    if open_meld_count >= 4:
        return f"既に副露 {open_meld_count} 組あり、これ以上鳴けません"

    # 役満狙い (門前限定役満) チェック
    try:
        from core.yakuman_evaluator import YakumanEvaluator
        ye = YakumanEvaluator(state)
        if ye.should_seal_melds():
            results = ye.evaluate_all()
            yname_map = {
                'kokushi': '国士無双', 'suuankou': '四暗刻', 'chuuren': '九蓮宝燈',
            }
            best = None
            for name, r in results.items():
                if r.is_possible and r.shanten <= 2 and name in yname_map:
                    if best is None or r.progress > best[1].progress:
                        best = (name, r)
            if best is not None:
                yname = yname_map[best[0]]
                return f"{yname} {best[1].shanten}向聴のため副露封印"
            return "役満狙い (門前限定) のため副露封印"
    except Exception:
        pass

    # 副露封印モード (MeldSealTracker)
    try:
        sealed = evaluator.meld_seal.evaluate(state.my_hand, state.my_melds,
                                              state.my_seat, state.chang,
                                              state.ju, params)
        if sealed:
            return "副露封印モード (役満狙い等で門前維持中)"
    except Exception:
        pass

    # 防御姿勢
    mode = evaluator.strategy.get_strategy_mode()
    if mode in ("完全撤退", "撤退準備"):
        return f"防御姿勢 ({mode}) のため副露禁止"
    if mode == "スリム化":
        return f"{mode}のため副露封印"

    # シャンテン数の改善チェック (should_call_meld の主要条件)
    # Why: 鳴いてもシャンテン数が改善しない、または悪化する場合は鳴かない。
    # これが should_call_meld の最も多い False 理由。
    try:
        from core.strategy_manager import ShantenCalculator
        hand_counts = state.my_hand_counts()
        before_shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count) if open_meld_count > 0 else ShantenCalculator.calculate_closed_effective(hand_counts)

        after_counts = list(hand_counts)
        if type_ == 1:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 2)
        elif type_ == 0:
            for t in tiles[1:]:
                tid = tile_to_id(t)
                after_counts[tid] = max(0, after_counts[tid] - 1)
        elif type_ == 2:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 3)
        after_shanten = ShantenCalculator.calculate_open(after_counts, open_meld_count + 1)

        if after_shanten > before_shanten:
            type_name = {0: 'チー', 1: 'ポン', 2: '大明槓'}.get(type_, '副露')
            return f"{type_name}後にシャンテン数が悪化 ({before_shanten}向聴 → {after_shanten}向聴) するため推奨せず"
        if after_shanten == before_shanten:
            type_name = {0: 'チー', 1: 'ポン', 2: '大明槓'}.get(type_, '副露')
            return f"{type_name}してもシャンテン数が改善せず ({before_shanten}向聴) 価値が低いため推奨せず"
    except Exception:
        pass

    # 2向聴以上 + 期待飜数低
    try:
        before_shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count) if open_meld_count > 0 else ShantenCalculator.calculate_closed_effective(hand_counts)
        if before_shanten >= 2:
            return f"2向聴以上 ({before_shanten}向聴) で役牌ポン以外かつ期待飜数 < 2 のため推奨度低"
    except Exception:
        pass

    return "鳴き条件を満たさない (具体理由は手牌構成依存)"


def _build_meld_reason(ctype: str, best_eval: dict, old_state, new_state, cand=None) -> str:
    if best_eval is None and ctype not in ("kakan", "ankan"):
        return ""

    open_meld_count = sum(1 for m in old_state.my_melds if m.is_open) if hasattr(old_state, 'my_melds') else 0
    turn = (old_state.tsumo_count // 4) if hasattr(old_state, 'tsumo_count') else 0

    lines = []

    if ctype in ("kakan", "ankan"):
        name = "加槓" if ctype == "kakan" else "暗槓"
        lines.append("嶺上牌をツモった後に判断します。")
        from core.strategy_manager import ShantenCalculator
        from core.str_converter import hand_to_counts
        if hasattr(old_state, 'my_hand') and old_state.my_hand:
            cnts = hand_to_counts(old_state.my_hand)
            old_shanten = ShantenCalculator.calculate_open(cnts, open_meld_count)
            if old_shanten == 0:
                lines.append(f"現在聴牌のため、{name}で放銃リスクが高まります。")
            else:
                lines.append(f"現在{old_shanten}向聴です。")
            # シャンテン戻しチェック
            if new_state and hasattr(new_state, 'my_hand') and new_state.my_hand:
                new_cnts = hand_to_counts(new_state.my_hand)
                new_open_cnt = sum(1 for m in new_state.my_melds if m.is_open) if hasattr(new_state, 'my_melds') else 0
                new_shanten = ShantenCalculator.calculate_open(new_cnts, new_open_cnt)
                if new_shanten > old_shanten:
                    lines.append("手が崩れてシャンテン戻しです。")
        if ctype == "ankan":
            lines.append("暗槓は門前役（四暗刻など）に影響します。")
        else:
            lines.append("加槓によりドラ表示牌が増える可能性があります。")
        return " ".join(lines)

    tile = _fmt_tile(best_eval["tile"])
    shanten = best_eval["shanten"]
    attack = best_eval["attack"]
    defense = best_eval["defense"]
    hvb = best_eval.get("hvb", 0)
    ukeire = best_eval.get("ukeire", 0)

    if ctype == "skip":
        lines.append(f"鳴かずに{tile}を切ります。")
        # 暗槓可能な状態でのスキップ→暗槓判断時は門前維持やシャンテン固定は自明なので省略
        from core.str_converter import hand_to_counts
        cnts = hand_to_counts(old_state.my_hand) if hasattr(old_state, 'my_hand') else []
        has_ankan = any(c >= 4 for c in cnts) if cnts else False

        if not has_ankan:
            # 副露封印チェック
            from core.strategy_manager import StrategyManager
            sm = StrategyManager(old_state, params={})
            if not sm.is_meld_open_allowed():
                # 副露禁止の実際の理由を特定
                try:
                    from core.yakuman_evaluator import YakumanEvaluator
                    ye = YakumanEvaluator(old_state)
                    if ye.should_seal_melds():
                        # どの役満候補が最良か
                        results = ye.evaluate_all()
                        yname_map = {
                            'kokushi': '国士無双', 'suuankou': '四暗刻', 'chuuren': '九蓮宝燈',
                            'daisuushii': '大四喜', 'shousuushii': '小四喜',
                            'ryuuiisou': '緑一色', 'suukantsu': '四槓子',
                            'daisangen': '大三元', 'tsuuiisou': '字一色',
                            'chinroutou': '清老頭', 'kokushi13': '国士無双13面',
                        }
                        best = None
                        for name, r in results.items():
                            if r.is_possible and r.shanten <= 2:
                                if best is None or r.progress > best[1].progress:
                                    best = (name, r)
                        if best is not None and best[0] in ('kokushi', 'suuankou', 'chuuren'):
                            yname = yname_map.get(best[0], best[0])
                            lines.append(f"{yname} {best[1].shanten}向聴の進行が見込めるため、副露を封印します。")
                        else:
                            # 開露可能な役満の場合や評価不能
                            lines.append("役満手の可能性が高まっているため、副露を封印します。")
                    else:
                        mode = sm.get_strategy_mode()
                        lines.append(f"{mode}のため、副露を控えます。")
                except Exception:
                    mode = sm.get_strategy_mode()
                    lines.append(f"{mode}のため、副露を控えます。")
            elif open_meld_count == 0:
                lines.append("門前を維持します。")
            else:
                lines.append("既に副露していますが、さらに鳴く価値がありません。")
            if shanten > 0:
                lines.append(f"現在{shanten}向聴です。")
                lines.append("シャンテン数が進まないため不要です。")
        else:
            if shanten > 0:
                lines.append(f"現在{shanten}向聴です。")
    else:
        meld_tile_str = ""
        if cand and cand.get("tiles"):
            meld_tile_str = _fmt_tile(cand["tiles"][0])
        if ctype == "pon":
            meld_name = "ポン"
        elif ctype == "daiminkan":
            meld_name = "大明槓"
        elif ctype == "ankan":
            meld_name = "暗槓"
        elif ctype == "kakan":
            meld_name = "加槓"
        else:
            meld_name = "チー"
        lines.append(f"{meld_name}して{tile}を切ります。")

        # 役牌チェック
        is_yakuhai = False
        yakuhai_reason = ""
        if ctype == "pon" and cand and cand.get("tiles"):
            from str_converter import is_honor, tile_to_id
            mt = cand["tiles"][0]
            mtid = tile_to_id(mt)
            if is_honor(mtid):
                dealer = getattr(old_state, 'dealer_seat', 0)
                seat_wind_id = 27 + (old_state.my_seat - dealer) % 4 if hasattr(old_state, 'my_seat') else 27
                round_wind_id = 27 + ((old_state.chang % 4) if hasattr(old_state, 'chang') else 0)
                if mtid in (31, 32, 33):
                    is_yakuhai = True
                    yakuhai_reason = "三元牌"
                elif mtid == seat_wind_id:
                    is_yakuhai = True
                    yakuhai_reason = "自風"
                elif mtid == round_wind_id:
                    is_yakuhai = True
                    yakuhai_reason = "場風"

                if is_yakuhai:
                    lines.append(f"役牌({yakuhai_reason})で1翻つくため価値が高いです。")
                else:
                    lines.append("役牌にならないため、手牌価値が低いと判断しました。")
        elif ctype == "pon":
            # 数牌ポン
            from hand_value import estimate_han_advanced
            old_han = estimate_han_advanced(old_state.my_hand, old_state.my_melds, old_state.doras,
                                            is_open=(open_meld_count > 0), has_reach=False,
                                            is_ippatsu=False, is_tsumo=False,
                                            seat=old_state.my_seat, chang=old_state.chang,
                                            ju=old_state.ju) if hasattr(old_state, 'my_hand') else 0
            lines.append("タンヤオ・染め手・対々和など高打点が狙える場合に有効です。")

        # シャンテン改善度
        if shanten <= -1:
            lines.append("副露後、和了形になります。積極的に仕掛けましょう。")
        elif shanten == 0:
            lines.append("副露後テンパイです。")
        else:
            lines.append(f"副露後{shanten}向聴です。")

        # 打点と有効牌
        if ukeire > 0:
            lines.append(f"有効牌{ukeire}枚。")

        # 安全性
        if defense >= 500:
            lines.append("安全な捨て牌があります。")
        elif defense < 100:
            lines.append("危険な牌を切る必要があり注意が必要です。")

        # 巡目
        if turn >= 10:
            lines.append(f"終盤({turn}巡目)のためスピード優先です。")
        elif turn <= 3:
            lines.append(f"序盤({turn}巡目)のため無理に仕掛ける必要はありません。")

    if hvb:
        lines.append(f"手役評価+{hvb}。")

    # 役満ボーナス
    yakuman_bonus = best_eval.get("yakuman_bonus", 0)
    yakuman_name = best_eval.get("yakuman_name", "")
    if yakuman_bonus > 0:
        name_jp = {"kokushi":"国士無双","suuankou":"四暗刻","daisangen":"大三元",
                   "tsuuiisou":"字一色","chinroutou":"清老頭","chuuren":"九蓮宝燈",
                   "daisuushii":"大四喜","shousuushii":"小四喜","ryuuiisou":"緑一色",
                   "suukantsu":"四槓子"}.get(yakuman_name, yakuman_name)
        lines.append(f"{name_jp}狙いで打点向上+{yakuman_bonus}。")

    text = "".join(lines)
    text += f" 【攻撃:{attack:.0f} 防御:{defense:.0f}"
    if hvb:
        text += f" 手役:{hvb}"
    text += "】"
    return text


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
    safety_desc = _safety_description(defense, evaluator, tile)
    attack_desc = _attack_description(shanten, ukeire)
    try:
        hvb = int(evaluator.attack._hand_value_bonus(tile))
    except:
        hvb = 0

    # 役満ボーナスの抽出
    yakuman_bonus = 0
    yakuman_name = ""
    key_details = []  # 決定理由に表示するIF判定ベースの詳細メッセージ
    try:
        details = evaluator.details.get(tile, [])
        for d in details:
            if "役満ボーナス" in d:
                m = re.search(r'\[(.+?)\] \(\+(\d+)\)', d)
                if m:
                    yakuman_name = m.group(1)
                    yakuman_bonus = int(m.group(2))
            # 戦略モードなど冗長なメッセージのみスキップ、数値付き評価因子は全て抽出
            if not any(skip in d for skip in ["戦略モード", "EV期待値評価", "順位状況価値", "形テンボーナス",
                                               "他家脅威による字牌評価減衰", "一発放銃回避"]):
                key_details.append(d)
    except:
        pass

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
        "hvb": hvb,
        "yakuman_bonus": yakuman_bonus,
        "yakuman_name": yakuman_name,
        "key_details": key_details,
        "reason": "",
    }


def _safety_description(defense: float, evaluator: 'Evaluator', tile: str = "") -> str:
    p = evaluator.params
    from evaluator import SCORE_GENBUTSU, SCORE_SUJI, SCORE_WALL_SUJI, SCORE_NO_CHANCE, SCORE_ONE_CHANCE, SCORE_HONOR
    from str_converter import is_honor, tile_to_id
    score_genbutsu = p.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
    score_wall = p.get('SCORE_WALL_SUJI', SCORE_WALL_SUJI)
    score_no_chance = p.get('SCORE_NO_CHANCE', SCORE_NO_CHANCE)
    score_suji = p.get('SCORE_SUJI', SCORE_SUJI)
    score_one_chance = p.get('SCORE_ONE_CHANCE', SCORE_ONE_CHANCE)
    score_honor = p.get('SCORE_HONOR', SCORE_HONOR)

    # Why: スコア数値だけで分岐すると実際の安全理由が反映されないため、
    # 条件で判定する (現物/字牌/生牌/スジ/ノーチャンス/壁端/壁スジ/ワンチャンス/危険)。
    # 各判定は実際の牌の状態で分岐する。
    # 優先順位は安全度の高い順 (現物 → 壁端 → 字牌(非常高) → ノーチャンス/スジ → 字牌(高)
    #   → 壁スジ → ワンチャンス → 字牌(中) → 生牌 → 準安全 → 無筋)。

    tile_id = tile_to_id(tile) if tile else None
    is_honor_tile = (tile_id is not None and is_honor(tile_id))

    # 生牌判定: 場に1枚も見えていない牌 (他家可視枚数 = 0)
    # 字牌でも数牌でも、生牌 = 危険牌
    is_shinpai = False
    all_visible = None
    if tile_id is not None:
        all_visible = evaluator.state.all_visible_counts()
        my_hand_counts = evaluator.state.my_hand_counts()
        public_visible = all_visible[tile_id] - my_hand_counts[tile_id]
        is_shinpai = (public_visible == 0)

    # 1. 現物: 他家の河にある (最高安全度)
    if tile_id is not None and not is_shinpai:
        for s in range(4):
            if s == evaluator.state.my_seat:
                continue
            for t in evaluator.state.river[s]:
                if tile_to_id(t) == tile_id:
                    return "現物 (安全度: 極高)"

    # 2. 壁端: 壁端安全牌 (数牌のみ、字牌には適用されない)
    if tile_id is not None and not is_shinpai and not is_honor_tile:
        try:
            wall_edge_ids = evaluator.defense._kabe_edge_safe_ids()
            if tile_id in wall_edge_ids:
                return "壁端 (安全度: 非常高)"
        except Exception:
            pass

    # 3. 字牌 (総可視枚数 4): 非常高 (他家持てない)
    if is_honor_tile and all_visible is not None:
        if all_visible[tile_id] >= 4:
            return "字牌 (安全度: 非常高)"

    # 4. ノーチャンス: 数牌のみ
    if tile_id is not None and not is_shinpai and not is_honor_tile:
        try:
            no_chance_ids = evaluator.defense._no_chance_ids()
            if tile_id in no_chance_ids:
                return "ノーチャンス (安全度: 高)"
        except Exception:
            pass

    # 5. スジ: 数牌のみ (他家河に同じスート ±3 の牌)
    if tile_id is not None and not is_shinpai and not is_honor_tile:
        for s in range(4):
            if s == evaluator.state.my_seat:
                continue
            for t in evaluator.state.river[s]:
                try:
                    did = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(did):
                    continue
                if (tile_id // 9) == (did // 9):
                    diff = abs((tile_id % 9) - (did % 9))
                    if diff == 3 and (tile_id % 9) in (0, 1, 3, 4, 6, 7) and (did % 9) in (0, 1, 3, 4, 6, 7):
                        return "スジ (安全度: 高)"

    # 6. 字牌 (総可視枚数 3): 高 (他家最大1枚、単騎のみ)
    if is_honor_tile and all_visible is not None:
        if all_visible[tile_id] >= 3:
            return "字牌 (安全度: 高)"

    # 7. 壁スジ: 数牌のみ
    if tile_id is not None and not is_shinpai and not is_honor_tile:
        try:
            wall_suji_ids = evaluator.defense._wall_suji_ids()
            if tile_id in wall_suji_ids:
                return "壁スジ (安全度: 中)"
        except Exception:
            pass

    # 8. ワンチャンス: 数牌のみ
    if defense >= score_one_chance and tile_id is not None and not is_shinpai and not is_honor_tile:
        return "ワンチャンス (安全度: 中)"

    # 9. 字牌: (手牌内枚数, 河・場の枚数) のマトリクスで安全度判定
    # Why: 残り枚数 (4 - 手牌 - 河) と相手視点で安全度ラインが決まる。
    # 優先順: 絶対安全 → 超安全 → 状況2択 (スジライン) → 明確な危険 (ワンチャンスライン) → 最も危険
    if is_honor_tile and all_visible is not None:
        hand_count = evaluator.state.my_hand_counts()[tile_id]
        public_count = all_visible[tile_id] - hand_count
        remaining = 4 - hand_count - public_count
        # 絶対安全 (放銃0%): 残り0枚、自分が最後の1枚
        if remaining == 0:
            return "字牌 絶対安全 (安全度: 極高)"
        # 超安全 (ほぼ鉄安): 残り1枚、単騎のみ
        if remaining == 1 and public_count == 2 and hand_count == 1:
            return "字牌 超安全 (安全度: 非常高)"
        # 状況2択 (スジライン): 残り1枚、シャボ or 生牌単騎狙い
        if remaining == 1 and public_count == 1 and hand_count == 2:
            return "字牌 状況2択・シャボ (安全度: 中)"
        if remaining == 1 and public_count == 0 and hand_count == 3:
            return "字牌 状況2択・生牌単騎 (安全度: 中低)"
        # 明確な危険 (ワンチャンスライン): 残り2枚、1枚枯れ
        if remaining == 2 and public_count == 1 and hand_count == 1:
            return "字牌 明確な危険 (安全度: 低)"
        # 最も危険: 残り2枚、生牌 (無筋の么九牌と同等)
        if remaining == 2 and public_count == 0 and hand_count == 2:
            return "字牌 最も危険 (安全度: 危険)"
        # 残り1枚: 残り1枚 (1, 0) ケース (生牌で残り1枚)
        if remaining == 1 and public_count == 0 and hand_count == 1:
            return "字牌 生牌・残り1枚 (安全度: 危険)"

    # 10. 生牌判定 (数牌で場に1枚も見えていない = 危険牌)
    if is_shinpai:
        return "生牌 (危険)"

    # 11. その他
    if defense > 0:
        return f"準安全 (守備点: {defense:.0f})"
    if defense == 0:
        return "無筋 (危険)"
    return f"危険 (守備点: {defense:.0f})"


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
        return f"テンパイ (有効牌: {ukeire}枚)"
    if ukeire == 0:
        return f"向聴維持 (有効牌: 0枚・手詰まり)"
    if shanten == 1:
        return f"1向聴 (有効牌: {ukeire}枚)"
    return f"{shanten}向聴 (有効牌: {ukeire}枚)"


TILE_NAMES = {
    '1m': '1萬', '2m': '2萬', '3m': '3萬', '4m': '4萬', '5m': '5萬', '6m': '6萬', '7m': '7萬', '8m': '8萬', '9m': '9萬',
    '0m': '赤5萬',
    '1p': '1筒', '2p': '2筒', '3p': '3筒', '4p': '4筒', '5p': '5筒', '6p': '6筒', '7p': '7筒', '8p': '8筒', '9p': '9筒',
    '0p': '赤5筒',
    '1s': '1索', '2s': '2索', '3s': '3索', '4s': '4索', '5s': '5索', '6s': '6索', '7s': '7索', '8s': '8索', '9s': '9索',
    '0s': '赤5索',
    '1z': '東', '2z': '南', '3z': '西', '4z': '北', '5z': '白', '6z': '發', '7z': '中'
}

def _fmt_tile(t):
    return TILE_NAMES.get(t, t)

def _build_decision_reason(entry: dict, strategy_details: dict,
                            evaluator: 'Evaluator', is_best: bool = False) -> str:
    tile = _fmt_tile(entry["tile"])
    shanten = entry["shanten"]
    ukeire = entry["ukeire"]
    attack = entry["attack"]
    defense = entry["defense"]
    key_details = entry.get("key_details", [])

    # ヘッダー行
    label = "推奨" if is_best else "打牌"
    try:
        bd = evaluator.attack._ukeire_quality_breakdown(entry["tile"])
        ukeire_str = f"有効牌{ukeire}枚(良形{bd['good']} 悪形{bd['bad']})"
    except:
        ukeire_str = f"有効牌{ukeire}枚"

    if shanten <= -1:
        shanten_str = "和了形"
    elif shanten == 0:
        shanten_str = "聴牌"
    else:
        shanten_str = f"{shanten}向聴"

    lines = [f"「{tile}」{label} | {shanten_str} {ukeire_str}"]

    # key_details を数値付き箇条書きに変換
    for d in key_details:
        m = re.search(r'\(([+-]?\d+(?:\.\d+)?)\)', d)
        if m:
            val = m.group(1)
            label_text = re.sub(r'\s*\([+-]?\d+(?:\.\d+)?\)', '', d).strip()
            lines.append(f"{val}: {label_text}")
        else:
            lines.append(f"・{d}")

    # 最終評価値行
    lines.append(f"【最終評価値: {entry['score']:.0f}  攻撃:{attack:.0f}  防御:{defense:.0f}】")

    return "\n".join(lines)


_YAOCHU_IDS = [0, 8, 9, 17, 18, 26] + list(range(27, 34))


def _build_kyushu_kyuhai_data(state: GameState) -> dict:
    result = {
        "can_declare": False,
        "recommend_declare": False,
        "reason": ""
    }
    if not state.my_hand:
        return result
    counts = hand_to_counts(state.my_hand)
    yaochu_types = sum(1 for i in _YAOCHU_IDS if counts[i] >= 1)
    yaochu_total = sum(counts[i] for i in _YAOCHU_IDS)
    if yaochu_types == 9 and yaochu_total == 9:
        result["can_declare"] = True
        result["recommend_declare"] = True
        result["reason"] = "9種9牌のため流局を推奨します。"
    elif yaochu_types == 10 and yaochu_total == 10:
        result["can_declare"] = True
        if state.my_score_rank() == 3:
            result["recommend_declare"] = False
            result["reason"] = "10種10牌ですが、現在ラスのため国士無双を狙うことを推奨します。"
        else:
            result["recommend_declare"] = True
            result["reason"] = "10種10牌のため流局を推奨します。"
    elif yaochu_types == 10 and yaochu_total >= 11:
        result["can_declare"] = True
        result["recommend_declare"] = False
        result["reason"] = "10種11牌以上（対子あり）のため国士無双を狙うことを推奨します。"
    elif yaochu_types >= 11:
        result["can_declare"] = True
        result["recommend_declare"] = False
        result["reason"] = "11種以上の么九牌のため国士無双を狙うことを推奨します。"
    return result


def _build_sufutsusenru_data(state: GameState, evaluator: 'Evaluator') -> dict:
    result = {
        "is_possible": False,
        "recommend_discard": False,
        "wind_tile": None,
        "reason": ""
    }
    wind_possible, wind_tile = state.is_first_turn_wind_limit_possible()
    if not wind_possible or wind_tile is None:
        return result
    result["is_possible"] = True
    result["wind_tile"] = wind_tile
    if evaluator.strategy.is_high_hand_value_first_turn():
        result["recommend_discard"] = False
        mode = evaluator.strategy.get_strategy_mode()
        result["reason"] = f"手牌価値が高いため、四風子連打を回避しアガリを目指すことを推奨します（手牌評価: {mode}）。"
    else:
        result["recommend_discard"] = True
        result["reason"] = "手牌価値が低いため、四風子連打による流局を狙うことを推奨します。"
    return result


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
    state.dealer_seat = state.ju

    hand = payload.get("hand", [])
    if not validate_tiles(hand):
        raise ValueError("hand contains invalid tile strings")
    state.my_hand = list(hand)

    # buildCoachPayload は常にツモ牌を hand の末尾に移動しているため、末尾が last_self_drawn
    if len(hand) >= 14:
        state.last_self_drawn = hand[-1]

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
                raw_type = m.get("type", 0)
                if isinstance(raw_type, str):
                    type_map = {'cpg': 1, 'chi': 1, 'pon': 2, 'peng': 2, 'kan': 5, 'minkan': 5, 'ankan': 3}
                    meld_type = type_map.get(raw_type.lower(), 1)
                else:
                    meld_type = int(raw_type)
                converted.append(Meld(
                    type=meld_type,
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
    state.player_stats = payload.get("player_stats", {})
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
                err_msg = str(e).encode('ascii', 'replace').decode('ascii')
                self.send_error(500, f"Error reading index.html: {err_msg}")

        elif path == '/simulator':
            # シミュレーター画面のHTMLを返す
            try:
                filepath = os.path.join(os.path.dirname(__file__), 'templates', 'simulator.html')
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                err_msg = str(e).encode('ascii', 'replace').decode('ascii')
                self.send_error(500, f"Error reading simulator.html: {err_msg}")

        elif path == '/majsoul_hook.user.js':
            # Tampermonkey自動インポート用のユーザースクリプトを返す
            try:
                # Why: PyInstaller ビルド時、__file__ は _MEIPASS 配下の temp 展開ディレクトリを指す。
                # dev 実行時は元の .py の場所を指す。両方に対応する。
                base_dir = os.path.dirname(__file__)
                if not os.path.exists(os.path.join(base_dir, 'majsoul_hook.js')):
                    # PyInstaller ビルド時: _internal 内に同梱される
                    base_dir = os.path.join(_FW_ROOT, '_internal')
                filepath = os.path.join(base_dir, 'majsoul_hook.js')
                with open(filepath, 'r', encoding='utf-8') as f:
                    content = f.read()
                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                # Why: ブラウザのキャッシュで古い版が表示されるのを防ぐため no-cache ヘッダを追加
                self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
                self.send_header('Pragma', 'no-cache')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                # Why: send_error のメッセージに日本語エラーメッセージを含めて latin-1 で送信すると
                # UnicodeEncodeError になるため、ASCII 文字のみで表現する。
                err_msg = str(e).encode('ascii', 'replace').decode('ascii')
                self.send_error(500, f"Error reading majsoul_hook.js: {err_msg}")

        elif path == '/api/records':
            # 保存されている trimmed 牌譜一覧をスキャンして返す
            try:
                records = []
                # 雀魂コーチングくんフォルダ内のトリミング済みJSONを検索
                files = glob.glob(os.path.join(_FW_ROOT, 'data', 'record_*_trimmed.json'))
                for filepath in files:
                    try:
                        with open(filepath, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                        head = data.get('head', {})
                        uuid = head.get('uuid')
                        if not uuid:
                            # ファイル名からUUIDを抽出: record_{uuid}_trimmed.json
                            basename = os.path.basename(filepath)
                            uuid = basename.replace('record_', '').replace('_trimmed.json', '')
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

                        # AI 総合評価 (S~C) と事前計算表示データのキャッシュ読み込み
                        eval_filepath = os.path.join(_FW_ROOT, 'data', f'record_{uuid}_eval.json')
                        evaluations = None
                        actions_map = None
                        if os.path.exists(eval_filepath):
                            try:
                                with open(eval_filepath, 'r', encoding='utf-8') as f:
                                    eval_data = json.load(f)
                                # 新構造 (grades/actions) と旧構造 (フラット) の両方に対応
                                if isinstance(eval_data, dict) and 'grades' in eval_data:
                                    evaluations = eval_data.get('grades', {})
                                    actions_map = eval_data.get('actions', {})
                                else:
                                    # 旧構造: フラットな {seat: {grade, ...}}
                                    evaluations = eval_data
                                    actions_map = {}
                            except Exception:
                                evaluations = None
                                actions_map = None

                        records.append({
                            'uuid': uuid,
                            'startTime': start_time,
                            'category': category,
                            'players': players,
                            'evaluations': evaluations,
                            'actions': actions_map,
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
                err_msg = str(e).encode('ascii', 'replace').decode('ascii')
                self.send_error(500, f"API Error: {err_msg}")

        elif path == '/api/record':
            uuid = query.get('uuid', [None])[0]
            if not uuid:
                self.send_error(400, "Missing uuid parameter")
                return

            filename = os.path.join(_FW_ROOT, 'data', f"record_{uuid}_trimmed.json")
            if not os.path.exists(filename):
                filename = os.path.join(_FW_ROOT, 'logs', f'{uuid}.mjson')
            if not os.path.exists(filename):
                self.send_error(404, f"Record not found")
                return

            try:
                with open(filename, 'r', encoding='utf-8') as f:
                    content = f.read()

                if filename.endswith('.mjson'):
                    majsoul = self._convert_mjson_to_majsoul(content, uuid)
                    content = json.dumps(majsoul, ensure_ascii=False)

                # Why: 事前計算データは /api/eval-actions 経由の軽量エンドポイントで取得する
                #      ようにしたため、/api/record レスポンスは牌譜データのみを返す。
                self.send_response(200)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(content.encode('utf-8'))
            except Exception as e:
                err_msg = str(e).encode('ascii', 'replace').decode('ascii')
                self.send_error(500, f"API Error: {err_msg}")
        elif path == '/api/eval-actions':
            # Why: 牌譜再生時の表示高速化のため、record_evaluator が保存した事前計算データを
            #      軽量エンドポイントで配信。forwarder.py の重い評価処理を介さない。
            uuid = query.get('uuid', [None])[0]
            if not uuid:
                self.send_response(400)
                self._set_cors_headers()
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"status":"error","message":"Missing uuid"}')
                return
            eval_filepath = os.path.join(_FW_ROOT, 'data', f'record_{uuid}_eval.json')
            actions_map = {}
            grades_map = {}
            meld_map = {}
            if os.path.exists(eval_filepath):
                try:
                    with open(eval_filepath, 'r', encoding='utf-8') as f:
                        eval_data = json.load(f)
                    if isinstance(eval_data, dict):
                        if 'actions' in eval_data:
                            actions_map = eval_data.get('actions') or {}
                            grades_map = eval_data.get('grades') or {}
                            # Why: シミュレーターが forwarder.py の重い /api/evaluate-meld や
                            # /api/evaluate を呼ばないように、副露判断も eval.json から直接配信する。
                            # actions には evaluate_state() のフルレスポンス (立直/九種九牌/四風子連打含む) が入る。
                            meld_map = eval_data.get('precomputed_meld_decisions') or {}
                        else:
                            # 旧構造: フラットな {seat: {grade, ...}} 形式
                            grades_map = eval_data
                except Exception:
                    pass
            payload = json.dumps({
                'status': 'ok',
                'available': bool(actions_map),
                'actions': actions_map,
                'grades': grades_map,
                'precomputed_meld_decisions': meld_map,
            }, ensure_ascii=False)
            self.send_response(200)
            self._set_cors_headers()
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(payload.encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()

    def _convert_mjson_to_majsoul(self, content: str, uuid: str = None) -> dict:
        """
        @title MJAIログから雀魂（Majsoul）形式への変換関数
        @description MJAI形式のJSON Linesデータを、牌譜シミュレーター（simulator.html）が解析可能な雀魂/MajsoulのJSON構造に変換します。
        @param {str} content - MJAI形式のログファイルテキスト
        @param {str} uuid - 牌譜のUUID
        @returns {dict} 変換後のMajsoul形式辞書データ
        """
        def to_majsoul_tile(tile_str):
            if not tile_str or tile_str == '?':
                return tile_str
            
            # 赤ドラの変換
            if tile_str == '5mr': return '0m'
            if tile_str == '5pr': return '0p'
            if tile_str == '5sr': return '0s'
            
            # 字牌の変換
            z_map = {
                'E': '1z', 'S': '2z', 'W': '3z', 'N': '4z',
                'P': '5z', 'F': '6z', 'C': '7z'
            }
            if tile_str in z_map:
                return z_map[tile_str]
                
            return tile_str

        clean_events = []
        names = []
        
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                ev = json.loads(line)
            except Exception:
                continue
                
            t = ev.get('type')
            if not t:
                continue
                
            if t == 'start_game' and 'names' in ev:
                if not names:
                    names = ev['names']
                continue
                
            if t == 'start_kyoku':
                tehais = ev.get('tehais', [])
                
                # 重複チェック
                is_dup = False
                for old_ev in reversed(clean_events):
                    if old_ev['type'] == 'start_kyoku':
                        if old_ev.get('kyoku') == ev.get('kyoku') and old_ev.get('honba') == ev.get('honba'):
                            is_dup = True
                        break
                if is_dup:
                    continue
                
                # 他のプレイヤーの手牌は'?'だが、最初のプレイヤーの手牌は既知
                # '?'を空配列に変換して保存
                cleaned_tehais = []
                for hand in tehais:
                    if '?' in hand:
                        cleaned_tehais.append([])
                    else:
                        cleaned_tehais.append([to_majsoul_tile(tile) for tile in hand])
                
                ev_copy = ev.copy()
                ev_copy['tehais'] = cleaned_tehais
                clean_events.append(ev_copy)
                
            elif t == 'tsumo':
                if ev.get('pai') == '?':
                    continue
                if clean_events and clean_events[-1]['type'] == 'tsumo':
                    if clean_events[-1].get('actor') == ev.get('actor') and clean_events[-1].get('pai') == ev.get('pai'):
                        continue
                clean_events.append(ev)
                
            elif t == 'dahai':
                if clean_events and clean_events[-1]['type'] == 'dahai':
                    if clean_events[-1].get('actor') == ev.get('actor') and clean_events[-1].get('pai') == ev.get('pai'):
                        continue
                clean_events.append(ev)
                
            elif t in ('chi', 'pon', 'daiminkan', 'ankan', 'kakan'):
                if clean_events and clean_events[-1]['type'] == t:
                    if clean_events[-1].get('actor') == ev.get('actor') and clean_events[-1].get('pai') == ev.get('pai') and clean_events[-1].get('consumed') == ev.get('consumed'):
                        continue
                clean_events.append(ev)
                
            elif t == 'reach':
                clean_events.append(ev)
                
            elif t in ('hora', 'ryukyoku'):
                if clean_events and clean_events[-1]['type'] in ('hora', 'ryukyoku'):
                    if 'scores' not in clean_events[-1] and 'scores' in ev:
                        clean_events[-1] = ev
                    continue
                clean_events.append(ev)
                
            elif t == 'end_kyoku':
                clean_events.append(ev)
                
        if not names:
            names = ["Player 0", "Player 1", "Player 2", "Player 3"]
            
        # Why: 四人戦の開始時持ち点として一般的な25000点を使用します。
        current_scores = [25000, 25000, 25000, 25000]
        # Why: 136枚の麻雀牌から配牌52枚と王牌14枚を除いた、初期の山牌枚数である70枚を設定します。
        left_tile_count = 70
        is_reach_declared = [False, False, False, False]
        doras = []
        actions = []
        
        for ev in clean_events:
            t = ev['type']
            if t == 'start_kyoku':
                # Why: 136枚の麻雀牌から配牌52枚と王牌14枚を除いた、初期の山牌枚数である70枚を設定します。
                left_tile_count = 70
                is_reach_declared = [False, False, False, False]
                
                dora_marker = to_majsoul_tile(ev.get('dora_marker'))
                doras = [dora_marker] if dora_marker else []
                
                tehais = ev.get('tehais', [])
                # tehaisは既に cleaned されている（'?'は空配列に変換済み）
                tiles = tehais if tehais and isinstance(tehais[0], list) else [[to_majsoul_tile(tile) for tile in hand] for hand in tehais]
                oya = ev.get('oya', 0)
                
                action = {
                    "result": {
                        "class_name": "RecordNewRound",
                        "data": {
                            "chang": {"E": 0, "S": 1, "W": 2, "N": 3}.get(ev.get('bakaze'), 0),
                            "ju": ev.get('kyoku', 0),
                            "ben": ev.get('honba', 0),
                            "liqibang": ev.get('kyotaku', 0),
                            "leftTileCount": left_tile_count,
                            "doras": doras,
                            "scores": list(current_scores),
                            "tiles0": tiles[0] if len(tiles) > 0 else [],
                            "tiles1": tiles[1] if len(tiles) > 1 else [],
                            "tiles2": tiles[2] if len(tiles) > 2 else [],
                            "tiles3": tiles[3] if len(tiles) > 3 else [],
                            "operation": {"seat": oya}
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'tsumo':
                seat = ev.get('actor')
                tile = to_majsoul_tile(ev.get('pai'))
                left_tile_count -= 1
                
                action = {
                    "result": {
                        "class_name": "RecordDealTile",
                        "data": {
                            "seat": seat,
                            "tile": tile,
                            "leftTileCount": left_tile_count
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'dahai':
                seat = ev.get('actor')
                tile = to_majsoul_tile(ev.get('pai'))
                tsumogiri = ev.get('tsumogiri', False)
                
                is_liqi = is_reach_declared[seat]
                if is_liqi:
                    is_reach_declared[seat] = False
                    
                action = {
                    "result": {
                        "class_name": "RecordDiscardTile",
                        "data": {
                            "seat": seat,
                            "tile": tile,
                            "isLiqi": is_liqi,
                            "moqie": tsumogiri
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'reach':
                seat = ev.get('actor')
                is_reach_declared[seat] = True
                
            elif t in ('chi', 'pon', 'daiminkan'):
                seat = ev.get('actor')
                pai = to_majsoul_tile(ev.get('pai'))
                consumed = [to_majsoul_tile(c) for c in ev.get('consumed', [])]
                target = ev.get('target')
                
                tiles_list = consumed + [pai]
                froms_list = [seat] * len(consumed) + [target]
                
                action = {
                    "result": {
                        "class_name": "RecordChiPengGang",
                        "data": {
                            "seat": seat,
                            "tiles": tiles_list,
                            "froms": froms_list,
                            # Why: 2は明槓を表し、0はチー・ポンを表します。
                            "type": 2 if t == 'daiminkan' else 0
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'ankan':
                seat = ev.get('actor')
                consumed = [to_majsoul_tile(c) for c in ev.get('consumed', [])]
                tile = consumed[0] if consumed else ""
                
                action = {
                    "result": {
                        "class_name": "RecordAnGangAddGang",
                        "data": {
                            "seat": seat,
                            "tiles": tile,
                            # Why: 3は暗槓アクションを表す数値です。
                            "type": 3
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'kakan':
                seat = ev.get('actor')
                tile = to_majsoul_tile(ev.get('pai'))
                
                action = {
                    "result": {
                        "class_name": "RecordAnGangAddGang",
                        "data": {
                            "seat": seat,
                            "tiles": tile,
                            # Why: 0は加槓アクションを表す数値です。
                            "type": 0
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'hora':
                if 'scores' in ev:
                    current_scores = ev['scores']
                    
                action = {
                    "result": {
                        "class_name": "RecordHule",
                        "data": {
                            "scores": list(current_scores)
                        }
                    }
                }
                actions.append(action)
                
            elif t == 'ryukyoku':
                if 'scores' in ev:
                    current_scores = ev['scores']
                    
                action = {
                    "result": {
                        "class_name": "RecordNoTile",
                        "data": {
                            "scores": list(current_scores)
                        }
                    }
                }
                actions.append(action)

        accounts = [{"seat": i, "nickname": name} for i, name in enumerate(names)]
        players_result = [{"seat": i, "partPoint1": current_scores[i]} for i in range(len(names))]

        # ファイル更新日などをタイムスタンプフォールバックとして取得
        file_mtime = 0
        if uuid:
            mjson_path = os.path.join(_FW_ROOT, 'logs', f'{uuid}.mjson')
            if os.path.exists(mjson_path):
                file_mtime = int(os.path.getmtime(mjson_path))

        majsoul_data = {
            "head": {
                "uuid": uuid or "mjson_converted_game",
                "startTime": file_mtime,
                "config": {
                    # Why: 2は四人戦を示す雀魂の対局カテゴリコードです。
                    "category": 2
                },
                "accounts": accounts,
                "result": {
                    "players": players_result
                }
            },
            "detail_records": {
                "actions": actions
            },
            "decoded_rounds": []
        }
        return majsoul_data

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

    def _handle_evaluate_meld(self, post_data: bytes):
        try:
            payload = json.loads(post_data.decode('utf-8'))
        except Exception as e:
            self._send_json({"status": "error", "message": f"Invalid JSON: {e}"}, status=400)
            return
        try:
            result = evaluate_meld(payload)
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
        if self.path == '/api/restart':
            self._send_json({"status": "ok", "message": "Restarting server..."})
            self.wfile.flush()
            import time
            import shutil

            # __pycache__を削除して古いキャッシュを無効化
            for root, dirs, files in os.walk(_FW_ROOT):
                for d in dirs:
                    if d == '__pycache__':
                        shutil.rmtree(os.path.join(root, d), ignore_errors=True)

            # Why: PyInstaller で exe 化した場合の再起動ロジック。
            # 新プロセスを別 stdout/stderr で spawn して、旧プロセスのファイルロックを回避。
            if getattr(sys, 'frozen', False):
                cmd = [sys.executable]
            else:
                cmd = [sys.executable, os.path.abspath(__file__)]

            try:
                # 旧プロセスから完全に独立した新プロセスを起動
                # Why: DETACHED_PROCESS を指定しないと新プロセスがコンソールを
                # 共有できず、PyInstaller の展開に失敗する。
                DETACHED_PROCESS = 0x00000008

                # デバッグ用: 新プロセスの stdout/stderr を別ファイルに
                restart_log_dir = os.path.join(os.path.dirname(_FW_ROOT), 'logs')
                os.makedirs(restart_log_dir, exist_ok=True)
                new_stdout = open(os.path.join(restart_log_dir, 'restart_stdout.log'), 'wb')
                new_stderr = open(os.path.join(restart_log_dir, 'restart_stderr.log'), 'wb')

                # 環境変数で再起動を通知 (新プロセスはブラウザを開かない)
                env = os.environ.copy()
                env['COACH_RESTARTED'] = '1'

                subprocess.Popen(
                    cmd,
                    cwd=os.path.dirname(os.path.abspath(__file__)),
                    creationflags=DETACHED_PROCESS,
                    env=env,
                    stdout=new_stdout,
                    stderr=new_stderr,
                )
            except Exception as e:
                sys.stderr.write(f"[restart] Failed to spawn: {e}\n")
                sys.stderr.flush()

            time.sleep(1.0)
            os._exit(0)
        if self.path == '/api/evaluate':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            self._handle_evaluate(post_data)
            return
        if self.path == '/api/evaluate-meld':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length) if content_length > 0 else b'{}'
            self._handle_evaluate_meld(post_data)
            return
        if self.path == '/packet':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)

            # Why: テストパケットは長さが可変なので、先頭バイトで識別。
            payload = json.loads(post_data.decode('utf-8'))
            from_client = payload.get('from_client', False)
            base64_data = payload.get('data', '')
            raw_bytes = base64.b64decode(base64_data)

            # Why: Majsoul の heartbeat (7 byte) と Tampermonkey テストパケットは
            # 牌譜データではないのでログから除外。ログを埋め尽くさないため。
            if not from_client and len(raw_bytes) < 32:
                # heartbeat を 200 OK で応答だけ返して捨てる
                self.send_response(200)
                self._set_cors_headers()
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"status": "heartbeat_skipped"}')
                return

            # 大きなパケットだけログ出力
            print(f"\n[PACKET RX] /packet received, Content-Length={content_length}, from_client={from_client}, raw_len={len(raw_bytes)}", flush=True)
            try:
                flow_msg = FlowMsgMock(raw_bytes, from_client)
                
                try:
                    result = liqi_parser.parse(flow_msg)

                    direction = "[C->S]" if from_client else "[S->C]"
                    print(f"\n{direction} (ID: {result.get('id')})")
                    print(f"Method: {result.get('method')}")
                    print(f"Data: {json.dumps(result.get('data'), ensure_ascii=False, indent=2)}")
                    print("-" * 80)

                    msg_type_str = str(result.get('type'))
                    method_name = result.get('method', '')
                    # Why: プロフィール確認パケットの形式を確認するためのデバッグ用ダンプ
                    if 'Statistic' in method_name or 'Player' in method_name:
                        debug_log_path = os.path.join(_FW_ROOT, 'logs', 'debug_stats_packet.json')
                        os.makedirs(os.path.dirname(debug_log_path), exist_ok=True)
                        with open(debug_log_path, 'w', encoding='utf-8') as df:
                            json.dump(result, df, ensure_ascii=False, indent=2)
                        print(f"\n[DEBUG] Captured player/statistic packet: {method_name}. Saved to logs/debug_stats_packet.json")

                    if result.get('method') == '.lq.Lobby.fetchGameRecord' and ('Res' in msg_type_str or '3' in msg_type_str):
                        save_game_record(result.get('data'))
                    # 牌譜データを含む他のメソッドもフォールバック
                    elif 'GameRecord' in method_name and 'Res' in msg_type_str:
                        save_game_record(result.get('data'))

                except AssertionError:
                    print(f"[Warning] Packet decode failed (out-of-order or missing init). Length: {len(raw_bytes)} bytes")

                    # フォールバック: 牌譜データを含む可能性のあるレスポンスを強制デコード
                    # Why: 初期パケットが欠落していても牌譜レスポンス (Type 3 / Res) 単体で
                    # デコードできる場合がある。牌譜データは通常 1000 バイト以上。
                    if not from_client and len(raw_bytes) > 1000:
                        _try_decode_record_fallback(raw_bytes)

                except Exception as parse_error:
                    print(f"[Warning] Packet parse error: {parse_error}")

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

def run(server_class=ThreadingHTTPServer, handler_class=PacketHandler, port=8080):
    """
    @title サーバー起動関数
    @description HTTPサーバーを指定されたポートで待機起動します。/api/restart POSTを受けると完全なプロセス再起動を行います。
    @param {type} server_class - HTTPServer クラス (シングルスレッド)
    @param {type} handler_class - 処理用のハンドラークラス
    @param {int} port - サーバー待機ポート (デフォルト: 8080)
    """
    server_address = ('', port)
    print(f"Creating server on port {port}...", flush=True)
    # Why: ソケットオプション SO_REUSEADDR を有効化。
    # PyInstaller で exe 化した再起動時に、旧プロセスのソケットが TIME_WAIT 状態でも
    # 新プロセスが同じポートにバインドできるようにする。
    # これがないと再起動後に 500 エラー (templates が見つからない) が発生する。
    HTTPServer.allow_reuse_address = True
    httpd = server_class(server_address, handler_class)
    # ハードコードされた数値 8080 は、ローカル開発サーバー用ポートとして一般的で重複を避けるために選定されたものです。
    print(f"Starting server on port {port}...", flush=True)

    # Why: 初回起動時にブラウザを自動で開く。
    # ただし /api/restart による再起動では開かない (ユーザーは既に開いているため)。
    # 再起動かどうかは環境変数 COACH_RESTARTED で判別。
    # Why: スレッド化は socket 競合や race condition を引き起こすため廃止。
    # 代わりに serve_forever の直前でブラウザを開く。
    if os.environ.get('COACH_RESTARTED') != '1':
        url = f"http://localhost:{port}/"
        # ブラウザは別プロセスで起動 (webbrowser.open はノンブロッキング)
        try:
            webbrowser.open(url)
            print(f"Browser opened: {url}", flush=True)
        except Exception as e:
            print(f"[Warning] Failed to open browser: {e}", flush=True)

    print(f"Calling serve_forever...", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping server...")
    finally:
        httpd.server_close()

if __name__ == '__main__':
    run()
