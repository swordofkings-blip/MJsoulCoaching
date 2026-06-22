"""
@title Akochan GA最適化ツール
@description
    gene_0 (ベタオリ強めで Akochan に勝てる遺伝子) をベースに、
    突然変異と交叉で遺伝子を進化させ、Akochan に対する勝率を最大化する。

    各世代で 3つの遺伝子を Akochan と対戦させ、勝率の高い遺伝子を次世代に残す。
"""
import os
import sys
import json
import time
import random
import argparse
import shutil
import subprocess

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)


# 突然変異の範囲
GENE_BOUNDS = {
    "RIICHI_URA_MULT": (1.0, 1.8),
    "RIICHI_FOLD_RATE": (0.3, 0.9),
    "RIICHI_DEFENSE_COST": (0.1, 0.6),
    "DAMATEN_FLEX_BONUS": (0, 50),
    "DAMATEN_YAKU_IMP_BONUS": (0.0, 0.2),
    "DAMATEN_WAIT_IMP_BONUS": (0.0, 0.1),
    "PUSH_SAFE_TILES_BONUS": (0.0, 0.6),
    "FOLD_SAFE_TILES_BONUS": (0.0, 0.6),
    "TERMINAL_TILE_PUSH_BONUS": (0.0, 0.3),
    "DYE_HONOR_PUSH_BONUS": (0.2, 0.7),
    "RIICHI_LATE_PENALTY": (0.5, 1.0),
    "RIICHI_OPP_REACH_PENALTY": (0.2, 0.7),
}


def load_gene(gene_path: str) -> dict:
    with open(gene_path, 'r', encoding='utf-8') as f:
        return json.load(f)


def save_gene(gene: dict, gene_path: str):
    with open(gene_path, 'w', encoding='utf-8') as f:
        json.dump(gene, f, ensure_ascii=False, indent=2)


def mutate_gene(gene: dict, mutation_rate: float = 0.4, mutation_size: float = 0.2) -> dict:
    """
    @title 遺伝子の突然変異
    @param {dict} gene - 突然変異前の遺伝子
    @param {float} mutation_rate - 各パラメータが突然変異する確率
    @param {float} mutation_size - 突然変異の最大幅 (0.0-1.0、範囲に対する割合)
    @returns {dict} 突然変異後の遺伝子
    """
    new_gene = dict(gene)
    for key, (mn, mx) in GENE_BOUNDS.items():
        if random.random() > mutation_rate:
            continue
        cur = new_gene.get(key, (mn + mx) / 2)
        d = (mx - mn) * mutation_size * (random.random() - 0.5) * 2
        new_gene[key] = round(max(mn, min(mx, cur + d)), 4)
    return new_gene


def crossover_gene(g1: dict, g2: dict) -> dict:
    """
    @title 2つの遺伝子の交叉
    @param {dict} g1 - 親1
    @param {dict} g2 - 親2
    @returns {dict} 交叉後の遺伝子
    """
    new_gene = {}
    for key in GENE_BOUNDS:
        if random.random() < 0.5:
            new_gene[key] = g1.get(key, 0.5)
        else:
            new_gene[key] = g2.get(key, 0.5)
    return new_gene


def run_battle_evaluation(gene_paths: list, seeds: int = 2) -> dict:
    """
    @title 3つの遺伝子 vs Akochan の評価
    @param {list} gene_paths - 3つの遺伝子ファイルパス
    @param {int} seeds - 評価に使うシード数
    @returns {dict} {gene_index: gyoku_pt, ...}
    """
    # 既存の結果ファイルを確認
    cmd = [
        sys.executable, os.path.join(THIS_DIR, 'mjai_battle_genes.py'),
        str(seeds), '1', '1',
        '--gene-dir', os.path.dirname(gene_paths[0])
    ]
    # gene_pathsをコピーして一時ディレクトリで評価
    print(f'  Running battle for: {[os.path.basename(p) for p in gene_paths if p]}')
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    output = result.stdout

    # 出力をパース: "OurAI-0 (gene_0): +X.X pt ★ BEST" のような行を探す
    scores = {}
    for line in output.splitlines():
        if '(gene_' in line and 'pt' in line:
            parts = line.split(':')
            if len(parts) >= 2:
                name_part = parts[0].strip()
                pt_part = parts[1].strip().split()[0]
                # "OurAI-0 (gene_0)" → index 0
                if 'OurAI-0' in name_part:
                    scores[0] = float(pt_part.replace('+', ''))
                elif 'OurAI-1' in name_part:
                    scores[1] = float(pt_part.replace('+', ''))
                elif 'OurAI-2' in name_part:
                    scores[2] = float(pt_part.replace('+', ''))
    return scores


