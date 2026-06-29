# -*- coding: utf-8 -*-
"""
@title MJAI TCP client (ver.2 評価器対応)
@description ver.2 評価器 (EvaluatorV2) を使って MJAI サーバーと対戦する。
              既存 mjai_client.py と並列稼働可能、デバッグや A/B テスト用。
              ver.2 の新機能: 戦略モード表示、手牌構造コーチング。
"""
from __future__ import annotations
import json
import os
import socket
import sys
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

# 既存 mjai_client.py の変換ロジックを再利用
from tools.mjai_client import _to_mjai, _to_us, AKOCHAN_NAME, AKOCHAN_IMG


class OurMjaiClientV2:
    """ver.2 評価器 (EvaluatorV2) を使った MJAI クライアント。"""

    def __init__(self, host: str, port: int, room: str, name: str, params: dict = None,
                 show_coaching: bool = True):
        """
        @title OurMjaiClientV2 初期化
        @param {str} host - MJAI サーバー
        @param {int} port - ポート
        @param {str} room - ルーム名
        @param {str} name - プレイヤー名
        @param {dict} params - 評価器パラメータ (None なら ver.2 デフォルト)
        @param {bool} show_coaching - 各打牌のコーチングを表示するか
        """
        self.name = name
        self.params = params or {}
        self.show_coaching = show_coaching
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))
        self._buf = b''
        self._id = -1
        self._last_tsumo = None
        self._step_count = 0

        from core.game_state import GameState
        from core.evaluator_v2 import EvaluatorV2

        self.state = GameState()
        self.params.setdefault('evaluator', 'v2')
        # 評価器は打牌ごとに作る (状態変化を反映)
        self._evaluator_factory = lambda s: EvaluatorV2(s, self.params)

        hello = self._recv()
        assert hello.get("type") == "hello", f"unexpected hello: {hello}"
        self._send({"type": "join", "name": name, "room": room})

    def _send(self, msg: dict):
        if "actor" not in msg:
            msg["actor"] = self._id
        self._sock.sendall((json.dumps(msg, ensure_ascii=False) + '\n').encode('utf-8'))

    def _recv(self) -> dict:
        while b'\n' not in self._buf:
            data = self._sock.recv(4096)
            if not data:
                raise ConnectionError("Socket closed by remote host")
            self._buf += data
        line, self._buf = self._buf.split(b'\n', 1)
        return json.loads(line.decode('utf-8'))

    def close(self):
        try:
            self._sock.close()
        except Exception:
            pass

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
                break

    def _handle(self, t: str, msg: dict):
        self._step_count += 1
        if t == "start_game":
            self._id = msg.get("id", -1)
            self.state.my_seat = self._id
            self._send({"type": "none"})

        elif t == "start_kyoku":
            tehais = msg["tehais"]
            my_hand_mjai = tehais[self._id]
            my_hand_us = [_to_us(t) for t in my_hand_mjai]
            scores = msg.get("scores", [25000] * 4)
            dora_mjai = msg.get("dora_marker", "1m")
            dora_us = _to_us(dora_mjai)
            kyoku = msg.get("kyoku", 1)
            ju = (kyoku - 1) % 4
            chang = (kyoku - 1) // 4
            ben = msg.get("honba", 0)
            liqibang = msg.get("kyotaku", 0)

            self.state.on_new_round(
                chang=chang, ju=ju, ben=ben, liqibang=liqibang,
                tiles=my_hand_us, scores=scores, left_tile_count=70, doras=[dora_us]
            )
            self.state.dealer_seat = msg.get("oya", 0)
            print(f"\n[ver.2] === {chang}場{ju+1}局 (本場 {ben}) ===")
            print(f"  手牌: {my_hand_us} ドラ表示: {dora_us}")
            self._send({"type": "none"})

        elif t == "tsumo":
            actor = msg["actor"]
            pai_mjai = msg.get("pai", "?")
            if actor == self._id:
                self._last_tsumo = pai_mjai
                pai_us = _to_us(pai_mjai)
                self.state.on_self_draw(pai_us)
                self._decide_self_tsumo(pai_mjai, msg)
            else:
                self.state.on_opponent_draw(actor)
                self._send({"type": "none"})

        elif t == "dahai":
            actor = msg["actor"]
            pai_mjai = msg["pai"]
            pai_us = _to_us(pai_mjai)
            tsumogiri = msg.get("tsumogiri", False)
            is_liqi = self.state.reach_states[actor].is_reach and len(self.state.river[actor]) == self.state.reach_states[actor].reach_turn
            self.state.on_discard(actor, pai_us, isLiqi=is_liqi, moqie=tsumogiri)
            if actor != self._id:
                self._decide_response(pai_mjai, msg, actor)
            else:
                self._send({"type": "none"})

        elif t == "reach":
            actor = msg["actor"]
            if actor != self._id:
                self.state.on_opponent_reach(actor)
            self._send({"type": "none"})

        elif t == "pon":
            actor = msg["actor"]
            consumed = [_to_us(t) for t in msg.get("consumed", [])]
            target = _to_us(msg.get("target", "1m"))
            self.state.on_opponent_meld(actor, 'pon', target, consumed)
            self._send({"type": "none"})

        elif t == "chi":
            actor = msg["actor"]
            consumed = [_to_us(t) for t in msg.get("consumed", [])]
            target = _to_us(msg.get("target", "1m"))
            self.state.on_opponent_meld(actor, 'chi', target, consumed)
            self._send({"type": "none"})

        elif t == "daiminkan" or t == "ankan" or t == "kakan":
            actor = msg["actor"]
            consumed = [_to_us(t) for t in msg.get("consumed", [])]
            target = _to_us(msg.get("target", "1m"))
            self.state.on_opponent_kan(actor, target, consumed)
            self._send({"type": "none"})

        elif t == "hora":
            print(f"\n[ver.2] 和了発生 (step {self._step_count})")
            self._send({"type": "none"})

        elif t == "ryukyoku":
            print(f"\n[ver.2] 流局 (step {self._step_count})")
            self._send({"type": "none"})

        elif t == "end_kyoku":
            self._send({"type": "none"})

        elif t == "end_game":
            print(f"\n[ver.2] 試合終了")
            return

        else:
            self._send({"type": "none"})

    def _decide_self_tsumo(self, pai_mjai: str, msg: dict):
        """自分のツモに対する応答"""
        possible = msg.get("possible_actions", [])

        # 1. ツモ和了
        for act in possible:
            if act.get("type") == "hora":
                print(f"[ver.2]  ツモ和了可能")
                self._send({"type": "hora", "target": self._id, "pai": pai_mjai})
                return

        # 2. 九種九牌
        for act in possible:
            if act.get("type") == "ryukyoku":
                yaochu_types = self._count_yaochu_types()
                if yaochu_types == 9:
                    self._send({"type": "ryukyoku"})
                    return

        # 3. 暗槓 / 加槓
        for act in possible:
            if act.get("type") in ("ankan", "kakan"):
                self._send(act)
                return

        # 4. 立直
        for act in possible:
            if act.get("type") == "reach":
                if self._should_riichi():
                    self._send({"type": "reach"})
                    return

        # 5. 通常打牌 (ver.2 評価器で決定)
        discard_us = self._decide_discard_v2()
        if not discard_us or discard_us not in self.state.my_hand:
            discard_us = _to_us(pai_mjai)
        discard_mjai = _to_mjai(discard_us)
        tsumogiri = (discard_us == _to_us(pai_mjai))
        self._send({"type": "dahai", "pai": discard_mjai, "tsumogiri": tsumogiri})

    def _decide_response(self, pai_mjai: str, msg: dict, actor: int):
        """他家打牌への応答 (ロン・鳴き判断)"""
        possible = msg.get("possible_actions", [])
        for act in possible:
            if act.get("type") == "hora":
                self._send({"type": "hora", "target": actor, "pai": pai_mjai})
                return
        for act in possible:
            act_type = act.get("type")
            if act_type in ("pon", "chi", "daiminkan"):
                if not self._should_call_meld(act_type, act, pai_mjai, actor):
                    continue
                self._send(act)
                return
        self._send({"type": "none"})

    def _decide_discard_v2(self) -> Optional[str]:
        """ver.2 評価器で打牌を決定 (コーチング付き)"""
        ev = self._evaluator_factory(self.state)
        hand = list(self.state.my_hand)
        chosen = ev.best_discard(hand)
        if self.show_coaching and chosen:
            explanation = ev.explain_discard(hand, chosen)
            structure = ev.describe_hand_structure()
            mode = ev.get_mode().name
            print(f"[ver.2]  打牌: {chosen} | モード: {mode}")
            print(f"  手牌構造: {structure}")
            print(f"  理由: {explanation}")
        return chosen

    def _should_riichi(self) -> bool:
        """ver.2 評価器で立直判定"""
        ev = self._evaluator_factory(self.state)
        return ev.should_riichi()

    def _should_call_meld(self, act_type: str, act: dict, pai_mjai: str, actor: int) -> bool:
        """ver.2 評価器で鳴き判定"""
        ev = self._evaluator_factory(self.state)
        call_type_map = {"chi": 0, "pon": 1, "daiminkan": 2}
        consumed_mjai = act.get("consumed", [])
        consumed_us = [_to_us(c) for c in consumed_mjai]
        pai_us = _to_us(pai_mjai)
        tiles_us = [pai_us] + consumed_us
        return ev.should_call_meld(call_type_map[act_type], tiles_us, actor)

    def _count_yaochu_types(self) -> int:
        """幺九牌の種類数 (九種九牌判定用)"""
        from str_converter import hand_to_counts
        counts = hand_to_counts(self.state.my_hand)
        yaochu_ids = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        return sum(1 for i in yaochu_ids if counts[i] >= 1)


def main():
    """簡易実行エントリ"""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11600)
    p.add_argument("--room", default="default")
    p.add_argument("--name", default="ver2_ai")
    p.add_argument("--quiet", action="store_true", help="コーチングを非表示")
    args = p.parse_args()
    client = OurMjaiClientV2(args.host, args.port, args.room, args.name,
                              show_coaching=not args.quiet)
    try:
        client.play_game()
    finally:
        client.close()


if __name__ == "__main__":
    main()
