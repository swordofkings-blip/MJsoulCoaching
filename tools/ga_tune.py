# -*- coding: utf-8 -*-
"""
@title 簡易 GA によるパラメータ自動調整
@description
  gene_variants/ 内の gene_0, gene_1, gene_2 を 1 世代として
  Akochan とバトルし、最も成績の良い遺伝子を残して 2 体を突然変異で生成する。
  世代交代を繰り返してパラメータを最適化する。

  使い方:
    python tools/ga_tune.py [世代数] [世代あたり seed 数] [最大時間(分)]

  例:
    python tools/ga_tune.py 20 3 280
"""
import os
import sys
import json
import time
import random
import copy
import shutil
import subprocess
import argparse
from typing import List, Dict, Optional

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
GENE_DIR = os.path.join(ROOT_DIR, 'gene_variants')
BASE_PARAMS_PATH = os.path.join(ROOT_DIR, 'config', 'config_parameters.json')
LOG_DIR = os.path.join(ROOT_DIR, 'logs', 'ga')
os.makedirs(LOG_DIR, exist_ok=True)

# GA で調整する主要パラメータ
# (キー, 最小値, 最大値, 突然変異幅 標準偏差)
GA_PARAMS = [
    ('RIICHI_URA_MULT',             1.0,   2.0,   0.10),
    ('RIICHI_FOLD_RATE',            0.20,  0.80,  0.05),
    ('RIICHI_DEFENSE_COST',         0.0,   0.5,   0.05),
    ('DAMATEN_FLEX_BONUS',           0,     30,    3),
    ('DAMATEN_YAKU_IMP_BONUS',       0.0,   0.2,   0.02),
    ('PUSH_SAFE_TILES_BONUS',       0.0,   0.6,   0.05),
    ('FOLD_SAFE_TILES_BONUS',       0.0,   0.6,   0.05),
    ('TERMINAL_TILE_PUSH_BONUS',     0.0,   0.3,   0.03),
    ('DYE_HONOR_PUSH_BONUS',         0.0,   1.0,   0.10),
    ('RIICHI_LATE_PENALTY',         0.5,   1.0,   0.05),
    ('RIICHI_OPP_REACH_PENALTY',     0.3,   1.0,   0.05),
    ('MELD_GAP_MAX',                1000,  4000,  200),
    ('MELD_GAP_MIN',                100,   600,   50),
    ('MELD_SPEED_BONUS',            1000,  4000,  200),
    ('MELD_HIGH_VALUE_THRESH',      1,     4,     0.5),
    ('DAMATEN_WAIT_IMP_BONUS',      0.0,   0.2,   0.02),
]


def load_base_params() -> dict:
    with open(BASE_PARAMS_PATH, 'r', encoding='utf-8') as f:
        return json.load(f)


def random_gene(base: dict) -> dict:
    """GA_PARAMS からランダムな遺伝子を生成"""
    gene = {}
    for key, lo, hi, _ in GA_PARAMS:
        if isinstance(lo, int):
            gene[key] = random.randint(lo, hi)
        else:
            gene[key] = random.uniform(lo, hi)
    return gene


def mutate_gene(parent: dict, mutation_rate: float = 0.3) -> dict:
    """親遺伝子を突然変異させて子遺伝子を生成"""
    child = copy.deepcopy(parent)
    for key, lo, hi, std in GA_PARAMS:
        if key not in child:
            child[key] = random.uniform(lo, hi) if not isinstance(lo, int) else random.randint(lo, hi)
            continue
        if random.random() < mutation_rate:
            if isinstance(lo, int):
                delta = int(random.gauss(0, std))
                new_val = max(lo, min(hi, child[key] + delta))
                child[key] = new_val
            else:
                delta = random.gauss(0, std)
                new_val = max(lo, min(hi, child[key] + delta))
                child[key] = new_val
    return child


def crossover_gene(parent1: dict, parent2: dict) -> dict:
    """2 つの親遺伝子から子を生成 (各パラメータをランダムに選択)"""
    child = {}
    for key, lo, hi, _ in GA_PARAMS:
        if key in parent1 and key in parent2:
            child[key] = parent1[key] if random.random() < 0.5 else parent2[key]
        elif key in parent1:
            child[key] = parent1[key]
        elif key in parent2:
            child[key] = parent2[key]
    return child


def save_gene(gene: dict, path: str):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gene, f, ensure_ascii=False, indent=2)


def load_gene(path: str) -> dict:
    with open(path, 'r', encoding='utf-8') as f:
        return json.load(f)


