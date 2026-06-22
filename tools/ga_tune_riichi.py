# -*- coding: utf-8 -*-
"""
@title 天鳳人間ログのリーチ判断一致率最大化 GA
@description
    リーチ判断専用の GA ツール。
    fitness = リーチ判断の一致率(人間リーチを正しく判定 + 人間ダマテンを正しく判定)

    各局面で:
    - 人間がリーチ宣言 → AI.should_riichi() == True なら match
    - 人間がテンパイでリーチしなかった → AI.should_riichi() == False なら match
    - 人間がリーチ宣言したのにAIがFalse, あるいはその逆 → mismatch

    GENE_DEFS: リーチ判断に使うパラメータのみ
"""
from __future__ import annotations

import argparse
import copy
import json
import multiprocessing
import os
import random
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, THIS_DIR)

from tools.ga_tune import expand_params, mutate
from tools.ga_fitness import _load_ids, _load_blobs


def crossover_riichi(parent1: dict, parent2: dict) -> dict:
    """
    @title リーチ用遺伝子の一様交叉
    @description 2つの親個体からランダムに遺伝子を引き継ぎ、新しい個体を生成します。
    """
    child = {}
    for key in GENE_DEFS_RIICHI.keys():
        if random.random() < 0.5:
            child[key] = parent1[key]
        else:
            child[key] = parent2[key]
    return child


def mutate_riichi(params: dict, rate: float = 0.3, size: float = 0.2) -> dict:
    """
    @title リーチ用遺伝子の突然変異
    """
    new = dict(params)
    for key, (mn, mx, typ) in GENE_DEFS_RIICHI.items():
        if key not in new:
            new[key] = mn if typ == int else (mn + mx) / 2
        if random.random() > rate:
            continue
        cur = new[key]
        if typ == int:
            d = int((mx - mn) * size * (random.random() - 0.5) * 2)
            new[key] = max(mn, min(mx, cur + d))
        else:
            d = (mx - mn) * size * (random.random() - 0.5) * 2
            new[key] = round(max(mn, min(mx, cur + d)), 3)
    return new


POP_SIZE = 12
N_GENERATIONS = 10
MUTATE_RATE = 0.3
MUTATE_SIZE = 0.2
ELITE = 4
BASE_PARAMS_PATH = os.path.join(ROOT_DIR, 'config', 'config_parameters.json')
STATE_FILE = os.path.join(THIS_DIR, 'ga_riichi_state.json')


# リーチ判断に使うパラメータのみ
GENE_DEFS_RIICHI = {
    # _compare_riichi_vs_damaten 内で使用
    'RIICHI_URA_MULT': (1.0, 1.5, float),
    'RIICHI_TSUMO_RATE': (0.2, 0.6, float),
    'RIICHI_FOLD_RATE': (0.2, 0.8, float),
    'RIICHI_STICK_COST': (0.1, 0.8, float),
    'RIICHI_OPP_REACH_PENALTY': (0.5, 1.0, float),
    'RIICHI_LATE_PENALTY': (0.3, 1.0, float),
    'RIICHI_DEFENSE_COST': (0.0, 0.5, float),
    'RIICHI_MODE_AGGRO': (0.0, 0.5, float),
    'DAMATEN_TSUMO_RATE': (0.1, 0.5, float),
    'DAMATEN_FLEX_BONUS': (0, 300, int),
    'DAMATEN_YAKU_IMP_BONUS': (0.0, 0.5, float),
    'DAMATEN_WAIT_IMP_BONUS': (0.0, 0.5, float),
    'RIICHI_WAIT_RYANMEN': (0.1, 0.6, float),
    'RIICHI_WAIT_SHANPON': (0.0, 0.3, float),
    'RIICHI_WAIT_KANCHAN': (0.0, 0.3, float),
    'RIICHI_WAIT_PENCHAN': (0.0, 0.4, float),
    'RIICHI_WAIT_TANKI': (0.0, 0.2, float),

    # ルールベース閾値(整数)
    'RIICHI_HAN_HIGH_THRESH': (3, 6, int),
    'RIICHI_LATE_TURN_DAMATEN': (10, 16, int),
    'RIICHI_LATE_WAIT_MAX': (2, 7, int),
    'RIICHI_VERY_LATE_TURN': (12, 18, int),
    'RIICHI_VERY_LATE_WAIT_MAX': (4, 8, int),
    'RIICHI_HAN_MID_THRESH': (2, 4, int),
    'RIICHI_WAIT_GOOD_THRESH': (5, 10, int),
    'RIICHI_WAIT_MIN_MID': (2, 6, int),
    'RIICHI_DORA_MID_THRESH': (0, 2, int),
    'RIICHI_YAKUHAI_MID_THRESH': (2, 4, int),
    'RIICHI_DORA_DOUBLE_THRESH': (1, 3, int),
    'RIICHI_TURN_MIN_MID': (1, 4, int),
    'RIICHI_TURN_MAX_MID': (8, 14, int),
    'RIICHI_WAIT_GOOD_LOW': (5, 10, int),
    'RIICHI_TURN_MIN_LOW': (1, 4, int),
    'RIICHI_TURN_MAX_LOW': (8, 14, int),
    'RIICHI_WAIT_VERY_LOW': (7, 13, int),
    'RIICHI_URA_THRESH': (0, 3, int),
    'RIICHI_DORA_LOW_THRESH': (1, 3, int),
    'RIICHI_YAKUHAI_LOW_THRESH': (2, 4, int),
    'RIICHI_LAST_WAIT_LOW': (3, 8, int),
    'RIICHI_LAST_TURN': (8, 14, int),
}


