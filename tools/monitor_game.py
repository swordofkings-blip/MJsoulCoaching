# -*- coding: utf-8 -*-
"""Real-time MJAI game monitor from docker logs."""
import sys
import subprocess
import json
import re

# 字牌の表示名マップ (麻雀の標準表記)
HONOR_NAMES = {
    "1z": "東", "2z": "南", "3z": "西", "4z": "北",
    "5z": "白", "6z": "發", "7z": "中"
}

def format_tile(tile: str) -> str:
    """JSONの牌名表記を日本語の馴染み深い表記に変換します"""
    if not tile:
        return ""
    # 字牌の変換 (例: "1z" -> "東")
    if tile in HONOR_NAMES:
        return HONOR_NAMES[tile]
    # 赤ドラの変換 (例: "5mr" -> "赤5m")
    if tile.endswith("r"):
        return f"赤{tile[:-1]}"
    return tile


def parse_and_monitor(container_name: str):
    """
    @title MJAIログのリアルタイム実況モニター
    @description 指定されたDockerコンテナの出力ログを監視し、麻雀の局進行と点数を実況テキストにして出力します。
    @param {str} container_name - 対象のDockerコンテナ名
    """
    print(f"=== Monitoring {container_name} ===")
    print("対局の実況を開始します。点数状況やアガリが発生すると表示されます。\n")

    # docker logs -f をパイプラインで読み込みます
    cmd = ["docker", "logs", "-f", container_name]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8")

    player_names = ["Player 0", "Player 1", "Player 2", "Player 3"]
    current_bakaze = "東"
    current_kyoku = 1
    current_honba = 0

    last_event = None

    try:
        for line in iter(proc.stdout.readline, ''):
            line = line.strip()
            if not line:
                continue

            # JSON行のみを抽出して解析します
            json_str = None
            if line.startswith('{') and line.endswith('}'):
                json_str = line
            else:
                # ログの余計な接頭辞 (server -> player など) がある場合のフォールバック抽出
                match = re.search(r'(\{.*\})', line)
                if match:
                    json_str = match.group(1)

            if not json_str:
                continue

            try:
                data = json.loads(json_str)
            except ValueError:
                continue

            msg_type = data.get("type")
            if not msg_type:
                continue

            # 重複判定（全プレイヤーへのパケット送信による同じ出来事の連続出力を防ぎます）
            event_key = None
            if msg_type == "start_game":
                event_key = ("start_game", tuple(data.get("names", [])))
            elif msg_type == "start_kyoku":
                event_key = ("start_kyoku", data.get("bakaze"), data.get("kyoku"), data.get("honba"))
            elif msg_type == "reach":
                event_key = ("reach", data.get("actor"))
            elif msg_type in ("pon", "chi", "ankan", "kakan", "daiminkan"):
                event_key = (msg_type, data.get("actor"), data.get("pai"))
            elif msg_type == "hora":
                event_key = ("hora", data.get("actor"), data.get("target"), data.get("hora_points"), tuple(data.get("scores", [])))
            elif msg_type == "ryukyoku":
                event_key = ("ryukyoku", data.get("reason"), tuple(data.get("scores", [])))

            if event_key is not None:
                if event_key == last_event:
                    continue
                last_event = event_key

            # 1. ゲーム開始 (プレイヤー名の確定)
            if msg_type == "start_game":
                names = data.get("names", [])
                if names:
                    player_names = names
                print(f"【対局開始】")
                for seat, name in enumerate(player_names):
                    wind = ["東家", "南家", "西家", "北家"][seat]
                    print(f"  {wind}: {name}")
                print("-" * 50)

            # 2. 局開始
            elif msg_type == "start_kyoku":
                bakaze = format_tile(data.get("bakaze", "E"))
                kyoku = data.get("kyoku", 1)
                honba = data.get("honba", 0)
                kyotaku = data.get("kyotaku", 0)
                dora_marker = format_tile(data.get("dora_marker", ""))
                
                current_bakaze = bakaze
                current_kyoku = kyoku
                current_honba = honba

                print(f"\n★ {bakaze}{kyoku}局 {honba}本場 (供託立直棒: {kyotaku}本) ★")
                if dora_marker:
                    print(f"  ドラ表示牌: [{dora_marker}]")
                print("-" * 35)

            # 3. 鳴き (ポン・チー・カン)
            elif msg_type == "pon":
                actor = data.get("actor", 0)
                pai = format_tile(data.get("pai", ""))
                print(f"  └ {player_names[actor]}: ポン! [{pai}]")

            elif msg_type == "chi":
                actor = data.get("actor", 0)
                pai = format_tile(data.get("pai", ""))
                print(f"  └ {player_names[actor]}: チー! [{pai}]")

            elif msg_type in ("ankan", "kakan", "daiminkan"):
                actor = data.get("actor", 0)
                print(f"  └ {player_names[actor]}: カン!")

            # 4. リーチ
            elif msg_type == "reach":
                actor = data.get("actor", 0)
                print(f"  [!] {player_names[actor]} が立直(リーチ)を発声！")

            # 5. アガリ (和了)
            elif msg_type == "hora":
                actor = data.get("actor", 0)
                target = data.get("target", 0)
                pai = format_tile(data.get("pai", ""))
                points = data.get("hora_points", 0)
                deltas = data.get("deltas", [0, 0, 0, 0])
                scores = data.get("scores", [25000, 25000, 25000, 25000])

                if actor == target:
                    print(f"\n🎉 【ツモアガリ】 {player_names[actor]} ── [{pai}] ({points}点)")
                else:
                    print(f"\n⚡ 【ロンアガリ】 {player_names[actor]} ── 放銃: {player_names[target]} [{pai}] ({points}点)")

                # スコア変動の表示
                print("  [点数移動]:")
                for seat, name in enumerate(player_names):
                    d = deltas[seat]
                    d_str = f"+{d}" if d > 0 else str(d)
                    print(f"    {name:10}: {scores[seat] - d:5} -> {scores[seat]:5} ({d_str})")
                print("-" * 50)

            # 6. 流局
            elif msg_type == "ryukyoku":
                reason = data.get("reason", "huangpai")
                deltas = data.get("deltas", [0, 0, 0, 0])
                scores = data.get("scores", [25000, 25000, 25000, 25000])

                reason_str = "荒牌平局 (通常の流局)" if reason == "huangpai" else f"途中流局 ({reason})"
                print(f"\n💨 【流局】 {reason_str}")

                # テンパイ者の割り出し (点数が増えた、あるいは減っていないがテンパイのケースを大まかに判定)
                tenpai_players = []
                for seat, d in enumerate(deltas):
                    if d > 0:
                        tenpai_players.append(player_names[seat])
                
                if tenpai_players:
                    print(f"  テンパイ: {', '.join(tenpai_players)}")
                else:
                    print("  全員ノーテン")

                # スコア変動の表示
                print("  [点数移動]:")
                for seat, name in enumerate(player_names):
                    d = deltas[seat]
                    d_str = f"+{d}" if d > 0 else str(d)
                    print(f"    {name:10}: {scores[seat] - d:5} -> {scores[seat]:5} ({d_str})")
                print("-" * 50)

            # 7. ゲーム終了
            elif msg_type == "end_game":
                print("\n==================== 【対局終了】 ====================")
                proc.terminate()
                break

    except KeyboardInterrupt:
        print("\nモニタリングを中断しました。")
        proc.terminate()
    finally:
        proc.wait()


if __name__ == "__main__":
    c_name = "mjai-srv-away-0"
    if len(sys.argv) > 1:
        c_name = sys.argv[1]
    parse_and_monitor(c_name)
