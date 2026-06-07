# コーチングAI 拡張実装計画

本計画書は、現在の「何切る」評価エンジンに対し、コーチングAIとしての質を高めるための拡張項目、およびロジック変更の効果検証のための対戦テストシステムを定義する。

---

## 全体方針

現在の評価エンジンは「攻撃評価（有効牌枚数ベース）」と「防御評価（現物/スジ/字牌の3段階）」をPushScoreでブレンドする設計。これを以下の方向で拡張する：

1. **防御評価の多層化**: 壁・ノーチャンス・牌危険度の導入
2. **攻撃評価の精密化**: 打点推定・待ちの質評価
3. **期待値計算の導入**: 和了確率×打点 − 放銃確率×失点
4. **コーチング機能**: 悪手検出・理由説明・候補ランキング

---

## Phase 1: 防御評価の強化

### 1-1. 壁判定（カベ）の導入

**現状**: スジ判定のみ。4枚見えの数牌があっても、そのまたスジまで安全と判定できない。

**実装内容**:
- `DefenseEvaluator` に `_wall_tile_ids()` メソッドを追加
- 各数牌(0-26)について `visible[tile_id] >= 4` なら壁として記録
- 壁のある牌のスジ（suji_safe_tiles）も安全扱いに加点
- スコア: `SCORE_WALL = 800`（現物1000 > 壁スジ800 > スジ500）

**変更ファイル**: `evaluator.py`（`DefenseEvaluator`）、`config_parameters.json`

### 1-2. ノーチャンス / ワンチャンス判定

**現状**: 全く考慮していない。

**実装内容**:
- 各数牌について残り枚数に応じて安全度を段階評価
- 0枚（ノーチャンス）= 安全（スジに準ずる）
- 1枚（ワンチャンス）= やや安全（軽い加点）
- 定義: 全プレイヤーの河・副露・ドラ表示牌から可視枚数をカウント
- スコア: `SCORE_NO_CHANCE = 700`, `SCORE_ONE_CHANCE = 200`

**変更ファイル**: `evaluator.py`（`DefenseEvaluator`）、`config_parameters.json`

### 1-3. またぎスジ危険度

**現状**: 単純にスジ＝安全と判定。5m切りに対して4mや6mが危険なことを考慮していない。

**実装内容**:
- またぎスジの危険牌リストを計算する `_matagi_danger_ids()` を追加
- またぎスジに該当する牌に軽い危険度ペナルティ
- 例: 相手が 5m を切っている → 4m, 6m はまたぎスジで危険（+0.5m基準）
- 実装は3-6-9, 2-5-8, 1-4-7 のブロック関係から判定

**変更ファイル**: `evaluator.py`（`DefenseEvaluator`）、`config_parameters.json`

### 1-4. 複数リーチ時のリスク増幅

**現状**: 複数リーチ時も単一リーチと同じ評価値。

**実装内容**:
- リーチ人数に応じて`SCORE_MUSUJI`を負の値に（-200 × リーチ人数）
- 2人リーチで musuji = -400、3人リーチで musuji = -600
- 現物/スジの評価は維持

**変更ファイル**: `evaluator.py`（`defense_score_for_tile`）、`config_parameters.json`

### 1-5. 放銃失点推定

**現状**: 放銃時の失点を全く考慮していない。

**実装内容**:
- `DefenseEvaluator` に `_estimate_deal_in_loss(tile_id) -> int` を追加
- ロジック:
  - 他家の副露内容から打点を大まかに推定
  - リーチ者の打点 = 3900（最低）〜8000（ドラあり）
  - 副露者の打点 = 副露数+ドラ+役牌から推定
  - その牌の危険度（genbutsu/suji/no-chance/musuji）から放銃確率を0〜30%で推定
  - `期待失点 = 推定打点 × 放銃確率`
- 最終的な防御スコアに期待失点を減算反映

**変更ファイル**: `evaluator.py`（`DefenseEvaluator`）、`config_parameters.json`

---

## Phase 2: 攻撃評価の精密化

### 2-1. 打点推定の精度向上

**現状**: `_estimate_han()` がドラ数+リーチ+門前bounsのみの粗略な計算。

**実装内容**:
- `HandValueEstimator` クラスを新規作成
- 以下の役を手牌構成から判定:
  - タンヤオ（1・9・字牌がない）
  - ホンイツ（1色+字牌のみ）
  - チンイツ（1色のみ）
  - 一気通貫（同色1-9が揃っているか）
  - 三色同順（同数字3色が揃っているか）
  - チャンタ/純チャン（幺九牌を含む順子等）
  - トイトイ（刻子のみ）
  - 三暗刻
  - 七対子
