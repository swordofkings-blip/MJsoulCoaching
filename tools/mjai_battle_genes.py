"""
@title 遺伝子別Akochan対戦ツール
@description
    3体の OurAI (それぞれ異なる遺伝子パラメータ) vs Akochan
    各AIの局所的な「遺伝子」だけをJSONから読み込み、mainパラメータにマージして対戦。
    最終的にどの遺伝子が Akochanに強かったかを評価する。
"""
import os
import sys
import json
import time
import argparse
import subprocess
import threading
import concurrent.futures
from typing import List, Tuple

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)


def run_our_ai_with_genes(port: int, name: str, gene_path: str, base_params: dict):
    """
    @title 自作AIを遺伝子パラメータで起動
    @param {int} port - MJAIサーバーポート
    @param {str} name - プレイヤー名
    @param {str} gene_path - 遺伝子JSONファイルパス (部分的なパラメータ)
    @param {dict} base_params - ベースパラメータ
    """
    from tools.mjai_client import OurMjaiClient

    # ベースパラメータを読み込み、遺伝子で上書き
    params = dict(base_params)  # deep copy
    if gene_path and os.path.exists(gene_path):
        with open(gene_path, 'r', encoding='utf-8') as f:
            gene_params = json.load(f)
        params.update(gene_params)

    # 自作AIはPython内で動く
    c = OurMjaiClient('127.0.0.1', port, 'default', name, params)
    try:
        c.play_game()
    finally:
        c.close()


def sh(cmd, timeout=60, **kwargs):
    if 'stderr' in kwargs or 'stdout' in kwargs:
        kwargs.setdefault('stdout', subprocess.PIPE)
        return subprocess.run(cmd, text=True, timeout=timeout, **kwargs)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)


def run_akochan(port: int, container_name: str):
    sh(['docker', 'exec', container_name,
        '/opt/akochan/system.exe', 'mjai_client',
        str(port), '/opt/akochan/setup_mjai.json'],
       timeout=1200)


