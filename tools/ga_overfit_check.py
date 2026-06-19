# -*- coding: utf-8 -*-
"""
@title GA best params の 30 ログオーバーフィットチェック
@description
    ga_tenhou_state.json の最良個体を 30 ログ (overfit セット) で再評価し、
    GA 評価 (10 ログ) との一致率差を報告する。
    差が大きければオーバーフィット。
"""
from __future__ import annotations

import argparse
import json
import os
import sys

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, THIS_DIR)

from tools.ga_tune import expand_params
from tools.ga_fitness import evaluate_fitness, DEFAULT_GA_ID_FILE
from tools.tenhou_match_rate import _query_logs, _worker_process_blob
from concurrent.futures import ProcessPoolExecutor, as_completed
import time


OVERFIT_ID_FILE = os.path.join(THIS_DIR, '_log_ids_overfit.txt')
STATE_FILE = os.path.join(THIS_DIR, 'ga_tenhou_state.json')
OUT_FILE = os.path.join(THIS_DIR, 'overfit_check.json')


def evaluate_with_blobs(blobs, params, workers):
    work_items = [(bid, blob, params) for bid, blob in blobs]
    sum_td = 0; sum_dm = 0; sum_tm = 0; sum_mm = 0
    logs_ok = 0
    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_worker_process_blob, item) for item in work_items]
        for fut in as_completed(futures):
            log_id, n_rounds, td, dm, tm, mm, status = fut.result()
            if status == 'ok':
                logs_ok += 1
                sum_td += td
                sum_dm += dm
                sum_tm += tm
                sum_mm += mm
    total = sum_td + sum_tm
    match = sum_dm + sum_mm
    return {
        'discard_total': sum_td, 'discard_match': sum_dm,
        'meld_total': sum_tm, 'meld_match': sum_mm,
        'overall_total': total, 'overall_match': match,
        'fitness': match / total if total else 0.0,
        'logs_ok': logs_ok,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', default=STATE_FILE, help='GA state ファイル')
    p.add_argument('--id-file', default=OVERFIT_ID_FILE)
    p.add_argument('--ga-id-file', default=DEFAULT_GA_ID_FILE, help='GA 評価時の id ファイル')
    p.add_argument('--db', default=os.path.join(ROOT_DIR, 'diffusion-ai', 'data', 'raw', 'tenhou_logs.db'))
    p.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 4) - 1))
    p.add_argument('--out', default=OUT_FILE)
    args = p.parse_args()

    with open(args.state, encoding='utf-8') as f:
        state = json.load(f)

    with open(os.path.join(ROOT_DIR, 'config', 'config_parameters.json'), encoding='utf-8') as f:
        base_params = json.load(f)

    best = state['pop'][0]
    flat = best['flat']
    ga_fitness = best.get('fitness')
    expanded = expand_params(flat, base_params)

    print(f'[overfit] best individual: fitness(GA 10)={ga_fitness*100:.2f}% '
          f'disc={best.get("discard_match")}/{best.get("discard_total")} '
          f'meld={best.get("meld_match")}/{best.get("meld_total")}')

    # 30 ログで再評価
    t0 = time.time()
    rows = _query_logs(args.db, 30, 0, True, 0, args.id_file)
    blobs = [(r[0], r[1]) for r in rows]
    res30 = evaluate_with_blobs(blobs, expanded, args.workers)
    elapsed30 = time.time() - t0
    print(f'[overfit] 30 logs: fitness={res30["fitness"]*100:.2f}% '
          f'disc={res30["discard_match"]}/{res30["discard_total"]} '
          f'meld={res30["meld_match"]}/{res30["meld_total"]} time={elapsed30:.0f}s')

    # GA 10 ログで再評価 (state の fitness と一致するか検算)
    t0 = time.time()
    ga_res = evaluate_fitness(expanded, id_file=args.ga_id_file, workers=args.workers, verbose=False)
    elapsed10 = time.time() - t0
    print(f'[overfit] 10 logs re-eval: fitness={ga_res["fitness"]*100:.2f}% time={elapsed10:.0f}s')

    diff = res30['fitness'] - ga_res['fitness']
    print(f'[overfit] diff (30 - 10): {diff*100:+.2f}% '
          f'({"overfit" if diff < -0.01 else "ok"})')

    out = {
        'ga_fitness_10': ga_res['fitness'],
        'overfit_fitness_30': res30['fitness'],
        'diff': diff,
        'ga_10': ga_res,
        'overfit_30': res30,
        'best_params': flat,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f'[overfit] saved: {args.out}')


if __name__ == '__main__':
    main()
