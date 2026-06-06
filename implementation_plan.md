# 評価パラメータのJSON化 ＆ 自動チューニング（LDEA/GA）対応 実装計画

本計画書は、自動プレイBotの各種評価パラメータ（守備・攻撃・押し引き）を外部JSONファイルに分離し、APIやBotからの動的オーバーライドをサポートするとともに、遺伝的アルゴリズム（GA）やLLM駆動型進化的アルゴリズム（LDEA）の適応度評価（Fitness）の基盤となる「何切る一致率評価スクリプト」を導入するための実装計画です。

---

## 1. 完了済みの項目 (確認用)

以下は前段階で実装が完了しており、本作業の前提となるロジックです。

- **有効シャンテン数計算 (`calculate_closed_effective`)**: チートイツ（対子4組以上）や国士無双（ヤオ九牌9種以上）の条件制限付きでシャンテン数を計算。
- **6ブロック維持ペナルティ (`PENALTY_6BLOCK_MAINTAIN = 80`)**: 3向聴以下で6ブロック以上を維持する打牌にペナルティを科し、5ブロックへの整理を自発的に促す。
- **他家進行度推定の精緻化**: リーチ状態、副露数、後半の手出し中張牌などから他家ごとの脅威度を計算し、押し引き判断に反映。

---

## 2. 新規実装項目 (本タスクの対象)

### 2-1. [config_parameters.json](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/config_parameters.json) の新規作成 [NEW]
すべての評価アルゴリズムが共通して参照する各種重みや閾値をJSONファイルに外出しします。

```json
{
  "SCORE_GENBUTSU": 1000,
  "SCORE_SUJI": 500,
  "SCORE_HONOR": 300,
  "SCORE_MUSUJI": 0,
  "SCORE_ATAMAKAKE_BONUS": 200,
  "KEITEN_BONUS_15_17": 1500,
  "KEITEN_BONUS_18": 3000,
  "PENALTY_SHANTEN_BACKWARD": 1000,
  "PENALTY_6BLOCK_MAINTAIN": 80,
  "UKEIRE_MULTIPLIER": 10,
  "SHANTEN_MULTIPLIER": 100,
  "REACH_THREAT": 1.0,
  "OPEN_BASE_BY_COUNT_1": 0.15,
  "OPEN_BASE_BY_COUNT_2": 0.40,
  "OPEN_BASE_BY_COUNT_3": 0.75,
  "OPEN_BASE_BY_COUNT_4": 0.95,
  "YAKUHAI_DORA_MELD_BONUS": 0.15,
  "LATE_TEDASHI_MIDDLE_BONUS_OPEN": 0.10,
  "LATE_TEDASHI_MIDDLE_BONUS_CLOSED": 0.08,
  "LATE_THRESHOLD": 10,
  "CLOSED_TSUMO_10_14": 0.05,
  "CLOSED_TSUMO_15_PLUS": 0.15,
  "BASE_THREAT": 0.0,
  "BASE_ATTACK_TENPAI_HIGH": 1.0,
  "BASE_ATTACK_TENPAI_LOW": 0.7,
  "BASE_ATTACK_1SHANTEN": 0.4,
  "LAST_ROUND_RANK0_PUSH_LIMIT": 0.2,
  "LAST_ROUND_RANK3_PUSH_MIN": 0.85
}
```

### 2-2. [evaluator.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/evaluator.py) の修正 [MODIFY]
- **パラメータ読み込み＆フォールバック**:
  - `SCORE_GENBUTSU` などのグローバル定数をデフォルト値（フォールバック用）としつつ、`__init__(self, state, params)` で渡される `params`（辞書）から優先的にパラメータを取得します。
  - `AttackEvaluator.attack_score_for_tile` で、有効牌倍率やシャンテン改善の重みも `self.params.get('UKEIRE_MULTIPLIER', 10)` などから動的に取得します。

