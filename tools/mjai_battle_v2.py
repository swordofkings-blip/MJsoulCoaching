# -*- coding: utf-8 -*-
"""
@title ver.2 MJAI対戦バトルランナー
@description Docker上の mjai-server および akochan と通信し、
              ver.2 AI の自動並列対局を実行して対戦成績（平均順位・期待値pt）を測定します。
"""
import os
import subprocess
import sys
import threading
import time
import re
import json
import concurrent.futures

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

SERVER_IMAGE = 'mjai-server'
AKOCHAN_IMAGE = 'akochan-docker-app'


def sh(cmd, timeout=60, **kwargs):
    if 'stderr' in kwargs or 'stdout' in kwargs:
        kwargs.setdefault('stdout', subprocess.PIPE)
        return subprocess.run(cmd, text=True, timeout=timeout, **kwargs)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)


def run_our_ai_v2(port: int, name: str):
    """ver.2 AI client (EvaluatorV2)"""
    from tools.mjai_client_v2 import OurMjaiClientV2

    base_dir = os.path.join(os.path.dirname(__file__), '..')
    params_path = os.path.join(base_dir, 'config', 'config_parameters.json')
    with open(params_path, 'r', encoding='utf-8') as f:
        params = json.load(f)

    c = OurMjaiClientV2('127.0.0.1', port, 'default', name, params)
    try:
        c.play_game()
    finally:
        c.close()


def run_akochan(port: int, container_name: str):
    sh(['docker', 'exec', container_name,
        '/opt/akochan/system.exe', 'mjai_client',
        str(port), '/opt/akochan/setup_mjai.json'],
       timeout=1200)


def run_one_game(game_idx: int, max_workers: int, start_seed: int) -> dict:
    seed_idx = game_idx // 4
    seat_offset = game_idx % 4
    seed_value = start_seed + seed_idx

    server_name = f"mjai-srv-{game_idx}"
    akochan_cname = f"akochan-srv-{game_idx}_akochan"
    port = 11600 + game_idx

    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    ruby_cmd = (f"ARGV.clear; ARGV.concat(['server', '--port={port}', '--host=0.0.0.0', "
                f"'--game_type=tonpu', '--room=default']); srand({seed_value}); "
                f"require 'mjai/mjai_command'; Mjai::MjaiCommand.execute('mjai', ARGV)")
    sh(['docker', 'run', '-d', '--rm', '--name', server_name,
        '-p', f'{port}:{port}', '--entrypoint', 'ruby',
        SERVER_IMAGE, '-e', ruby_cmd])
    time.sleep(2)

    sh(['docker', 'run', '-d', '--name', akochan_cname,
        '--add-host', 'host.docker.internal:host-gateway',
        '--entrypoint', 'sleep', AKOCHAN_IMAGE, 'infinity'])

    sh(['docker', 'exec', '-u', 'root', akochan_cname,
        'bash', '-c', 'apt-get update -qq && apt-get install -y -qq socat'],
       timeout=120)
    sh(['docker', 'exec', '-u', 'root', '-d', akochan_cname,
        'socat', f'TCP-LISTEN:{port},fork,reuseaddr',
        f'TCP:host.docker.internal:{port}'])
    time.sleep(1)

    players = [
        ("OurAIv2-0", lambda p: threading.Thread(target=run_our_ai_v2, args=(p, "OurAIv2-0"), daemon=True)),
        ("OurAIv2-1", lambda p: threading.Thread(target=run_our_ai_v2, args=(p, "OurAIv2-1"), daemon=True)),
        ("Akochan-0", lambda p: threading.Thread(target=run_akochan, args=(p, akochan_cname), daemon=True)),
        ("Akochan-1", lambda p: threading.Thread(target=run_akochan, args=(p, akochan_cname), daemon=True))
    ]
    shift = seat_offset
    rotated_players = players[shift:] + players[:shift]

    threads = []
    akochan_threads = []
    for name, launch_func in rotated_players:
        t = launch_func(port)
        t.start()
        threads.append(t)
        if "Akochan" in name:
            akochan_threads.append(t)
        time.sleep(0.5)

    time.sleep(3)

    for at in akochan_threads:
        at.join(timeout=1200)

    logs = sh(['docker', 'logs', server_name], stderr=subprocess.STDOUT)

    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, f"game_{game_idx}.log"), "w", encoding="utf-8") as f:
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

    with open(os.path.join(log_dir, f"game_{game_idx}.mjson"), "w", encoding="utf-8") as f:
        for mline in mjson_lines:
            f.write(mline + '\n')

    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    # mjson から各プレイヤーのスタッツを集計
    player_names = [p[0] for p in rotated_players]
    stats = {n: {'wins': 0, 'tsumo': 0, 'ron': 0, 'reach': 0} for n in player_names}
    last_hora = None
    for mline in mjson_lines:
        try:
            obj = json.loads(mline)
            t = obj.get("type")
            if t == "reach":
                actor = obj.get("actor", -1)
                if 0 <= actor < 4:
                    stats[player_names[actor]]['reach'] += 1
            elif t == "hora":
                actor = obj.get("actor", -1)
                target = obj.get("target", -1)
                if 0 <= actor < 4:
                    stats[player_names[actor]]['wins'] += 1
                    if actor != target and target >= 0:
                        stats[player_names[actor]]['ron'] += 1
                    else:
                        stats[player_names[actor]]['tsumo'] += 1
        except Exception:
            pass

    scores = {}
    end_game_scores = None
    for mline in reversed(mjson_lines):
        try:
            obj = json.loads(mline)
            if obj.get("type") == "end_game" and "scores" in obj:
                end_game_scores = obj["scores"]
                break
        except Exception:
            pass

    if end_game_scores and len(end_game_scores) >= 4:
        for seat_idx in range(4):
            player_name = rotated_players[seat_idx][0]
            scores[player_name] = int(end_game_scores[seat_idx])

    if not scores:
        match = re.search(r"game \d+: (.+)", logs.stdout)
        if match:
            parts = match.group(1).strip().split()
            for part in parts:
                if ':' not in part:
                    continue
                name, score_str = part.rsplit(':', 1)
                try:
                    scores[name] = int(score_str)
                except ValueError:
                    continue

    return {'scores': scores, 'stats': stats}