def save_gene_temp(gene: dict, idx: int, temp_dir: str) -> str:
    """指定ディレクトリに遺伝子を保存"""
    path = os.path.join(temp_dir, f'gene_{idx}.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(gene, f, ensure_ascii=False, indent=2)
    return path


def main():
    parser = argparse.ArgumentParser(description='Akochan GA Optimization')
    parser.add_argument('--base-gene', default='gene_variants/gene_0.json',
                        help='開始遺伝子ファイルパス')
    parser.add_argument('--generations', type=int, default=3,
                        help='世代数')
    parser.add_argument('--seeds', type=int, default=3,
                        help='各世代の評価に使うシード数 (推奨: 3以上)')
    parser.add_argument('--work-dir', default='ga_work',
                        help='作業ディレクトリ')
    parser.add_argument('--population', type=int, default=3,
                        help='集団サイズ (3つに固定)')
    parser.add_argument('--mutation-rate', type=float, default=0.4,
                        help='突然変異率')
    parser.add_argument('--mutation-size', type=float, default=0.2,
                        help='突然変異サイズ')
    parser.add_argument('--anchor-gene', default=None,
                        help='固定遺伝子 (常に1つに含める)')
    args = parser.parse_args()

    work_dir = os.path.join(ROOT_DIR, args.work_dir)
    os.makedirs(work_dir, exist_ok=True)

    # ベース遺伝子を読み込み
    base_gene = load_gene(os.path.join(ROOT_DIR, args.base_gene))
    print(f'Base gene: {args.base_gene}')
    print(f'Base score (gene_0, Akochan +39.2pt @ 3 seeds)')
    if args.anchor_gene:
        anchor_gene = load_gene(os.path.join(ROOT_DIR, args.anchor_gene))
        print(f'Anchor gene: {args.anchor_gene} (固定)')
    print()

    # 初期集団
    population = [base_gene]
    population.append(mutate_gene(base_gene, args.mutation_rate * 1.5, args.mutation_size * 1.5))
    population.append(mutate_gene(base_gene, args.mutation_rate, args.mutation_size))

    best_gene = base_gene
    best_score = 39.2

    history = []

    for gen in range(args.generations):
        print(f'=== Generation {gen + 1}/{args.generations} (seeds={args.seeds}) ===')
        for i, g in enumerate(population):
            save_gene_temp(g, i, work_dir)

        # anchor_geneを使う場合: gene_0を固定で、gene_1, gene_2を進化
        if args.anchor_gene:
            # anchor_geneをgene_0位置にコピー
            shutil.copy(
                os.path.join(ROOT_DIR, args.anchor_gene),
                os.path.join(work_dir, 'gene_0.json')
            )
            # gene_1, gene_2は進化
            save_gene_temp(population[1], 1, work_dir)
            save_gene_temp(population[2], 2, work_dir)

        gene_paths = [os.path.join(work_dir, f'gene_{i}.json') for i in range(args.population)]
        scores = run_battle_evaluation(gene_paths, args.seeds)

        if not scores or len(scores) != args.population:
            print(f'  Error: invalid scores {scores}')
            continue

        for i, s in scores.items():
            print(f'  Gene {i}: {s:+.1f} pt')
        history.append(scores)

        best_idx = max(scores, key=scores.get)
        gen_best = population[best_idx]
        gen_best_score = scores[best_idx]
        print(f'  Best of gen {gen+1}: gene_{best_idx} ({gen_best_score:+.1f} pt)')

        if gen_best_score > best_score:
            best_score = gen_best_score
            best_gene = gen_best
            save_gene(best_gene, os.path.join(ROOT_DIR, 'gene_variants', 'gene_best.json'))
            print(f'  ★ New best: {best_score:+.1f} pt (saved to gene_best.json)')

        # 次世代
        next_population = [gen_best]
        next_population.append(mutate_gene(gen_best, args.mutation_rate, args.mutation_size))
        next_population.append(mutate_gene(gen_best, args.mutation_rate * 1.2, args.mutation_size * 1.5))
        population = next_population

        print()

    print('=' * 60)
    print(f'Final best: {best_score:+.1f} pt (vs Akochan)')
    print(f'Saved to gene_variants/gene_best.json')
    print()
    print('=== History ===')
    for gen_idx, scores in enumerate(history):
        best_idx = max(scores, key=scores.get)
        print(f'  Gen {gen_idx+1}: best gene_{best_idx} = {scores[best_idx]:+.1f} pt')

    # 結果ファイル
    history_path = os.path.join(ROOT_DIR, 'ga_akochan_history.json')
    with open(history_path, 'w', encoding='utf-8') as f:
        json.dump({
            'best_score': best_score,
            'best_gene': best_gene,
            'history': history,
        }, f, ensure_ascii=False, indent=2)
    print(f'History saved to {history_path}')


if __name__ == '__main__':
    main()
