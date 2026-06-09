# -*- coding: utf-8 -*-
"""副露封印統合テスト"""
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))

from game_state import GameState
from strategy_manager import StrategyManager
from yakuman_evaluator import YakumanEvaluator

# 国士無双1向聴 → 副露封印ON
state1 = GameState()
state1.my_seat = 0
state1.my_hand = ['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m']
state1.scores = [25000,25000,25000,25000]
state1.tsumo_count = 5
state1.doras = ['1m']
state1.left_tile_count = 70 - 5*4

sm1 = StrategyManager(state1, params={})
seal1 = not sm1.is_meld_open_allowed()
print(f'国士無双1向聴: 副露封印={"ON" if seal1 else "OFF"}')
yak1 = YakumanEvaluator(state1)
print(f'  -> should_seal_melds()={yak1.should_seal_melds()}')

# 通常手 → 副露封印OFF
state2 = GameState()
state2.my_seat = 0
state2.my_hand = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','4p']
state2.scores = [25000,25000,25000,25000]
state2.tsumo_count = 5
state2.doras = ['1m']
state2.left_tile_count = 70 - 5*4

sm2 = StrategyManager(state2, params={})
seal2 = not sm2.is_meld_open_allowed()
print(f'通常手: 副露封印={"ON" if seal2 else "OFF"}')
yak2 = YakumanEvaluator(state2)
print(f'  -> should_seal_melds()={yak2.should_seal_melds()}')

# 大三元1向聴（副露可）→ 副露封印OFF
state3 = GameState()
state3.my_seat = 0
state3.my_hand = ['5z','5z','5z','6z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p']
state3.scores = [25000,25000,25000,25000]
state3.tsumo_count = 5
state3.doras = ['1m']
state3.left_tile_count = 70 - 5*4

sm3 = StrategyManager(state3, params={})
seal3 = not sm3.is_meld_open_allowed()
print(f'大三元1向聴: 副露封印={"ON" if seal3 else "OFF"}')
yak3 = YakumanEvaluator(state3)
print(f'  -> should_seal_melds()={yak3.should_seal_melds()}')

# 確認
all_ok = seal1 == True and seal2 == False and seal3 == False
print(f'\n{"ALL OK" if all_ok else "NG"}')
