# -*- coding: utf-8 -*-
"""並列処理版 パラメータ調整 - 複数ファイルを同時に評価"""
import json, os, sys, copy, glob, time
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from tools.evaluate_parameter_fitness import evaluate_all

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONFIG = os.path.join(BASE, 'config', 'config_parameters.json')
DATA = os.path.join(BASE, 'data')

def eval_file(args):
    rp, params = args
    return evaluate_all(rp, params)

def evaluate_params(params, records, n_workers=None):
    if n_workers is None:
        n_workers = min(os.cpu_count() or 4, len(records))
    total = m = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        futures = {ex.submit(eval_file, (rp, params)): rp for rp in records}
        for f in as_completed(futures):
            r = f.result()
            total += r['total_discards']
            m += r['matches']
    return m / total if total else 0.0, m, total

def main():
    import argparse
    parser = argparse.ArgumentParser(description='並列パラメータ調整')
    parser.add_argument('--param', required=True, help='パラメータ名')
    parser.add_argument('--values', required=True, nargs='+', help='テストする値')
    parser.add_argument('--validate', action='store_true', help='全ファイルで検証')
    args = parser.parse_args()

    with open(CONFIG, encoding='utf-8') as f:
        base_params = json.load(f)

    # Parse values
    values = []
    for v in args.values:
        try:
            values.append(float(v) if '.' in v else int(v))
        except:
            values.append(v)

    all_records = sorted(glob.glob(os.path.join(DATA, 'record_*_trimmed.json')))
    
    if args.validate:
        records = all_records
    else:
        records = all_records[:3]  # 訓練: 先頭3ファイル

    n_workers = min(os.cpu_count() or 4, len(records))

    # Baseline
    t0 = time.time()
    base_rate, bm, bt = evaluate_params(base_params, records, n_workers)
    print(f'Baseline: {bm}/{bt} = {base_rate*100:.2f}% ({time.time()-t0:.0f}s with {n_workers} workers)')
    
    for v in values:
        p = dict(base_params)
        p[args.param] = v
        t0 = time.time()
        rate, m, t = evaluate_params(p, records, n_workers)
        delta = (rate - base_rate) * 100
        sign = '+' if delta >= 0 else ''
        print(f'  {args.param}={v}: {m}/{t} = {rate*100:.2f}% ({sign}{delta:.2f}pt) [{time.time()-t0:.0f}s]')

if __name__ == '__main__':
    main()
