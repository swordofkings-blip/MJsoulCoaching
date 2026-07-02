# -*- coding: utf-8 -*-
"""
@title v1 AIプレイヤー
@description GameState を受け取り、v1 Evaluator を用いて打牌・副露・リーチ判断を行う AI エントリポイント。
"""
from __future__ import annotations
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from evaluator import Evaluator
    from game_state import GameState


class AIPlayer:
    def __init__(self, name: str, evaluator_class, params: dict):
        self.name = name
        self.evaluator_class = evaluator_class
        self.params = params
        self.seat = -1
        self.yakuman_bonus_count = 0
        self.meld_seal_count = 0
        self.gap_relaxation_count = 0

    def reset_stats(self):
        self.yakuman_bonus_count = 0
        self.meld_seal_count = 0
        self.gap_relaxation_count = 0

    def clone(self, seat: int) -> AIPlayer:
        p = AIPlayer(self.name, self.evaluator_class, self.params)
        p.seat = seat
        return p

    def _make_evaluator(self, state: GameState):
        evaluator = self.evaluator_class(state, params=self.params)
        evaluator._ai_player = self
        return evaluator

    def decide_discard(self, state: GameState) -> Optional[str]:
        evaluator = self._make_evaluator(state)
        return evaluator.best_discard(list(state.my_hand))

    def should_riichi(self, state: GameState) -> bool:
        evaluator = self._make_evaluator(state)
        return evaluator.should_riichi()

    def choose_riichi_discard(self, state: GameState) -> Optional[str]:
        evaluator = self._make_evaluator(state)
        return evaluator.best_discard(list(state.my_hand))

    def should_kan(self, state: GameState) -> bool:
        evaluator = self._make_evaluator(state)
        return evaluator.should_kan()

    def should_tsumo(self, state: GameState) -> bool:
        evaluator = self._make_evaluator(state)
        if evaluator.should_go_kokushi_13():
            return False
        return True

    def should_kyushu_kyuhai(self, state: GameState) -> bool:
        from str_converter import hand_to_counts
        hand_counts = hand_to_counts(state.my_hand)
        yaochu_ids = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        yaochu_types = sum(1 for i in yaochu_ids if hand_counts[i] >= 1)
        yaochu_total = sum(hand_counts[i] for i in yaochu_ids)
        if yaochu_types == 9 and yaochu_total == 9:
            return True
        if yaochu_types == 10:
            if yaochu_total == 10:
                if state.my_score_rank() == 3:
                    return False
                return True
            return False
        if yaochu_types >= 11:
            return False
        return False

    def should_ron(self, state: GameState) -> bool:
        return True

    def should_call_meld(self, state: GameState, call_type: int, tiles: List[str], from_seat: int) -> bool:
        evaluator = self._make_evaluator(state)
        return evaluator.should_call_meld(call_type, tiles, from_seat)
