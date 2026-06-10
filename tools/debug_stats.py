# -*- coding: utf-8 -*-
"""役満統計カウンター動作確認"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from game_state import GameState
from evaluator import Evaluator
from ai_player import AIPlayer

params = json.load(open('config/config_parameters.json', encoding='utf-8'))

# 国士無双1向聴でAIを模擬
state = GameState()
state.my_seat = 0
state.my_hand = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m']
state.scores = [15000, 35000, 25000, 25000]
state.tsumo_count = 5
state.doras = ['1m']
state.left_tile_count = 70 - 5*4

ai = AIPlayer('test', Evaluator, params)
evaluator = ai._make_evaluator(state)
evaluator.evaluate_tile('2z')  # 老頭・字牌にボーナスが乗るはず

print(f'役満ボーナスカウント: {ai.yakuman_bonus_count}')
print(f'副露封印カウント: {ai.meld_seal_count}')
print(f'点差緩和カウント: {ai.gap_relaxation_count}')