def run_battle(gene_paths: List[Optional[str]], seeds: int, max_workers: int, start_seed: int) -> Dict[str, float]:
    """1 世代のバトルを実行し、各 gene の平均 Gyoku pt を返す"""
    # 一時的に gene ファイルを保存
    for i, gene_path in enumerate(gene_paths):
        out_path = os.path.join(GENE_DIR, f'gene_{i}.json')
        if gene_path and os.path.exists(gene_path):
            shutil.copy(gene_path, out_path)
        else:
            # gene が無い場合は空 dict ファイルを作成 (デフォルト params のみ使用)
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump({}, f)

    cmd = [
        'python', os.path.join(THIS_DIR, 'mjai_battle_genes.py'),
        str(seeds), str(max_workers), str(start_seed),
    ]
    print(f'  Running: {" ".join(cmd)}')
    log_path = os.path.join(LOG_DIR, f'ga_gen_{int(time.time())}.log')
    with open(log_path, 'w', encoding='utf-8') as f:
        result = subprocess.run(cmd, stdout=f, stderr=subprocess.STDOUT, text=True, timeout=3600 * 5)

    # ログから結果を読む (mjai-server のログは Shift_JIS が混在する場合がある)
    with open(log_path, 'rb') as f:
        log_text = f.read().decode('utf-8', errors='replace')

    # 各 gene の Gyoku pt を抽出
    scores = {}
    for line in log_text.splitlines():
        if 'Avg Gyoku Pt:' in line:
            # 例: "  Avg Gyoku Pt: +12.5"
            parts = line.split()
            try:
                val = float(parts[-1])
                # 直前行から名前を抽出
                prev_line = ''
                # (前を見るのは難しいので、別アプローチで)
                pass
            except (ValueError, IndexError):
                pass

    # ログを行ごとに処理して name -> score の辞書を作る
    current_name = None
    for line in log_text.splitlines():
        line = line.strip()
        if line.endswith(':'):
            name = line[:-1]
            if name in ('OurAI-0', 'OurAI-1', 'OurAI-2', 'Akochan'):
                current_name = name
        elif line.startswith('Avg Gyoku Pt:'):
            if current_name:
                try:
                    val = float(line.split('Avg Gyoku Pt:')[1].strip())
                    scores[current_name] = val
                except ValueError:
                    pass

    return scores


