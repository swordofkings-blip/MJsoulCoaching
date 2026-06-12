# -*- coding: utf-8 -*-
"""
簡易パラメータチューニングループ: 指定パラメータの値を変えながら一致率を測定し、最適値を探す。
"""
import json, os, sys, copy, glob
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from tools.evaluate_parameter_fitness import evaluate_all

BASE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
CONFIG_PATH = os.path.join(BASE_DIR, 'config', 'config_parameters.json')
DATA_DIR = os.path.join(BASE_DIR, 'data')

# チューニング対象パラメータと探索範囲
# (パラメータ名, [テストする値], 説明)
TUNE_PARAMS = [
    # === 攻撃評価（手牌効率）===
    ('UKEIRE_MULTIPLIER', [6, 8, 10, 12, 14, 16, 18, 20], '有効牌1枚あたりの加点'),
    ('SHANTEN_MULTIPLIER', [80, 100, 150, 200, 250, 300, 400, 500], 'シャンテン数のペナルティ'),
    ('SCORE_MUSUJI_PER_REACH', [-400, -300, -250, -200, -150, -100, 0], 'リーチ1人あたり無筋減点'),
    ('MATAGI_PENALTY', [0, 50, 80, 100, 120, 150, 200], 'またぎスジペナルティ'),
    # === 守備評価（新規追加）===
    ('URASUJI_PENALTY', [0, 15, 30, 50, 70, 100], '裏スジペナルティ'),
    ('EARLY_DISCARD_SAFETY_BONUS', [0, 100, 200, 300, 400, 500], '序盤(1-3巡)安全ボーナス'),
    ('EARLY_DISCARD_SAFETY_BONUS_MID', [0, 50, 100, 150, 200], '中盤(4-6巡/ツモ切)安全ボーナス'),
    ('EARLY_MID_HAND_DRAWN_PENALTY', [0, 50, 80, 100, 120, 150], '中盤(4-6巡/手出し)危険ペナルティ'),
]

def load_base_params():
    with open(CONFIG_PATH, encoding='utf-8') as f:
        return json.load(f)

def evaluate_params(params, records, label=''):
    total = m = 0
    for rp in records:
        r = evaluate_all(rp, params)
        total += r['total_discards']
        m += r['matches']
    rate = m / total if total else 0.0
    sys.stdout.write(f'\r  {label}: {m}/{total} = {rate*100:.2f}%')
    sys.stdout.flush()
    return rate, m, total

def grid_search(params, records):
    """グリッドサーチ: 各パラメータを1つずつ最適化"""
    best_params = copy.deepcopy(params)
    best_rate, _, _ = evaluate_params(best_params, records, 'baseline')
    print(f'\n  Baseline: {best_rate*100:.2f}%')

    all_records_paths = sorted(glob.glob(os.path.join(DATA_DIR, 'record_*_trimmed.json')))
    
    for param_name, values, desc in TUNE_PARAMS:
        print(f'\n--- {param_name} ({desc}) ---')
        best_val = best_params.get(param_name)
        local_best_rate = best_rate
        
        for v in values:
            test_params = copy.deepcopy(best_params)
            test_params[param_name] = v
            rate, m, t = evaluate_params(test_params, records, f'{param_name}={v}')
            if rate > local_best_rate:
                local_best_rate = rate
                best_val = v
                print(f' ← NEW BEST')
            else:
                print()
        
        best_params[param_name] = best_val
        if local_best_rate > best_rate:
            best_rate = local_best_rate
            print(f'  >> {param_name} improved to {best_val} (rate: {best_rate*100:.2f}%)')
    
    return best_params, best_rate


