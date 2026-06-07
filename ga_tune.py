# -*- coding: utf-8 -*-
import json, random, copy, os, time, glob, sys, multiprocessing
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate_parameter_fitness import evaluate_all

def _eval_worker(args):
    params, record_paths = args
    total = m = 0
    for rp in record_paths:
        r = evaluate_all(rp, params)
        total += r['total_discards']
        m += r['matches']
    return m / total if total > 0 else 0.0

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
    'MODE_ZENTSU_THRESHOLD': (0.5, 0.95, float),
    'MODE_BETAORI_THRESHOLD': (0.01, 0.15, float),
    'IPPATSU_PENALTY': (100, 600, int),
    'BETAORI_SLIM_BONUS': (10, 80, int),
    'TANYAO_TERMINAL_BONUS': (20, 80, int),
    'AKA_KEEP_BONUS': (30, 120, int),
    'ISOLATED_MIDDLE_BONUS': (5, 40, int),
    'ISOLATED_EDGE_PENALTY': (5, 40, int),
    'UKEIRE_QUAL_HONOR': (0.2, 0.8, float),
    'UKEIRE_QUAL_RYANMEN': (0.7, 1.0, float),
    'UKEIRE_QUAL_KANCHAN': (0.3, 0.9, float),
    'UKEIRE_QUAL_CONNECT_BASE': (0.2, 0.7, float),
    'UKEIRE_QUAL_CONNECT_PER': (0.1, 0.4, float),
}

STATE_FILE = 'ga_state.json'

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

def save_state(pop, gen, log):
    state = {'gen': gen, 'pop': [(f, p) for f, p in pop]}
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)
    log.write(f'State saved at gen {gen}\n')
    log.flush()

def load_state():
    with open(STATE_FILE, encoding='utf-8') as f:
        state = json.load(f)
    return state['gen'], [(f, p) for f, p in state['pop']]

def main():
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    all_records = sorted(glob.glob(os.path.join(data_dir, 'record_*_trimmed.json')))
    train_records = all_records[:2]

    base_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config_parameters_ldea_v1.json')
    with open(base_path, encoding='utf-8') as f:
        base_params = json.load(f)

    resume_from = len(sys.argv) > 1 and sys.argv[1] == '--resume'
    start_gen = 0
    pop_size = 8
    keep = 2
    generations = 30
    train_records = all_records[:2]

    log_file = 'ga_result.log'

    with open(log_file, 'a', encoding='utf-8') as log:
        if resume_from and os.path.exists(STATE_FILE):
            start_gen, pop = load_state()
            log.write(f'Resumed from gen {start_gen}\n')
            print(f'Resumed from gen {start_gen}', flush=True)
        else:
            base_fit = evaluate_fitness(base_params, train_records)
            log.write(f'Baseline: {base_fit*100:.2f}%\n')
            print(f'Baseline: {base_fit*100:.2f}%')
            pop = [(base_fit, base_params)]
            for _ in range(pop_size - 1):
                pop.append((0.0, mutate(base_params, 0.5, 0.2)))
            save_state(pop, 0, log)

        for gen in range(start_gen + 1, start_gen + generations + 1):
            t0 = time.time()
            need_eval = [i for i in range(pop_size) if pop[i][0] == 0.0]
            if need_eval and len(need_eval) > 1:
                args_list = [(pop[i][1], train_records) for i in need_eval]
                n_workers = min(multiprocessing.cpu_count(), len(need_eval))
                with multiprocessing.Pool(n_workers) as pool:
                    results = pool.map(_eval_worker, args_list)
                for i, fit in zip(need_eval, results):
                    pop[i] = (fit, pop[i][1])
            else:
                for i in need_eval:
                    pop[i] = (_eval_worker((pop[i][1], train_records)), pop[i][1])
            pop.sort(key=lambda x: -x[0])
            msg = f'G{gen}: best={pop[0][0]*100:.2f}% ({time.time()-t0:.0f}s)'
            log.write(msg + '\n')
            log.flush()
            print(msg, flush=True)

            if gen % 10 == 0:
                save_state(pop, gen, log)
                # Show top params every 10 gens
                best_p = pop[0][1]
                for k in list(GENE_DEFS.keys())[:6]:
                    print(f'  {k}={best_p.get(k, "?")}', end='  ')
                print()

            rate = max(0.05, 0.35 * (1 - (gen - start_gen) / 100))
            size = max(0.05, 0.18 * (1 - (gen - start_gen) / 100))
            nxt = pop[:keep]
            while len(nxt) < pop_size:
                nxt.append((0.0, mutate(random.choice(pop[:3])[1], rate, size)))
            pop = nxt

        save_state(pop, start_gen + 100, log)
        log.write(f'\nValidation on {len(all_records)} records:\n')
        bf = evaluate_fitness(base_params, all_records)
        gf = evaluate_fitness(pop[0][1], all_records)
        log.write(f'Baseline: {bf*100:.2f}%\n')
        log.write(f'GA best:  {gf*100:.2f}%\n')
        print(f'Validation: base={bf*100:.2f}% ga={gf*100:.2f}%')
        if gf > bf:
            log.write('Improved!\n')
            best_path = 'ga_best.json'
            with open(best_path, 'w', encoding='utf-8') as f:
                json.dump(pop[0][1], f, indent=2, ensure_ascii=False)

if __name__ == '__main__':
    main()