# ------------------------------------------------------------
# 1 ログ内のリーチ判断を評価
# ------------------------------------------------------------
def evaluate_riichi_in_log(blob, params) -> Tuple[int, int, int, int]:
    """
    @title 1 ログのリーチ判断評価
    @description 各局面で:
        - 人間がリーチ宣言 → AI.should_riichi() == True で match
        - 人間がテンパイでリーチせず → AI.should_riichi() == False で match
    @param {bytes} blob - 天鳳ログのBLOB
    @param {dict} params - パラメータ
    @returns {tuple} (riichi_total, riichi_match, damaten_total, damaten_match)
    """
    from core.game_state import GameState
    from core.evaluator import Evaluator
    from core.str_converter import hand_to_counts
    from core.strategy_manager import ShantenCalculator
    from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

    riichi_total = 0  # 人間がリーチ宣言した局面
    riichi_match = 0  # そのうちAIもリーチ推奨
    damaten_total = 0  # 人間がテンパイでダマテンした局面
    damaten_match = 0  # そのうちAIもダマテン推奨

    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except Exception:
        return (0, 0, 0, 0)
    if n_rounds == 0:
        return (0, 0, 0, 0)

    actions = json_dict.get('detail_records', {}).get('actions', [])
    if not actions:
        return (0, 0, 0, 0)

    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    for a in actions:
        if a.get('type') != 1:
            continue
        r = a.get('result', {})
        cls = r.get('class_name', '')
        d = r.get('data', {})

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(
                    d.get('chang', 0), d.get('ju', 0), d.get('ben', 0), d.get('liqibang', 0),
                    d.get(k, []), d.get('scores', [25000] * 4), d.get('leftTileCount', 70),
                    d.get('doras', [])
                )
                states[s].chang = d.get('chang', 0)
                states[s].ju = d.get('ju', 0)
            oya = d.get('oya', 0)
            states[oya].dealer_seat = oya
            for s in range(4):
                if s != oya: states[s].dealer_seat = oya
            awaiting = [True] * 4
            continue

        if cls == 'RecordDealTile':
            seat = d.get('seat')
            tile = d.get('tile')
            if seat is None or tile is None:
                continue
            for s in range(4):
                if s == seat:
                    states[s].on_self_draw(tile)
                else:
                    states[s].on_opponent_draw(seat)
            if 0 <= seat < 4:
                awaiting[seat] = True
            continue

        if cls == 'RecordDiscardTile':
            seat = d.get('seat')
            tile = d.get('tile')
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if seat is None or seat < 0 or seat >= 4:
                continue

            if isL and awaiting[seat]:
                # 人間リーチ宣言
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    if sh <= 0:
                        try:
                            ev = Evaluator(states[seat], params)
                            ai_should = ev.should_riichi()
                            riichi_total += 1
                            if ai_should:
                                riichi_match += 1
                        except Exception:
                            pass

            elif not isL and awaiting[seat]:
                # 人間テンパイでダマテンしたかチェック
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    if sh <= 0:
                        # 自分の手番でテンパイしているがリーチ宣言していない
                        try:
                            ev = Evaluator(states[seat], params)
                            ai_should = ev.should_riichi()
                            damaten_total += 1
                            if not ai_should:
                                damaten_match += 1
                        except Exception:
                            pass

            for s in range(4):
                if s == seat:
                    states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4:
                awaiting[seat] = False
            continue

        if cls == 'RecordChiPengGang':
            call_type = d.get('type')
            call_seat = d.get('seat')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tileStates', [])
            if 0 <= call_seat < 4:
                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls in ('RecordHule', 'RecordNoTile'):
            for s in range(4):
                awaiting[s] = False
            continue

    return (riichi_total, riichi_match, damaten_total, damaten_match)


