# -*- coding: utf-8 -*-
"""デバッグ: 大三元1向聴のボーナス確認"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from game_state import GameState
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator
from str_converter import tile_to_id

params = json.load(open('config/config_parameters.json', encoding='utf-8'))
state = GameState()
state.my_seat = 0
state.my_hand = ['5z','5z','5z','6z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p']
state.scores = [25000,25000,25000,25000]
state.tsumo_count = 5
state.doras = ['1m']
state.left_tile_count = 70 - 5 * 4

yak_eval = YakumanEvaluator(state)
results = yak_eval.evaluate_all()
print('Yakuman evaluations:')
for name, r in results.items():
    if r.progress > 0:
        print(f'  [{name}] progress={r.progress:.2f} shanten={r.shanten} possible={r.is_possible}')

evaluator = Evaluator(state, params=params)
print('\nTile bonuses:')
for tile in ['5z','6z','7z','1m','2m','3m','4p','5p','6p']:
    s = evaluator.evaluate_tile(tile)
    details = evaluator.details.get(tile, [])
    yakuman = [d for d in details if '役満' in d]
    print(f'  {tile} (id={tile_to_id(tile)}): score={s:.1f} bonus={" | ".join(yakuman) if yakuman else "(none)"}')
