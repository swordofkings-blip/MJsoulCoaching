# -*- coding: utf-8 -*-
"""役満統計カウンター詳細デバッグ（テンパイ手牌）"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from game_state import GameState
from evaluator import Evaluator
from ai_player import AIPlayer

params = json.load(open('config/config_parameters.json', encoding='utf-8'))

# 国士無双テンパイ（七対子形）→ どの牌を切ってもテンパイ維持
state = GameState()
state.my_seat = 0
state.my_hand = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z','7z']
state.scores = [15000, 35000, 25000, 25000]
state.tsumo_count = 5
state.doras = ['1m']
state.left_tile_count = 70 - 5*4

ai = AIPlayer('test', Evaluator, params)
evaluator = ai._make_evaluator(state)
for t in ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z']:
    evaluator.evaluate_tile(t)
    d = evaluator.details.get(t, [])
    b = [x for x in d if '役満' in x]
    if b:
        print(f'{t}: {" | ".join(b)}')
        print(f'  full: {d}')

print(f'\n役満ボーナスカウント: {ai.yakuman_bonus_count}')
print(f'点差緩和カウント: {ai.gap_relaxation_count}')