# ------------------------------------------------------------
# worker: (pop_idx, blob, params) -> (pop_idx, rt, rm, dt, dm)
# ------------------------------------------------------------
def _eval_worker(args):
    pop_idx, blob, params = args
    try:
        rt, rm, dt, dm = evaluate_riichi_in_log(blob, params)
        return (pop_idx, rt, rm, dt, dm)
    except Exception as e:
        return (pop_idx, 0, 0, 0, 0)


# ------------------------------------------------------------
# 1 個体の評価: 全ログを逐次処理
# ------------------------------------------------------------
def evaluate_individual_riichi(flat_params: dict, blobs: list, base_params: dict) -> dict:
    expanded = expand_params(flat_params, base_params)
    sum_rt = 0; sum_rm = 0; sum_dt = 0; sum_dm = 0
    for blob in blobs:
        rt, rm, dt, dm = evaluate_riichi_in_log(blob, expanded)
        sum_rt += rt; sum_rm += rm; sum_dt += dt; sum_dm += dm
    total = sum_rt + sum_dt
    match = sum_rm + sum_dm
    return {
        'fitness': match / total if total else 0.0,
        'riichi_total': sum_rt, 'riichi_match': sum_rm,
        'damaten_total': sum_dt, 'damaten_match': sum_dm,
    }


def _eval_one_individual_in_proc(args):
    i, flat, blobs_local, base_params = args
    expanded = expand_params(flat, base_params)
    sum_rt = 0; sum_rm = 0; sum_dt = 0; sum_dm = 0
    for blob in blobs_local:
        rt, rm, dt, dm = evaluate_riichi_in_log(blob, expanded)
        sum_rt += rt; sum_rm += rm; sum_dt += dt; sum_dm += dm
    return (i, sum_rt, sum_rm, sum_dt, sum_dm)


def _eval_population(pop: List[dict], blobs: list, n_workers: int, base_params: dict,
                     fitness_cache: dict = None) -> List[dict]:
    if fitness_cache is None:
        fitness_cache = {}

    new_pop_indices = []
    results = [None] * len(pop)
    cached_count = 0
    for i, fp in enumerate(pop):
        key = json.dumps(fp, sort_keys=True, ensure_ascii=False)
        if key in fitness_cache:
            cached = fitness_cache[key]
            results[i] = {'flat': fp, **cached, 'from_cache': True}
            cached_count += 1
        else:
            new_pop_indices.append(i)

    if new_pop_indices:
        items = [(i, pop[i], blobs, base_params) for i in new_pop_indices]
        pop_results = [{
            'rt': 0, 'rm': 0, 'dt': 0, 'dm': 0
        } for _ in pop]
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(_eval_one_individual_in_proc, item) for item in items]
            for fut in as_completed(futs):
                i, rt, rm, dt, dm = fut.result()
                pop_results[i]['rt'] += rt
                pop_results[i]['rm'] += rm
                pop_results[i]['dt'] += dt
                pop_results[i]['dm'] += dm
        for i in new_pop_indices:
            r = pop_results[i]
            total = r['rt'] + r['dt']
            match = r['rm'] + r['dm']
            res = {
                'fitness': match / total if total else 0.0,
                'riichi_total': r['rt'], 'riichi_match': r['rm'],
                'damaten_total': r['dt'], 'damaten_match': r['dm'],
            }
            results[i] = {'flat': pop[i], **res, 'from_cache': False}
            key = json.dumps(pop[i], sort_keys=True, ensure_ascii=False)
            fitness_cache[key] = res
    results.sort(key=lambda r: r['fitness'], reverse=True)
    return results


def make_population(base_params: dict, pop_size: int) -> List[dict]:
    init_flat = {}
    for k, (mn, mx, typ) in GENE_DEFS_RIICHI.items():
        val = base_params.get(k, None)
        if val is None:
            val = int((mn + mx) / 2) if typ == int else round((mn + mx) / 2, 3)
        init_flat[k] = val
    pop = [init_flat]
    for _ in range(pop_size - 1):
        pop.append(mutate_riichi(init_flat, rate=MUTATE_RATE, size=MUTATE_SIZE))
    return pop


