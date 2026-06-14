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
ローカルPC上で、天鳳の個室（例: `1000`）へ接続するゲートウェイを起動します。
```bash
# ポート 11600 でMJAIクライアント（coach_I）の接続を待ち受け、天鳳の個室「1000」に接続する場合
./mjai-gateway -port 11600 -id [用意した天鳳ID] -room 1000
```
* ※ `-id` には「IDxxxxxx」の形式でIDを指定します。
* ※ ゲートウェイが天鳳サーバーとのWebSocket接続を確立し、MJAIポートの受信待機状態になります。
* ※ ルーム番号の形式: `数字_数字`（例: `0_0`=テスト対戦、`1000-7999_0`=個室）

### 手順 2: AI（coach_I）の接続起動
別のターミナルを開き、作成した `tenhou_battle.py` を実行します。
```bash
python tools/tenhou_battle.py --host 127.0.0.1 --port 11600 --room 0_0 --name coach_I
```
* ※ これにより `coach_I` がローカルのゲートウェイに接続し、天鳳の個室「0_0」にプレイヤーとしてログインします。

### 手順 3: 対局の開始
1. 天鳳のブラウザまたはクライアントから、同じ個室番号「0_0」に手動プレイヤーとして入場します。
2. AIと自分で対戦させる、または不足しているプレイヤー（最大4人）を同様のIDで追加し、4人揃った段階で個室内の対局を開始します。