### 2-3. [strategy_manager.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/strategy_manager.py) の修正 [MODIFY]
- **クラス定数依存の解消**:
  - `StrategyManager` 内の `REACH_THREAT` などの固定定数や押し引き制限値を、`self.params.get(key, DEFAULT)` で動的に取得するように変更します。
  - 特に従属的な辞書構造である `OPEN_BASE_BY_COUNT` も、`OPEN_BASE_BY_COUNT_X` という個別のキーから読み込みマージするか、個別指定を可能にします。

### 2-4. [forwarder.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/forwarder.py) の修正 [MODIFY]
- **API パラメータ伝播**:
  - `_handle_evaluate` および `evaluate_state` において、リクエストペイロード内の `params`（存在する場合）を取り出し、`Evaluator` インスタンス生成時に渡すようにします。
  これにより、シミュレータUIや外部チューニングスクリプトからAPI経由で動的にパラメータを切り替えた評価が可能になります。

### 2-5. [my_bot.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/my_bot.py) の修正 [MODIFY]
- **デフォルトJSONロード**:
  - `MyBot` の `__init__` でカレントディレクトリの `config_parameters.json` を探索し、存在すればロードして `self.params` に保持します。
  - `Evaluator(self.state, params=self.params)` として評価器にパラメータを渡します。

### 2-6. [evaluate_parameter_fitness.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/evaluate_parameter_fitness.py) の新規作成 [NEW]
GA/LDEAチューニングにおける「適応度（Fitness）評価」のエンジンとなるスクリプトを新規に作成します。

- **機能仕様**:
  1. `data/record_*_trimmed.json` に保存されている軽量牌譜データを読み込みます。
  2. 牌譜内のプレイヤーの中で、評価したいプレイヤーの座順（例: 最も段位の高いプレイヤーなど）を指定、または自動選定します。
  3. 各局のアクション（配牌、ツモ、打牌、鳴きなど）を順次実行し、`GameState` をシミュレート・更新していきます。
  4. 対象プレイヤー의 打牌手番（自摸直後、打牌決定前）において、`Evaluator` を用いて現在のパラメータ設定に基づく推奨打牌（`best_discard`）を計算します。
  5. 実際の強者が選んだ打牌と、Botの推奨打牌が一致したかどうかを記録します。
  6. **何切る一致率（Fitness ＝ 一致した打牌数 ／ 総打牌数）** を出力します。
- **実行インターフェース**:
  - コマンドライン引数から `--params <JSON_PATH>` を指定して別々の設定を評価できるようにします。
  - `--override "PENALTY_6BLOCK_MAINTAIN=120,SCORE_GENBUTSU=900"` のように個別のパラメータをワンライナーで上書き評価できるようにします。
  - バッチ実行結果（一致率、対象の牌譜UUID、総打牌数、所要時間など）をJSONまたは標準出力として出力します。

---

## 3. 検証計画

### 3-1. 自動テスト
- **パラメータ読み込みテスト**:
  - `config_parameters.json` を編集して値を書き換えた際、`MyBot` や `Evaluator` が期待通りその値を使用していることを確認します。
  - 不足しているパラメータがある場合、例外を発生させずにコード内デフォルト値にフォールバックすることを確認します。

### 3-2. 一致率評価スクリプトの動作検証
- 既存の `record_260606-a3630c24-a385-4a6d-b4e0-f3b67c1fb128_trimmed.json` を指定して `evaluate_parameter_fitness.py` を実行し、正しく何切る一致率（Fitness）が算出されることを確認します。
- 一部のパラメータ（例: `PENALTY_SHANTEN_BACKWARD`）を極端に小さく（例: 0）変更した時に、一致率が低下するかどうかを検証し、パラメータと最適化指標が正しく連動していることを実証します。

### 3-3. API 動的オーバーライド検証
- `forwarder.py` を起動した状態で、外部から `params` を含めた `/api/evaluate` リクエストを送り、レスポンス内の評価値が変化することを確認します。
