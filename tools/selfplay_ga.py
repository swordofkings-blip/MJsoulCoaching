import json
import os
import random
import sys
import time
import multiprocessing
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import List, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from tools.ga_tune import GENE_DEFS, expand_params, mutate, crossover
from tools.battle_test import compute_pt
from tools.mahjong_simulator import MahjongSimulator
from core.ai_player import AIPlayer
from core.evaluator import Evaluator


POP_SIZE = 24
EVAL_SEEDS = 3
GAME_TYPE = 'tonpu'
ROOM = 'jade'
BASE_PARAMS_PATH = 'config/config_parameters.json'
STATE_FILE = 'selfplay_ga_state.json'
DAMATEN_GENE_KEY = 'OPPONENT_DEFAULT_DAMATEN_RATE'


def load_base_params(path: str) -> dict:
    base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    full = os.path.join(base, path)
    with open(full, encoding='utf-8') as f:
        return json.load(f)


def _eval_group(group_idx: int, flat_params_list: List[dict], seeds: List[int],
                base_params: dict, game_type: str, room: str) -> Tuple[int, List[float], List[dict]]:
    from core.strategy_manager import ShantenCalculator
    expanded_list = [expand_params(fp, base_params) for fp in flat_params_list]
    total_pts = [0.0] * 4
    total_stats = [{'wins': 0, 'deal_in': 0, 'call_kyoku': 0, 'reach_wins': 0, 'damaten_wins': 0, 'kyoku': 0} for _ in range(4)]
    for seed in seeds:
        ShantenCalculator.clear_cache()
        players = [AIPlayer(f"P{i}", Evaluator, ep) for i, ep in enumerate(expanded_list)]
        gr = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type).run_game()
        for s in range(4):
            pl = gr.placement_of(s)
            total_pts[s] += compute_pt(pl, gr.final_scores[s], room)
            ps = gr.player_stats[s] if s < len(gr.player_stats) else None
            if ps:
                total_stats[s]['wins'] += ps.wins
                total_stats[s]['deal_in'] += ps.dealt_in
                total_stats[s]['kyoku'] += ps.num_kyoku
                total_stats[s]['reach_wins'] += ps.reach_wins
                total_stats[s]['damaten_wins'] += ps.damaten_wins
    n = len(seeds)
    avg = [p / n for p in total_pts]
    return (group_idx, avg, total_stats)


def make_population(base_params: dict, pop_size: int) -> List[Tuple[float, dict]]:
    init_flat = {}
    for k in GENE_DEFS.keys():
        if k.startswith('meld_defense_'):
            sub = k[len('meld_defense_'):]
            val = base_params.get('yaku_strategy', {}).get('meld_defense', {}).get(sub, None)
        else:
            val = base_params.get(k, None)
        if val is None:
            mn, mx, typ = GENE_DEFS[k]
            val = int((mn + mx) / 2) if typ == int else round((mn + mx) / 2, 3)
        init_flat[k] = val
    pop = [(0.0, init_flat)]
    for _ in range(pop_size - 1):
        pop.append((0.0, mutate(init_flat, 0.5, 0.2)))
    return pop


def save_state(pop: list, gen: int, cache: dict):
    state = {'gen': gen, 'pop': [(f, p) for f, p in pop], 'cache': cache}
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2)


def load_state() -> Tuple[int, list, dict]:
    with open(STATE_FILE, encoding='utf-8') as f:
        s = json.load(f)
    return s['gen'], [(f, p) for f, p in s['pop']], s.get('cache', {})


def _damaten_rate_of(flat: dict) -> float:
    mn, mx, typ = GENE_DEFS.get(DAMATEN_GENE_KEY, (0.05, 0.80, float))
    val = flat.get(DAMATEN_GENE_KEY, (mn + mx) / 2)
    return float(val)


def _ensure_damaten_specialist(pop: list, hall_of_fame: dict, keep: int, pop_size: int):
    if hall_of_fame is None:
        return
    best_in_pop = max(_damaten_rate_of(p[1]) for p in pop)
    hof_rate = _damaten_rate_of(hall_of_fame)
    if hof_rate <= best_in_pop:
        return
    worst_idx = min(range(len(pop)), key=lambda i: pop[i][0])
    if pop[worst_idx][0] >= -999:
        return
    pop[worst_idx] = (-20.0, dict(hall_of_fame))


def _merge_stats(stats_list: List[dict]) -> dict:
    merged = {'wins': 0, 'deal_in': 0, 'kyoku': 0, 'reach_wins': 0, 'damaten_wins': 0}
    for s in stats_list:
        for k in merged:
            merged[k] += s.get(k, 0)
    return merged