def make_next_gen(ranked: List[dict], pop_size: int) -> List[dict]:
    next_pop = [r['flat'] for r in ranked[:ELITE]]
    while len(next_pop) < pop_size:
        a = random.choice(ranked[:pop_size // 2])['flat']
        b = random.choice(ranked[:pop_size // 2])['flat']
        child = crossover_riichi(a, b)
        child = mutate_riichi(child, rate=0.5, size=0.3)  # 高めの変異率
        next_pop.append(child)
    return next_pop


def save_state(gen: int, ranked: List[dict], history: List[dict]):
    state = {
        'gen': gen,
        'pop': [{'flat': r['flat'], 'fitness': r['fitness'],
                 'riichi_match': r.get('riichi_match'), 'riichi_total': r.get('riichi_total'),
                 'damaten_match': r.get('damaten_match'), 'damaten_total': r.get('damaten_total')}
                for r in ranked],
        'history': history,
        'base_params_path': BASE_PARAMS_PATH,
    }
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def load_state():
    with open(STATE_FILE, encoding='utf-8') as f:
        s = json.load(f)
    return s['gen'], s['pop'], s.get('history', [])


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pop-size', type=int, default=POP_SIZE)
    p.add_argument('--gens', type=int, default=N_GENERATIONS)
    p.add_argument('--workers', type=int, default=min(6, multiprocessing.cpu_count()))
    p.add_argument('--id-file', default=os.path.join(THIS_DIR, '_log_ids_1000.txt'))
    p.add_argument('--db', default=os.path.join(ROOT_DIR, 'diffusion-ai', 'data', 'raw', 'tenhou_logs.db'))
    p.add_argument('--mutate-rate', type=float, default=MUTATE_RATE)
    p.add_argument('--mutate-size', type=float, default=MUTATE_SIZE)
    p.add_argument('--elite', type=int, default=ELITE)
    p.add_argument('--restart', action='store_true')
    p.add_argument('--seed', type=int, default=42)
    args = p.parse_args()

    random.seed(args.seed)

    with open(BASE_PARAMS_PATH, encoding='utf-8') as f:
        base_params = json.load(f)

    ids = _load_ids(args.id_file)
    rows = _load_blobs(args.db, ids)
    blobs = [r[1] for r in rows]
    print(f'[setup] {len(blobs)} logs, pop={args.pop_size}, gens={args.gens}, '
          f'workers={args.workers}, seed={args.seed}')

    fitness_cache: dict = {}

    if os.path.exists(STATE_FILE) and not args.restart:
        start_gen, prev_pop, history = load_state()
        pop = [r['flat'] for r in prev_pop]
        print(f'[resume] gen={start_gen} pop_size={len(pop)}')
    else:
        pop = make_population(base_params, args.pop_size)
        start_gen = 0
        history = []
        print(f'[init] pop_size={len(pop)}')

    for gen in range(start_gen, start_gen + args.gens):
        t0 = time.time()
        ranked = _eval_population(pop, blobs, args.workers, base_params, fitness_cache)
        elapsed = time.time() - t0
        n_cached = sum(1 for r in ranked if r.get('from_cache'))
        n_new = len(ranked) - n_cached
        best = ranked[0]
        worst = ranked[-1]
        avg = sum(r['fitness'] for r in ranked) / len(ranked)
        history.append({
            'gen': gen,
            'best_fitness': best['fitness'],
            'worst_fitness': worst['fitness'],
            'avg_fitness': avg,
            'elapsed_sec': elapsed,
            'cache_size': len(fitness_cache),
            'cached': n_cached,
            'new': n_new,
            'best_riichi': f"{best.get('riichi_match', 0)}/{best.get('riichi_total', 0)}",
            'best_damaten': f"{best.get('damaten_match', 0)}/{best.get('damaten_total', 0)}",
        })
        print(f'[gen {gen}] best={best["fitness"]*100:.2f}% avg={avg*100:.2f}% '
              f'cache={len(fitness_cache)} hit={n_cached}/{len(ranked)} '
              f'time={elapsed:.0f}s '
              f'riichi={best.get("riichi_match", 0)}/{best.get("riichi_total", 0)} '
              f'damaten={best.get("damaten_match", 0)}/{best.get("damaten_total", 0)}', flush=True)
        save_state(gen, ranked, history)
        pop = make_next_gen(ranked, args.pop_size)

    print('[done] best params saved to', STATE_FILE)


if __name__ == '__main__':
    main()
