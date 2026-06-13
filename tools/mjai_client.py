# -*- coding: utf-8 -*-
"""MJAI TCP client - uses system.exe pipe for decisions."""
from __future__ import annotations
import json
import os
import socket
import subprocess
import sys
import threading
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

HONOR_MAP = {'1z': 'E', '2z': 'S', '3z': 'W', '4z': 'N',
             '5z': 'P', '6z': 'F', '7z': 'C'}
RED5_MAP = {'0m': '5mr', '0p': '5pr', '0s': '5sr'}
REV_HONOR = {v: k for k, v in HONOR_MAP.items()}
REV_RED5 = {v: k for k, v in RED5_MAP.items()}
AKOCHAN_IMG = 'akochan-docker-app'
AKOCHAN_NAME = 'akochan_srv'
SETUP_JSON = '/opt/akochan/setup_mjai.json'
SYSTEM_EXE = '/opt/akochan/system.exe'

_pipe_lock = threading.Lock()


def _to_mjai(tile: str) -> str:
    return RED5_MAP.get(tile, HONOR_MAP.get(tile, tile))


def _to_us(tile: str) -> str:
    """
    @title MJAI牌から内部牌表記への変換
    @description MJAIで用いられる牌表記（5mr, Eなど）を自作AI内部の牌表記（0m, 1zなど）に変換します。
    @param {str} tile - MJAI形式の牌表記
    @returns {str} 内部形式の牌表記
    """
    # 自作AIは内部で0mや1zなどの牌表記を使用しているため、MJAIの5mrやEから逆変換する必要があります。
    return REV_HONOR.get(tile, REV_RED5.get(tile, tile))



def _call_pipe(events: List[dict], seat: int, container_name: str = AKOCHAN_NAME) -> Optional[List[dict]]:
    """
    @title akochanのパイプ呼び出し
    @description 指定されたコンテナ内のsystem.exeを実行し、現在の局面情報から意思決定を取得します。
    @param {List[dict]} events - これまでのMJAIゲームイベント履歴
    @param {int} seat - 起家から数えたプレイヤーの座順ID
    @param {str} container_name - 対象 of Dockerコンテナ名
    @returns {Optional[List[dict]]} system.exeが出力した意思決定イベント配列、またはNone
    """
    input_str = '\n'.join(json.dumps(e, ensure_ascii=False) for e in events)
    with _pipe_lock:
        try:
            # 30 は思考処理が詰まったと判断するタイムアウト時間(秒)です。
            r = subprocess.run(
                ['docker', 'exec', '-i', container_name, SYSTEM_EXE,
                 'pipe', SETUP_JSON, str(seat)],
                input=input_str, capture_output=True, text=True, timeout=30
            )
        except subprocess.TimeoutExpired:
            print(f"akochan timeout expired on seat {seat}", file=sys.stderr)
            return None
    if r.returncode != 0:
        print(f"akochan process error (code {r.returncode}) on seat {seat}:\n{r.stderr}", file=sys.stderr)
        return None
    if not r.stdout.strip():
        return None
    lines = [l.strip() for l in r.stdout.split('\n') if l.strip()]
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


