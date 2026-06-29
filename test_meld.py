# -*- coding: utf-8 -*-
import sys, json, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator

with open('config/config_parameters.json', 'r', encoding='utf-8') as f:
    params = json.load(f)

# 南家 (my_seat=1) で西 (3z) をポンする場合
state = GameState()
state.my_hand = ['4m','6m','2p','5p','7p','9p','1s','2s','7s','8s','1z','3z','3z','8s']
state.my_melds = []
state.my_seat = 1
state.ju = 0
state.chang = 0
state.doras = ['8p']
state.tsumo_count = 5
state.left_tile_count = 68
state.scores = [25000, 25000, 25000, 25000]
state.river = [['3z'], [], [], []]
state.reach_states = [type('R', (), {'is_reach': False, 'is_ippatsu': False, 'reach_turn': -1})() for _ in range(4)]

ev = Evaluator(state, params)

# ポン判定
meld_type = 1  # ポン
tiles = ['3z', '3z', '3z']  # 西
from_seat = 0  # 東家から

result = ev.should_call_meld(meld_type, tiles, from_seat)
print(f'should_call_meld(pon, 西, from=東) = {result}')

# もう一つのテスト: 自分の自風牌 (南) をポン
meld_type = 1
tiles = ['2z', '2z', '2z']  # 南
from_seat = 0
result = ev.should_call_meld(meld_type, tiles, from_seat)
print(f'should_call_meld(pon, 南 (自風), from=東) = {result}')

# 三元牌 (白) をポン
meld_type = 1
tiles = ['5z', '5z', '5z']  # 白
from_seat = 0
result = ev.should_call_meld(meld_type, tiles, from_seat)
print(f'should_call_meld(pon, 白 (三元), from=東) = {result}')
