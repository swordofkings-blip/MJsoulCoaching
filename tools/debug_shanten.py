# -*- coding: utf-8 -*-
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from game_state import GameState
from yakuman_evaluator import YakumanEvaluator
s = GameState()
s.my_seat = 0
s.my_hand = ['1m','1m','9m','9m','1p','1p','9p','1s','1s','9s','5m','5p','5s','2m']
s.scores = [25000]*4; s.tsumo_count = 5; s.doras = ['1m']; s.left_tile_count = 70-5*4
ye = YakumanEvaluator(s); r = ye.evaluate_all()
print('chinroutou shanten=' + str(r['chinroutou'].shanten))
print('tsuuiisou shanten=' + str(r['tsuuiisou'].shanten))
print('ryuuiisou shanten=' + str(r['ryuuiisou'].shanten))
print('chuuren shanten=' + str(r['chuuren'].shanten))
