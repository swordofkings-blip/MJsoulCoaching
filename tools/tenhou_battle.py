# -*- coding: utf-8 -*-
"""
@title 天鳳接続テストスクリプト (coach_I用)
@description mjai-gatewayを介して自作AI「coach_I」を天鳳の個室に接続し、対局させます。
"""
import argparse
import json
import os
import sys

# プロジェクトルートをインポートパスに追加
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from tools.mjai_client import OurMjaiClient

def main():
    parser = argparse.ArgumentParser(description="coach_I 天鳳個室接続スクリプト")
    parser.add_argument("--host", default="127.0.0.1", help="mjai-gatewayのホスト名")
    parser.add_argument("--port", type=int, default=11600, help="mjai-gatewayのポート番号")
    parser.add_argument("--room", default="1000_1", help="接続対象の天鳳個室番号(形式: room_game_type, 例: 1000_1)")
    parser.add_argument("--name", default="coach_I", help="プレイヤー名")
    parser.add_argument("--config", default="config/config_parameters.json", help="パラメータファイルのパス")
    args = parser.parse_args()

    # パラメータのロード
    if os.path.exists(args.config):
        with open(args.config, 'r', encoding='utf-8') as f:
            params = json.load(f)
    else:
        params = {}

    print(f"Connecting to mjai-gateway at {args.host}:{args.port} (room: {args.room}, name: {args.name})...")
    
    # tools/mjai_client.py の OurMjaiClient クラスを使用してTCP接続を行います。
    # 接続後、天鳳側からのパケットを受信するループを開始します。
    client = OurMjaiClient(
        host=args.host,
        port=args.port,
        room=args.room,
        name=args.name,
        params=params
    )
    
    try:
        client.play_game()
    except KeyboardInterrupt:
        print("Interrupted by user. Closing connection...")
    finally:
        client.close()
        print("Connection closed.")

if __name__ == "__main__":
    main()
