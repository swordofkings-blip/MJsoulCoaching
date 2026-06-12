# -*- coding: utf-8 -*-
"""Phase1 一括テスト"""
import json, os, sys, copy, glob, time
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from tools.evaluate_parameter_fitness import evaluate_all

BASE = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONFIG = os.path.join(BASE, 'config', 'config_parameters.json')
DATA = os.path.join(BASE, 'data')

with open(CONFIG, encoding='utf-8') as f:
    base_params = json.load(f)

all_records = sorted(glob.glob(os.path.join(DATA, 'record_*_trimmed.json')))
train = all_records[:3]

def eval_params(params, records, n_workers=6):
    total = m = 0
    with ProcessPoolExecutor(max_workers=n_workers) as ex:
        fs = {ex.submit(evaluate_all, rp, params): rp for rp in records}
        for f in as_completed(fs):
            r = f.result()
            total += r['total_discards']
            m += r['matches']
    return m/total if total else 0.0, m, total

# Baseline
base_rate, bm, bt = eval_params(base_params, train)
print(f'Current baseline: {bm}/{bt} = {base_rate*100:.2f}%')

# Parameters to test with specific values
tests = [
    ('HONOR_DISCARD_BONUS', [35, 45, 55, 60, 70, 85, 100], '字牌切りボーナス'),
    ('ISOLATED_MIDDLE_BONUS', [0, 3, 5, 8, 10, 15], '孤立中張牌保持ペナルティ'),
    ('BLOCK_COMPETITION_PENALTY', [0, 1, 2, 3, 5, 8], 'ブロック競合ペナルティ'),
    ('MODE_BETAORI_THRESHOLD', [0.03, 0.05, 0.08, 0.10, 0.15, 0.20], 'ベタオリ閾値'),
    ('SCORE_MUSUJI_PER_REACH', [-400, -350, -300, -250, -200, -150], 'リーチ無筋減点'),
    ('MATAGI_PENALTY', [80, 100, 120, 150, 180, 200], 'またぎスジペナルティ'),
]

for name, values, desc in tests:
    t0 = time.time()
    cur = base_params.get(name, '(default)')
    best_v, best_r = cur, base_rate
    for v in values:
        p = dict(base_params)
        p[name] = v
        rate, m, t = eval_params(p, train)
        delta = (rate - base_rate) * 100
        sign = '+' if delta > 0 else ' '
        print(f'  {name}={v:>6}: {m:>3}/{t} = {rate*100:.2f}% ({sign}{delta:+.2f})  [{desc}]')
        if rate > best_r:
            best_v, best_r = v, rate
    if best_v != cur and best_r > base_rate:
        print(f'  >> {name}: {cur} -> {best_v} ({(best_r-base_rate)*100:+.2f}pt)')
    print(f'     ({time.time()-t0:.0f}s)')
