# -*- coding: utf-8 -*-
"""Orchestrate MJAI server + akochan (3) vs our AI (1) battle in parallel for 2 games."""
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
    @title 1対局の並列実行ロジック (アウェイ構成: OurAI 1 vs Akochan 3)
    @description シード固定したMJAIサーバーを起動し、1名のOurAIと3名のAkochanを接続して対局を行います。
    @param {int} game_idx - 対局の通し番号
    @param {int} max_workers - 最大並列数
    @param {int} start_seed - 開始シード値
    @returns {dict} プレイヤーごとの最終スコア辞書
    """
    # seed_value は各対局セットで固定のシード値、seat_offset は席の回転量です。
    seed_idx = game_idx // 4
    seat_offset = game_idx % 4
    seed_value = start_seed + seed_idx

    server_name = f"mjai-srv-away-{game_idx}"
    akochan_cname = f"akochan-srv-away-{game_idx}_akochan"
    port = 11700 + game_idx

    # 前回の残骸コンテナがあれば強制削除します
    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    # MJAIサーバーの起動
    ruby_cmd = f"ARGV.clear; ARGV.concat(['server', '--port={port}', '--host=0.0.0.0', '--game_type=tonpu', '--room=default']); srand({seed_value}); require 'mjai/mjai_command'; Mjai::MjaiCommand.execute('mjai', ARGV)"
    sh(['docker', 'run', '-d', '--rm', '--name', server_name,
        '-p', f'{port}:{port}',
        '--entrypoint', 'ruby',
        SERVER_IMAGE, '-e', ruby_cmd])
    # 2 はサーバーの起動完了を待つバッファ秒数です。
    time.sleep(2)

    # akochan用コンテナを起動 (1つのコンテナ内に3つのクライアントを並列接続させます)
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

    # アウェイ卓構成: OurAIが1名、Akochanが3名
    players = [
        ("OurAI", lambda p: threading.Thread(target=run_our_ai, args=(p, "OurAI"), daemon=True)),
        ("Akochan-0", lambda p: threading.Thread(target=run_akochan, args=(p, akochan_cname), daemon=True)),
        ("Akochan-1", lambda p: threading.Thread(target=run_akochan, args=(p, akochan_cname), daemon=True)),
        ("Akochan-2", lambda p: threading.Thread(target=run_akochan, args=(p, akochan_cname), daemon=True))
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
        # 0.5 は接続時のスレッド間競合を防ぐためのディレイ秒数です。
        time.sleep(0.5)

    # 接続安定化の待ち合わせ (3秒)
    time.sleep(3)

    # 全ての akochan の思考（対局）が終了するのを待ちます (タイムアウト1200秒)
    for at in akochan_threads:
        at.join(timeout=1200)

    # サーバーログの取得とデバッグ用ファイルへの保存
    logs = sh(['docker', 'logs', server_name], stderr=subprocess.STDOUT)
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    log_dir = os.path.join(base_dir, '..', 'logs')
    os.makedirs(log_dir, exist_ok=True)
    with open(os.path.join(log_dir, f"away_game_{game_idx}.log"), "w", encoding="utf-8") as f:
        f.write(logs.stdout)

    # クリーンアップ
    sh(['docker', 'rm', '-f', server_name])
    sh(['docker', 'rm', '-f', akochan_cname])

    # ログから最終スコアをパースします
    scores = {}
    # なぜこのようにするか：Akochanが複数人いる場合、プレイヤー名がすべて "Akochan" で重複し、
    # ログ最終行の 'game 1: OurAI:38900 Akochan:38200...' をパースすると辞書キーが上書きされて
    # 正しい順位・スコアが取れないため、end_gameパケットのscores配列と接続順プレイヤー名をマッピングします。
    # 1 は正規表現グループインデックスです。
    match = re.search(r'"type":"end_game","scores":\[([\d,\-]+)\]', logs.stdout)
    if match:
        score_list = [int(x) for x in match.group(1).split(',')]
        for seat, score in enumerate(score_list):
            name = rotated_players[seat][0]
            scores[name] = score
    else:
        # フォールバック
        match = re.search(r"game \d+: (.+)", logs.stdout)
        if match:
            parts = match.group(1).strip().split()
            for part in parts:
                name, score_str = part.rsplit(':', 1)
                scores[name] = int(score_str)
    
    return scores


def main():
    # 計算負荷軽減のため、固定で 2ゲーム（1シード、席0と席1のみ）実行します。
    total_games = 2
    max_workers = 2
    start_seed = 1

    print(f"=== MJAI Away Battle: Our AI (1) vs Akochan (3) (Duplicate Mode) ===")
    print(f"Total Games: {total_games}")
    print(f"Max Workers: {max_workers}")
    print(f"Start Seed:  {start_seed}")
    print(f"Base Port:   11700")
    print(f"====================================================================")

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
                print(f"[Away Game {game_idx + 1}/{total_games}] (Seed {seed_num}, Seat {seat_num}) Finished. Scores: {scores}")
            except Exception as exc:
                print(f"[Away Game {game_idx + 1}/{total_games}] Generated an exception: {exc}")

    # 統計集計 (OurAI vs Akochan 3名の平均)
    stats = {
        "OurAI": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []},
        "Akochan": {"scores": [], "ranks": [], "so_pts": [], "gyokujin_pts": [], "ouza_pts": []}
    }

    for scores in results:
        if not scores:
            continue
        sorted_players = sorted(scores.items(), key=lambda x: x[1], reverse=True)
        
        # 雀魂 順位点 (東風戦)
        uma_gyokujin = [70.0, 35.0, -5.0, -95.0]
        uma_ouza = [75.0, 35.0, -5.0, -165.0]

        for rank, (name, score) in enumerate(sorted_players, 1):
            so_pt = (score - 25000) / 1000.0
            gyokujin_pt = so_pt + uma_gyokujin[rank - 1]
            ouza_pt = so_pt + uma_ouza[rank - 1]

            if name == "OurAI":
                stats["OurAI"]["scores"].append(score)
                stats["OurAI"]["ranks"].append(rank)
                stats["OurAI"]["so_pts"].append(so_pt)
                stats["OurAI"]["gyokujin_pts"].append(gyokujin_pt)
                stats["OurAI"]["ouza_pts"].append(ouza_pt)
            else:
                # Akochan-0, Akochan-1, Akochan-2 は Akochan に合算
                stats["Akochan"]["scores"].append(score)
                stats["Akochan"]["ranks"].append(rank)
                stats["Akochan"]["so_pts"].append(so_pt)
                stats["Akochan"]["gyokujin_pts"].append(gyokujin_pt)
                stats["Akochan"]["ouza_pts"].append(ouza_pt)

    print("\n=== Final Away Statistics (Mahjong Soul Style) ===")
    for name, data in stats.items():
        if not data["scores"]:
            print(f"{name}: No data")
            continue
        avg_score = sum(data["scores"]) / len(data["scores"])
        avg_rank = sum(data["ranks"]) / len(data["ranks"])
        avg_so_pt = sum(data["so_pts"]) / len(data["so_pts"])
        avg_gyokujin_pt = sum(data["gyokujin_pts"]) / len(data["gyokujin_pts"])
        avg_ouza_pt = sum(data["ouza_pts"]) / len(data["ouza_pts"])
        
        rank_counts = [data["ranks"].count(r) for r in (1, 2, 3, 4)]
        print(f"{name}:")
        print(f"  Average Rank:     {avg_rank:.3f}")
        print(f"  Average Score:    {avg_score:.1f}")
        print(f"  Average 素点pt:   {avg_so_pt:+.3f} pt")
        print(f"  Average 玉の間pt: {avg_gyokujin_pt:+.3f} pt")
        print(f"  Average 王座の間pt: {avg_ouza_pt:+.3f} pt")
        print(f"  Rank Dist:        1st:{rank_counts[0]}, 2nd:{rank_counts[1]}, 3rd:{rank_counts[2]}, 4th:{rank_counts[3]}")


if __name__ == '__main__':
    main()