def main():
    total_seeds = 25
    max_workers = 3
    start_seed = 1

    if len(sys.argv) > 1:
        try:
            total_seeds = int(sys.argv[1])
        except ValueError:
            pass
    if len(sys.argv) > 2:
        try:
            max_workers = int(sys.argv[2])
        except ValueError:
            pass
    if len(sys.argv) > 3:
        try:
            start_seed = int(sys.argv[3])
        except ValueError:
            pass

    total_games = total_seeds * 4

    print(f"=== MJAI Parallel Battle: ver.2 AI vs Akochan (Duplicate Mode) ===")
    print(f"Total Seeds: {total_seeds} ({total_games} games)")
    print(f"Max Workers: {max_workers}")
    print(f"Start Seed:  {start_seed}")
    print(f"Base Port:   11600")
    print(f"===============================================================")

    results = []

    with concurrent.futures.ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_one_game, i, max_workers, start_seed): i
            for i in range(total_games)
        }

        for future in concurrent.futures.as_completed(futures):
            game_idx = futures[future]
            try:
                scores = future.result()
                results.append(scores)
                seed_num = start_seed + (game_idx // 4)
                seat_num = game_idx % 4
                print(f"[Game {game_idx + 1}/{total_games}] (Seed {seed_num}, Seat {seat_num}) Finished. Scores: {scores}")
            except Exception as exc:
                print(f"[Game {game_idx + 1}/{total_games}] Generated an exception: {exc}")

    stats = {
        "OurAIv2-0": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "OurAIv2-1": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "Akochan-0": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "Akochan-1": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []}
    }

    for scores in results:
        if not scores:
            continue
        sorted_players = sorted(scores['scores'].items(), key=lambda x: x[1], reverse=True)

        uma_gyokujin = [70.0, 35.0, -5.0, -95.0]
        uma_ouza = [75.0, 35.0, -5.0, -165.0]

        for rank, (name, score) in enumerate(sorted_players, 1):
            if name in stats:
                so_pt = (score - 25000) / 1000.0
                gyokujin_pt = so_pt + uma_gyokujin[rank - 1]
                ouza_pt = so_pt + uma_ouza[rank - 1]
                stats[name]["scores"].append(score)
                stats[name]["ranks"].append(rank)
                stats[name]["so_pts"].append(so_pt)
                stats[name]["gyokujin_pts"].append(gyokujin_pt)
                stats[name]["ouza_pts"].append(ouza_pt)

    print("\n=== Final Statistics (Mahjong Soul Style) ===")
    our_gyokujin_total = []
    our_ouza_total = []
    our_so_total = []
    ako_gyokujin_total = []
    ako_ouza_total = []
    ako_so_total = []

    for name, data in stats.items():
        if not data["scores"]:
            print(f"{name}: No data")
            continue
        avg_score = sum(data["scores"]) / len(data["scores"])
        avg_rank = sum(data["ranks"]) / len(data["ranks"])
        avg_so_pt = sum(data["so_pts"]) / len(data["so_pts"])
        avg_gyokujin_pt = sum(data["gyokujin_pts"]) / len(data["gyokujin_pts"])
        avg_ouza_pt = sum(data["ouza_pts"]) / len(data["ouza_pts"])

        if "OurAIv2" in name:
            our_so_total.extend(data["so_pts"])
            our_gyokujin_total.extend(data["gyokujin_pts"])
            our_ouza_total.extend(data["ouza_pts"])
        elif "Akochan" in name:
            ako_so_total.extend(data["so_pts"])
            ako_gyokujin_total.extend(data["gyokujin_pts"])
            ako_ouza_total.extend(data["ouza_pts"])

        rank_counts = [data["ranks"].count(r) for r in (1, 2, 3, 4)]
        print(f"{name}:")
        print(f"  Average Rank:     {avg_rank:.3f}")
        print(f"  Average Score:    {avg_score:.1f}")
        print(f"  Average 素点pt:   {avg_so_pt:+.3f} pt")
        print(f"  Average 玉の間pt: {avg_gyokujin_pt:+.3f} pt (雀豪1基準)")
        print(f"  Average 王座の間pt: {avg_ouza_pt:+.3f} pt (雀聖1基準)")
        print(f"  Rank Dist:        1st:{rank_counts[0]}, 2nd:{rank_counts[1]}, 3rd:{rank_counts[2]}, 4th:{rank_counts[3]}")

    if our_gyokujin_total and ako_gyokujin_total:
        our_avg_so = sum(our_so_total) / len(our_so_total)
        ako_avg_so = sum(ako_so_total) / len(ako_so_total)

        our_avg_gyo = sum(our_gyokujin_total) / len(our_gyokujin_total)
        ako_avg_gyo = sum(ako_gyokujin_total) / len(ako_gyokujin_total)

        our_avg_ouza = sum(our_ouza_total) / len(our_ouza_total)
        ako_avg_ouza = sum(ako_ouza_total) / len(ako_ouza_total)

        print("\n==============================================")
        print(f"OurAIv2 Avg 素点pt:      {our_avg_so:+.3f} pt | Akochan: {ako_avg_so:+.3f} pt (Diff: {our_avg_so - ako_avg_so:+.3f} pt)")
        print(f"OurAIv2 Avg 玉の間pt:    {our_avg_gyo:+.3f} pt | Akochan: {ako_avg_gyo:+.3f} pt (Diff: {our_avg_gyo - ako_avg_gyo:+.3f} pt)")
        print(f"OurAIv2 Avg 王座の間pt:  {our_avg_ouza:+.3f} pt | Akochan: {ako_avg_ouza:+.3f} pt (Diff: {our_avg_ouza - ako_avg_ouza:+.3f} pt)")
        print("==============================================")


if __name__ == '__main__':
    main()
