# 天鳳個室接続（coach_I）環境構築の計画（引き継ぎ用）

天鳳の「個室（ロビー）」に自作AI「coach_I」を参加させ、他プレイヤーに迷惑をかけない安全な環境で自動対局検証を行えるようにするための環境構築手順を定義します。

後継のAIエージェントがすぐに実装を開始できるように、具体的なソースコード設計と起動手順をすべて本ドキュメントに記載します。

---

## 開発方針：個室限定でのテスト運用（アプローチB）

天鳳のAI専用IDの一般新規受付が停止しているため、運営の利用規約や一般プレイヤーのゲーム体験に影響を与えないよう、以下の制約の元で運用します。

1. **一般の段位戦（対人戦）には一切参加させない**。
2. 完全に「個室（例: 任意の個室番号 `9999` など）」を立ち上げ、そこに対してのみ自動接続を行う。
3. デバッグ終了後は直ちにプロセスを切断し、長時間の稼働によるサーバー負荷を防ぐ。

---

## 提案される変更点と具体的な実装設計

後継エージェントは、以下の2ファイルを新規作成し、動作を検証してください。

### 1. 新規接続スクリプトの作成
#### [NEW] [tenhou_battle.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/tools/tenhou_battle.py)
既存の [mjai_client.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/tools/mjai_client.py) 内に定義されている `OurMjaiClient` を読み込み、ローカルで起動された `mjai-gateway` を介して天鳳に接続するためのPythonスクリプトです。

以下のコードをそのまま新規ファイルとして作成してください。

```python
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
    parser.add_argument("--room", default="9999", help="接続対象の天鳳個室番号(例: 0000-9999)")
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
```

---

### 2. ゲートウェイ導入手順書の作成
#### [NEW] [mjai_gateway_setup.md](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/docs/mjai_gateway_setup.md)
ゲートウェイの入手先、ビルド方法、起動オプションなどを記述したドキュメントです。

以下の内容を新規ファイルとして作成してください。

```markdown
# mjai-gateway 導入および天鳳個室接続マニュアル

自作AI「coach_I」（MJAIプロトコル）を天鳳のWebSocketプロトコルに中継するため、**`mjai-gateway`** を使用します。

## 1. mjai-gateway の入手とビルド
1. 開発用PCに Go言語（golang）がインストールされていることを確認します。
2. GitHubからリポジトリを取得してビルドするか、またはビルド済みバイナリを取得します。
   * **GitHub リポジトリ**: [tomohxx/mjai-gateway](https://github.com/tomohxx/mjai-gateway)
   ```bash
   # リポジトリのクローンとビルド例
   git clone https://github.com/tomohxx/mjai-gateway.git
   cd mjai-gateway
   go build -o mjai-gateway main.go
   ```

## 2. 天鳳アカウント（テスト用ID）の準備
* テスト用に天鳳の通常アカウント（一般のID）を新規作成、または既存のテスト用ID（例: `ID000000` 形式）を用意します。
* テスト中に万が一BAN等の対象にならないよう、普段使用しているメインのアカウントIDは使用しないでください。

## 3. 接続テストの実行手順

### 手順 1: mjai-gateway の起動
ローカルPC上で、天鳳の個室（例: `9999`）へ接続するゲートウェイを起動します。
```bash
# ポート 11600 でMJAIクライアント（coach_I）の接続を待ち受け、天鳳の個室「9999」に接続する場合
./mjai-gateway -port 11600 -id [用意した天鳳ID] -room 9999
```
* ※ `-id` には「IDxxxxxx」の形式でIDを指定します。
* ※ ゲートウェイが天鳳サーバーとのWebSocket接続を確立し、MJAIポートの受信待機状態になります。

### 手順 2: AI（coach_I）の接続起動
別のターミナルを開き、作成した `tenhou_battle.py` を実行します。
```bash
python tools/tenhou_battle.py --host 127.0.0.1 --port 11600 --room 9999 --name coach_I
```
* ※ これにより `coach_I` がローカルのゲートウェイに接続し、天鳳の個室「9999」にプレイヤーとしてログインします。

### 手順 3: 対局の開始
1. 天鳳のブラウザまたはクライアントから、同じ個室番号「9999」に手動プレイヤーとして入場します。
2. AIと自分で対戦させる、または不足しているプレイヤー（最大4人）を同様のIDで追加し、4人揃った段階で個室内の対局を開始します。
```

---

## 後継AIエージェントへの引き継ぎ指示（TODOリスト）

1. [ ] 上記の設計に基づき、[tenhou_battle.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/tools/tenhou_battle.py) を新規作成する。
2. [ ] 上記のドキュメントに基づき、[mjai_gateway_setup.md](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/docs/mjai_gateway_setup.md) を新規作成する。
3. [ ] ユーザーに Go 環境の有無や、テスト用に用意できる天鳳ID（または新規作成手順）を確認し、`mjai-gateway` のビルド/起動を案内する。
4. [ ] 実際に `mjai-gateway` を起動した状態で `tenhou_battle.py` を稼働させ、エラーなく接続できること、および個室対局が開始した際に `OurMjaiClient` が正常にゲームパケットを解釈し、最初の打牌を行えることを検証する。