- 現在の手牌 + 副露から確定役・発展可能性を推定
- 打点（符計算は簡略化し、ハネ満/満貫/跳満/倍満の閾値判定）

**変更ファイル**: 新規 `hand_value.py`、`evaluator.py`（`AttackEvaluator` から参照）

### 2-2. 待ちの質評価

**現状**: 全ての有効牌を均等に評価している。

**実装内容**:
- `AttackEvaluator.ukeire_for_discard()` に待ち質の評価を追加
- リャンメン待ち = 係数1.0（基準）
- カンチャン待ち = 係数0.5
- ペンチャン待ち = 係数0.4
- シャンポン待ち = 係数0.6
- 単騎待ち = 係数0.3
- 有効牌枚数に待ち質係数を乗算した「実効有効牌」に置き換えオプション

**変更ファイル**: `evaluator.py`（`AttackEvaluator`）、`config_parameters.json`

### 2-3. テンパイ時の和了確率推定

**現状**: 有効牌枚数をカウントするのみで、実際に和了できる確率を推定していない。

**実装内容**:
- `WinProbabilityEstimator` を追加
- 簡易的な残り牌からの確率計算:
  - `待ち枚数 / 残り山牌数 × 残り巡目数`
  - 他家の不要牌確率で補正（スジで待っていれば相手が切る確率UP）
  - リーチ後はツモ確率のみ考慮

**変更ファイル**: 新規 `probability.py`、`evaluator.py`

---

## Phase 3: 期待値評価フレームワーク

### 3-1. ExpectedValueEvaluator クラス

**現状**: `attack_score * push + defense_score * (1-push)` のブレンド式で、期待値ではない。

**実装内容**:
- 新クラス `ExpectedValueEvaluator` を `evaluator.py` に追加
- 各打牌候補の期待値を計算:
  ```
  EV = P_win × (estimated_han_score + 250(リーチボーナス) - 1000(供託))
     - P_deal_in × estimated_deal_in_loss
     + positional_value (順位点変動の期待値)
  ```
- 現状の `evaluate_tile()` をラップし、EV値も併記する形に
- 従来のattack/defense blended score は下位互換として維持（`--ev-mode` で切替）

**変更ファイル**: `evaluator.py`（`Evaluator` クラスの拡張）、`config_parameters.json`

### 3-2. 順位期待値の考慮

**現状**: オーラスのみ順位を考慮。

**実装内容**:
- 点棒状況から順位変動の期待値を計算
- トップとの差、ラスとの差から「攻める価値」を定量化
- 飛び（箱下）リスクの判定

**変更ファイル**: `evaluator.py`、`strategy_manager.py`

### 3-3. 南入判定（30000点アガリ止めルール対応 + 残り局数考慮）

**現状**: 雀魂には「30000点以上でゲーム終了（アガリ止め）」ルールがあるが、全く考慮していない。

**背景**:
- 雀魂 東風戦: 東4局終了時、トップが30000点未満 → **南入**（南1局〜南4局が追加）
- 雀魂 半荘戦: 南4局終了時、トップが30000点未満 → **西入**（西1局〜西4局が追加）
- 30000点はゲーム終了のトリガーであり、戦略に大きな影響を与える

**実装内容**:

**A. 30000点アガリ止め判定（南入 / 西入）**:

```python
def should_game_continue(state) -> bool:
    # 最低限の局数消化後、トップが30000点未満なら続行
    min_rounds = 4 if tonpu else 8  # 東風: 4局, 半荘: 8局
    current_round = state.chang * 4 + state.ju
    if current_round < min_rounds - 1:
        return True  # まだ最低限の局数に達していない
    # 東4局(tonpu) or 南4局(hanchan) → トップの点数で判定
    top_score = max(state.scores)
    return top_score < 30000
```

**B. 戦略への反映**:

