#!/usr/bin/env python3
import sys, json, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.game_state import GameState, ReachState, Meld
from core.evaluator import Evaluator
from core.strategy_manager import ShantenCalculator
from core.str_converter import tile_to_id

HONOR_MAP = {'E':'1z','S':'2z','W':'3z','N':'4z','5':'5z','6':'6z','7':'7z'}
REV_HONOR = {v:k for k,v in HONOR_MAP.items()}

def to_internal(t):
    if t.startswith('r'):
        return '0' + t[1]
    if len(t) == 2 and t[0].isalpha():
        return HONOR_MAP.get(t[0], t)
    return t

def to_mjai(t):
    if t.startswith('0'):
        return 'r' + t[1]
    return t

state = GameState()
state.my_seat = 0

def handle_msg(msg):
    global state
    msg_type = msg.get('type')
    if msg_type == 'none':
        return None
    if msg_type == 'start_game':
        state.my_seat = msg.get('id', 0)
        return None
    if msg_type == 'start_kyoku':
        state.on_new_round(
            chang=0, ju=msg.get('kyoku',1)-1, ben=msg.get('honba',0),
            liqibang=msg.get('kyotaku',0),
            tiles=[to_internal(t) for t in msg.get('tehai',[])],
            scores=msg.get('scores',[25000]*4),
            left_tile_count=msg.get('tile_count',70),
            doras=[to_internal(msg['dora_indicator'])] if 'dora_indicator' in msg else [],
        )
        state.tsumo_count = 0
        return None
    if msg_type == 'dora':
        state.doras.append(to_internal(msg['dora_indicator']))
        return None
    if msg_type == 'tsumo':
        seat = msg.get('actor', state.my_seat)
        tile = to_internal(msg['pai'])
        if seat == state.my_seat:
            state.on_self_draw(tile)
        else:
            state.on_opponent_draw(seat)
        return None
    if msg_type == 'discard':
        seat = msg.get('actor', state.my_seat)
        tile = to_internal(msg['pai'])
        moqie = msg.get('tsumogiri', False)
        is_riichi = msg.get('declared_riichi', False)
        state.on_discard(seat, tile, is_riichi, moqie)
        state.tsumo_count = (state.tsumo_count // 4 + 1) * 4
        return None
    if msg_type == 'pon':
        seat = msg.get('actor', 0)
        target = msg.get('target', 0)
        tiles = [to_internal(t) for t in msg['consumed']]
        state.on_chi_peng_gang(2, seat, tiles, [target, seat, seat], [])
        state.tsumo_count += 1
        return None
    if msg_type == 'chi':
        seat = msg.get('actor', 0)
        target = msg.get('target', 0)
        tiles = [to_internal(t) for t in msg['consumed']]
        state.on_chi_peng_gang(1, seat, tiles, [target, seat, seat], [])
        state.tsumo_count += 1
        return None
    if msg_type == 'daiminkan':
        seat = msg.get('actor', 0)
        target = msg.get('target', 0)
        tiles = [to_internal(t) for t in msg['consumed']]
        state.on_chi_peng_gang(2, seat, tiles, [target, seat, seat], [])
        state.tsumo_count += 1
        return None
    if msg_type == 'ankan':
        seat = msg.get('actor', 0)
        tiles = [to_internal(t) for t in msg['consumed']]
        state.on_an_gang_add_gang(3, seat, tiles[0])
        state.tsumo_count += 1
        return None
    if msg_type == 'kakan':
        seat = msg.get('actor', 0)
        tiles = [to_internal(t) for t in msg['consumed']]
        state.on_an_gang_add_gang(2, seat, tiles[0])
        state.tsumo_count += 1
        return None
    if msg_type in ('hule', 'ryukyoku'):
        return None
    return None

def decide_discard(hand):
    hand = [to_internal(t) for t in hand]
    state.my_hand = hand
    params_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_parameters_ldea_v1.json')
    with open(params_path) as f:
        params = json.load(f)
    ev = Evaluator(state, params)
    tile = ev.best_discard(hand)
    if tile:
        return to_mjai(tile)
    return None

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        resp = handle_msg(msg)
        if resp:
            print(json.dumps(resp), flush=True)
        elif msg.get('type') == 'check':
            # Check if we can act
            action = msg.get('action', '')
            if action == 'discard':
                tile = decide_discard(msg.get('tehai', []))
                if tile:
                    print(json.dumps({'type':'discard','pai':tile}), flush=True)
                else:
                    print(json.dumps({'type':'nothing'}), flush=True)
            elif action in ('pon','chi','daiminkan','kan'):
                print(json.dumps({'type':'nothing'}), flush=True)
            elif action in ('tsumo_agari','ron_agari'):
                print(json.dumps({'type':'nothing'}), flush=True)
            elif action == 'riichi':
                tile = decide_discard(msg.get('tehai', []))
                if tile:
                    print(json.dumps({'type':'riichi','pai':tile}), flush=True)
                else:
                    print(json.dumps({'type':'nothing'}), flush=True)
            else:
                print(json.dumps({'type':'nothing'}), flush=True)

if __name__ == '__main__':
    main()
