# -*- coding: utf-8 -*-
"""
@title 天鳳人間ログ一致率最大化 GA (高速版)
@description
    固定 10 ログ (tools/_log_ids_ga.txt) での OurAI vs 人間打牌の
    総合一致率を fitness として遺伝的アルゴリズムを回す。

    高速化:
    - 1 個体の中もログ単位で並列 (ga_tune.py と同じパターン)
    - 個体間も並列 (ProcessPoolExecutor)
    - 6 コアマシンで最大 6 タスクを同時実行
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

from tools.ga_tune import GENE_DEFS, expand_params, mutate, crossover
from tools.ga_fitness import _load_ids, _load_blobs, DEFAULT_GA_ID_FILE


POP_SIZE = 12
N_GENERATIONS = 10
MUTATE_RATE = 0.3
MUTATE_SIZE = 0.2
ELITE = 4  # キャッシュヒットを増やすため多めに
BASE_PARAMS_PATH = os.path.join(ROOT_DIR, 'config', 'config_parameters.json')
STATE_FILE = os.path.join(THIS_DIR, 'ga_tenhou_state.json')
SKIP_MELD = False  # --skip-meld フラグで上書き


# ------------------------------------------------------------
# worker: (pop_idx, blob, params) -> (pop_idx, td, dm, tm, mm)
# ------------------------------------------------------------
def _eval_worker(args):
    pop_idx, blob, params = args
    try:
        from tenhou_xml_to_actions import tenhou_blob_to_actions
        from tenhou_process_dict import process_dict
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0:
            return (pop_idx, 0, 0, 0, 0)
        _lines, td, dm, tm, mm, _fname = process_dict(json_dict, params)
        return (pop_idx, td, dm, tm, mm)
    except Exception as e:
        return (pop_idx, 0, 0, 0, 0)


# ------------------------------------------------------------
# 1 個体の評価: 全ログを並列で処理
# ------------------------------------------------------------
def evaluate_individual(flat_params: dict, blobs: list, n_workers: int, base_params: dict,
                         skip_meld: bool = False) -> dict:
    """1 個体の中は逐次処理 (10 ログを連続実行して ShantenCalculator キャッシュを温存)"""
    from tenhou_process_dict import process_dict
    from tenhou_xml_to_actions import tenhou_blob_to_actions
    expanded = expand_params(flat_params, base_params)
    sum_td = 0; sum_dm = 0; sum_tm = 0; sum_mm = 0
    for blob in blobs:
        json_dict, _ = tenhou_blob_to_actions(blob)
        _lines, td, dm, tm, mm, _fname = process_dict(json_dict, expanded)
        sum_td += td; sum_dm += dm; sum_tm += tm; sum_mm += mm
    if skip_meld:
        total = sum_td
        match = sum_dm
    else:
        total = sum_td + sum_tm
        match = sum_dm + sum_mm
    return {
        'fitness': match / total if total else 0.0,
        'discard_total': sum_td, 'discard_match': sum_dm,
        'meld_total': sum_tm, 'meld_match': sum_mm,
    }


def _eval_population(pop: List[dict], blobs: list, n_workers: int, base_params: dict,
                    fitness_cache: dict = None) -> List[dict]:
    """pop 内の全個体を並列評価。
    1 個体内 10 ログを N 個に分割して、計 pop_size * N タスクで並列評価。
    動的負荷分散が効く + 同一ワーカー内なら ShantenCalculator キャッシュも効く。

    fitness_cache: {param_key: result_dict} の dict。同じ遺伝子は再評価せず
    キャッシュから即座に返す (エリート保存などで世代をまたいで重複するため)。

    各 result dict に `from_cache: bool` フラグを付与。
    """
    if fitness_cache is None:
        fitness_cache = {}

    # キャッシュヒットする個体と新規評価が必要な個体を分ける
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
        # 1 個体 1 タスク (個体内 10 ログを逐次) で各 worker 1 個体を処理。
        # n_workers = pop_size に近いとき、各 worker は 1 個体を担当し、
        # 個体内の ShantenCalculator キャッシュが効く。
        items = [(i, pop[i], blobs, base_params) for i in new_pop_indices]
        pop_results = [{
            'td': 0, 'dm': 0, 'tm': 0, 'mm': 0
        } for _ in pop]
        with ProcessPoolExecutor(max_workers=n_workers) as ex:
            futs = [ex.submit(_eval_one_individual_in_proc, item) for item in items]
            for fut in as_completed(futs):
                i, td, dm, tm, mm = fut.result()
                pop_results[i]['td'] += td
                pop_results[i]['dm'] += dm
                pop_results[i]['tm'] += tm
                pop_results[i]['mm'] += mm
        # SKIP_MELD フラグ（モジュールグローバル変数）で fitness 計算を切り替え
        skip_meld = getattr(sys.modules[__name__], 'SKIP_MELD', False)
        for i in new_pop_indices:
            r = pop_results[i]
            if skip_meld:
                total = r['td']
                match = r['dm']
            else:
                total = r['td'] + r['tm']
                match = r['dm'] + r['mm']
            res = {
                'fitness': match / total if total else 0.0,
                'discard_total': r['td'], 'discard_match': r['dm'],
                'meld_total': r['tm'], 'meld_match': r['mm'],
            }
            results[i] = {'flat': pop[i], **res, 'from_cache': False}
            key = json.dumps(pop[i], sort_keys=True, ensure_ascii=False)
            fitness_cache[key] = res
    results.sort(key=lambda r: r['fitness'], reverse=True)
    return results


def _eval_one_individual_in_proc(args):
    """(pop_idx, flat_params, blobs, base_params) -> (pop_idx, td, dm, tm, mm)"""
    i, flat, blobs_local, base_params = args
    from tenhou_process_dict import process_dict
    from tenhou_xml_to_actions import tenhou_blob_to_actions
    expanded = expand_params(flat, base_params)
    sum_td = 0; sum_dm = 0; sum_tm = 0; sum_mm = 0
    for blob in blobs_local:
        json_dict, _ = tenhou_blob_to_actions(blob)
        _lines, td, dm, tm, mm, _fname = process_dict(json_dict, expanded)
        sum_td += td; sum_dm += dm; sum_tm += tm; sum_mm += mm
    return (i, sum_td, sum_dm, sum_tm, sum_mm)


def _eval_one_chunk(args):
    """(pop_idx, flat_params, blobs_chunk, base_params) -> (pop_idx, td, dm, tm, mm)"""
    i, flat, blobs_chunk, base_params = args
    from tenhou_process_dict import process_dict
    from tenhou_xml_to_actions import tenhou_blob_to_actions
    expanded = expand_params(flat, base_params)
    sum_td = 0; sum_dm = 0; sum_tm = 0; sum_mm = 0
    for blob in blobs_chunk:
        json_dict, _ = tenhou_blob_to_actions(blob)
        _lines, td, dm, tm, mm, _fname = process_dict(json_dict, expanded)
        sum_td += td; sum_dm += dm; sum_tm += tm; sum_mm += mm
    return (i, sum_td, sum_dm, sum_tm, sum_mm)


def make_population(base_params: dict, pop_size: int) -> List[dict]:
    init_flat = {}
    for k, (mn, mx, typ) in GENE_DEFS.items():
        if k.startswith('meld_defense_'):
            sub = k[len('meld_defense_'):]
            val = base_params.get('yaku_strategy', {}).get('meld_defense', {}).get(sub, None)
        else:
            val = base_params.get(k, None)
        if val is None:
            val = int((mn + mx) / 2) if typ == int else round((mn + mx) / 2, 3)
        init_flat[k] = val
    pop = [init_flat]
    for _ in range(pop_size - 1):
        pop.append(mutate(init_flat, rate=MUTATE_RATE, size=MUTATE_SIZE))
    return pop


def make_next_gen(ranked: List[dict], pop_size: int) -> List[dict]:
    """エリート保存 + 交叉 + 突然変異。
    キャッシュヒットを最大化するため、エリートを多めに保存。"""
    next_pop = [r['flat'] for r in ranked[:ELITE]]
    while len(next_pop) < pop_size:
        a = random.choice(ranked[:pop_size // 2])['flat']
        b = random.choice(ranked[:pop_size // 2])['flat']
        child = crossover(a, b)
        child = mutate(child, rate=MUTATE_RATE, size=MUTATE_SIZE)
        next_pop.append(child)
    return next_pop


def save_state(gen: int, ranked: List[dict], history: List[dict]):
    state = {
        'gen': gen,
        'pop': [{'flat': r['flat'], 'fitness': r['fitness'],
                 'discard_match': r.get('discard_match'), 'discard_total': r.get('discard_total'),
                 'meld_match': r.get('meld_match'), 'meld_total': r.get('meld_total')}
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
    p.add_argument('--workers', type=int, default=min(6, multiprocessing.cpu_count()),
                   help='ワーカー数 (デフォルト 6, CPU コア数上限)')
    p.add_argument('--id-file', default=DEFAULT_GA_ID_FILE)
    p.add_argument('--db', default=os.path.join(ROOT_DIR, 'diffusion-ai', 'data', 'raw', 'tenhou_logs.db'))
    p.add_argument('--mutate-rate', type=float, default=MUTATE_RATE)
    p.add_argument('--mutate-size', type=float, default=MUTATE_SIZE)
    p.add_argument('--elite', type=int, default=ELITE)
    p.add_argument('--restart', action='store_true')
    p.add_argument('--seed', type=int, default=42, help='乱数シード (再現性のため)')
    p.add_argument('--skip-meld', action='store_true', help='副露を fitness から除外して打牌のみで評価')
    args = p.parse_args()

    # スレッド間で共有するグローバルフラグ (read-only なので安全)
    global SKIP_MELD
    SKIP_MELD = args.skip_meld

    random.seed(args.seed)

    with open(BASE_PARAMS_PATH, encoding='utf-8') as f:
        base_params = json.load(f)

    ids = _load_ids(args.id_file)
    rows = _load_blobs(args.db, ids)
    blobs = [r[1] for r in rows]
    mode_str = '打牌のみ' if args.skip_meld else '打牌+副露'
    print(f'[setup] {len(blobs)} logs, pop={args.pop_size}, gens={args.gens}, '
          f'workers={args.workers}, seed={args.seed}, mode={mode_str}')

    fitness_cache: dict = {}  # {param_key: result_dict}

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
            'best_disc': f"{best.get('discard_match', 0)}/{best.get('discard_total', 0)}",
            'best_meld': f"{best.get('meld_match', 0)}/{best.get('meld_total', 0)}" if not SKIP_MELD else 'skipped',
        })
        meld_str = '' if SKIP_MELD else f' meld={best.get("meld_match", 0)}/{best.get("meld_total", 0)}'
        print(f'[gen {gen}] best={best["fitness"]*100:.2f}% avg={avg*100:.2f}% '
              f'cache={len(fitness_cache)} hit={n_cached}/{len(ranked)} '
              f'time={elapsed:.0f}s '
              f'disc={best.get("discard_match", 0)}/{best.get("discard_total", 0)}'
              f'{meld_str}', flush=True)
        save_state(gen, ranked, history)
        pop = make_next_gen(ranked, args.pop_size)

    print('[done] best params saved to', STATE_FILE)


if __name__ == '__main__':
    main()
