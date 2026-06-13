# -*- coding: utf-8 -*-
"""Orchestrate MJAI server + akochan + our AI battle in parallel."""
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
    """
    @title 外部コマンドの実行ヘルパー
    @description subprocess.runのラッパー関数です。
    @param {list} cmd - 実行するコマンドのリスト
    @param {int} timeout - タイムアウト秒数。60秒を基本とします。
    @returns {subprocess.CompletedProcess} 実行結果オブジェクト
    """
    if 'stderr' in kwargs or 'stdout' in kwargs:
        kwargs.setdefault('stdout', subprocess.PIPE)
        return subprocess.run(cmd, text=True, timeout=timeout, **kwargs)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kwargs)


def run_our_ai(port: int, name: str):
    """
    @title 自作AIクライアントの実行
    @description 自作のルールベースAI (Evaluator) を作成し、指定されたポートのMJAIサーバーに接続させてプレイさせます。
    @param {int} port - MJAIサーバーのポート番号
    @param {str} name - プレイヤー名
    """
    from tools.mjai_client import OurMjaiClient
    
    base_dir = os.path.join(os.path.dirname(__file__), '..')
    params_path = os.path.join(base_dir, 'config', 'config_parameters.json')
    with open(params_path, 'r', encoding='utf-8') as f:
        params = json.load(f)

    # 自作AIはPython内で動くため、Dockerコンテナは不要です。
    c = OurMjaiClient('127.0.0.1', port, 'default', name, params)
    try:
        c.play_game()
    finally:
        c.close()


def run_akochan(port: int, container_name: str):
    """
    @title akochanクライアントの実行
    @description 指定されたコンテナ内のsystem.exeを実行し、MJAIクライアントとして接続します。
    @param {int} port - 接続先ポート番号
    @param {str} container_name - 対象のDockerコンテナ名
    """
    # 対局全体のタイムアウト秒数です。akochanの思考が非常に重いため、余裕を持って1200秒（20分）を設定しています。
    sh(['docker', 'exec', container_name,
        '/opt/akochan/system.exe', 'mjai_client',
        str(port), '/opt/akochan/setup_mjai.json'],
       timeout=1200)


def run_one_game(game_idx: int, max_workers: int, start_seed: int) -> dict:
    """
    @title 1対局の並列実行ロジック (デュプリケーター式)
    @description ゲームIDから牌山シード値と席移動オフセットを決定し、シード固定したMJAIサーバーを起動して対局を行います。
    @param {int} game_idx - 対局 of 通し番号
    @param {int} max_workers - 最大並列数
    @param {int} start_seed - 開始シード値
    @returns {dict} プレイヤーごとの最終スコア辞書
    """
    # 4対局で1セット（1つのシードに対する席替え）とします。
    # seed_value は各対局セットで固定のシード値、shift は席の回転量です。
    seed_idx = game_idx // 4
    seat_offset = game_idx % 4
    seed_value = start_seed + seed_idx

    server_name = f"mjai-srv-{game_idx}"
    akochan_cname = f"akochan-srv-{game_idx}_akochan"
    port = 11600 + game_idx

    # 前回の残骸コンテナがあれば強制削除します
    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    # MJAIサーバーの起動 (rubyラッパーを使用してシード値をsrandで固定)
    ruby_cmd = f"ARGV.clear; ARGV.concat(['server', '--port={port}', '--host=0.0.0.0', '--game_type=tonpu', '--room=default']); srand({seed_value}); require 'mjai/mjai_command'; Mjai::MjaiCommand.execute('mjai', ARGV)"
    sh(['docker', 'run', '-d', '--rm', '--name', server_name,
        '-p', f'{port}:{port}',
        '--entrypoint', 'ruby',
        SERVER_IMAGE, '-e', ruby_cmd])
    # 2 はサーバーの起動完了を待つバッファ秒数です。
    time.sleep(2)

    # 4人目のakochan用コンテナを起動 (CPU制限を解除し、高速動作を許可します)
    sh(['docker', 'run', '-d', '--name', akochan_cname,
        '--add-host', 'host.docker.internal:host-gateway',
        '--entrypoint', 'sleep', AKOCHAN_IMAGE, 'infinity'])
    
    # socat のインストールとポートフォワード設定 (タイムアウト 120 秒)
    sh(['docker', 'exec', '-u', 'root', akochan_cname,
        'bash', '-c', 'apt-get update -qq && apt-get install -y -qq socat'],
       timeout=120)
    sh(['docker', 'exec', '-u', 'root', '-d', akochan_cname,
        'socat', f'TCP-LISTEN:{port},fork,reuseaddr',
        f'TCP:host.docker.internal:{port}'])
    # 1 はsocatのポートバインド完了を待つバッファ秒数です。
    time.sleep(1)

    # 席順（接続順序）を seat_offset に基づいてローテーションさせ、運の偏りを排除します。
    players = [
        ("OurAI-0", lambda p: threading.Thread(target=run_our_ai, args=(p, "OurAI-0"), daemon=True)),
        ("OurAI-1", lambda p: threading.Thread(target=run_our_ai, args=(p, "OurAI-1"), daemon=True)),
        ("OurAI-2", lambda p: threading.Thread(target=run_our_ai, args=(p, "OurAI-2"), daemon=True)),
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
        # 0.5 は接続時のスレッド間競合を防ぐためのディレイ秒数です。
        time.sleep(0.5)

    # 接続安定化の待ち合わせ (3秒)
    time.sleep(3)

    # akochan の思考（対局）が終了するのを待ちます (対局全体のタイムアウト秒数に合わせた1200秒)
    if akochan_thread:
        akochan_thread.join(timeout=1200)

    # サーバーログの取得とデバッグ用ファイルへの保存
    logs = sh(['docker', 'logs', server_name], stderr=subprocess.STDOUT)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, f"game_{game_idx}.log"), "w", encoding="utf-8") as f:
        f.write(logs.stdout)

    # simulator.htmlで可視化再生できるようにするため、生ログからMJAIプロトコルのJSON行のみを抽出してmjsonファイルとして保存します。
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

    # クリーンアップ
    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    # ログから最終スコアをパースします
    scores = {}
    match = re.search(r"game \d+: (.+)", logs.stdout)
    if match:
        parts = match.group(1).strip().split()
        for part in parts:
            name, score_str = part.rsplit(':', 1)
            scores[name] = int(score_str)
    
    return scores


