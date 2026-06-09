# -*- coding: utf-8 -*-
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

    def should_ron(self, state: GameState) -> bool:
        return True

    def should_call_meld(self, state: GameState, call_type: int, tiles: List[str], from_seat: int) -> bool:
        evaluator = self._make_evaluator(state)
        return evaluator.should_call_meld(call_type, tiles, from_seat)