| 順位 | 状況 | 戦略調整 |
|------|------|---------|
| 1位 かつ 29000+点 | あと1回和了でゲーム終了 | 防御寄りに傾けつつ、和了も狙う（逃げ切り） |
| 1位 かつ 27000-28999点 | 南入させず終わらせたい | 必要なら強気に加点を狙う |
| 1位 かつ <27000点 | 南入/西入は不可避 | 標準プレイ。むしろ南入後のリスク管理 |
| 2-4位 かつ トップが29000+点 | トップを止めたい | トップへの放銃を特に警戒（現物優先） |
| 2-4位 かつ トップが27000-28999点 | トップを30000未満に留めたい | トップへの危険牌は慎重に管理 |
| 2-4位 かつ残り局数僅か | まくってトップ交代も視野 | 必要打点を計算した攻め |

**C. 残り局数認識（南入/西入の可能性も含む）**:

- `remaining_rounds(including_extra)` : 最大残り局数を計算（南入/西入の可能性を加味）
  - 東風戦: 残り = (4-ju) + (南入可能性 × 4)
  - 半荘戦: 残り = (1-chang)×4 + (4-ju) + (西入可能性 × 4)
- 残り局数に応じた押し引きテーブル（上記Bと組み合わせて最終判断）

**D. パラメータ**:

```json
{
  "AGARI_YAME_THRESHOLD": 30000,
  "AGARI_YAME_LEADER_CLOSE_RANGE": 1000,
  "PUSH_MOD_LEADER_AGARI_YAME_CLOSE": 1.2,
  "PUSH_MOD_LEADER_AGARI_YAME_FAR": 0.8,
  "DEFENSE_BONUS_AGAINST_LEADER": 200
}
```

**変更ファイル**: `game_state.py`（`is_last_round` の拡張 or 新メソッド追加）、`strategy_manager.py`（`compute_push_score` に南入判断を統合）、`config_parameters.json`

---

## Phase 4: 鳴き判断

### 4-1. should_call_meld の実装

**現状**: 常に `False` を返すスタブ。

**実装内容**:
- チー・ポン・カーの各ケースで判断:
  1. 鳴いた後のシャンテン数が改善するか
  2. 鳴くことで打点が上がるか（役牌ポンなど）
  3. 巡目的に間に合うか（終盤すぎないか）
  4. 鳴くことで他家の脅威が高まらないか（カンドラ等）
  5. 自分の押し引き状態と整合するか
- 鳴きのメリット（手牌進行 + 打点向上）とデメリット（打点低下/他家警戒）をスコア化

**変更ファイル**: `evaluator.py`（`Evaluator.should_call_meld`）、`config_parameters.json`

---

## Phase 5: コーチングUI連携機能

### 5-1. 悪手検出・差分表示

**実装内容**:
- `best_discard_with_score()` の拡張：全候補の評価値リストを返す
- 実際の打牌とAI推奨手の評価値差を計算
- 差が大きい場合（例: 200点以上）を「悪手」としてフラグ

### 5-2. 候補手ランキング表示API

**実装内容**:
- `/api/evaluate` のレスポンスに以下を追加:
  ```json
  {
    "best_discard": "5m",
    "candidates": [
      {"tile": "5m", "score": 1250, "attack": 800, "defense": 1000, "reason": "..."},
      {"tile": "3p", "score": 980, "attack": 750, "defense": 500, "reason": "..."},
      ...
    ],
    "strategy": { "mode": "...", "push_score": 0.7, ... },
    "error": null
  }
  ```

### 5-3. 打牌理由の自然言語生成

**実装内容**:
- 各評価要素を `reason` 文字列に変換する関数群
- 例:
  - "5m: スジで安全(500)。有効牌8種24枚。テンパイ"
  - "1s: 現物で最も安全(1000)。ただし手牌が1シャンテンに後退"
  - "中: 壁無しのノーチャンス牌(700)。安全だが打点寄与なし"

**変更ファイル**: `evaluator.py`、`forwarder.py`（`_handle_evaluate`）、`templates/simulator.html`

---

## Phase 6: パラメータチューニング

### 6-1. config_parameters.json の拡張

新規パラメータ:

