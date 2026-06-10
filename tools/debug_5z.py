# -*- coding: utf-8 -*-
"""デバッグ: 大三元2向聴 5zボーナス確認"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from game_state import GameState
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator
from str_converter import tile_to_id

params = json.load(open('config/config_parameters.json', encoding='utf-8'))
params['yakuman_strategy']['YAKUMAN_TILE_CONTRIBUTION_ENABLED'] = True
params['yakuman_strategy']['YAKUMAN_MIN_SHANTEN'] = 2

state = GameState()
state.my_seat = 0
state.my_hand = ['5z','5z','5z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p','9s']
state.scores = [25000]*4
state.tsumo_count = 5
state.doras = ['1m']
state.left_tile_count = 70 - 5*4

ye = YakumanEvaluator(state)
results = ye.evaluate_all()
print('Yakuman:')
for n,r in results.items():
    if r.progress > 0:
        print(f'  [{n}] progress={r.progress:.2f} shanten={r.shanten} possible={r.is_possible}')

ev = Evaluator(state, params=params)
for t in ['5z','6z','7z','1m','9s']:
    ev.evaluate_tile(t)

print('\nDetails for 5z:')
for d in ev.details.get('5z', []):
    print(f'  {d}')
