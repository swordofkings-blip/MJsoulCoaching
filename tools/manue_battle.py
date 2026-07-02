# -*- coding: utf-8 -*-
"""
@title Manue AI 対戦バトルランナー
@description Manue ベース AI と Akochan の対戦を実行し、成績を計測する。
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import random
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass, field, asdict
from typing import List, Optional
from functools import partial

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, ReachState, Meld
from core.evaluator import Evaluator
from core.strategy_manager import ShantenCalculator
from core.str_converter import tile_to_id, id_to_tile, hand_to_counts
from tools.mahjong_simulator import MahjongSimulator, GameResult, PlayerGameStats


PT_TABLES = {
    'gold':  {0: 55, 1: 25, 2: -5, 3: -55},
    'jade':  {0: 75, 1: 35, 2: -5, 3: -95},
    'throne': {0: 95, 1: 45, 2: -5, 3: -125},
}
BASE_SCORE = 25000


class ManueAIPlayer:
    """ManueAI を AIPlayer インターフェースに適合させるラッパー"""

    def __init__(self, name, manue_ai):
        self.name = name
        self._manue_ai = manue_ai
        self.seat = -1

    def clone(self, seat):
        p = ManueAIPlayer(self.name, self._manue_ai)
        p.seat = seat
        return p

    def decide_discard(self, state):
        adapter = ManueGameAdapter(self.seat, self._manue_ai)
        return adapter.decide_discard(state)

    def should_tsumo(self, state):
        adapter = ManueGameAdapter(self.seat, self._manue_ai)
        return adapter.should_tsumo(state)

    def should_ron(self, state):
        adapter = ManueGameAdapter(self.seat, self._manue_ai)
        return adapter.should_ron(state)

    def should_riichi(self, state):
        adapter = ManueGameAdapter(self.seat, self._manue_ai)
        return adapter.should_riichi(state)

    def choose_riichi_discard(self, state):
        adapter = ManueGameAdapter(self.seat, self._manue_ai)
        return adapter.decide_discard(state)

    def should_kan(self, state):
        return False

    def should_call_meld(self, state, call_type, tiles, from_seat):
        return False


class ManueGameAdapter:
    """ManueAI を MahjongSimulator の Player インターフェースに接続するアダプター"""

    def __init__(self, seat, manue_ai):
        self._seat = seat
        self._manue_ai = manue_ai
        self._game = None
        self._state = None
        self._pending_melds = []

    def clone(self, seat):
        adapter = ManueGameAdapter(seat, self._manue_ai)
        adapter._game = self._game
        return adapter

    def set_game_context(self, game):
        self._game = game

    def _build_game_proxy(self):
        return ManueGameProxy(self._game, self._seat)

    def decide_discard(self, state):
        game_proxy = ManueGameProxy(state, self._seat)
        player_proxy = ManuePlayerProxy(state, self._seat)
        action = {
            'type': 'tsumo',
            'actor': self._seat,
            'pai': state.my_hand[-1] if state.my_hand else None,
            'possible_actions': [],
            'cannot_dahai': [],
        }
        resp = self._manue_ai.respond_to_action(action, player_proxy, game_proxy)
        if resp and resp.get('type') == 'dahai':
            pai = resp.get('pai')
            if pai:
                if hasattr(pai, 'to_string'):
                    tile_str = pai.to_string()
                else:
                    tile_str = str(pai)
                if tile_str in state.my_hand:
                    return tile_str
        if state.my_hand:
            return state.my_hand[-1]
        return None

    def should_tsumo(self, state):
        game_proxy = ManueGameProxy(state, self._seat)
        player_proxy = ManuePlayerProxy(state, self._seat)
        action = {
            'type': 'tsumo',
            'actor': self._seat,
            'pai': state.my_hand[-1] if state.my_hand else None,
            'possible_actions': [{'type': 'hora'}],
        }
        resp = self._manue_ai.respond_to_action(action, player_proxy, game_proxy)
        return resp and resp.get('type') == 'hora'

    def should_riichi(self, state):
        game_proxy = ManueGameProxy(state, self._seat)
        player_proxy = ManuePlayerProxy(state, self._seat)
        action = {
            'type': 'tsumo',
            'actor': self._seat,
            'pai': state.my_hand[-1] if state.my_hand else None,
            'possible_actions': [{'type': 'reach'}],
        }
        resp = self._manue_ai.respond_to_action(action, player_proxy, game_proxy)
        return resp and resp.get('type') == 'reach'

    def should_ron(self, state):
        game_proxy = ManueGameProxy(state, self._seat)
        player_proxy = ManuePlayerProxy(state, self._seat)
        action = {
            'type': 'dahai',
            'actor': (self._seat + 3) % 4,
            'pai': state.last_discard_tile if hasattr(state, 'last_discard_tile') else None,
            'possible_actions': [{'type': 'hora'}],
        }
        resp = self._manue_ai.respond_to_action(action, player_proxy, game_proxy)
        return resp and resp.get('type') == 'hora'

    def should_call_meld(self, state, meld_type, tiles, from_seat):
        game_proxy = ManueGameProxy(state, self._seat)
        player_proxy = ManuePlayerProxy(state, self._seat)
        mjai_type = {0: 'chi', 1: 'pon', 2: 'daiminkan'}.get(meld_type, 'daiminkan')
        possible_actions = [{
            'type': mjai_type, 'pai': tiles[0],
            'consumed': list(tiles[1:]),
            'target': from_seat
        }]
        action = {
            'type': 'dahai',
            'actor': from_seat,
            'pai': tiles[0],
            'possible_actions': possible_actions,
        }
        resp = self._manue_ai.respond_to_action(action, player_proxy, game_proxy)
        return resp is not None and resp.get('type') != 'none'

    def should_kan(self, state):
        return False


class ManuePlayerProxy:
    def __init__(self, state, seat):
        self._state = state
        self.id = seat
        self.tehais = [TileProxy(t) for t in state.my_hand]
        self.sutehais = [TileProxy(t) for t in state.river[seat]]
        self.furos = []
        self.score = state.scores[seat] if state.scores else 25000
        rs = state.reach_states[seat] if hasattr(state, 'reach_states') and seat < len(state.reach_states) else None
        if rs and rs.is_reach:
            self.reach_state = "accepted"
            self.reach_sutehai_index = rs.reach_turn - 1 if rs.reach_turn > 1 else 0
        else:
            self.reach_state = "none"
            self.reach_sutehai_index = -1


HONOR_MAP_MJAI = {'E': '1z', 'S': '2z', 'W': '3z', 'N': '4z', 'P': '5z', 'F': '6z', 'C': '7z'}
HONOR_NUM_MJAI = {'E': 1, 'S': 2, 'W': 3, 'N': 4, 'P': 5, 'F': 6, 'C': 7}


def to_internal_tile(t):
    if t.startswith('r'):
        return '0' + t[1]
    if len(t) == 1 and t in HONOR_MAP_MJAI:
        return HONOR_MAP_MJAI[t]
    if len(t) == 2 and t[0] in HONOR_MAP_MJAI:
        return HONOR_MAP_MJAI[t[0]]
    return t


class TileProxy:
    def __init__(self, tile_str):
        self._str = tile_str
        internal = to_internal_tile(tile_str) if tile_str else None
        self._id = tile_to_id(internal) if internal else -1

    def id(self):
        return self._id

    def red(self):
        return self._str and self._str.startswith('0')

    def equal(self, other):
        if isinstance(other, TileProxy):
            return self._id == other._id and self.red() == other.red()
        return False

    def has_same_symbol(self, other):
        if isinstance(other, TileProxy):
            return self._id == other._id
        return False

    def type(self):
        if self._str is None:
            return None
        t = self._str[-1]
        if t in ('m', 'p', 's'):
            return t
        return "t"

    def number(self):
        if self._str is None:
            return None
        if self._str in HONOR_NUM_MJAI:
            return HONOR_NUM_MJAI[self._str]
        if self._str.startswith('0') and len(self._str) >= 2:
            return 5
        n = self._str[0]
        if n.isdigit():
            return int(n)
        return None

    def is_yaochu(self):
        t = self.type()
        n = self.number()
        return t == "t" or n == 1 or n == 9

    def remove_red(self):
        if self._str and self._str.startswith('0'):
            return TileProxy('5' + self._str[1])
        return TileProxy(self._str)

    def next(self, n):
        t = self.type()
        num = self.number()
        if t and t != "t" and num:
            new_num = num + n
            if 1 <= new_num <= 9:
                return TileProxy(f"{new_num}{t}")
        return None

    def next_for_dora(self):
        t = self.type()
        n = self.number()
        if (t == "t" and n == 4) or (t != "t" and n == 9):
            next_number = 1
        elif t == "t" and n == 7:
            next_number = 5
        else:
            if n is None:
                return None
            next_number = n + 1
        ttype = t if t != "t" else None
        if t == "t":
            honor_map = {1: 'E', 2: 'S', 3: 'W', 4: 'N', 5: 'P', 6: 'F', 7: 'C'}
            return TileProxy(honor_map.get(next_number, '?'))
        elif ttype:
            return TileProxy(f"{next_number}{ttype}")
        return None

    def to_string(self):
        return self._str

    def __repr__(self):
        return f"TileProxy({self._str})"


class ManueGameProxy:
    def __init__(self, game_state, my_seat):
        self._state = game_state
        self._my_seat = my_seat

    def players(self):
        return [ManuePlayerStateProxy(self._state, i) for i in range(4)]

    def oya(self):
        return ManuePlayerStateProxy(self._state, self._state.ju % 4)

    def bakaze(self):
        return TileProxy(f"E")

    def jikaze(self, player):
        winds = ["E", "S", "W", "N"]
        return TileProxy(winds[player.id % 4])

    def doras(self):
        result = []
        for t in self._state.doras:
            tp = TileProxy(t)
            next_tp = tp.next_for_dora()
            if next_tp:
                result.append(next_tp)
        return result

    def anpais(self, player):
        return [TileProxy(t) for t in self._state.river[player.id]]

    def visible_pais(self, me):
        all_tiles = []
        for t in self._state.doras:
            all_tiles.append(TileProxy(t))
        for t in self._state.my_hand:
            all_tiles.append(TileProxy(t))
        for seat in range(4):
            for t in self._state.river[seat]:
                all_tiles.append(TileProxy(t))
            for meld in self._state.melds[seat]:
                for t in meld.tiles:
                    all_tiles.append(TileProxy(t))
        return all_tiles

    def num_pipais(self):
        return self._state.left_tile_count

    def turn(self):
        return (ManueGameProxy.NUM_INITIAL_PIPAIS - self._state.left_tile_count) / 4

    def yakuhai_fan(self, pai, player):
        if pai.type() == "t":
            n = pai.number()
            if n >= 5:
                return 1
            if 1 <= n <= 4:
                wind_idx = n - 1
                if wind_idx == self._state.chang % 4 or wind_idx == player.id % 4:
                    return 1
        return 0

    def get_distance(self, player, chicha):
        return (player.id - chicha.id) % 4

    def chicha(self):
        return ManuePlayerStateProxy(self._state, self._state.ju % 4)

    def next_kyoku(self):
        wind_map = ['E', 'S', 'W', 'N']
        return {'bakaze': wind_map[self._state.chang % 4], 'kyoku_num': self._state.ju + 1}


ManueGameProxy.NUM_INITIAL_PIPAIS = 70


class ManuePlayerStateProxy:
    def __init__(self, state, seat):
        self._state = state
        self.id = seat
        self.tehais = [TileProxy(t) for t in state.my_hand] if seat == state.my_seat else []
        self.reach_state = "none"
        self.sutehais = [TileProxy(t) for t in state.river[seat]]
        self.reach_sutehai_index = -1
        for i, rs in enumerate(state.reach_states):
            if i == seat and rs.is_reach:
                self.reach_state = "accepted"
                if rs.reach_turn > 0 and rs.reach_turn <= len(state.river[seat]):
                    self.reach_sutehai_index = rs.reach_turn - 1
        self.furos = []
        self.score = state.scores[seat] if state.scores else 25000


class ExistingAIPlayer:
    def __init__(self, label, params):
        self._label = label
        self._params = params

    def clone(self, seat):
        return ExistingAIPlayerAdapter(seat, self._label, self._params)


class ExistingAIPlayerAdapter:
    def __init__(self, seat, label, params):
        self._seat = seat
        self._label = label
        self._params = params

    def clone(self, seat):
        return ExistingAIPlayerAdapter(seat, self._label, self._params)

    def decide_discard(self, state):
        state.my_seat = self._seat
        ev = Evaluator(state, self._params)
        tile = ev.best_discard(state.my_hand)
        if tile and tile in state.my_hand:
            return tile
        if state.my_hand:
            return state.my_hand[-1]
        return None

    def should_tsumo(self, state):
        return True

    def should_riichi(self, state):
        return False

    def should_ron(self, state):
        return True

    def should_call_meld(self, state, meld_type, tiles, from_seat):
        return False

    def should_kan(self, state):
        return False


def load_params(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, 'r', encoding='utf-8-sig') as f:
        return json.load(f)


def compute_pt(placement, final_score, room):
    placement_pt = PT_TABLES.get(room, PT_TABLES['jade']).get(placement, 0)
    score_bonus = (final_score - BASE_SCORE) // 1000
    return placement_pt + score_bonus


def run_single_seed(seed, base_dir, existing_params, room, game_type):
    from core.manue.manue_ai import ManueAI
    manue_ai = ManueAI(base_dir)
    existing_ai = ExistingAIPlayer("existing", existing_params)
    manue_adapter = ManueGameAdapter(0, manue_ai)

    players = [existing_ai.clone(i) for i in range(4)]
    players[0] = manue_adapter.clone(0)

    gr = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type).run_game()

    manue_seat = 0
    pl = gr.placement_of(manue_seat)
    pt = compute_pt(pl, gr.final_scores[manue_seat], room)

    return {
        'seed': seed,
        'placement': pl,
        'score': gr.final_scores[manue_seat],
        'pt': pt,
    }


def run_battle(seeds, base_dir, existing_params, room='jade', game_type='tonpu', verbose=False, workers=0):
    if workers == 0:
        workers = min(multiprocessing.cpu_count(), len(seeds))
    if workers <= 1:
        results = []
        for seed in seeds:
            r = run_single_seed(seed, base_dir, existing_params, room, game_type)
            results.append(r)
            if verbose:
                print(f"Seed {seed}: placement={r['placement']+1}, score={r['score']}, pt={r['pt']:+.0f}")
        return results

    results = []
    with ProcessPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_single_seed, seed, base_dir, existing_params, room, game_type): seed
                   for seed in seeds}
        done_count = 0
        for future in as_completed(futures):
            seed = futures[future]
            try:
                r = future.result()
                results.append(r)
                done_count += 1
                if verbose:
                    print(f"Seed {seed}: placement={r['placement']+1}, score={r['score']}, pt={r['pt']:+.0f} ({done_count}/{len(seeds)})")
            except Exception as e:
                print(f"Seed {seed} failed: {e}")
                done_count += 1
    return results


def main():
    parser = argparse.ArgumentParser(description='Manue vs Existing AI Battle')
    parser.add_argument('--seeds', default='1-10', help='Seed range (e.g., 1-100)')
    parser.add_argument('--game-type', default='tonpu', choices=['tonpu', 'hanchan'])
    parser.add_argument('--room', default='jade', choices=['gold', 'jade', 'throne'])
    parser.add_argument('--params', default='config/config_parameters.json', help='Existing AI params')
    parser.add_argument('--verbose', '-v', action='store_true')
    parser.add_argument('--parallel', type=int, default=0, help='Workers (0=auto)')
    args = parser.parse_args()

    if sys.stdout.encoding and sys.stdout.encoding.lower() in ('cp932', 'shift_jis'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')

    if '-' in args.seeds and ',' not in args.seeds:
        parts = args.seeds.split('-')
        seeds = list(range(int(parts[0]), int(parts[1]) + 1))
    elif ',' in args.seeds:
        seeds = [int(s.strip()) for s in args.seeds.split(',')]
    else:
        seeds = [int(args.seeds)]

    params = load_params(args.params)

    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')

    print(f"Manue vs Existing AI Battle")
    print(f"Seeds: {len(seeds)} ({seeds[0]}-{seeds[-1]})")
    print(f"Game: {args.game_type} / Room: {args.room}")
    print(f"Workers: {args.parallel if args.parallel > 0 else 'auto'}")
    print()

    start_time = time.time()
    results = run_battle(seeds, base_dir, params, args.room, args.game_type, args.verbose, args.parallel)
    elapsed = time.time() - start_time

    manue_pts = [r['pt'] for r in results]
    manue_placements = [r['placement'] for r in results]
    manue_scores = [r['score'] for r in results]

    avg_pt = sum(manue_pts) / len(manue_pts)
    total_pt = sum(manue_pts)
    avg_placement = sum(manue_placements) / len(manue_placements) + 1
    avg_score = sum(manue_scores) / len(manue_scores)

    placement_counts = [manue_placements.count(i) for i in range(4)]

    print()
    print("=== Battle Results ===")
    print(f"Seeds: {len(seeds)}")
    print(f"Time: {elapsed:.1f}s")
    print()
    print(f"Manue AI:")
    print(f"  Avg Placement: {avg_placement:.2f}")
    print(f"  Avg Score: {avg_score:.0f}")
    print(f"  Avg PT: {avg_pt:+.2f}/game")
    print(f"  Total PT: {total_pt:+.0f}")
    print()
    print(f"  1st: {placement_counts[0]} ({placement_counts[0]/len(seeds)*100:.1f}%)")
    print(f"  2nd: {placement_counts[1]} ({placement_counts[1]/len(seeds)*100:.1f}%)")
    print(f"  3rd: {placement_counts[2]} ({placement_counts[2]/len(seeds)*100:.1f}%)")
    print(f"  4th: {placement_counts[3]} ({placement_counts[3]/len(seeds)*100:.1f}%)")


if __name__ == '__main__':
    main()