def main():
    base_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    base_params = load_base_params(os.path.join(base_dir, BASE_PARAMS_PATH))

    resume_from = '--resume' in sys.argv
    extra_gens = 0
    pop_size = POP_SIZE
    gens_total = 30
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    if resume_from and args:
        try:
            extra_gens = int(args[0])
            args = args[1:]
        except:
            pass
    if args:
        try:
            gens_total = int(args[0])
            args = args[1:]
        except:
            pass
    if args:
        try:
            pop_size = int(args[0])
        except:
            pass
    pop_size = max(4, (pop_size // 4) * 4)

    keep = max(1, pop_size // 6)
    generations = gens_total + extra_gens
    eval_seeds_pool = list(range(1, 1001))
    fitness_cache = {}
    log_file = os.path.join(base_dir, 'selfplay_ga_result.log')
    damaten_hall_of_fame = None

    with open(log_file, 'a', encoding='utf-8') as log:
        if resume_from and os.path.exists(STATE_FILE):
            start_gen, pop, fitness_cache = load_state()
            target = max(pop_size, len(pop))
            while len(pop) < target:
                parent = random.choice(pop[:max(1, len(pop)//3)])[1]
                pop.append((0.0, mutate(parent, 0.4, 0.2)))
            pop_size = len(pop)
            keep = max(1, pop_size // 6)
            log.write(f'Resumed from gen {start_gen}, pop={pop_size}\n')
            print(f'Resumed from gen {start_gen}, pop={pop_size}', flush=True)
        else:
            start_gen = 0
            pop = make_population(base_params, pop_size)
            save_state(pop, 0, fitness_cache)
            print(f'Initialized pop={pop_size}, seeds_per_gen={EVAL_SEEDS}', flush=True)

        n_workers = max(1, multiprocessing.cpu_count())
        print(f'Using {n_workers} workers', flush=True)

        for gen in range(start_gen + 1, start_gen + generations + 1):
            t0 = time.time()
            gen_seeds = random.sample(eval_seeds_pool, EVAL_SEEDS)

            indices = list(range(pop_size))
            random.shuffle(indices)
            groups = []
            for gi in range(0, pop_size, 4):
                group = indices[gi:gi + 4]
                if len(group) < 4:
                    for i in group:
                        pop[i] = (-20.0, pop[i][1])
                    continue
                groups.append(group)

            eval_args = []
            for gi, group in enumerate(groups):
                flat_list = [pop[idx][1] for idx in group]
                eval_args.append((gi, flat_list, gen_seeds, base_params, GAME_TYPE, ROOM))

            results = []
            if len(eval_args) <= 1:
                for args in eval_args:
                    results.append(_eval_group(*args))
            else:
                with ProcessPoolExecutor(max_workers=min(n_workers, len(eval_args))) as pool:
                    futures = [pool.submit(_eval_group, *args) for args in eval_args]
                    for fut in as_completed(futures):
                        results.append(fut.result())

            all_stats = []
            for gi, avg_pts, stats_list in results:
                group = groups[gi]
                for i, idx in enumerate(group):
                    pop[idx] = (avg_pts[i], pop[idx][1])
                all_stats.extend(stats_list)

            pop.sort(key=lambda x: -x[0])
            elapsed = time.time() - t0

            merged = _merge_stats(all_stats)
            n_kyoku = max(merged['kyoku'], 1)
            n_wins = merged['wins']
            call_wins = n_wins - merged['reach_wins'] - merged['damaten_wins']
            if DAMATEN_GENE_KEY in GENE_DEFS:
                best_dr = max(_damaten_rate_of(p[1]) for p in pop)
                if damaten_hall_of_fame is None or _damaten_rate_of(damaten_hall_of_fame) < best_dr:
                    damaten_hall_of_fame = dict(max(pop, key=lambda x: _damaten_rate_of(x[1]))[1])
                _ensure_damaten_specialist(pop, damaten_hall_of_fame, keep, pop_size)

            msg = (f'G{gen}: best={pop[0][0]:+.1f}pt  avg={sum(p[0] for p in pop)/pop_size:+.1f}pt  '
                   f'K={n_kyoku} W={merged["wins"]}/{n_kyoku*4}({merged["wins"]/n_kyoku*100:.1f}%) '
                   f'Deal={merged["deal_in"]}/{n_kyoku}({merged["deal_in"]/n_kyoku*100:.1f}%) '
                   f'R={merged["reach_wins"]} D={merged["damaten_wins"]} C={call_wins} '
                   f'({elapsed:.0f}s)')
            log.write(msg + '\n')
            log.flush()
            print(msg, flush=True)

            save_state(pop, gen, fitness_cache)

            progress = (gen - start_gen) / generations
            rate = max(0.05, 0.35 * (1 - progress))
            size = max(0.05, 0.18 * (1 - progress))
            nxt = pop[:keep]
            while len(nxt) < pop_size:
                if random.random() < 0.7 and len(pop[:keep]) >= 2:
                    p1 = random.choice(pop[:keep])[1]
                    candidates = [p[1] for p in pop[:keep] if p[1] != p1]
                    p2 = random.choice(candidates) if candidates else p1
                    child = crossover(p1, p2)
                else:
                    child = random.choice(pop[:keep])[1]
                nxt.append((0.0, mutate(child, rate, size)))
            pop = nxt

        save_state(pop, start_gen + generations, fitness_cache)

        best_expanded = expand_params(pop[0][1], base_params)
        best_path = os.path.join(base_dir, 'selfplay_ga_best.json')
        with open(best_path, 'w', encoding='utf-8') as f:
            json.dump(best_expanded, f, indent=2)
        print(f'\nSaved best to {best_path}', flush=True)
        print(f'Best pt: {pop[0][0]:+.1f}', flush=True)

        for k in list(GENE_DEFS.keys()):
            print(f'  {k}={pop[0][1].get(k, "?")}', flush=True)


if __name__ == '__main__':
    multiprocessing.freeze_support()
    main()
