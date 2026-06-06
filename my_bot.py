# -*- coding: utf-8 -*-
from __future__ import annotations
import time
from typing import List, Optional

from sdk import MajsoulHandler, Operation, all_tiles

from game_state import GameState
from evaluator import Evaluator
from str_converter import is_red_five, tile_to_id


try:
    from action.action import GUIInterface
except Exception:
    GUIInterface = None


class MyBot(MajsoulHandler):
    def __init__(self, gui: Optional[object] = None, think_time_sec: float = 0.5):
        super().__init__()
        self.state = GameState()
        self.evaluator = Evaluator(self.state)
        self.gui = gui
        self.think_time_sec = think_time_sec
        self._pending_op_list: List[dict] = []
        self._pending_op_seat: int = -1
        self._last_self_drawn: Optional[str] = None
        self._auto_discard_enabled: bool = True

    def enable_auto_discard(self, enabled: bool = True):
        self._auto_discard_enabled = enabled

    def _update_evaluator(self):
        self.evaluator = Evaluator(self.state)

    def _safe_print_eval(self, hand: List[str]):
        try:
            tile, score = self.evaluator.best_discard_with_score(hand)
        except Exception as e:
            print(f'[MyBot] evaluator error: {e}')
            return None, None
        return tile, score

    def authGame(self, accountId: int, seatList: List[int]):
        self.accountId = accountId
        self.seatList = seatList
        if accountId in seatList:
            self.mySeat = seatList.index(accountId)
            self.state.my_seat = self.mySeat
        print(f'[MyBot] authGame accountId={accountId} seat={self.mySeat}')

    def newRound(self, chang, ju, ben, liqibang, tiles, scores, leftTileCount, doras):
        self.state.on_new_round(chang, ju, ben, liqibang, tiles, scores, leftTileCount, doras)
        self.state.my_seat = self.mySeat
        self._update_evaluator()
        print(f'[MyBot] newRound hand_size={len(tiles)} dora={doras}')

    def newDora(self, dora: str):
        self.state.on_new_dora(dora)
        self._update_evaluator()
        print(f'[MyBot] newDora={dora}')

    def iDealTile(self, seat: int, tile: str, leftTileCount: int, liqi, operation):
        if seat != self.mySeat:
            return
        self.state.on_self_draw(tile)
        self._last_self_drawn = tile
        self._update_evaluator()
        if operation is not None:
            op_list = operation.get('operationList', [])
            self._handle_self_operations(seat, tile, op_list)
        else:
            self._decide_and_discard()

    def dealTile(self, seat: int, leftTileCount: int, liqi):
        self.state.on_opponent_draw(seat)
        self._update_evaluator()
        print(f'[MyBot] opponent_draw seat={seat}')

    def discardTile(self, seat: int, tile: str, moqie: bool, isLiqi: bool, operation):
        self.state.on_discard(seat, tile, isLiqi, moqie)
        self._update_evaluator()
        if seat == self.mySeat:
            return
        if operation is not None:
            op_list = operation.get('operationList', [])
            self._pending_op_list = op_list
            self._pending_op_seat = self.mySeat
            self._handle_call_operations(seat, tile, op_list)

    def chiPengGang(self, type_, seat, tiles, froms, tileStates):
        self.state.on_chi_peng_gang(type_, seat, tiles, froms, tileStates)
        self._update_evaluator()

    def anGangAddGang(self, type_, seat, tiles):
        self.state.on_an_gang_add_gang(type_, seat, tiles)
        self._update_evaluator()

    def hule(self, hand, huTile, seat, zimo, liqi, doras, liDoras, fan, fu, oldScores, deltaScores, newScores):
        self.state.scores = list(newScores)
        self._update_evaluator()
        print(f'[MyBot] hule seat={seat} zimo={zimo} fan={fan} fu={fu}')

    def liuju(self, tingpai, hands, oldScores, deltaScores):
        print(f'[MyBot] liuju tingpai={tingpai}')

    def specialLiuju(self):
        print('[MyBot] specialLiuju')

    def _handle_self_operations(self, seat: int, tile: str, op_list: List[dict]):
        can_actions = {op['type']: op for op in op_list}
        if can_actions.get(Operation.Zimo.value):
            self.actionZimo()
            return
        if can_actions.get(Operation.Hu.value):
            self.actionHu()
            return
        if can_actions.get(Operation.JiaGang.value):
            if self.evaluator.should_kan():
                self._execute_kang(can_actions[Operation.JiaGang.value])
                return
        if can_actions.get(Operation.Liqi.value):
            if self.evaluator.should_riichi():
                discard = self._choose_riichi_discard_tile()
                if discard is not None:
                    self.actionLiqi(discard)
                    return
        if can_actions.get(Operation.MingGang.value):
            if self.evaluator.should_kan():
                self._execute_kang(can_actions[Operation.MingGang.value])
                return
        self._decide_and_discard()

    def _handle_call_operations(self, discarder_seat: int, discard_tile: str, op_list: List[dict]):
        if not op_list:
            return
        if not self.evaluator.strategy.is_meld_open_allowed():
            return
        can_actions = {op['type']: op for op in op_list}
        if can_actions.get(Operation.Hu.value):
            self.actionHu()
            return
        if can_actions.get(Operation.MingGang.value):
            self._execute_kang(can_actions[Operation.MingGang.value])
            return
        if can_actions.get(Operation.Peng.value):
            if self.evaluator.strategy.is_meld_open_allowed():
                self._execute_meld(Operation.Peng, can_actions[Operation.Peng.value])
                return
        if can_actions.get(Operation.Chi.value):
            if self.evaluator.strategy.is_meld_open_allowed():
                self._execute_meld(Operation.Chi, can_actions[Operation.Chi.value])
                return

    def _decide_and_discard(self):
        if not self._auto_discard_enabled:
            return
        hand = list(self.state.my_hand)
        if len(hand) % 3 != 2:
            return
        tile, _ = self._safe_print_eval(hand)
        if tile is None:
            return
        if tile not in all_tiles:
            print(f'[MyBot] best_discard invalid: {tile}')
            return
        time.sleep(self.think_time_sec)
        self.actionDiscardTile(tile)

    def _choose_riichi_discard_tile(self) -> Optional[str]:
        try:
            tile, _ = self.evaluator.best_discard_with_score(list(self.state.my_hand))
        except Exception:
            return None
        return tile

    def _execute_kang(self, op: dict):
        if self.gui is None:
            return
        try:
            self.gui.actionChiPengGang(Operation.MingGang, op.get('combination', []))
        except Exception as e:
            print(f'[MyBot] execute_kang gui error: {e}')

    def _execute_meld(self, type_: Operation, op: dict):
        if self.gui is None:
            return
        try:
            self.gui.actionChiPengGang(type_, op.get('combination', []))
        except Exception as e:
            print(f'[MyBot] execute_meld gui error: {e}')

    def actionDiscardTile(self, tile: str):
        """
        @title 打牌アクションの送信
        @description GUIインターフェースを通じて打牌を指示し、内部の一時変数（最後に自摸した牌）をクリアする。状態更新はWebSocket応答（discardTile）で行う。
        @param tile 打牌の文字列 (例: "1m")
        """
        if self.gui is not None:
            try:
                self.gui.actionDiscardTile(tile)
            except Exception as e:
                print(f'[MyBot] gui discard error: {e}')
        # 状態更新はWebSocketのdiscardTile応答で行うため、ここでは手牌/河を更新しない
        # （重複更新による河の二重登録・手牌の誤削除を防ぐため）
        self._last_self_drawn = None
        print(f'[MyBot] discard {tile}')

    def actionLiqi(self, tile: str):
        """
        @title 立直アクションの送信
        @description GUIインターフェースを通じて立直を指示し、打牌を実行する。立直状態はWebSocket応答（discardTile）で反映されるため、ここでは更新しない。
        @param tile 宣言牌の文字列 (例: "1m")
        """
        if self.gui is not None:
            try:
                self.gui.actionLiqi(tile)
            except Exception as e:
                print(f'[MyBot] gui liqi error: {e}')
        # 立直フラグはWebSocket応答で一元管理するため手動設定しない
        self.actionDiscardTile(tile)

    def actionHu(self):
        if self.gui is not None:
            try:
                self.gui.actionHu()
            except Exception as e:
                print(f'[MyBot] gui hu error: {e}')
        print('[MyBot] hu')

    def actionZimo(self):
        if self.gui is not None:
            try:
                self.gui.actionZimo()
            except Exception as e:
                print(f'[MyBot] gui zimo error: {e}')
        print('[MyBot] zimo')

    def actionChiPengGang(self, type: Operation, tiles: List[str]):
        if self.gui is None:
            print(f'[MyBot] chiPengGang type={type} tiles={tiles} (no gui)')
            return
        try:
            self.gui.actionChiPengGang(type, tiles)
        except Exception as e:
            print(f'[MyBot] gui chiPengGang error: {e}')


def run_bot_with_replay(filename: str = 'ws_dump.pkl'):
    from sdk import replayWebSocket
    bot = MyBot(gui=None)
    bot.state.my_seat = bot.mySeat if hasattr(bot, 'mySeat') else 0
    bot._auto_discard_enabled = False
    import sdk as _sdk
    original_handler = _sdk.replayWebSocket

    def wrapped():
        liqi = _sdk.LiqiProto()
        import pickle
        history = pickle.load(open(filename, 'rb'))
        for flow_msg in history:
            result = liqi.parse(flow_msg)
            bot.parse(result)
    wrapped()


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Rule+Fuzzy Hybrid Mahjong Bot')
    parser.add_argument('-l', '--load', default='', help='Replay websocket dump for testing')
    parser.add_argument('--gui', action='store_true', help='Enable GUI interface')
    args = parser.parse_args()

    gui = None
    if args.gui and GUIInterface is not None:
        try:
            gui = GUIInterface()
        except Exception as e:
            print(f'[MyBot] GUI init failed: {e}')
            gui = None
    if args.load:
        run_bot_with_replay(args.load)
    else:
        print('No mode selected. Use --load FILE or --gui')