def hill_climb(params, records, iterations=10):
    """山登り法: ランダムにパラメータを微小変更"""
    import random
    best_params = copy.deepcopy(params)
    best_rate, _, _ = evaluate_params(best_params, records, 'baseline')
    print(f'\n  Baseline: {best_rate*100:.2f}%')
    
    param_config = {name: (vals[0], vals[-1]) for name, vals, desc in TUNE_PARAMS if len(vals) >= 2}
    
    for i in range(iterations):
        # Pick a random parameter and adjust it
        name = random.choice(list(param_config.keys()))
        mn, mx = param_config[name]
        cur = best_params.get(name, mn)
        
        # Find neighbors in the value list for this param
        for _, vals, _ in TUNE_PARAMS:
            if _ == name:
                break
        idx = vals.index(cur) if cur in vals else len(vals) // 2
        
        candidates = []
        if idx > 0:
            candidates.append(vals[idx - 1])
        if idx < len(vals) - 1:
            candidates.append(vals[idx + 1])
        if not candidates:
            continue
        
        new_val = random.choice(candidates)
        test_params = copy.deepcopy(best_params)
        test_params[name] = new_val
        
        rate, m, t = evaluate_params(test_params, records, f'iter{i+1} {name}={new_val}')
        
        if rate > best_rate:
            best_rate = rate
            best_params = copy.deepcopy(test_params)
            print(f' ← improved!')
        else:
            print()
    
    return best_params, best_rate


def main():
    import argparse
    parser = argparse.ArgumentParser(description='パラメータチューニングループ')
    parser.add_argument('--mode', choices=['grid', 'hill', 'both'], default='grid')
    parser.add_argument('--train', type=int, nargs='*', default=None,
                        help='訓練レコードのインデックス（例: 0 1 2）= 先頭3ファイル')
    parser.add_argument('--iter', type=int, default=20, help='山登りの反復回数')
    parser.add_argument('--validate', action='store_true', help='全レコードで最終検証')
    args = parser.parse_args()
    
    base_params = load_base_params()
    all_records = sorted(glob.glob(os.path.join(DATA_DIR, 'record_*_trimmed.json')))
    
    if args.train is not None:
        train_records = [all_records[i] for i in args.train if i < len(all_records)]
    else:
        train_records = all_records[:3]  # default: first 3
    
    print(f'Records: {len(all_records)} total, {len(train_records)} for training')
    print(f'Training files: {[os.path.basename(r) for r in train_records]}')
    
    best_params = copy.deepcopy(base_params)
    
    if args.mode in ('grid', 'both'):
        print('\n=== Grid Search ===')
        best_params, best_rate = grid_search(best_params, train_records)
        print(f'\nGrid best rate: {best_rate*100:.2f}%')
    
    if args.mode in ('hill', 'both'):
        print(f'\n=== Hill Climbing ({args.iter} iterations) ===')
        best_params, best_rate = hill_climb(best_params, train_records, args.iter)
        print(f'\nHill climb best rate: {best_rate*100:.2f}%')
    
    if args.validate:
        print('\n=== Validation on ALL records ===')
        rate, m, t = evaluate_params(best_params, all_records, 'final')
        print(f'\nFinal: {m}/{t} = {rate*100:.2f}%')
        
        # Also evaluate baseline
        base_rate, bm, bt = evaluate_params(base_params, all_records, 'baseline (validation)')
        print(f'\nBaseline: {bm}/{bt} = {base_rate*100:.2f}%')
        print(f'Improvement: {(rate - base_rate)*100:+.2f}%')
    
    # Print best params
    print('\n=== Best Parameters ===')
    changed = []
    for name, vals, desc in TUNE_PARAMS:
        old = base_params.get(name, 'default')
        new = best_params.get(name, old)
        if new != old:
            changed.append(f'  {name}: {old} -> {new}')
            print(f'  {name}: {old} -> {new}  ({desc})')
    
    if not changed:
        print('  No changes (baseline was best)')
    
    # Save best
    out_path = os.path.join(BASE_DIR, 'config', 'parameters_tuned.json')
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(best_params, f, indent=2, ensure_ascii=False)
    print(f'\nSaved to {out_path}')


if __name__ == '__main__':
    main()
