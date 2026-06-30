# -*- coding: utf-8 -*-
"""
@title MJAI TCP client (ver.2 評価器対応)
@description ver.2 評価器 (EvaluatorV2) を使って MJAI サーバーと対戦する。
               v1 (mjai_client.py) のプロトコル処理をベースに v2 評価器を統合。
"""
from __future__ import annotations
import json
import os
import random
import socket
import sys
from typing import List, Optional

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from tools.mjai_client import _to_mjai, _to_us, AKOCHAN_NAME, AKOCHAN_IMG


class OurMjaiClientV2:
    """ver.2 評価器 (EvaluatorV2) を使った MJAI クライアント。"""

    def __init__(self, host: str, port: int, room: str, name: str, params: dict = None,
                 show_coaching: bool = True):
        self.name = name
        self.params = params or {}
        self.show_coaching = show_coaching
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.connect((host, port))
        self._buf = b''
        self._id = -1
        self._last_tsumo_mjai = None
        self._step_count = 0

        from core.game_state import GameState
        from core.evaluator_v2 import EvaluatorV2

        self.state = GameState()
        self.params.setdefault('evaluator', 'v2')
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
                raise ConnectionError("Socket closed")
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

    def _decide_discard_v2(self) -> Optional[str]:
        """ver.2 評価器で打牌を決定"""
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
        ev = self._evaluator_factory(self.state)
        return ev.should_riichi()

    def _should_call_meld(self, act_type: str, act: dict, pai_mjai: str, actor: int) -> bool:
        ev = self._evaluator_factory(self.state)
        call_type_map = {"chi": 0, "pon": 1, "daiminkan": 2}
        consumed_mjai = act.get("consumed", [])
        consumed_us = [_to_us(c) for c in consumed_mjai]
        pai_us = _to_us(pai_mjai)
        tiles_us = [pai_us] + consumed_us
        return ev.should_call_meld(call_type_map[act_type], tiles_us, actor)

    def _count_yaochu_types(self) -> int:
        from str_converter import hand_to_counts
        counts = hand_to_counts(self.state.my_hand)
        yaochu_ids = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        return sum(1 for i in yaochu_ids if counts[i] >= 1)

    def _handle(self, t: str, msg: dict):
        """
        @title MJAI プロトコル処理
        @description v1 (mjai_client.py) をベースに、ver.2 評価器で判断。
        """
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
                self._last_tsumo_mjai = pai_mjai
                pai_us = _to_us(pai_mjai)
                self.state.on_self_draw(pai_us)

                # リーチ後はツモアガリか暗槓のみ、それ以外はツモ切り強制
                if self.state.reach_states[self._id].is_reach:
                    for act in msg.get("possible_actions", []):
                        if act.get("type") == "hora":
                            if self._should_tsumo():
                                self._send({"type": "hora", "target": actor, "pai": pai_mjai})
                                return
                    for act in msg.get("possible_actions", []):
                        if act.get("type") == "ankan":
                            if self._should_kan():
                                self._send(act)
                                return
                    self._send({"type": "dahai", "pai": pai_mjai, "tsumogiri": True})
                    return

                # 0. 九種九牌
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "ryukyoku":
                        if self._count_yaochu_types() >= 9:
                            self._send({"type": "ryukyoku"})
                            return
                        break

                # 1. ツモ和了
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "hora":
                        print(f"[ver.2]  ツモ和了可能")
                        self._send({"type": "hora", "target": self._id, "pai": pai_mjai})
                        return

                # 2. 暗槓 / 加槓
                for act in msg.get("possible_actions", []):
                    if act.get("type") in ("ankan", "kakan"):
                        if self._should_kan():
                            self._send(act)
                            return

                # 3. 立直
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "reach":
                        if self._should_riichi():
                            self._send({"type": "reach"})
                            return

                # 4. 通常打牌
                tsumo_pai_us = _to_us(pai_mjai)
                discard_us = self._decide_discard_v2()
                if not discard_us or discard_us not in self.state.my_hand:
                    discard_us = tsumo_pai_us

                # 空切り判定: ツモ切りになる場面で意図的に手出しに偽装する
                if self._should_karagiri(discard_us, tsumo_pai_us):
                    tsumogiri = False
                else:
                    tsumogiri = (discard_us == tsumo_pai_us)

                discard_mjai = _to_mjai(discard_us)
                self._send({"type": "dahai", "pai": discard_mjai, "tsumogiri": tsumogiri})
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
                # ロン和了
                for act in msg.get("possible_actions", []):
                    if act.get("type") == "hora":
                        if self._should_ron():
                            self._send({"type": "hora", "target": actor, "pai": pai_mjai})
                            return
                # ポン・チー・大明槓
                for act in msg.get("possible_actions", []):
                    act_type = act.get("type")
                    if act_type in ("pon", "chi", "daiminkan"):
                        if self._should_call_meld(act_type, act, pai_mjai, actor):
                            self._send(act)
                            return
                self._send({"type": "none"})
            else:
                self._send({"type": "none"})

        elif t == "reach":
            actor = msg["actor"]
            self.state.reach_states[actor].is_reach = True
            self.state.reach_states[actor].reach_turn = len(self.state.river[actor])

            if actor == self._id:
                # 自分がリーチ: 不能牌を除外して打牌
                cannot_mjai = msg.get("cannot_dahai", [])
                cannot_us = [_to_us(p) for p in cannot_mjai]
                discard_us = self._decide_discard_v2()
                if not discard_us or discard_us not in self.state.my_hand or discard_us in cannot_us:
                    valid = [t for t in self.state.my_hand if t not in cannot_us]
                    if valid:
                        if self._last_tsumo_mjai and _to_us(self._last_tsumo_mjai) in valid:
                            discard_us = _to_us(self._last_tsumo_mjai)
                        else:
                            discard_us = valid[0]
                    else:
                        discard_us = self.state.my_hand[-1]
                discard_mjai = _to_mjai(discard_us)
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
            target = msg.get("target", actor)
            pai_mjai = msg.get("pai", "1m")
            consumed_mjai = msg.get("consumed", [])

            type_map = {"chi": 0, "pon": 1, "daiminkan": 2}
            type_ = type_map[t]

            tiles_us = [_to_us(pai_mjai)] + [_to_us(c) for c in consumed_mjai]
            froms = [target] + [actor] * len(consumed_mjai)
            tile_states = [0] * len(tiles_us)

            self.state.on_chi_peng_gang(type_, actor, tiles_us, froms, tile_states)

            if actor == self._id:
                discard_us = self._decide_discard_v2()
                if not discard_us or discard_us not in self.state.my_hand:
                    discard_us = self.state.my_hand[-1]
                discard_mjai = _to_mjai(discard_us)
                self._send({"type": "dahai", "pai": discard_mjai, "tsumogiri": False})
            else:
                self._send({"type": "none"})

        elif t in ("ankan", "kakan"):
            actor = msg["actor"]
            consumed_mjai = msg.get("consumed", [])
            consumed_us = [_to_us(c) for c in consumed_mjai]
            type_ = 3 if t == "ankan" else 2
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

    def _should_tsumo(self) -> bool:
        """ver.2 評価器でツモ和了判定"""
        ev = self._evaluator_factory(self.state)
        return ev.should_tsumo()

    def _should_ron(self) -> bool:
        """ver.2 評価器でロン和了判定"""
        ev = self._evaluator_factory(self.state)
        return ev.should_ron()

    def _should_kan(self) -> bool:
        """@title ver.2 評価器で槓判定"""
        ev = self._evaluator_factory(self.state)
        return ev.should_kan()

    def _should_karagiri(self, discard_us: str, tsumo_pai_us: str) -> bool:
        """
        @title 空切り判定
        @description ツモ切りになる場面で意図的に手出し（tsumogiri=False）に偽装し、
                     他家への情報漏洩を抑止する。
        Why: ツモ切り連発は「テンパイした」「手牌が整った」というシグナルを
             他家に与えてしまう。空切りにより手牌情報のアドバンテージを減らす。
        @param {str} discard_us - 評価器が選択した打牌
        @param {str} tsumo_pai_us - 今回ツモった牌
        @returns {bool} 空切りを実行すべきか
        """
        # ツモ牌と異なる牌を切る場合は空切り対象外（元々手出しになるため）
        if discard_us != tsumo_pai_us:
            return False
        from core.str_converter import tile_to_id
        tid = tile_to_id(tsumo_pai_us)
        hand_counts = self.state.my_hand_counts()
        # 手牌に同種牌が2枚以上ないと手出しできない
        if hand_counts[tid] < 2:
            return False
        # シャンテン数計算
        from core.shanten_v2 import ShantenCalculatorV2
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            shanten = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
        else:
            shanten = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)
        # テンパイまたは一シャンテン以外は対象外
        if shanten > 1:
            return False
        # モード判定: 攻撃系・バランスのみ空切りを検討
        from core.strategy_v2 import get_mode, Mode
        current_turn = (self.state.tsumo_count - 1) // 4 + 1
        is_last_round = self.state.is_last_round() if hasattr(self.state, 'is_last_round') else False
        mode = get_mode(self.state, current_turn, is_last_round)
        if mode not in (Mode.ATTACK, Mode.URGENT_ATTACK, Mode.BALANCED):
            return False
        # 40% の確率で空切り実行
        return random.random() < 0.4


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=11600)
    p.add_argument("--room", default="default")
    p.add_argument("--name", default="ver2_ai")
    p.add_argument("--quiet", action="store_true")
    args = p.parse_args()
    client = OurMjaiClientV2(args.host, args.port, args.room, args.name,
                              show_coaching=not args.quiet)
    try:
        client.play_game()
    finally:
        client.close()


if __name__ == "__main__":
    main()
