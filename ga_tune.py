# -*- coding: utf-8 -*-
import json, random, copy, os, time, glob, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_parameter_fitness import evaluate_all

GENE_DEFS = {
    'UKEIRE_MULTIPLIER': (5, 20, int),
    'SHANTEN_MULTIPLIER': (100, 500, int),
    'SCORE_WALL_SUJI': (400, 900, int),
    'SCORE_MUSUJI_PER_REACH': (-400, 0, int),
    'RIICHI_BASE': (0.3, 0.9, float),
    'RIICHI_WAIT_WEIGHT': (0.5, 2.0, float),
    'RIICHI_OPP_REACH_PENALTY': (-0.8, 0.0, float),
    'WAIT_KANCHAN': (0.3, 0.9, float),
    'DORA_DISCARD_PENALTY': (40, 200, int),
    'MATAGI_PENALTY': (0, 300, int),
    'PENALTY_6BLOCK_MAINTAIN': (30, 150, int),
}

def mutate(params, rate=0.3, size=0.15):
    new = dict(params)
    for key, (mn, mx, typ) in GENE_DEFS.items():
        if random.random() > rate:
            continue
        cur = new.get(key, mn if typ == int else (mn + mx) / 2)
        if typ == int:
            d = int((mx - mn) * size * (random.random() - 0.5) * 2)
            new[key] = max(mn, min(mx, cur + d))
        else:
            d = (mx - mn) * size * (random.random() - 0.5) * 2
            new[key] = round(max(mn, min(mx, cur + d)), 3)
    return new

def evaluate_fitness(params, record_paths):
    total = m = 0
    for rp in record_paths:
        r = evaluate_all(rp, params)
        total += r['total_discards']
        m += r['matches']
    return m / total if total > 0 else 0.0

def main():
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    all_records = sorted(glob.glob(os.path.join(data_dir, 'record_*_trimmed.json')))
    train_records = all_records[:2]  # 2 records for speed (~4s total)

    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_parameters_ldea_v1.json')
    with open(base_path, encoding='utf-8') as f:
        base_params = json.load(f)

    pop_size = 5
    generations = 8
    keep = 2
    log_file = 'ga_result.log'

    with open(log_file, 'w', encoding='utf-8') as log:
        log.write(f'GA start: {len(train_records)} training records\n')
        log.flush()

        base_fit = evaluate_fitness(base_params, train_records)
        log.write(f'Baseline: {base_fit*100:.2f}%\n')
        log.flush()
        print(f'Baseline: {base_fit*100:.2f}%')

        pop = [(base_fit, base_params)]
        for _ in range(pop_size - 1):
            pop.append((0.0, mutate(base_params, 0.5, 0.2)))

        for gen in range(generations):
            t0 = time.time()
            for i in range(pop_size):
                if pop[i][0] == 0.0:
                    fit = evaluate_fitness(pop[i][1], train_records)
                    pop[i] = (fit, pop[i][1])
            pop.sort(key=lambda x: -x[0])
            msg = f'G{gen+1}: best={pop[0][0]*100:.2f}% ({time.time()-t0:.0f}s)'
            log.write(msg + '\n')
            log.flush()
            print(msg)
            if gen < generations - 1:
                nxt = pop[:keep]
                for _ in range(pop_size - keep):
                    nxt.append((0.0, mutate(random.choice(pop[:2])[1], 0.3, 0.15)))
                pop = nxt

        log.write(f'\nValidation on {len(all_records)} records:\n')
        bf = evaluate_fitness(base_params, all_records)
        gf = evaluate_fitness(pop[0][1], all_records)
        log.write(f'Baseline: {bf*100:.2f}%\n')
        log.write(f'GA best:  {gf*100:.2f}%\n')
        if gf > bf:
            log.write('Improved! Saving to ga_best.json\n')
            with open('ga_best.json', 'w', encoding='utf-8') as f:
                json.dump(pop[0][1], f, indent=2, ensure_ascii=False)
        else:
            log.write('No improvement\n')

    print(f'Done. Check {log_file}')

if __name__ == '__main__':
    main()