def evaluate_population(population: List[dict], seeds: int, max_workers: int, start_seed: int) -> List[Dict[str, float]]:
    """個体群を評価し、各個体の Gyoku pt を返す"""
    gene_paths = []
    for i, gene in enumerate(population):
        path = os.path.join(GENE_DIR, f'_temp_gene_{i}.json')
        save_gene(gene, path)
        gene_paths.append(path)

    scores = run_battle(gene_paths, seeds, max_workers, start_seed)
    # 一時ファイル削除
    for p in gene_paths:
        try:
            os.remove(p)
        except OSError:
            pass
    return scores


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--generations', type=int, default=20)
    parser.add_argument('--seeds', type=int, default=1)
    parser.add_argument('--max-minutes', type=int, default=280)
    parser.add_argument('--max-workers', type=int, default=3)
    parser.add_argument('--start-seed', type=int, default=1)
    parser.add_argument('--mutation-rate', type=float, default=0.3)
    parser.add_argument('--population-size', type=int, default=3)
    parser.add_argument('--elite-count', type=int, default=1)
    parser.add_argument('--resume', action='store_true', help='Resume from previous run')
    parser.add_argument('--history-file', type=str, default=os.path.join(LOG_DIR, 'ga_history.json'))
    args = parser.parse_args()

    start_time = time.time()
    deadline = start_time + args.max_minutes * 60

    random.seed(int(time.time()) % 100000)

    # 既存の gene_best.json があれば初期遺伝子として使用
    best_gene_path = os.path.join(GENE_DIR, 'gene_best.json')
    if os.path.exists(best_gene_path):
        try:
            best_gene = load_gene(best_gene_path)
            print(f'Loaded best gene from {best_gene_path}')
        except Exception:
            best_gene = None
    else:
        best_gene = None

    # 初期個体群
    population = []
    for i in range(args.population_size):
        if best_gene and i == 0:
            # 1 個体は最良遺伝子から開始 (エリート)
            population.append(best_gene)
        else:
            # 残りはランダム
            base = load_base_params()
            gene = random_gene(base)
            # 50% の確率で best_gene から突然変異 (突然変異で初期化)
            if best_gene and random.random() < 0.5:
                gene = mutate_gene(best_gene, mutation_rate=0.5)
            population.append(gene)

    history = []

    print(f'=== GA Parameter Tuning ===')
    print(f'Generations: {args.generations}, Seeds/gen: {args.seeds}, Workers: {args.max_workers}')
    print(f'Time limit: {args.max_minutes} min')
    print(f'Population: {args.population_size}, Elite: {args.elite_count}, Mutation rate: {args.mutation_rate}')
    print('=' * 60)

    seed_offset = args.start_seed

    # Why: ロードされた best_gene をエリートの初期値とする
    # (1 世代目ですぐに上書きされるが、第 1 世代で全個体がロードされた best_gene より
    # 悪い場合にも gene_best.json を保持できる)
    all_time_best_gene = best_gene
    all_time_best_score = -999.0  # 初期値、最初の本評価で必ず更新される

    # Why: resume モードでは前回の続きから開始
    # (population は best_gene から再生成するので実体は同じ)
    history = []
    if args.resume and os.path.exists(args.history_file):
        try:
            with open(args.history_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
            if history:
                last_gen = history[-1]['generation']
                seed_offset = args.start_seed + (last_gen + 1) * args.seeds
                # 履歴から全世代ベストを復元
                all_time_best_score = max(r[2] for h in history for r in h.get('results', []))
                print(f'Resumed from gen {last_gen + 1}, seed_offset={seed_offset}, all_time_best={all_time_best_score:+.1f} pt')
        except Exception as e:
            print(f'Warning: could not load history: {e}')

    for gen in range(args.generations):
        elapsed = time.time() - start_time
        if elapsed > args.max_minutes * 60:
            print(f'Time limit reached after {gen} generations')
            break

        print(f'\n[Gen {gen + 1}/{args.generations}] (elapsed {elapsed/60:.1f} min)')

        # 評価
        t1 = time.time()
        scores = evaluate_population(population, args.seeds, args.max_workers, seed_offset)
        t_eval = time.time() - t1

    # 各個体の Gyoku pt
    results = []
    for i, gene in enumerate(population):
        name = f'OurAI-{i}'
        score = scores.get(name, -999.0)
        results.append((i, name, score, gene))

        results.sort(key=lambda x: -x[2])  # 降順

        # Why: 現世代ベストと全世代ベストを比較。全世代ベストのみ保存する。
        # 1 世代内 (4 局) はサンプルが小さく、エリートが真に改善しているとは限らない。
        # 1 世代で最良の遺伝子を保存してしまうと、ノイズで過学習してしまう。
        current_best_score = results[0][2]
        if current_best_score > all_time_best_score:
            all_time_best_score = current_best_score
            all_time_best_gene = population[results[0][0]]
            # 全世代ベストを保存
            save_gene(all_time_best_gene, best_gene_path)
            print(f'  All-time best updated: {all_time_best_score:+.1f} pt (gene idx {results[0][0]})')

        print(f'  Evaluation: {t_eval/60:.1f} min')
        for i, (idx, name, score, _) in enumerate(results):
            marker = ' ★' if i < args.elite_count else ''
            print(f'    Gene {idx} ({name}): {score:+.1f} pt{marker}')

        history.append({
            'generation': gen,
            'time': elapsed,
            'results': [(i, name, s) for i, name, s, _ in results],
            'best_gene_idx': results[0][0],
        })

        # 次世代を生成
        if gen < args.generations - 1:
            new_population = [all_time_best_gene]  # エリート (全世代ベスト)
            # 残りを突然変異で生成
            while len(new_population) < args.population_size:
                # エリートから突然変異、またはエリート + 2番目から交叉
                if random.random() < 0.5:
                    new_population.append(mutate_gene(all_time_best_gene, mutation_rate=args.mutation_rate))
                else:
                    parent1 = all_time_best_gene
                    parent2 = population[results[1][0]] if len(results) > 1 else all_time_best_gene
                    child = crossover_gene(parent1, parent2)
                    # 交叉した子にも突然変異
                    child = mutate_gene(child, mutation_rate=args.mutation_rate * 0.5)
                    new_population.append(child)
            population = new_population

        # 履歴保存
        history_path = os.path.join(LOG_DIR, 'ga_history.json')
        with open(history_path, 'w', encoding='utf-8') as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        seed_offset += args.seeds

    # 最終結果
    print(f'\n=== GA Complete ===')
    print(f'Total time: {(time.time() - start_time) / 60:.1f} min')
    print(f'Generations: {len(history)}')
    print(f'Best gene saved to: {best_gene_path}')
    print(f'Final all-time best gene (score {all_time_best_score:+.1f} pt):')
    print(json.dumps(all_time_best_gene, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