```json
{
  "SCORE_GENBUTSU": 1000,
  "SCORE_SUJI": 500,
  "SCORE_WALL_SUJI": 800,
  "SCORE_NO_CHANCE": 700,
  "SCORE_ONE_CHANCE": 200,
  "SCORE_HONOR": 300,
  "SCORE_MUSUJI_1_REACH": 0,
  "SCORE_MUSUJI_2_REACH": -400,
  "SCORE_MUSUJI_3_REACH": -600,
  "MATAGI_PENALTY": 100,
  "FURITEN_PENALTY": 300,
  "PENALTY_SHANTEN_BACKWARD": 1000,
  "PENALTY_6BLOCK_MAINTAIN": 80,
  "UKEIRE_MULTIPLIER": 10,
  "SHANTEN_MULTIPLIER": 100,
  "KEITEN_BONUS_15_17": 1500,
  "KEITEN_BONUS_18": 3000,
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
  "LAST_ROUND_RANK3_PUSH_MIN": 0.85,
  "WAIT_QUALITY_RYANMEN": 1.0,
  "WAIT_QUALITY_KANCHAN": 0.5,
  "WAIT_QUALITY_PENCHAN": 0.4,
  "WAIT_QUALITY_SHABO": 0.6,
  "WAIT_QUALITY_TANKI": 0.3
}
```

---

## 実装スケジュール（推奨）

| Phase | 項目 | 優先度 | 見込み工数 |
|-------|------|--------|-----------|
| 1-1 | 壁判定 | ★★★ 高 | 小（0.5日） |
| 1-2 | ノーチャンス/ワンチャンス | ★★★ 高 | 小（0.5日） |
| 1-3 | またぎスジ | ★★ 中 | 小（0.5日） |
| 1-4 | 複数リーチリスク | ★★★ 高 | 微（0.2日） |
| 1-5 | 放銃失点推定 | ★★★ 高 | 中（1日） |
| 2-1 | 打点推定 | ★★★ 高 | 大（2日） |
| 2-2 | 待ちの質評価 | ★★ 中 | 小（0.5日） |
| 2-3 | 和了確率推定 | ★★ 中 | 中（1日） |
| 3-1 | EV評価フレームワーク | ★★★ 高 | 中（1.5日） |
| 3-2 | 順位期待値 | ★★ 中 | 小（0.5日） |
| 4-1 | 鳴き判断 | ★★ 中 | 中（1日） |
| 5-1 | 悪手検出 | ★★ 中 | 小（0.5日） |
| 5-2 | 候補ランキングAPI | ★★ 中 | 小（0.5日） |
| 5-3 | 打牌理由生成 | ★ 低 | 中（1日） |
| 6-1 | パラメータ拡張 | ★★★ 高 | 微（0.2日） |

---

## 変更ファイル一覧

| ファイル | 変更内容 |
|----------|----------|
| `evaluator.py` | DefenseEvaluator 拡張（壁/ノーチャンス/またぎ/複数リーチ/放銃失点）、AttackEvaluator 拡張（待ち質）、ExpectedValueEvaluator 追加、should_call_meld 実装 |
| `strategy_manager.py` | 順位期待値の考慮、打点推定結果の利用 |
| `hand_value.py` | **新規**: 役判定・打点推定クラス |
| `probability.py` | **新規**: 和了確率/放銃確率推定 |
| `config_parameters.json` | 全新規パラメータを追加 |
| `forwarder.py` | /api/evaluate レスポンス拡張（candidates, reasons） |
| `my_bot.py` | 必要に応じて新クラス参照を追加 |

---

## Phase 7: 対戦テストシステム（デュプリケーター式バトル）

拡張ロジックの効果を検証するため、同一山牌を使ったデュプリケーター式の対戦テストを自動実行するシステムを構築する。

---

### 7-1. 麻雀ゲームエンジン `mahjong_simulator.py` [新規]

**役割**: 4人のAIプレイヤーによる対局をシミュレーションする軽量ゲームエンジン。

**仕様**:

**壁管理**:
- 136枚の全牌リストを保持。シード値指定でシャッフル可能（乱数再現性の確保）
- 山牌の先頭からツモる方式。王牌（14枚）は考慮し、残り牌＝`wall[14:]` の枚数で管理
- ドラ表示牌・裏ドラ・槓ドラの管理

**進行管理**:
- 配牌: 各プレイヤーに13枚ずつ配布 → 親（東家 = seat 0）が14枚目をツモ
- ツモ → 打牌（プレイヤーの意思決定）→ 他家に鳴き判定 → 次のプレイヤー
- リーチ後はツモ切り（非リーチ者は通常の意思決定）
- 打牌後の優先順位: ロン > ツモ > カン > ポン > チー > スルー
- 鳴きが競合した場合、ロン優先、同時ロンは供託処理

**和了判定**:
- シャンテン計算機（既存 `ShantenCalculator`）でテンパイ確認
- ツモ和了: 自摸時に`shanten == -1`
- ロン和了: 他家の捨て牌に対して`shanten == -1`