def run_one_game_gene(game_idx: int, max_workers: int, start_seed: int, gene_paths: List[str]) -> dict:
    seed_idx = game_idx // 4
    seat_offset = game_idx % 4
    seed_value = start_seed + seed_idx

    server_name = f"mjai-srv-g{game_idx}"
    akochan_cname = f"akochan-srv-g{game_idx}_akochan"
    port = 11600 + game_idx

    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    ruby_cmd = f"ARGV.clear; ARGV.concat(['server', '--port={port}', '--host=0.0.0.0', '--game_type=tonpu', '--room=default']); srand({seed_value}); require 'mjai/mjai_command'; Mjai::MjaiCommand.execute('mjai', ARGV)"
    sh(['docker', 'run', '-d', '--rm', '--name', server_name,
        '-p', f'{port}:{port}',
        '--entrypoint', 'ruby',
        'mjai-server', '-e', ruby_cmd])
    time.sleep(2)

    sh(['docker', 'run', '-d', '--name', akochan_cname,
        '--add-host', 'host.docker.internal:host-gateway',
        '--entrypoint', 'sleep', 'akochan-docker-app', 'infinity'])
    sh(['docker', 'exec', '-u', 'root', akochan_cname,
        'bash', '-c', 'apt-get update -qq && apt-get install -y -qq socat'],
       timeout=120)
    sh(['docker', 'exec', '-u', 'root', '-d', akochan_cname,
        'socat', f'TCP-LISTEN:{port},fork,reuseaddr',
        f'TCP:host.docker.internal:{port}'])
    time.sleep(1)

    # ベースパラメータを読み込み (遺伝子なしの基本形)
    base_params_path = os.path.join(ROOT_DIR, 'config', 'config_parameters.json')
    with open(base_params_path, 'r', encoding='utf-8') as f:
        base_params = json.load(f)

    # 3体の OurAI: それぞれ異なる遺伝子
    # gene_paths[0], [1], [2] の3つ
    players = [
        ("OurAI-0", lambda p: threading.Thread(
            target=run_our_ai_with_genes,
            args=(p, "OurAI-0", gene_paths[0] if len(gene_paths) > 0 else None, base_params),
            daemon=True)),
        ("OurAI-1", lambda p: threading.Thread(
            target=run_our_ai_with_genes,
            args=(p, "OurAI-1", gene_paths[1] if len(gene_paths) > 1 else None, base_params),
            daemon=True)),
        ("OurAI-2", lambda p: threading.Thread(
            target=run_our_ai_with_genes,
            args=(p, "OurAI-2", gene_paths[2] if len(gene_paths) > 2 else None, base_params),
            daemon=True)),
        ("Akochan", lambda p: threading.Thread(target=run_akochan, args=(p, akochan_cname), daemon=True))
    ]
    shift = seat_offset
    rotated_players = players[shift:] + players[:shift]

    threads = []
    akochan_thread = None
    for name, launch_func in rotated_players:
        t = launch_func(port)
        t.start()
        threads.append(t)
        if name == "Akochan":
            akochan_thread = t
        time.sleep(0.5)

    time.sleep(3)

    if akochan_thread:
        akochan_thread.join(timeout=1200)

    logs = sh(['docker', 'logs', server_name], stderr=subprocess.STDOUT)

    log_dir = os.path.join(ROOT_DIR, 'logs')
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, f"game_gene_{game_idx}.log"), "w", encoding="utf-8") as f:
        f.write(logs.stdout)

    mjson_lines = []
    for line in logs.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith('{') and line.endswith('}'):
            try:
                json.loads(line)
                mjson_lines.append(line)
                continue
            except ValueError:
                pass
        import re
        match = re.search(r'(?:server -> player \d+|server <- player \d+|\*?\[\d+\])\s*\t\s*(\{.*\})', line)
        if match:
            json_str = match.group(1).strip()
            try:
                json.loads(json_str)
                mjson_lines.append(json_str)
            except ValueError:
                pass
        elif any(p in line for p in ['player ?', 'player 0', 'player 1', 'player 2', 'player 3']):
            match_json = re.search(r'(\{.*\})', line)
            if match_json:
                json_str = match_json.group(1).strip()
                try:
                    json.loads(json_str)
                    mjson_lines.append(json_str)
                except ValueError:
                    pass
    with open(os.path.join(log_dir, f"game_gene_{game_idx}.mjson"), "w", encoding="utf-8") as f:
        for line in mjson_lines:
            f.write(line + "\n")

    scores = _parse_final_scores(logs.stdout)
    if scores:
        return scores

    return {"OurAI-0": 25000, "OurAI-1": 25000, "OurAI-2": 25000, "Akochan": 25000}


def _parse_final_scores(log_text: str) -> dict:
    scores = {}
    for line in log_text.splitlines():
        if 'final_scores' in line.lower() or 'no_winner' in line.lower():
            continue
        # Look for score patterns like "player X score: Y" or JSON with scores
        import re
        matches = re.findall(r'"(?:scores|score)"\s*:\s*\[([\d,\s]+)\]', line)
        for m in matches:
            score_list = [int(s.strip()) for s in m.split(',') if s.strip()]
            if len(score_list) == 4:
                for i, name in enumerate(['OurAI-0', 'OurAI-1', 'OurAI-2', 'Akochan']):
                    if i < len(score_list):
                        scores[name] = score_list[i]
                return scores
    return scores


