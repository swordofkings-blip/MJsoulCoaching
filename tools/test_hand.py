# -*- coding: utf-8 -*-
"""特定の局面をAIに評価させるテストツール。

使い方:
  python tools/test_hand.py <局面JSONファイル>
  python tools/test_hand.py --interactive  (対話モード)

局面JSONのフォーマット:
  {
    "chang": 0, "ju": 0, "ben": 0,
    "my_seat": 0,
    "scores": [25000, 25000, 25000, 25000],
    "hand": ["2m","2m","4m","5m","6m","7m","7m","2p","7p","8p","9p","8s","8s"],
    "tsumo": "5p",
    "dora_indicator": "5m",
    "left_tile_count": 53,
    "tsumo_count": 5,
    "river": [
        ["北","東","2s","1p"],
        ["東","1p","9p","7p"],
        ["北","9m","9p","9p"],
        ["西","1s","9m","6s"]
    ],
    "melds": [[],[],[],[]],
    "reach_states": [false,false,false,false]
  }
"""
from __future__ import annotations
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, Meld
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, dora_indicator_to_dora


def load_config(path: str) -> dict:
    with open(path, encoding='utf-8') as f:
        return json.load(f)


def setup_state(config: dict) -> GameState:
    state = GameState()
    state.chang = config.get('chang', 0)
    state.ju = config.get('ju', 0)
    state.ben = config.get('ben', 0)
    state.liqibang = config.get('liqibang', 0)
    state.my_seat = config.get('my_seat', 0)
    state.scores = list(config.get('scores', [25000]*4))
    state.left_tile_count = config.get('left_tile_count', 70)
    state.tsumo_count = config.get('tsumo_count', 0)

    dora_indicator = config.get('dora_indicator', '1m')
    state.doras = [dora_indicator]

    hand = list(config.get('hand', []))
    tsumo = config.get('tsumo')
    if tsumo:
        hand.append(tsumo)
    state.my_hand = hand

    rivers = config.get('river', [[],[],[],[]])
    for s in range(4):
        state.river[s] = list(rivers[s]) if s < len(rivers) else []
        state.river_moqie[s] = [False] * len(state.river[s])

    melds_data = config.get('melds', [[],[],[],[]])
    state.melds = [[], [], [], []]
    for s in range(4):
        if s < len(melds_data):
            for m in melds_data[s]:
                if isinstance(m, dict):
                    state.melds[s].append(Meld(
                        type=int(m.get('type', 0)),
                        tiles=list(m.get('tiles', [])),
                        froms=list(m.get('froms', [])),
                        tile_states=list(m.get('tile_states', [])),
                    ))
                elif isinstance(m, list):
                    state.melds[s].append(Meld(type=0, tiles=list(m), froms=[], tile_states=[]))
    state.my_melds = list(state.melds[state.my_seat])

    reach_data = config.get('reach_states', [False]*4)
    for s in range(4):
        state.reach_states[s].is_reach = bool(reach_data[s]) if s < len(reach_data) else False

    return state


def evaluate_hand(state: GameState, params: dict):
    evaluator = Evaluator(state, params=params)
    unique_tiles = list(dict.fromkeys(state.my_hand))
    scored = []
    for t in unique_tiles:
        score = evaluator.evaluate_tile(t)
        details = evaluator.details.get(t, [])
        scored.append((score, t, details))
    scored.sort(key=lambda x: (-x[0], x[1]))

    best_score, best_tile, _ = scored[0]

    print(f"\n{'='*60}")
    print(f"戦略モード: {evaluator.strategy.get_strategy_mode()}")
    ds = evaluator.strategy.get_strategy_details()
    print(f"攻撃度(base_attack): {ds['base_attack']}")
    print(f"最大脅威度(max_threat): {ds['max_threat']}")
    print(f"プッシュスコア(push_score): {ds['push_score']}")
    print(f"{'='*60}")
    print(f"{'打牌':>6} | {'総合スコア':>10} | 内訳")
    print(f"{'-'*6}-+-{'-'*10}-+-{'-'*60}")
    for score, tile, details in scored:
        mark = " ★" if tile == best_tile else ""
        d_short = details[0][:55] if details else ""
        print(f"{tile:>6} | {score:>10.1f}{mark} | {d_short}")
        for d in details[1:]:
            print(f"{'':>6} | {'':>10} | {d}")
    print()

    # 推奨と2位の差
    if len(scored) >= 2:
        diff = scored[0][0] - scored[1][0]
        print(f"推奨: {best_tile} (スコア {best_score:.1f})")
        print(f"2位: {scored[1][1]} (スコア {scored[1][0]:.1f}, 差 {diff:.1f})")
    else:
        print(f"推奨: {best_tile} (スコア {best_score:.1f})")

    return evaluator, scored


def main():
    import argparse
    parser = argparse.ArgumentParser(description='特定局面の何切る評価')
    parser.add_argument('config_file', nargs='?', help='局面JSONファイル')
    parser.add_argument('--params', '-p', default=None, help='パラメータJSON(省略時はconfig_parameters.json)')
    parser.add_argument('--set', '-s', action='append', default=[], help='パラメータ上書き 例: -s HONOR_DISCARD_BONUS=200')
    parser.add_argument('--interactive', '-i', action='store_true', help='対話モード')
    args = parser.parse_args()

    params_path = args.params or os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                               '..', 'config', 'config_parameters.json')
    params = load_config(params_path)

    for kv in args.set:
        if '=' not in kv:
            continue
        k, v = kv.split('=', 1)
        try:
            params[k] = int(v)
        except ValueError:
            try:
                params[k] = float(v)
            except ValueError:
                params[k] = v

    if args.interactive:
        print("対話モード: 局面JSONを入力 (Ctrl+Z+Enter で終了)")
        for line in sys.stdin:
            line = line.strip()
            if not line:
                continue
            try:
                config = json.loads(line)
                state = setup_state(config)
                evaluate_hand(state, params)
            except Exception as e:
                print(f"エラー: {e}")
        return

    if not args.config_file:
        print("使用方法: python tools/test_hand.py <局面JSON> [--params <パラメータJSON>]")
        print("  または: python tools/test_hand.py --interactive")
        return

    with open(args.config_file, encoding='utf-8') as f:
        config = json.load(f)

    state = setup_state(config)
    evaluate_hand(state, params)


if __name__ == '__main__':
    main()