**点数計算**（簡易版）:
- 符計算は簡略化（30符固定 or 基本符計算）
- 役（翻数）計算は `_estimate_han()` をベースに後日拡張
- 子のロン: `符 × 2^(2+翻) × 4`（簡易）
- 親のロン: `符 × 2^(2+翻) × 6`（簡易）
- ツモ和了: 子/親の折半負担
- 満貫・跳満・倍満・三倍満・役満の閾値判定
- 連荘棒・供託リーチ棒の管理

**局・半荘管理**:
- 東風戦（4局）または半荘戦（8局）を選択可能
- 親の連荘（和了 or 聴牌流局）・流局（親流れ）の管理
- オーラス（`is_last_round`）の状態反映

**スコアリング**:
- 各局終了時のスコア（点棒）を累積
- 半荘/東風戦終了時の最終スコアを出力
- オカとウマの計算（25000点持ちの30000点返し）

**インターフェース**:
```python
class MahjongSimulator:
    def __init__(self, wall_seed: int, ai_players: List[AIPlayer], game_type: str = 'hanchan'):
        # game_type: 'tonpu' (東風戦) or 'hanchan' (半荘戦)
        # 推奨: 半荘の方が戦略性が高く、ロジック差が出やすい
        pass

    def run_game(self) -> GameResult:
        # 1ゲームを最後まで実行し、結果を返す
        pass

@dataclass
class GameResult:
    seed: int
    final_scores: List[int]        # 最終スコア (25000点単位)
    placement: List[int]           # 順位 (0=1位)
    game_log: List[Action]         # 全アクションのログ
```

**変更ファイル**: 新規 `mahjong_simulator.py`

---

### 7-2. AIプレイヤーアダプター `ai_player.py` [新規]

**役割**: `Evaluator` ベースの打牌ロジックを、シミュレーターが呼び出せる共通インターフェースにラップする。

**仕様**:
```python
class AIPlayer:
    def __init__(self, name: str, evaluator_class, params: dict):
        self.name = name
        self.evaluator_class = evaluator_class  # Evaluator またはそのサブクラス
        self.params = params

    def on_new_round(self, state: GameState):
        # 新しい局の開始
        pass

    def decide_discard(self, state: GameState) -> str:
        # 打牌を決定
        evaluator = self.evaluator_class(state, params=self.params)
        return evaluator.best_discard(list(state.my_hand))

    def decide_call(self, state: GameState, call_options: dict) -> Optional[CallAction]:
        # ロン or カン or ポン or チー or パス を決定
        evaluator = self.evaluator_class(state, params=self.params)
        # ... 判断ロジック
        pass

    def decide_riichi(self, state: GameState) -> bool:
        # リーチするかどうか
        evaluator = self.evaluator_class(state, params=self.params)
        return evaluator.should_riichi()

    def decide_kan(self, state: GameState) -> bool:
        evaluator = self.evaluator_class(state, params=self.params)
        return evaluator.should_kan()

    def decide_tsumo(self, state: GameState) -> bool:
        # ツモ和了するか（常にTrueで良いが、9面待ち等の戦略的スルーは後日対応）
        return True
```

**比較方式**:
- `LogicA` (= 現在の評価ロジック): `Evaluator` をそのまま使用
- `LogicB` (= Phase 1 適用後): Phase 1の拡張を反映した `EnhancedEvaluator`（またはパラメータ違いの `Evaluator`）を使用

**変更ファイル**: 新規 `ai_player.py`

---

### 7-3. デュプリケーター対戦テスト `battle_test.py` [新規]

**役割**: 同一山牌での対戦を自動実行し、ロジック間の性能差を雀魂ポイントベースで比較する。

**デュプリケーター方式の詳細**:

1つの山牌シードに対して以下の8ゲームを実行:

| グループ | ゲーム | 東(0) | 南(1) | 西(2) | 北(3) |
|----------|--------|-------|-------|-------|-------|
| **A** (ベースライン) | #1 | A | A | A | A |
| | #2 | A | A | A | A (席替え) |
| | #3 | A | A | A | A (席替え) |
| | #4 | A | A | A | A (席替え) |
| **B** (テスト) | #5 | **B** | A | A | A |
| | #6 | A | **B** | A | A |
| | #7 | A | A | **B** | A |
| | #8 | A | A | A | **B** |

