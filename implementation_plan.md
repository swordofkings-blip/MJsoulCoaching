# 自動プレイBot 性能向上 ＆ シミュレーター機能拡張 実装計画 (最新版)

本計画書は、自動プレイBotの「面子崩しバグ」「6ブロック整理」「他家進行度推定」を精緻化し、シミュレーターUIの機能拡張を行うための実装計画です。

すでに完了したバグ修正項目と、これから実装する新規機能項目を整理して記載しています。

---

## 1. 【作業済み】バグ修正項目 (シャンテン後退・チートイツ無理分岐の解消)

以下はすでに実装コードに反映されているため、再作業は不要です。

- **有効シャンテン数 `calculate_closed_effective` の導入**:
  - 対子が4組未満の場合はチートイツのシャンテン数を除外し、ヤオ九牌が9種未満の場合は国士無双を除外するよう修正済み。
- **シャンテン後退ペナルティの適用**:
  - 打牌後のシャンテン数が最小（最良）シャンテン数より大きくなる（後退する）場合に、ペナルティ `PENALTY_SHANTEN_BACKWARD` (デフォルト値: `1000`) を適用する処理が `attack_score_for_tile` に実装済み。

---

## 2. 【未作業】新規実装項目 (他のAIがこれから実装する項目)

### 2-1. [strategy_manager.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/strategy_manager.py) の修正
- **[NEW]** `ShantenCalculator._solve_blocks_mps(c: Tuple[int, ...])` の追加
  - 数牌スートを探索し、面子(3)、ターツ(2)、対子(2)に分割して得られる最大ブロック数を返す再帰関数を実装してください（`lru_cache` で高速化）。
- **[NEW]** `ShantenCalculator.calculate_blocks(hand_counts: List[int], open_meld_count: int = 0)` の追加
  - 萬子、筒子、索子の数牌ブロック数 ＋ 字牌の対子以上（2枚以上）の数 ＋ 副露数を合計し、手牌全体の最大ブロック数を算出するメソッドを追加してください。
- **[MODIFY]** `StrategyManager` のパラメータ注入対応と他家進行度推定の精緻化
  - `StrategyManager.__init__(self, state: GameState, params: dict = None)` に対応させてください。
  - 各他家 `i != my_seat` に対して、手出しツモ切り履歴（`river_moqie`）、副露（`melds`）、巡目（`tsumo_count`）から動的に `threat_i` とその理由を計算します。最悪の脅威とその内訳理由（例: `"Player 1: 2副露 (0.40) + 役牌ポン (+0.15) = 0.55"`) を `get_strategy_details` から返却するようにしてください。

### 2-2. [evaluator.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/evaluator.py) の修正
- **[MODIFY]** `AttackEvaluator.attack_score_for_tile` の修正
  - `shanten <= 3`（3向聴以下）のときに、打牌前ブロック数 ≧ 6 かつ打牌後ブロック数 ≧ 6（ブロック整理が行われない）であれば、攻撃スコアから `PENALTY_6BLOCK_MAINTAIN`（デフォルト: `80`点）を減算する処理を追加してください。
  - **Why: 3向聴以下の手が進んだ段階での6ブロック維持は、受入が狭まりテンパイ時に危険牌を切り出すリスクを高めます。ペナルティを課すことで、最も有効牌の減少が少ない（最も弱い）ターツを払い、5ブロックにスリム化する「ブロック整理」を自発的に行わせます。**
- **[MODIFY]** `Evaluator` の外部パラメータ注入対応の拡張
  - `params: dict = None` を受け取り、`PENALTY_SHANTEN_BACKWARD`, `PENALTY_6BLOCK_MAINTAIN`, `SCORE_GENBUTSU` 等を外部から上書き可能にしてください。

### 2-3. [game_state.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/game_state.py) の修正
- **[MODIFY]** `river_moqie` によるツモ切り（模切）情報の追跡
  - `river_moqie: List[List[bool]] = [[], [], [], []]` を初期化・保持するようにしてください。
  - `on_discard` 時に、受け取った `moqie` 引数を `river_moqie` に追加し、`GameState.summary` にも含めてください。

### 2-4. [forwarder.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/forwarder.py) の修正
- **[MODIFY]** `/api/evaluate` への `river_moqie` 情報復元の追加
  - シミュレーターUIから送信される `river_moqie` データを `_restore_game_state` 内でデコードし、`GameState.river_moqie` に復元する処理を追加してください。

### 2-5. [templates/simulator.html](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/templates/simulator.html) の修正
- **[MODIFY]** `buildCoachPayload` の拡張
  - `engine.discards` から `moqie` 情報を抽出し、`river_moqie` リストを組み立てて API 送信データに含めるようにしてください。
- **[MODIFY]** コーチングUIへの「脅威度の内訳理由」の表示
  - 「戦略モードの内訳」パネル（`#botCoachStrategy`）の下部に、サーバーから受信した `threat_details`（他家の進行度推定の根拠）を表示するテキスト欄（`#botCoachStrategyThreat`）を新設してください。
- **[MODIFY]** キーボードの左右キーによる手番タイムライン操作の追加
  - キーボードの `keydown` イベントを監視し、`ArrowLeft` で `step(-1)`、`ArrowRight` で `step(1)` を呼び出すイベントハンドラを追加してください（入力フォームフォーカス時は無視）。

---

## 検証計画

### 自動テスト
- ブロック数計算の単体テスト:
  - 5ブロック（面子崩しなし）、6ブロック（面子崩しあり）の手牌を渡し、ブロック数が正しく 5 や 6 と計算されるか検証します。
- 今回再現した手牌において、`2z`（南）切り時の打牌後ブロック数が 6、`4m`切り時の打牌後ブロック数が 5 となり、ペナルティロジックが正常に作動することをプログラム上でテストします。

### 手動検証
- 修正後に `forwarder.py` を再起動し、シミュレーターを開きます。
- 1. 本局面において、`7m` ではなく `4m`（もしくは `南` など）が緑色のパルス発光で推奨され、面子崩しが防止されることを確認します。
- 2. キーボードの左右矢印キーでタイムラインがスムーズに進退することを確認します。
- 3. 右側の「ロボットコーチング」に誰がどの理由で危険か（例: 後半手出し中張牌など）が詳細に表示されることを確認します。