def main():
    # 引数仕様: python tools/mjai_battle.py <シード数> <並列数> <開始シード値>
    # 1シードあたり4席のローテーションを行うため、総ゲーム数は シード数 * 4 となります。
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
    
    print(f"=== MJAI Parallel Battle: Our AI vs Akochan (Duplicate Mode) ===")
    print(f"Total Seeds: {total_seeds} ({total_games} games)")
    print(f"Max Workers: {max_workers}")
    print(f"Start Seed:  {start_seed}")
    print(f"Base Port:   11600")
    print(f"================================================================")

    results = []
    
    # ProcessPoolExecutor を用いて並列にゲームを走らせます
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

    # 統計集計 (素点および雀魂段位ポイント)
    stats = {
        "OurAI-0": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "OurAI-1": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "OurAI-2": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "Akochan": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []}
    }

    for scores in results:
        if not scores:
            continue
        sorted_players = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        # 雀魂 順位点 (東風戦)
        # 1. 玉の間・雀豪1基準: 1位+70, 2位+35, 3位-5, 4位-95
        # 2. 王座の間・雀聖1基準: 1位+75, 2位+35, 3位-5, 4位-165
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

    for name, data in stats.items():
        if not data["scores"]:
            print(f"{name}: No data")
            continue
        avg_score = sum(data["scores"]) / len(data["scores"])
        avg_rank = sum(data["ranks"]) / len(data["ranks"])
        avg_so_pt = sum(data["so_pts"]) / len(data["so_pts"])
        avg_gyokujin_pt = sum(data["gyokujin_pts"]) / len(data["gyokujin_pts"])
        avg_ouza_pt = sum(data["ouza_pts"]) / len(data["ouza_pts"])
        
        if "OurAI" in name:
            our_so_total.extend(data["so_pts"])
            our_gyokujin_total.extend(data["gyokujin_pts"])
            our_ouza_total.extend(data["ouza_pts"])

        rank_counts = [data["ranks"].count(r) for r in (1, 2, 3, 4)]
        print(f"{name}:")
        print(f"  Average Rank:     {avg_rank:.3f}")
        print(f"  Average Score:    {avg_score:.1f}")
        print(f"  Average 素点pt:   {avg_so_pt:+.3f} pt")
        print(f"  Average 玉の間pt: {avg_gyokujin_pt:+.3f} pt (雀豪1基準)")
        print(f"  Average 王座の間pt: {avg_ouza_pt:+.3f} pt (雀聖1基準)")
        print(f"  Rank Dist:        1st:{rank_counts[0]}, 2nd:{rank_counts[1]}, 3rd:{rank_counts[2]}, 4th:{rank_counts[3]}")

    if our_gyokujin_total and stats["Akochan"]["gyokujin_pts"]:
        our_avg_so = sum(our_so_total) / len(our_so_total)
        ako_avg_so = sum(stats["Akochan"]["so_pts"]) / len(stats["Akochan"]["so_pts"])
        
        our_avg_gyo = sum(our_gyokujin_total) / len(our_gyokujin_total)
        ako_avg_gyo = sum(stats["Akochan"]["gyokujin_pts"]) / len(stats["Akochan"]["gyokujin_pts"])
        
        our_avg_ouza = sum(our_ouza_total) / len(our_ouza_total)
        ako_avg_ouza = sum(stats["Akochan"]["ouza_pts"]) / len(stats["Akochan"]["ouza_pts"])
        
        print("\n==============================================")
        print(f"OurAI Avg 素点pt:       {our_avg_so:+.3f} pt | Akochan: {ako_avg_so:+.3f} pt (Diff: {our_avg_so - ako_avg_so:+.3f} pt)")
        print(f"OurAI Avg 玉の間pt:     {our_avg_gyo:+.3f} pt | Akochan: {ako_avg_gyo:+.3f} pt (Diff: {our_avg_gyo - ako_avg_gyo:+.3f} pt)")
        print(f"OurAI Avg 王座の間pt:   {our_avg_ouza:+.3f} pt | Akochan: {ako_avg_ouza:+.3f} pt (Diff: {our_avg_ouza - ako_avg_ouza:+.3f} pt)")
        print("==============================================")


if __name__ == '__main__':
    main()
