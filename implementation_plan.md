# 四風子連打流れ回避（または狙い）と九種九牌判定の実装計画

自作AI「coach-I」に、1巡目の「四風子連打流れ回避・狙い」機能および「九種九牌判定（国士無双移行判断含む）」を搭載し、牌譜シミュレータ上で可視化するための実装計画です。

---

## 合意された仕様

### 1. 四風子連打流れ回避・狙い
- **発生条件**:
  - 1巡目（他家・自家ともに1回目の打牌前、かつ鳴きが一度も発生していない）。
  - 自分より前のプレイヤー全員が同じ風牌（東・南・西・北のいずれか）を捨てている（自分が4人目の打牌者である）。
  - 自分の手牌に対象の風牌がある。
- **手牌価値による挙動の分岐**:
  - `StrategyManager` による手牌価値 `base_attack` のファジィ分類結果を基準とします。
  - **流し（狙う）**: 手牌価値が「低（`y_low`最大 ＝ スリム化・撤退準備・完全撤退ライン）」の場合は、対象の風牌を捨てて流局を確定させます。
  - **回避（流さない）**: 手牌価値が「中（`y_med`最大 ＝ 積極駒組み・様子見・回し打ちライン）」または「高（`y_high`最大 ＝ 全力攻撃・押し気味・危険度勝負ライン）」の場合は、対象の風牌を避けて他の中張牌などを捨てます。

### 2. 九種九牌判定（国士無双移行）
- **発生条件**:
  - 配牌または第1ツモ時に、手牌に么九牌が9種以上あり、流局宣言（`ryukyoku`）アクションが可能な状態。
- **判断分岐**:
  - **ちょうど9種9牌**: 流局宣言（流す）します。
  - **10種10牌（么九牌が10枚で対子がない状態）**:
    - 自分がラス（現在4位）なら、流局宣言せず**国士無双**を狙います。
    - それ以外（1〜3位）なら、流局宣言（流す）します。
  - **10種11牌以上（11種以上、または10種で対子がある状態）**:
    - 順位に関わらず流局宣言せず**国士無双**を狙います。
- **国士無双狙い時の打牌制御**:
  - 国士無双に必要な么九牌の山残り（露出数が4枚未満）がある限り「国士無双モード」を継続します。
  - モード継続中は、么九牌の打牌に強いペナルティを与え、不要な非么九牌（中張牌）を優先して捨てるように `Evaluator` のスコアを補正します。
  - 必要牌のいずれかが4枚見えて成立不可になった場合、または他家からのリーチ等の高脅威度発生により押し引き判断でベタオリにシフトした場合は、モードを終了または上書きします。

### 3. シミュレータ UI
- 右側の「BOTコーチング」パネル内（立直・暗槓パネルの下）に、それぞれ対象の局面（発生条件合致時）のみ表示される以下のカードを新しく追加します。
  - **九種九牌判断カード**:
    - 推奨（流局 or 国士狙い）と、その判断理由（手牌の么九牌種・枚数と順位状況）を表示。
  - **四風子連打判断カード**:
    - 推奨（流局 or 回避）と、その判断理由（手牌価値のファジィ分類結果）を表示。

---

## 変更対象ファイルと具体的な実装仕様

### 1. [core/game_state.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/game_state.py)
- **`GameState` クラスの拡張**:
  - `is_first_turn_wind_limit_possible(self) -> Tuple[bool, Optional[str]]`
    - 1巡目であり、自分より前のプレイヤー全員が同じ風牌を捨てているかを判定する。条件を満たせば `(True, 風牌の種類)` を返す。
  - `my_score_rank(self) -> int`
    - （既存）現在の点数から自分の順位（0=1位〜3=4位）を返す。

### 2. [core/strategy_manager.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/strategy_manager.py)
- **`StrategyManager` クラスの拡張**:
  - `is_high_hand_value_first_turn(self) -> bool`
    - ファジィエンジンにより `y_low` が最大ではない（`y_med` または `y_high` が最大である）場合に `True` を返す。