- A = 現行ロジック、B = 拡張ロジック
- 席替えは順方向ローテーション（例: 東→南→西→北→東）
- 山牌は同一シードを使用（完全同一条件）
- ただしロン・ツモ・鳴きの選択で局面が分岐するため、ゲーム展開は異なる

**評価指標**:

雀魂の段位戦ポイント獲得ルールに基づいて評価:

| 部屋 | 1位 | 2位 | 3位 | 4位 |
|------|-----|-----|-----|-----|
| 金の間 東風 | +40 | +5 | -15 | -25 |
| 玉の間 東風 | +60 | +10 | -20 | -30 |
| 王座の間 東風 | +80 | +15 | -25 | -40 |

- 部屋は設定可能（デフォルト: 玉の間 / 四人東風戦）
- ゲーム終了時の最終スコア（点棒）も記録

**比較方法**:

- **方式A**: Bのpt獲得量 vs Aの平均pt獲得量（同一シード内の比較）
  - Bのpt合計（4ゲーム） vs Aのpt合計（同一シード4ゲーム）
- **方式B**: A席でBが獲得したpt vs 同一席でAが獲得したpt（正味差）
  - 席ごとに「Bがその席で取ったpt − A平均がその席で取ったpt」を集計
- 最終的に全シードの平均pt差・累積pt差を出力

**出力例**:
```
=== バトルテスト結果 ===
シード: 1〜1000 / ゲーム: 東風戦 / 部屋: 玉の間

ベースライン(A): 平均 +12.3pt/戦
拡張ロジック(B): 平均 +18.7pt/戦
pt差: +6.4pt/戦 (B優勢)

内訳:
  東家での差: +5.2pt
  南家での差: +6.8pt
  西家での差: +7.1pt
  北家での差: +6.5pt

累積pt差: 6.4pt × 4000戦 = +25,600pt
```

**コマンドラインインターフェース**:
```
python battle_test.py --seeds 1-1000 --game-type tonpu --room jade \
  --logic-a-params config_parameters.json \
  --logic-b-params config_parameters_phase1.json \
  --output result.json
```

**パラメータ一覧**:
| 引数 | 説明 | デフォルト |
|------|------|-----------|
| `--seeds` | 使用する山牌シード範囲 (例: 1-1000, またはカンマ区切り) | 1-100 |
| `--game-type` | 東風戦(tonpu) or 半荘戦(hanchan) | tonpu |
| `--room` | 部屋 (gold/jade/throne) | jade |
| `--logic-a-params` | LogicAの設定JSON | config_parameters.json |
| `--logic-b-params` | LogicBの設定JSON | (必須) |
| `--output` | 結果出力JSONパス | battle_result.json |
| `--verbose` | 各ゲームの詳細を表示 | False |
| `--parallel` | 並列実行ワーカー数 | 1 |

**変更ファイル**: 新規 `battle_test.py`

---

### 7-4. バトルテスト用設定JSON `battle_config.json` [新規]

```
{
  "game_type": "tonpu",
  "room": "jade",
  "seed_range": [1, 1000],
  "logic_a_label": "現行ロジック",
  "logic_b_label": "Phase1拡張",
  "logic_a_params": "config_parameters.json",
  "logic_b_params": "config_parameters_phase1.json",
  "pt_table": {
    "1st": 60,
    "2nd": 10,
    "3rd": -20,
    "4th": -30
  },
  "initial_score": 25000,
  "return_score": 30000,
  "uma": {
    "1st": 10,
    "2nd": 0,
    "3rd": -10,
    "4th": -20
  }
}
```

**変更ファイル**: 新規 `battle_config.json`

---

### 7-5. 点数計算モジュール `scoring.py` [新規]

**役割**: 和了時の翻数・符計算・得点計算を担当。

**実装内容**:
- `calculate_fu(hand, win_tile, is_tsumo, is_open)` : 符計算
  - 基本符: 20符（門前ロンは30符）
  - 面子構成による加符（刻子・槓子の種類とアタマの種類）
  - 待ちの種類（リャンメン20符、カンチャン/ペンチャン/単騎/シャボは2符加算）
  - ツモ和了: 2符加算
- `calculate_han(hand, melds, win_tile, doras, is_tsumo, is_open, reach_state)` : 翻数計算
  - Phase 2-1 の `HandValueEstimator` を利用
  - ドラ・赤ドラの加算
  - リーチ・一発・ツモ・タンヤオ等の基本役