def _build_pipe_events(record: List[dict], my_id: int, extra_dahai: dict = None) -> List[dict]:
    events = []
    events.append({"type": "start_game", "kyoku_first": 4, "aka_flag": True})
    for m in record:
        mt = m.get("type")
        if mt == "start_game":
            continue
        if mt == "start_kyoku":
            new_tehais = []
            for i in range(4):
                if i == my_id:
                    new_tehais.append([_to_mjai(t) for t in m["tehais"][i]])
                else:
                    new_tehais.append(["?"] * len(m["tehais"][i]))
            events.append({
                "type": "start_kyoku", "bakaze": m.get("bakaze", "E"),
                "kyoku": m.get("kyoku", 1), "honba": m.get("honba", 0),
                "kyotaku": m.get("kyotaku", 0), "oya": m.get("oya", 0),
                "dora_marker": m.get("dora_marker", "1m"),
                "tehais": new_tehais, "scores": m.get("scores", [25000]*4),
            })
        elif mt == "tsumo":
            events.append({"type": "tsumo", "actor": m["actor"],
                           "pai": _to_mjai(m["pai"]) if m.get("actor") == my_id else "?"})
        elif mt == "dahai":
            events.append({"type": "dahai", "actor": m["actor"],
                           "pai": m["pai"], "tsumogiri": m.get("tsumogiri", False)})
        elif mt in ("reach", "reach_accepted"):
            events.append({"type": mt, "actor": m["actor"]})
        elif mt in ("pon", "chi", "daiminkan", "ankan", "kakan"):
            ev = {"type": mt, "actor": m["actor"]}
            if "target" in m: ev["target"] = m["target"]
            if "pai" in m: ev["pai"] = m["pai"]
            if "consumed" in m: ev["consumed"] = m["consumed"]
            events.append(ev)
        elif mt == "dora":
            events.append({"type": "dora", "dora_marker": m["dora_marker"]})
    if extra_dahai:
        events.append(extra_dahai)
    return events