### 3. [core/evaluator.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/evaluator.py)
- **`Evaluator` クラスの拡張**:
  - `best_discard_with_score(self, hand: List[str]) -> Tuple[Optional[str], float]`
    - 四風子連打成立可能な状況で、手牌価値が高い（`is_high_hand_value_first_turn()` が `True`）場合、対象の風牌を捨てる打牌の評価値を大幅に下げる（回避）。
    - 価値が低い場合は、逆に対象の風牌の評価値を大きく引き上げて優先して切らせる（流し）。
  - `evaluate_tile(self, tile: str) -> float`
    - 配牌時の国士無双狙い条件を満たしており、かつ国士無双が成立可能な場合、手牌にある么九牌（`YAOCHU_IDS`）を捨てる打牌に対して強いペナルティ（例: `-2000` 点）を課し、非么九牌（中張牌）を優先して捨てるようにする。

### 4. [core/ai_player.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/ai_player.py)
- **`AIPlayer` クラスの拡張**:
  - `should_kyushu_kyuhai(self, state: GameState) -> bool`
    - 前述の九種九牌判定ロジックに従い、流局宣言（`ryukyoku`）を行うべきかを判定して `True`/`False` を返す。

### 5. [tools/mjai_client.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/tools/mjai_client.py)
- **`OurMjaiClient._handle` メソッドの変更**:
  - `tsumo` 時、`possible_actions` に `ryukyoku` が含まれる場合、`self.ai.should_kyushu_kyuhai(self.state)` の結果に基づき `{"type": "ryukyoku"}` アクションを送信するか、無視して通常の打牌に進む。

### 6. [server/forwarder.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/server/forwarder.py)
- **`evaluate_state` 関数の拡張**:
  - 返却する辞書データに、九種九牌および四風子連打の判定結果を追加します。
  - レスポンス追加項目:
    ```json
    "kyushu_kyuhai": {
        "can_declare": true,
        "recommend_declare": false,
        "reason": "10種10牌ですが、現在ラスのため国士無双を狙うことを推奨します。"
    },
    "sufutsusenru": {
        "is_possible": true,
        "recommend_discard": false,
        "wind_tile": "1z",
        "reason": "手牌価値が高いため、四風子連打を回避しアガリを目指すことを推奨します（手牌評価: 積極駒組み）。"
    }
    ```

### 7. [server/templates/simulator.html](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/server/templates/simulator.html)
- **HTML の変更**:
  - `#botCoachKanPanel` の下あたりに、`#botCoachKyushuPanel` と `#botCoachSufutsuPanel` を新しく定義する。
- **JavaScript の変更**:
  - `renderBotCoachUI(data)` 関数内で、API から渡される `kyushu_kyuhai` および `sufutsusenru` データをチェックし、条件に合致すれば対応するパネルを表示 (`display: flex`) し、判断結果と理由を反映する。条件外なら非表示にする。

---

## Verification Plan

### Automated/Manual Test Cases
1. **四風子連打回避テスト**:
   - 1巡目に他家3人が「東」を切っており、自分に「東」があり、かつ手牌が良い場合（3向聴以下など）：
     - 四風子連打回避カードが表示され、「回避推奨」および理由（手牌価値高）が表示されること。
     - AIが「東」以外を推奨すること。
2. **四風子連打流しテスト**:
   - 同条件で手牌が悪い場合（5向聴など）：
     - 四風子連打カードが表示され、「流局推奨」および理由（手牌価値低）が表示されること。
     - AIが「東」の打牌を推奨すること。
3. **九種九牌流局テスト**:
   - 第1ツモ時に麼九牌が9種9牌のとき：
     - 九種九牌カードが表示され、「流局推奨」が表示されること。
4. **10種10牌ラス時（国士無双狙い）テスト**:
   - 第1ツモ時に麼九牌が10種10牌で自分がラスのとき：
     - 九種九牌カードが表示され、「国士無双推奨（流局しない）」および理由（ラスのため）が表示されること。
     - 麼九牌が温存され、中張牌が推奨打牌になること。
5. **10種10牌非ラス時（流局推奨）テスト**:
   - 同条件で自分が2位のとき：
     - 九種九牌カードが表示され、「流局推奨」が表示されること。
6. **10種11牌以上（国士無双狙い）テスト**:
   - 第1ツモ時に么九牌が10種11牌（対子あり）のとき：
     - 順位に関わらず「国士無双推奨」が表示され、么九牌が温存されること。
