# 雀魂ラッパー (Mahjong Soul Wrapper)

雀魂 (Mahjong Soul) の牌譜をリアルタイムにキャプチャし、ブラウザで再生・AI 相談できるローカルツール。
麻雀 AI コア (押しオリ判断・牌選択) も同梱。

## 機能

### エンドユーザー向け
- **牌譜キャプチャ**: Tampermonkey + forwarder.exe で雀魂の対局を自動記録
- **ブラウザ再生**: 保存した牌譜を 1 打ずつ再生
- **AI 相談プロンプト**: 任意の手番で「何切る」相談用プロンプトをクリップボードにコピー
- **コーチング UI**: 直近の手番に対する AI 判断 (ベタオリ・押し・他) の解説表示

### 開発者向け
- **麻雀 AI コア**: 牌選択・押しオリ判断・役判定 (Akochan 互換 MJAI プロトコル対応)
- **天鳳ログ解析**: 78,504 件のベタオリ局面・鳴き判断の人間データセット同梱
- **Akochan バトル**: ローカルの Akochan と AI を対戦させて強さを測定
- **GA パラメータ調整**: 遺伝的アルゴリズムで AI パラメータを最適化

## クイックスタート (エンドユーザー)

1. `build/forwarder.exe` を実行
2. ブラウザで `http://localhost:8080/` を開く
3. 「🔧 Tampermonkey スクリプトを導入」ボタンをクリック
4. 雀魂で対局をプレイ
5. ブラウザで `http://localhost:8080/` を再訪 → 牌譜一覧から再生

詳細は [`docs/README.txt`](docs/README.txt) を参照。

## クイックスタート (開発者)

### 麻雀 AI をローカルで対戦させる

```bash
# Akochan Docker イメージを準備
docker pull akochan-docker-app

# Akochan vs 3 つの遺伝子 (4 シード × 4 局 = 16 試合)
python tools/mjai_battle_genes.py 4 1 1
```

### ベタオリ判断の精度テスト

```bash
python test_local_betari.py
```

### GA でパラメータを最適化

```bash
python tools/ga_akochan.py
```

## ディレクトリ構成

```
雀魂ラッパー/
├── README.md                    # 本ファイル
├── LICENSE                      # MIT License
├── .gitignore
│
├── docs/                        # ドキュメント
│   ├── README.txt               # エンドユーザー向け導入マニュアル
│   ├── mjai_gateway_setup.md    # 天鳳 MJAI 接続設定 (開発者向け)
│   └── img/                     # 画像
│
├── forwarder.exe                # 牌譜キャプチャサーバー (配布バイナリ)
│
├── majsoul_wrapper/             # 雀魂 WebSocket パケット解析 (MIT, 3rd party)
├── server/                      # 牌譜再生・AI 相談 Web UI
│   ├── templates/
│   └── logs/                    # 自動生成 (.gitignore)
│
├── core/                        # 麻雀 AI コア
│   ├── ai_player.py             # メイン AI エントリ
│   ├── evaluator.py             # 牌評価
│   ├── strategy_manager.py      # 戦略モード管理 (押しオリ)
│   ├── fuzzy_logic.py           # ファジィ推論
│   ├── game_state.py            # ゲーム状態
│   ├── opponent_model.py        # 相手モデル
│   ├── hand_value.py            # 手牌価値計算
│   ├── yakuman_evaluator.py     # 役満評価
│   └── manue/                   # 別実装の麻雀 AI
│
├── bots/                        # ボットエントリポイント
├── config/                      # AI パラメータ
│   └── config_parameters.json
├── gene_variants/               # チューニング済み遺伝子
│   ├── gene_0.json              # Akochan に強い (推奨)
│   ├── gene_1.json
│   ├── gene_2.json
│   └── gene_best.json
│
├── tools/                       # 補助ツール
│   ├── mjai_battle.py           # Akochan バトル (基本)
│   ├── mjai_battle_genes.py     # 遺伝子別 Akochan バトル
│   ├── mjai_battle_away.py      # Akochan バトル (Away モード)
│   ├── mjai_client.py           # MJAI クライアント
│   ├── mjai_protocol.py         # MJAI プロトコル
│   ├── tenhou_battle.py         # 天鳳バトル
│   ├── tenhou_xml_to_actions.py # 天鳳ログ → アクション変換
│   ├── tenhou_match_rate.py     # 天鳳牌譜一致率測定
│   ├── akochan_battle.py        # 旧 Akochan バトル
│   ├── battle_test.py           # バトルテスト
│   ├── evaluate_parameter_fitness.py  # パラメータ評価
│   ├── mahjong_simulator.py     # 麻雀シミュレーター
│   ├── monitor_game.py          # ゲームモニター
│   ├── package.py               # パッケージング
│   ├── run_test.py              # テストランナー
│   └── tune_loop.py             # パラメータ調整ループ
│
├── build/                       # ビルド成果物
├── dist/                        # 配布物
├── share/                       # サンプル牌譜
├── data/                        # サンプルデータ
└── logs/                        # 実行ログ (自動生成, .gitignore)
```

## AI の性能

- **Akochan とのバトル**: gene_0 で Akochan に **+36.5pt** (4 シード × 4 局 = 16 試合平均)
- **人間ベタオリ一致率**: 90.1% (78,504 局面テスト)

## 開発

### 依存関係

- Python 3.10+
- 詳細は `requirements.txt` (未同梱) を参照

### テスト

```bash
# ベタオリ精度テスト
python test_local_betari.py

# Akochan バトル
python tools/mjai_battle.py
```

## ライセンス

このプロジェクトは MIT License で公開されています。
詳細は [`LICENSE`](LICENSE) を参照。

### サードパーティ

- **`majsoul_wrapper/`**: Copyright (c) 2020 Yue Qin, MIT License
  - 雀魂 WebSocket パケット解析エンジン

## 謝辞

麻雀 AI の研究において、数多くの先駆者の研究成果を参考にしました。
特に以下のプロジェクトには多大な影響を受けています:
- [Akochan](https://github.com/Akagi201/akochan) - 牌譜解析 AI
- [mjai-gateway](https://github.com/tomohxx/mjai-gateway) - 天鳳 → MJAI 変換
- [Cryolite](https://github.com/smly/Cryolite) - 麻雀 AI ライブラリ