- `calculate_score(han, fu, is_dealer, is_tsumo, honba)` : 得点計算
  - 子のロン: `fu × 4 × 2^(2+han)` 切り上げ
  - 親のロン: `fu × 6 × 2^(2+han)` 切り上げ
  - 満貫以上はテーブル参照（5翻 = 満貫、6-7 = 跳満、8-10 = 倍満、11-12 = 三倍満、13+ = 役満）

**変更ファイル**: 新規 `scoring.py`

---

### 7-6. パラメータ継承と拡張の仕組み

`config_parameters.json` に評価パラメータを一元化し、拡張ロジックもこれを継承する形とする。

- 現行ロジック: `config_parameters.json`
- Phase 1 拡張ロジック: `config_parameters_phase1.json`（既存パラメータを継承 + 新パラメータを追加）

`battle_test.py` 起動時に `--logic-a-params` / `--logic-b-params` で任意のJSONを指定可能。これにより:
- 異なる拡張Phase同士の対戦テスト
- GA/LDEAで調整したパラメータの評価
- パラメータ値のスイープテスト

が可能になる。

**変更ファイル**: `config_parameters.json`（前述Phase 6参照）、`config_parameters_phase1.json`（新規・Phase 1完了時に作成）

---

## 実装スケジュール（更新版）

| 優先順位 | Phase | 項目 | 工数 | 備考 |
|----------|-------|------|------|------|
| ★★★ 1 | **7-1** | 麻雀ゲームエンジン（半荘優先） | 大（3日） | 最もコア。半荘8局対応必須 |
| ★★★ 2 | **7-3** | 対戦テストフレームワーク | 中（1.5日） | エンジンと並行開発可能 |
| ★★★ 3 | **7-2** | AIプレイヤーアダプター | 小（0.5日） | 薄いラッパー、短期で完了 |
| ★★★ 4 | **7-5** | 点数計算モジュール | 中（1.5日） | エンジンと密結合 |
| ★★★ 5 | **1-1〜1-4** | 防御評価の強化（壁/ノーチャンス/またぎ/複数リーチ） | 小（1日） | バトルテストで検証したい第一弾 |
| ★★★ 6 | **3-3** | 局進行認識（南入・残り局数考慮） | 小（0.5日） | strategy_managerに追加 |
| ★★★ 7 | 6-1 | パラメータ拡張 | 微（0.2日） | 随時更新 |
| ★★ 8 | 7-4 | バトル設定JSON | 微（0.2日） | 随時作成 |
| ★★ 9 | 1-5 | 放銃失点推定 | 中（1日） | Phase1の仕上げ |
| ★★ 10 | 2-1〜2-3 | 攻撃評価の精密化 | 大（3日） | Phase 2 |
| ★★ 11 | 3-1〜3-2 | EV評価フレームワーク + 順位期待値 | 中（2日） | Phase 3 |
| ★ 12 | 4-1 | 鳴き判断 | 中（1日） | Phase 4 |
| ★ 13 | 5-1〜5-3 | コーチングUI | 中（1.5日） | Phase 5 |

---

## 変更ファイル一覧（最終版）

| ファイル | 変更内容 |
|----------|----------|
| `mahjong_simulator.py` | **新規**: 麻雀ゲームエンジン（壁管理・進行管理・和了判定・局管理） |
| `ai_player.py` | **新規**: AIプレイヤーアダプター（Evaluatorをラップ） |
| `battle_test.py` | **新規**: デュプリケーター対戦テスト実行・集計 |
| `battle_config.json` | **新規**: バトルテスト設定 |
| `scoring.py` | **新規**: 符・翻・得点計算 |
| `config_parameters.json` | Phase 1〜6 の全パラメータを追加 |
| `config_parameters_phase1.json` | **新規**: Phase 1 拡張用パラメータセット |
| `game_state.py` | 南入・西入判定メソッド追加。残り最大局数計算 |
| `evaluator.py` | Phase 1 防御評価拡張 + Phase 2/3 攻撃/EV拡張 |
| `strategy_manager.py` | 残り局数認識 + `remaining_rounds()`追加。押し引き判断に局進行を反映 |
| `hand_value.py` | **新規**: 役判定・打点推定（Phase 2-1） |
| `probability.py` | **新規**: 和了確率/放銃確率推定（Phase 2-2） |
| `forwarder.py` | 候補ランキングAPI拡張（Phase 5） |
| `my_bot.py` | 必要に応じて新クラス参照を追加 |