class MjaiPipeClient:
    """MJAI client using system.exe pipe for decisions."""

    def __init__(self, host: str, port: int, room: str, name: str, container_name: str = AKOCHAN_NAME):
        """
        @title MjaiPipeClientの初期化
        @description MJAIサーバーとTCP接続し、指定されたDockerコンテナを介して打牌決定を行うクライアントを作成します。
        @param {str} host - MJAIサーバーのホスト名またはIP
        @param {int} port - MJAIサーバーのポート番号
        @param {str} room - 接続するルーム名
        @param {str} name - プレイヤー名
        @param {str} container_name - このプレイヤーが使用するDockerコンテナ名
        """
        self.name = name
        self.container_name = container_name
        self.player_id = -1
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))
        self._buf = b''
        self._record: List[dict] = []
        self._id = -1
        self._pending_reach_dahai: Optional[dict] = None  # リーチ後の打牌を一時退避させるための変数

        hello = self._recv()
        assert hello.get("type") == "hello"
        self._send({"type": "join", "name": name, "room": room})

    def _send(self, msg: dict):
        if "actor" not in msg:
            msg["actor"] = self._id
        self._sock.sendall((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))

    def _recv(self) -> dict:
        while b'\n' not in self._buf:
            # 4096 はソケットから一度に読み出す最大バッファサイズです。
            self._buf += self._sock.recv(4096)
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))

    def _query_pipe(self, extra_dahai: dict = None) -> Optional[List[dict]]:
        events = _build_pipe_events(self._record, self._id, extra_dahai)
        # CPU競合を回避するため、自分に割り当てられたコンテナを指定して呼び出します。
        return _call_pipe(events, self._id, self.container_name)

    def play_game(self):
        while True:
            try:
                msg = self._recv()
            except Exception:
                break
            t = msg.get("type")
            try:
                self._handle(t, msg)
            except StopIteration:
                break
            except Exception as ex:
                print(f"Error handling message {t}: {ex}", file=sys.stderr)
                # ツモ時やロン選択時に不正な 'none' を送信して対局がフリーズするのを防ぐため、
                # トップレベルでキャッチした例外はログを出して終了する（切断）ようにします。
                break

    def _handle(self, t: str, msg: dict):
        if t == "start_game":
            self._id = msg.get("id", self.player_id)
            self._record = [msg]
            self._send({"type": "none", "actor": self._id})

        elif t == "start_kyoku":
            self._record.append(msg)
            self._send({"type": "none", "actor": self._id})

        elif t == "tsumo":
            self._record.append(msg)
            if msg.get("actor") == self._id:
                decs = None
                try:
                    decs = self._query_pipe()
                    dec = decs[0] if decs else None
                except Exception as ex:
                    print(f"Error querying pipe on tsumo: {ex}", file=sys.stderr)
                    dec = None

                # タイムアウト等でakochanから指示が得られなかった場合は、安全にツモ切り（tsumogiri=True）を行います。
                if not dec:
                    dec = {"type": "dahai", "pai": msg["pai"], "tsumogiri": True}

                # 意思決定が立直の場合、2枚目の要素（打牌）を取り出して保持します（手出し立直を可能にするため）。
                if dec.get("type") == "reach":
                    if decs and len(decs) > 1 and decs[1].get("type") == "dahai":
                        self._pending_reach_dahai = decs[1]
                    else:
                        self._pending_reach_dahai = None

                self._send(dec)
            else:
                self._send({"type": "none", "actor": self._id})

        elif t in ("dahai", "reach", "pon", "chi"):
            self._record.append(msg)
            if t == "reach" and msg.get("actor") == self._id:
                # 保留していた立直用打牌データがあればそれを送信します。
                if self._pending_reach_dahai:
                    self._send(self._pending_reach_dahai)
                    self._pending_reach_dahai = None
                else:
                    # 退避データがない場合の安全なフォールバックとして、最後のツモ牌でのツモ切り立直を行います。
                    last_tsumo = None
                    for m in reversed(self._record):
                        if m.get("type") == "tsumo" and m.get("actor") == self._id:
                            last_tsumo = m["pai"]
                            break
                    # "1m" は最後のツモ牌の検出に失敗した場合の最終フォールバック牌です。
                    self._send({"type": "dahai", "actor": self._id,
                                "pai": last_tsumo or "1m", "tsumogiri": True})

            elif t in ("pon", "chi") and msg.get("actor") == self._id:
                try:
                    decs = self._query_pipe()
                    dec = decs[0] if decs else None
                except Exception as ex:
                    print(f"Error querying pipe on pon/chi: {ex}", file=sys.stderr)
                    dec = None

                pai = dec.get("pai") if dec and dec.get("type") == "dahai" else None
                if pai:
                    self._send({"type": "dahai", "actor": self._id,
                                "pai": pai, "tsumogiri": False})
                else:
                    # "1m" は鳴き直後の打牌情報の取得に失敗した場合の安全なフォールバック用です（他になければ1mを切ります）。
                    self._send({"type": "dahai", "actor": self._id,
                                "pai": "1m", "tsumogiri": False})

            elif t == "dahai" and msg.get("actor") != self._id and \
                    msg.get("possible_actions", []):
                try:
                    decs = self._query_pipe(extra_dahai={
                        "type": "dahai", "actor": msg["actor"],
                        "pai": msg["pai"], "tsumogiri": msg.get("tsumogiri", False)
                    })
                    dec = decs[0] if decs else None
                except Exception as ex:
                    print(f"Error querying pipe on opponent dahai: {ex}", file=sys.stderr)
                    dec = None

                if dec and dec.get("type") in ("hora", "pon", "chi", "daiminkan"):
                    self._send(dec)
                else:
                    self._send({"type": "none", "actor": self._id})
            else:
                self._send({"type": "none", "actor": self._id})

        elif t in ("daiminkan", "ankan", "kakan",
                    "reach_accepted", "dora", "hora", "ryukyoku", "end_kyoku"):
            self._record.append(msg)
            self._send({"type": "none", "actor": self._id})

        elif t == "end_game":
            self._send({"type": "none", "actor": self._id})
            raise StopIteration

        elif t == "error":
            print(f"Server: {msg.get('message', '')}", file=sys.stderr)
            self._send({"type": "none", "actor": self._id})
        else:
            self._send({"type": "none", "actor": self._id})

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass


class OurMjaiClient:
    """自作AI (Evaluator/AIPlayer) をMJAIサーバーに接続させてプレイさせるためのクライアント。"""

    def __init__(self, host: str, port: int, room: str, name: str, params: dict):
        """
        @title OurMjaiClientの初期化
        @description 自作AIオブジェクトを準備し、MJAIサーバーにTCP接続します。
        @param {str} host - MJAIサーバーのIPまたはホスト
        @param {int} port - MJAIサーバーのポート番号
        @param {str} room - ルーム名
        @param {str} name - プレイヤー名
        @param {dict} params - 自作AIの重みパラメータ辞書
        """
        self.name = name
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))
        self._buf = b''
        self._id = -1
        
        # 自作AIのゲーム状態管理オブジェクトをロード
        from core.game_state import GameState
        from core.ai_player import AIPlayer
        from core.evaluator import Evaluator
        
        self.state = GameState()
        self.ai = AIPlayer(name, Evaluator, params)
        self._last_tsumo_mjai = None


        hello = self._recv()
        assert hello.get("type") == "hello"
        self._send({"type": "join", "name": name, "room": room})

    def _send(self, msg: dict):
        if "actor" not in msg:
            msg["actor"] = self._id
        self._sock.sendall((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))

    def _recv(self) -> dict:
        while b'\n' not in self._buf:
            # 4096 はソケット受信用の最大バッファサイズです。
            data = self._sock.recv(4096)
            if not data:
                raise ConnectionError("Socket closed by remote host")
            self._buf += data
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))

    def close(self):
        """ソケットを安全に閉じます。"""
        try:
            self._sock.close()
        except Exception:
            pass

    def play_game(self):
        """MJAIサーバーからの受信ループを実行します。"""
        while True:
            try:
                msg = self._recv()
            except Exception:
                break
            t = msg.get("type")
            try:
                self._handle(t, msg)
            except StopIteration:
                break
            except Exception as ex:
                print(f"Error handling message {t}: {ex}", file=sys.stderr)
                # ルール違反のnoneを送信してハングするのを防ぐため、例外時は終了します。
                break

    def _handle(self, t: str, msg: dict):
        if t == "start_game":
            self._id = msg.get("id", -1)
            self.state.my_seat = self._id
            self._send({"type": "none"})

        elif t == "start_kyoku":
            tehais = msg["tehais"]
            my_hand_mjai = tehais[self._id]
            # MJAI形式から内部形式（0m, 1zなど）に変換してゲーム状態に渡します。
            my_hand_us = [_to_us(t) for t in my_hand_mjai]
            # 25000 はMJAIサーバーおよび一般的な麻雀における初期持ち点のデフォルト値です。
            scores = msg.get("scores", [25000] * 4)
            
            dora_mjai = msg.get("dora_marker", "1m")
            dora_us = _to_us(dora_mjai)

            kyoku = msg.get("kyoku", 1)
            # ju (局数) と chang (場風) の算出
            ju = (kyoku - 1) % 4
            chang = (kyoku - 1) // 4
            ben = msg.get("honba", 0)
            liqibang = msg.get("kyotaku", 0)

            # 70 は新局開始時の標準的な山牌残り枚数です。
            self.state.on_new_round(
                chang=chang, ju=ju, ben=ben, liqibang=liqibang,
                tiles=my_hand_us, scores=scores, left_tile_count=70, doras=[dora_us]
            )
            self.state.dealer_seat = msg.get("oya", 0)
            self._send({"type": "none"})

        elif t == "tsumo":
            actor = msg["actor"]
            pai_mjai = msg.get("pai", "?")
            
            if actor == self._id:
                self._last_tsumo_mjai = pai_mjai
                pai_us = _to_us(pai_mjai)
                self.state.on_self_draw(pai_us)
                
                # 立直後はツモアガリまたはルール上可能な暗カン（ankan）のみを判定し、それ以外はツモ切りを強制します。
                if self.state.reach_states[self._id].is_reach:
                    has_hora = False
                    for act in msg.get("possible_actions", []):
                        if act.get("type") == "hora":
                            has_hora = True
                    if has_hora and self.ai.should_tsumo(self.state):
                        self._send({"type": "hora", "target": actor, "pai": pai_mjai})
                        return

                    # 立直後でも送り暗カン等でなければ、サーバーから可能なアクションとして ankan が送られます。
                    can_ankan = False
                    ankan_action = None
                    for act in msg.get("possible_actions", []):
                        if act.get("type") == "ankan":
                            can_ankan = True
                            ankan_action = act
                    if can_ankan and self.ai.should_kan(self.state):
                        self._send(ankan_action)
                        return

                    self._send({"type": "dahai", "pai": pai_mjai, "tsumogiri": True})
                    return


                
                # 1. ツモアガリの判定
                has_hora = False
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "hora":
                        has_hora = True
                if has_hora and self.ai.should_tsumo(self.state):
                    self._send({"type": "hora", "target": actor, "pai": pai_mjai})
                    return

                # 2. カン (暗カン・加カン) の判定
                can_kan = False
                kan_action = None
                for act in msg.get("possible_actions", []):
                    if act.get("type") in ("ankan", "kakan"):
                        can_kan = True
                        kan_action = act
                if can_kan and self.ai.should_kan(self.state):
                    self._send(kan_action)
                    return

                # 3. リーチの判定
                can_reach = False
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "reach":
                        can_reach = True
                if can_reach and self.ai.should_riichi(self.state):
                    self._send({"type": "reach"})
                    return

                # 4. 通常の打牌の決定
                discard_us = self.ai.decide_discard(self.state)
                # フォールバックとして、手牌に無いかエラーになった場合はツモ牌を切ります。
                if not discard_us or discard_us not in self.state.my_hand:
                    discard_us = _to_us(pai_mjai)
                
                discard_mjai = _to_mjai(discard_us)
                tsumogiri = (discard_us == _to_us(pai_mjai))
                self._send({"type": "dahai", "pai": discard_mjai, "tsumogiri": tsumogiri})
            else:
                self.state.on_opponent_draw(actor)
                self._send({"type": "none"})

        elif t == "dahai":
            actor = msg["actor"]
            pai_mjai = msg["pai"]
            pai_us = _to_us(pai_mjai)
            tsumogiri = msg.get("tsumogiri", False)
            
            # リーチ宣言直後の打牌であれば、リーチ状態を確定させます
            is_liqi = self.state.reach_states[actor].is_reach and len(self.state.river[actor]) == self.state.reach_states[actor].reach_turn
            self.state.on_discard(actor, pai_us, isLiqi=is_liqi, moqie=tsumogiri)

            if actor != self._id:
                # 1. ロンアガリの判定
                has_hora = False
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "hora":
                        has_hora = True
                if has_hora and self.ai.should_ron(self.state):
                    self._send({"type": "hora", "target": actor, "pai": pai_mjai})
                    return

                # 2. ポン・チー・大明槓の判定
                possible = msg.get("possible_actions", [])
                best_meld = None
                for act in possible:
                    act_type = act.get("type")
                    if act_type in ("pon", "chi", "daiminkan"):
                        # 0=チー, 1=ポン, 2=大明槓
                        call_type_map = {"chi": 0, "pon": 1, "daiminkan": 2}
                        call_type = call_type_map[act_type]
                        consumed_mjai = act.get("consumed", [])
                        consumed_us = [_to_us(c) for c in consumed_mjai]
                        tiles_us = [pai_us] + consumed_us
                        
                        if self.ai.should_call_meld(self.state, call_type, tiles_us, actor):
                            best_meld = act
                            break
                if best_meld:
                    self._send(best_meld)
                    return

                self._send({"type": "none"})
            else:
                self._send({"type": "none"})

        elif t == "reach":
            actor = msg["actor"]
            self.state.reach_states[actor].is_reach = True
            self.state.reach_states[actor].reach_turn = len(self.state.river[actor])
            
            if actor == self._id:
                cannot_dahai_mjai = msg.get("cannot_dahai", [])
                cannot_dahai_us = [_to_us(p) for p in cannot_dahai_mjai]
                
                discard_us = self.ai.choose_riichi_discard(self.state)
                
                # AIの思考結果が手牌にない場合や、ノーテンリーチ等のルール違反（cannot_dahaiに含まれる）の場合は、手牌から有効な候補を自動選択します。
                if not discard_us or discard_us not in self.state.my_hand or discard_us in cannot_dahai_us:
                    valid_discards = [t for t in self.state.my_hand if t not in cannot_dahai_us]
                    if valid_discards:
                        # 直前のツモ牌が有効候補にあればツモ切りを優先し、そうでなければ候補の最初の牌を選択します。
                        last_tsumo_us = _to_us(self._last_tsumo_mjai) if self._last_tsumo_mjai else None
                        if last_tsumo_us in valid_discards:
                            discard_us = last_tsumo_us
                        else:
                            discard_us = valid_discards[0]
                    else:
                        # 万が一有効な選択肢が1つもない場合は、手牌の最後の牌を最終フォールバックとします。
                        discard_us = self.state.my_hand[-1]

                discard_mjai = _to_mjai(discard_us)
                
                # リーチ宣言直後の打牌が、直前のツモ牌と同一である場合はツモ切り（tsumogiri: true）と判定します。
                tsumogiri = (discard_us == _to_us(self._last_tsumo_mjai)) if self._last_tsumo_mjai else False
                self._send({"type": "dahai", "pai": discard_mjai, "tsumogiri": tsumogiri})
            else:

                self._send({"type": "none"})

        elif t == "reach_accepted":
            actor = msg["actor"]
            self.state.reach_states[actor].is_reach = True
            if "scores" in msg:
                self.state.scores = msg["scores"]
            self._send({"type": "none"})

        elif t in ("pon", "chi", "daiminkan"):
            actor = msg["actor"]
            target = msg["target"]
            pai_mjai = msg["pai"]
            consumed_mjai = msg["consumed"]
            
            type_map = {"chi": 0, "pon": 1, "daiminkan": 2}
            type_ = type_map[t]
            
            tiles_us = [_to_us(pai_mjai)] + [_to_us(c) for c in consumed_mjai]
            froms = [target] + [actor] * len(consumed_mjai)
            tile_states = [0] * len(tiles_us)
            
            self.state.on_chi_peng_gang(type_, actor, tiles_us, froms, tile_states)
            
            # 自分が鳴いた場合、手牌から1枚切る必要があります
            if actor == self._id:
                discard_us = self.ai.decide_discard(self.state)
                if not discard_us or discard_us not in self.state.my_hand:
                    discard_us = self.state.my_hand[-1]
                discard_mjai = _to_mjai(discard_us)
                self._send({"type": "dahai", "pai": discard_mjai, "tsumogiri": False})
            else:
                self._send({"type": "none"})

        elif t in ("ankan", "kakan"):
            actor = msg["actor"]
            consumed_mjai = msg["consumed"]
            consumed_us = [_to_us(c) for c in consumed_mjai]
            
            type_ = 3 if t == "ankan" else 2  # 3=暗槓, 2=加槓
            self.state.on_an_gang_add_gang(type_, actor, consumed_us[0])
            self._send({"type": "none"})

        elif t == "dora":
            dora_mjai = msg["dora_marker"]
            self.state.on_new_dora(_to_us(dora_mjai))
            self._send({"type": "none"})

        elif t in ("hora", "ryukyoku", "end_kyoku"):
            self._send({"type": "none"})

        elif t == "end_game":
            self._send({"type": "none"})
            raise StopIteration
        else:
            self._send({"type": "none"})