def main():
    parser = argparse.ArgumentParser(description='Gene-variant Akochan battle')
    parser.add_argument('total_seeds', type=int, default=3, nargs='?',
                        help='シード数 (各4ゲーム)')
    parser.add_argument('max_workers', type=int, default=3, nargs='?',
                        help='並列数')
    parser.add_argument('start_seed', type=int, default=1, nargs='?',
                        help='開始シード')
    parser.add_argument('--gene-dir', default='gene_variants',
                        help='遺伝子JSONファイルのディレクトリ')
    args = parser.parse_args()

    # 遺伝子ファイルをロード (gene_0.json, gene_1.json, gene_2.json)
    gene_dir = os.path.join(ROOT_DIR, args.gene_dir)
    if not os.path.exists(gene_dir):
        os.makedirs(gene_dir)
        print(f'Created empty gene directory: {gene_dir}')
        print(f'Please add gene_0.json, gene_1.json, gene_2.json files.')
        return

    gene_paths = []
    for i in range(3):
        gene_path = os.path.join(gene_dir, f'gene_{i}.json')
        if os.path.exists(gene_path):
            gene_paths.append(gene_path)
        else:
            gene_paths.append(None)
            print(f'Warning: gene_{i}.json not found, using default params')

    print(f'=== Gene Battle: 3 Gene Variants vs Akochan ===')
    print(f'Total Seeds: {args.total_seeds} ({args.total_seeds * 4} games)')
    print(f'Max Workers: {args.max_workers}')
    print(f'Start Seed:  {args.start_seed}')
    print(f'Gene variants:')
    for i, p in enumerate(gene_paths):
        if p:
            print(f'  OurAI-{i}: {os.path.basename(p)}')
        else:
            print(f'  OurAI-{i}: (default params)')
    print('=' * 60)

    results = []
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.max_workers) as executor:
        futures = {
            executor.submit(run_one_game_gene, i, args.max_workers, args.start_seed, gene_paths): i
            for i in range(args.total_seeds * 4)
        }

        for future in concurrent.futures.as_completed(futures):
            game_idx = futures[future]
            try:
                scores = future.result()
                results.append(scores)
                seed_num = args.start_seed + (game_idx // 4)
                seat_num = game_idx % 4
                print(f"[Game {game_idx + 1}] (Seed {seed_num}, Seat {seat_num}) {scores}")
            except Exception as exc:
                print(f"[Game {game_idx + 1}] Error: {exc}")

    if not results:
        print('No results collected')
        return

    # 統計
    stats = {f"OurAI-{i}": {"scores": [], "ranks": [], "so_pts": [], "gy_pts": [], "ou_pts": []} for i in range(3)}
    stats["Akochan"] = {"scores": [], "ranks": [], "so_pts": [], "gy_pts": [], "ou_pts": []}

    uma_gy = [70, 35, -5, -95]
    uma_ou = [75, 35, -5, -165]

    for scores in results:
        sorted_players = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        for rank, (name, score) in enumerate(sorted_players, 1):
            if name in stats:
                stats[name]['scores'].append(score)
                stats[name]['ranks'].append(rank)
                so_pt = (score - 25000) / 1000.0
                gy_pt = so_pt + uma_gy[rank - 1]
                ou_pt = so_pt + uma_ou[rank - 1]
                stats[name]['so_pts'].append(so_pt)
                stats[name]['gy_pts'].append(gy_pt)
                stats[name]['ou_pts'].append(ou_pt)

    print()
    print('=' * 60)
    print('=== Final Statistics ===')
    print('=' * 60)
    for name in ['OurAI-0', 'OurAI-1', 'OurAI-2', 'Akochan']:
        s = stats[name]
        if not s['scores']:
            continue
        n = len(s['scores'])
        avg_rank = sum(s['ranks']) / n
        avg_so = sum(s['so_pts']) / n
        avg_gy = sum(s['gy_pts']) / n
        avg_ou = sum(s['ou_pts']) / n
        rank_dist = [s['ranks'].count(r) for r in [1, 2, 3, 4]]
        print(f'\n{name}:')
        print(f'  Games: {n}')
        print(f'  Avg Rank: {avg_rank:.2f}  Dist: {rank_dist}')
        print(f'  Avg Score: {sum(s["scores"])/n:.0f}')
        print(f'  Avg SoPt: {avg_so:+.1f}')
        print(f'  Avg Gyoku Pt: {avg_gy:+.1f}')
        print(f'  Avg Ouza Pt: {avg_ou:+.1f}')

    # 遺伝子比較
    print()
    print('=' * 60)
    print('=== Gene Comparison (vs Akochan) ===')
    ourai_scores = [sum(stats[f"OurAI-{i}"]["gy_pts"]) / max(1, len(stats[f"OurAI-{i}"]["gy_pts"])) for i in range(3)]
    best_gene = ourai_scores.index(max(ourai_scores))
    for i in range(3):
        marker = ' ★ BEST' if i == best_gene else ''
        print(f'  OurAI-{i} (gene_{i}): {ourai_scores[i]:+.1f} pt{marker}')

    ako_gy = sum(stats["Akochan"]["gy_pts"]) / max(1, len(stats["Akochan"]["gy_pts"]))
    print(f'  Akochan: {ako_gy:+.1f} pt')
    print()
    best_diff = ourai_scores[best_gene] - ako_gy
    print(f'Best gene vs Akochan: {best_diff:+.1f} pt')


if __name__ == '__main__':
    main()
