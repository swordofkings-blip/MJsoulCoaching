# 押し引きロジックの2次元ファジィ関数化および9モード戦略モデルの実装計画

コーチングAIの意思決定を、従来の1次元押し引き度スレッショルド（攻撃・通常・守備の3モード）から、**手牌価値（自分軸）**と**場の脅威度（他家・場軸）**を独立して扱う**2次元ファジィ推論による9モード戦略選択モデル**へ拡張します。

作業を別のAIが自律して進められるよう、新規モジュール定義や既存コードの具体的な差し替え箇所を含めた詳細な実装手順を以下に規定します。

---

## 2次元ファジィマトリクス設計

### 1. 入力軸の定義
- **縦軸（自分軸）: 手牌価値（$y$ 軸）**
  - 自家の手牌進行度（シャンテン数）と見積もり打点（期待飜数）から計算される `base_attack` ($0.0 \sim 1.0$) を使用。
  - **LOW（ゴミ手）**: テンパイから遠く打点も低い状態（目安: `base_attack` < 0.25）
  - **MEDIUM（普通手）**: 1〜2シャンテンの中打点、またはドラがある状態（目安: 0.25 <= `base_attack` < 0.60）
  - **HIGH（勝負手）**: テンパイ、または好形の高打点イーシャンテン（目安: `base_attack` >= 0.60）

- **横軸（相手・場軸）: 場の脅威度（$x$ 軸）**
  - 他家のリーチ・副露状況や手出し情報から計算される `max_threat` ($0.0 \sim 1.0$) を使用。
  - **LOW（安全・平場）**: 主に他家に動きがない序盤や、全員が門前で静かな状況（目安: `max_threat` < 0.15）
  - **MEDIUM（警戒）**: 1〜2副露している他家がいる、または中盤〜終盤で門前の他家にテンパイ気配がある状況（目安: 0.15 <= `max_threat` < 0.60）
  - **HIGH（危険）**: 他家がリーチしている、または3副露以上やドラポン等の高打点仕掛けがある状況（目安: `max_threat` >= 0.60）

### 2. 9つの戦略モードの定義
手牌価値（縦軸）と場の脅威度（横軸）のファジィ論理積（$\min$）により、各モードの適合度を計算し、最も適合度の高いモードを最終戦略として選択します。同点の場合は**安全優先タイブレーク**を適用します。

| 手牌価値 \ 場の脅威度 | Low（安全・序盤） | Medium（警戒） | High（危険・終盤） |
| :--- | :--- | :--- | :--- |
| **High（勝負手）** | **① 全力攻撃** | **② 押し気味** | **③ 危険度勝負** |
| **Medium（普通手）** | **④ 積極駒組み** | **⑤ 様子見** | **⑥ 回し打ち** |
| **Low（ゴミ手）** | **⑦ スリム化** | **⑧ 撤退準備** | **⑨ 完全撤退** |

---

## 提案される変更点とソースコード詳細

### 1. 新規モジュール
#### [NEW] [fuzzy_logic.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/fuzzy_logic.py)
ファジィメンバーシップ関数と9モードの適合度判定、およびタイブレーク順序をカプセル化したクラスを定義します。

```python
# -*- coding: utf-8 -*-
"""
@title ファジィ推論エンジン
@description 手牌価値と他家脅威度から、9つの戦略モードへの適合度を計算し、最適なモードを選択する。
"""

class FuzzyLogicEngine:
    """
    @title ファジィ推論エンジンクラス
    @description 設定パラメータから各軸のメンバーシップ関数を構成し、9つの戦略モードを決定する。
    """
    def __init__(self, params: dict):
        """
        @title コンストラクタ
        @param {dict} params - 設定パラメータ（config_parameters.jsonの内容）
        """
        self.params = params

    def _membership_low(self, val: float, bound: float) -> float:
        """
        @title Low メンバーシップ関数
        @description 値が0のときに1.0、boundに近づくほど0.0へ線形に減少する。
        @param {float} val - 入力値 (0.0〜1.0)
        @param {float} bound - 減少境界のしきい値
        @returns {float} メンバーシップ適合度 (0.0〜1.0)
        """
        # しきい値が0以下の場合、値が0なら1.0、それ以外は0.0を返すことでゼロ除算を防ぐ
        if bound <= 0.0:
            return 1.0 if val <= 0.0 else 0.0
        return max(0.0, 1.0 - val / bound)

    def _membership_medium(self, val: float, peak: float, width: float) -> float:
        """
        @title Medium メンバーシップ関数
        @description peakで1.0となり、左右にwidth離れると0.0になる対称三角メンバーシップ関数。
        @param {float} val - 入力値 (0.0〜1.0)
        @param {float} peak - ピーク（中央）となるしきい値
        @param {float} width - 裾野の広さ（許容幅）
        @returns {float} メンバーシップ適合度 (0.0〜1.0)
        """
        # 幅が0以下の場合、ピークと一致すれば1.0、それ以外は0.0を返すことでゼロ除算を防ぐ
        if width <= 0.0:
            return 1.0 if val == peak else 0.0
        return max(0.0, 1.0 - abs(val - peak) / width)

    def _membership_high(self, val: float, bound: float) -> float:
        """
        @title High メンバーシップ関数
        @description boundより低いと0.0、boundから1.0に向かって線形に増加する。
        @param {float} val - 入力値 (0.0〜1.0)
        @param {float} bound - 増加開始 of しきい値
        @returns {float} メンバーシップ適合度 (0.0〜1.0)
        """
        # しきい値が1.0以上の場合、値が1.0以上なら1.0、それ以外は0.0を返すことでゼロ除算を防ぐ
        if bound >= 1.0:
            return 1.0 if val >= 1.0 else 0.0
        return max(0.0, (val - bound) / (1.0 - bound))

    def evaluate_strategy(self, base_attack: float, max_threat: float) -> tuple[str, dict]:
        """
        @title 戦略モードの推論評価
        @description 2軸の入力値から9モードの適合度（MIN）を算出し、安全優先タイブレークに基づいて最大適合度のモードを返す。
        @param {float} base_attack - 手牌価値 (0.0〜1.0)
        @param {float} max_threat - 場の脅威度 (0.0〜1.0)
        @returns {tuple[str, dict]} (決定された戦略モード文字列, 各モードの適合度辞書)
        """
        # 手牌価値軸 (y軸) のメンバーシップ用パラメータ
        y_low_bound = self.params.get('FUZZY_Y_LOW_BOUND', 0.25)   # 手牌価値が低いとみなす境界線（0.25）
        y_med_peak = self.params.get('FUZZY_Y_MED_PEAK', 0.50)     # 手牌価値の中央（0.50）
        y_med_width = self.params.get('FUZZY_Y_MED_WIDTH', 0.25)   # 手牌価値の中間領域の幅（0.25）
        y_high_bound = self.params.get('FUZZY_Y_HIGH_BOUND', 0.60) # 手牌価値が高いとみなす境界線（0.60）

        # 脅威度軸 (x軸) のメンバーシップ用パラメータ
        x_low_bound = self.params.get('FUZZY_X_LOW_BOUND', 0.15)   # 脅威度が安全とみなす境界線（0.15）
        x_med_peak = self.params.get('FUZZY_X_MED_PEAK', 0.40)     # 脅威度の警戒中央（0.40）
        x_med_width = self.params.get('FUZZY_X_MED_WIDTH', 0.25)   # 脅威度の警戒領域の幅（0.25）
        x_high_bound = self.params.get('FUZZY_X_HIGH_BOUND', 0.65) # 脅威度が危険とみなす境界線（0.65）

        # メンバーシップ値の計算
        y_low = self._membership_low(base_attack, y_low_bound)
        y_med = self._membership_medium(base_attack, y_med_peak, y_med_width)
        y_high = self._membership_high(base_attack, y_high_bound)

        x_low = self._membership_low(max_threat, x_low_bound)
        x_med = self._membership_medium(max_threat, x_med_peak, x_med_width)
        x_high = self._membership_high(max_threat, x_high_bound)

        # 9つのルールによる適合度算出 (MIN演算による積集合)
        scores = {
            "全力攻撃": min(y_high, x_low),
            "押し気味": min(y_high, x_med),
            "危険度勝負": min(y_high, x_high),
            "積極駒組み": min(y_med, x_low),
            "様子見": min(y_med, x_med),
            "回し打ち": min(y_med, x_high),
            "スリム化": min(y_low, x_low),
            "撤退準備": min(y_low, x_med),
            "完全撤退": min(y_low, x_high)
        }

        # 安全優先のタイブレーク順序定義
        # 同点（例: 0.5で様子見と回し打ちが並んだ）の場合、より安全側のモードを優先する
        priority_order = [
            "完全撤退",   # 最優先（最も安全）
            "撤退準備",
            "スリム化",
            "回し打ち",
            "様子見",
            "積極駒組み",
            "危険度勝負",
            "押し気味",
            "全力攻撃"    # 最低優先（最も危険）
        ]

        best_mode = "完全撤退"
        max_score = -1.0
        for mode in priority_order:
            score = scores[mode]
            if score > max_score:
                max_score = score
                best_mode = mode

        return best_mode, scores
```

---

### 2. Configの更新
#### [MODIFY] [config_parameters.json](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/config/config_parameters.json)
ファジィメンバーシップ関数のパラメータおよび、打牌評価ブレンドのパラメータを追加定義します。既存の閾値は GA チューニングの破壊を防ぐため変更しません。

```json
  "FUZZY_Y_LOW_BOUND": 0.25,
  "FUZZY_Y_MED_PEAK": 0.50,
  "FUZZY_Y_MED_WIDTH": 0.25,
  "FUZZY_Y_HIGH_BOUND": 0.60,
  "FUZZY_X_LOW_BOUND": 0.15,
  "FUZZY_X_MED_PEAK": 0.40,
  "FUZZY_X_MED_WIDTH": 0.25,
  "FUZZY_X_HIGH_BOUND": 0.65,
  "FUZZY_VAL_ALPHA": 0.70,
  "FUZZY_VAL_BETA": 0.85,
  "FUZZY_VAL_GAMMA": 0.40,
```

---

### 3. Strategy Manager の変更
#### [MODIFY] [strategy_manager.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/strategy_manager.py)
- **重複削除**: 重複定義されている `is_zenchi_mode(self) -> bool` (strategy_manager.py:838-842) を完全に削除。
- **初期化保持**: `StrategyManager.__init__` で `FuzzyLogicEngine` を1度だけインスタンス化して保持するように修正。
- `get_strategy_mode(self) -> str` のロジックを、ファジィ推論エンジン呼び出しに変更。
- `get_strategy_details(self) -> dict` にファジィ適合度情報を付与。

##### A. インポートと初期化部分（__init__ 周辺）
```python
# 変更後
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        
        # ファジィ推論エンジンの初期化保持（get_strategy_mode, get_strategy_detailsでの重複生成を回避）
        from fuzzy_logic import FuzzyLogicEngine
        self.fuzzy_engine = FuzzyLogicEngine(self.params)
```

##### B. 戦略モード決定および詳細データ取得部分
```python
# strategy_manager.py の L828-L836 差し替え
    def get_strategy_mode(self) -> str:
        """
        @title 戦略モード判定の取得
        @description 2次元ファジィ関数に基づき、9つのモードから現在のモードを推論する。
        @returns {str} 戦略モード文字列
        """
        if self.is_zenchi_mode():
            # ラス親などの緊急全ツッパ時は、ファジィをバイパスして攻撃に固定
            return "全力攻撃"
        
        base_attack = self.compute_base_attack()
        max_threat = self.compute_opponent_threat()
        
        mode, _ = self.fuzzy_engine.evaluate_strategy(base_attack, max_threat)
        return mode
```

`get_strategy_details` の変更：
```python
# strategy_manager.py の L843-L862 変更後
    def get_strategy_details(self) -> dict:
        a_base = self.compute_base_attack()
        t_max, threat_reason = self._max_threat_with_reason()
        push = self.compute_push_score()
        
        mode, scores = self.fuzzy_engine.evaluate_strategy(a_base, t_max)
        
        # UI連携およびデバッグ用にファジィ情報をパッケージ
        return {
            "base_attack": round(a_base, 3),
            "max_threat": round(t_max, 3),
            "push_score": round(push, 3),
            "mode": mode,
            "threat_reason": threat_reason,
            "is_last_round": self.state.is_last_round(),
            "my_rank": self.state.my_score_rank(),
            "yakuman_seal": not self.is_meld_open_allowed(),
            "yakuman_boost": round(self._yakuman_attack_boost(), 3),
            "fuzzy_scores": {k: round(v, 3) for k, v in scores.items()}
        }
```

---

### 4. Evaluator の変更
#### [MODIFY] [evaluator.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/core/evaluator.py)
- `evaluate_tile` 内のモード判定を 9つのモードへと分岐させ、既存の特殊手（チートイ・トイトイなど）の古い "防御" 判定を修正。
- **字牌評価減衰のガード**: 2127行目の `mode != "防御"` 判定箇所を `mode not in ("完全撤退", "撤退準備")` に書き換え。
- **オリ時の安全牌足切り**: `best_discard_with_score` (2383-2384行目) の `mode == "防御"` を `mode in ("完全撤退", "撤退準備")` に書き換え。
- **役満ボーナスへの減衰適用**: `AttackEvaluator._yakuman_bonus()` (1758行目付近) の中で、戦略モードに応じた `yakuman_scale` を適用してボーナスを抑制します。

##### A. evaluate_tile (L2086 - L2106 付近)
```python
# 変更後
        mode = self.strategy.get_strategy_mode()

        # パラメータ定義のロード
        # 各種ブレンドのしきい値
        alpha = self.params.get('FUZZY_VAL_ALPHA', 0.70) # 押し気味モード時の攻撃比率（0.70）
        beta = self.params.get('FUZZY_VAL_BETA', 0.85)   # 危険度勝負時の攻撃比率（0.85）
        gamma = self.params.get('FUZZY_VAL_GAMMA', 0.40) # 回し打ち時の攻撃比率（0.40）
        safe_threshold = self.params.get('SCORE_SUJI', 500)

        # 1. 基本的な戦略モードごとの v_attack / v_defense のブレンド
        if mode == "全力攻撃":
            v = float(v_attack)
            self.record_detail(tile, "戦略モード「全力攻撃」を適用")

        elif mode == "押し気味":
            v = float(alpha * v_attack + (1.0 - alpha) * v_defense)
            self.record_detail(tile, f"戦略モード「押し気味」(攻撃比率: {alpha:.2f})を適用")

        elif mode == "危険度勝負":
            v = float(beta * v_attack + (1.0 - beta) * v_defense)
            self.record_detail(tile, f"戦略モード「危険度勝負」(攻撃比率: {beta:.2f})を適用")

        elif mode == "積極駒組み":
            v = float(v_attack)
            self.record_detail(tile, "戦略モード「積極駒組み」を適用")

        elif mode == "様子見":
            v = float(push_score * v_attack + (1.0 - push_score) * v_defense)
            self.record_detail(tile, f"戦略モード「様子見」(Push={push_score:.2f})を適用")

        elif mode == "回し打ち":
            v = float(gamma * v_attack + (1.0 - gamma) * v_defense)
            self.record_detail(tile, f"戦略モード「回し打ち」(攻撃比率: {gamma:.2f})を適用")

        elif mode == "スリム化":
            # 誰も来てないが手が悪いため、安牌を少しキープ
            v = float(v_attack + v_defense * 0.2)
            self.record_detail(tile, "戦略モード「スリム化」を適用")

        elif mode == "撤退準備":
            # 危険になりつつあるゴミ手。ほぼオリ
            v = float(0.1 * v_attack + v_defense)
            self.record_detail(tile, "戦略モード「撤退準備」を適用")

        elif mode == "完全撤退":
            if v_defense >= safe_threshold:
                v = float(v_defense * 2 + v_attack * 0.01)
                self.record_detail(tile, "戦略モード「完全撤退」（安牌評価強化）を適用")
            else:
                v = float(v_defense + v_attack * 0.05)
                self.record_detail(tile, "戦略モード「完全撤退」（非安牌・危険回避）を適用")
                
        else:
            # フォールバック処理
            v = float(push_score * v_attack + (1.0 - push_score) * v_defense)
```

##### B. 字牌評価減衰のガードと安全牌足切り修正
```python
# evaluator.py: L2127 付近
# 変更前
        if is_honor(tile_to_id(tile)) and threat > 0.1 and mode != "防御":
# 変更後
        if is_honor(tile_to_id(tile)) and threat > 0.1 and mode not in ("完全撤退", "撤退準備"):
```

```python
# evaluator.py: L2383-L2384 付近 (best_discard_with_score)
# 変更前
        if mode == "防御":
            threshold = self.params.get('SCORE_SUJI', 500)
# 変更後
        if mode in ("完全撤退", "撤退準備"):
            threshold = self.params.get('SCORE_SUJI', 500)
```

##### C. 役満ボーナスの抑制（`AttackEvaluator._yakuman_bonus` 内で反映）
役満ボーナスの計算ロジック（`AttackEvaluator._yakuman_bonus`）の戻り値直前にて、戦略モードに応じた `yakuman_scale` を適用します。

```python
# evaluator.py: L1768 付近 (_yakuman_bonus内)
# 変更後
        if max_yakuman_bonus > 0:
            # 決定された戦略モードを取得し、安全重視のモードでは役満ボーナスを減衰させる
            mode = self.evaluator.strategy.get_strategy_mode()
            yakuman_scale = 1.0
            if mode == "完全撤退":
                yakuman_scale = 0.0
            elif mode in ("撤退準備", "回し打ち"):
                yakuman_scale = 0.5

            scaled_bonus = int(max_yakuman_bonus * yakuman_scale)
            if scaled_bonus > 0:
                total_bonus += scaled_bonus
                self.record_detail(tile, f"役満ボーナス[{best_yakuman_name}] (+{scaled_bonus})")
                
                # 統計情報の更新
                ai = getattr(getattr(self, 'evaluator', None), '_ai_player', None)
                if ai is not None:
                    ai.yakuman_bonus_count += 1
                    if min_shanten > yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2):
                        ai.gap_relaxation_count += 1

        return total_bonus
```

---

### 5. Server (forwarder.py) の変更
#### [MODIFY] [forwarder.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/server/forwarder.py)
- **古いモード判定の書き換え**: `_build_decision_reason()` (L805 付近) 内で、解説テキストを出力するために古いモード名 ("攻撃", "防御", "様子見") を使っていた判定を、9モードに適合するように修正します。

```python
# 変更前 (L805 - L814)
    if mode == "攻撃":
        lines.append("攻める手です。")
    elif mode == "防御":
        if defense >= 800:
            lines.append("防御モードですが安全牌があるので問題ありません。")
        else:
            lines.append("防御モードですが安全牌がなく、苦しい選択です。")
    else:
        lines.append("様子見です。")

# 変更後
    if mode in ("全力攻撃", "積極駒組み", "押し気味", "危険度勝負"):
        lines.append(f"戦略【{mode}】: 攻める手です。")
    elif mode in ("完全撤退", "撤退準備", "回し打ち"):
        if defense >= 800:
            lines.append(f"戦略【{mode}】: 防御的ですが安全牌があるので問題ありません。")
        else:
            lines.append(f"戦略【{mode}】: 防御的ですが安全牌がなく、苦しい選択です。")
    else: # 様子見、スリム化
        lines.append(f"戦略【{mode}】: 様子見またはスリム化の手です。")
```

---

### 6. UI (Simulator) の変更
#### [MODIFY] [simulator.html](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/server/templates/simulator.html)
テキストと数値だけだった戦略内訳パネルに、**3x3のファジィ戦略マップ（2次元グラフ）**を描画するUIを追加します。
縦軸に「手牌価値（base_attack）」、横軸に「場の脅威度（max_threat）」をとり、現在の状況がマトリクスのどこに位置しているかをドット（LEDインジケーター）でリアルタイムにプロット表示します。また、現在選択されている戦略セルをハイライト表示します。

##### A. スタイルの追加（`<style>` タグ内に追加）
```css
        /* 2次元ファジィ戦略マップのコンテナ */
        .bot-coach-strategy-map-container {
            position: relative;
            width: 100%;
            aspect-ratio: 1.6 / 1; /* 横長比率 */
            margin: 8px 0;
            background: rgba(0, 0, 0, 0.35);
            border: 1px solid rgba(255, 255, 255, 0.1);
            border-radius: 6px;
            overflow: hidden;
            display: flex;
            flex-direction: column;
        }
        /* 3x3の戦略グリッド */
        .bot-coach-strategy-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            grid-template-rows: repeat(3, 1fr);
            width: 100%;
            height: 100%;
        }
        /* 各セルの基本スタイル */
        .bot-coach-strategy-cell {
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 0.58rem;
            color: rgba(255, 255, 255, 0.3);
            border: 1px solid rgba(255, 255, 255, 0.02);
            text-align: center;
            padding: 2px;
            font-weight: bold;
            transition: all 0.3s ease;
        }
        /* 性格に応じたセルの背景色 */
        .cell-attack { background: rgba(239, 68, 68, 0.07); } /* 攻撃的（赤） */
        .cell-normal { background: rgba(245, 158, 11, 0.07); } /* 様子見・中間（黄） */
        .cell-defend { background: rgba(59, 130, 246, 0.07); } /* 守備的（青） */
        
        /* 現在選ばれているアクティブセルのハイライト */
        .cell-active-match {
            color: #fff !important;
            background: rgba(139, 92, 246, 0.45) !important;
            box-shadow: inset 0 0 8px rgba(139, 92, 246, 0.6);
            text-shadow: 0 0 4px #fff;
        }
        
        /* 2次元プロット用ドット（ネオン風） */
        .bot-coach-strategy-plot-dot {
            position: absolute;
            width: 10px;
            height: 10px;
            background: #a29bfe;
            border: 2px solid #fff;
            border-radius: 50%;
            box-shadow: 0 0 8px #a29bfe, 0 0 16px #a29bfe;
            transform: translate(-50%, -50%);
            transition: left 0.3s ease, top 0.3s ease;
            pointer-events: none;
            z-index: 5;
        }
```

##### B. HTML構造の変更（L1483 - L1488 付近）
```html
                        <div class="bot-coach-strategy" id="botCoachStrategy" style="display:none;">
                            <div class="bot-coach-strategy-title">戦略モードの内訳</div>
                            <div class="bot-coach-strategy-mode" id="botCoachStrategyMode">--</div>
                            
                            <!-- 2次元ファジィ戦略マップ（新規追加） -->
                            <div class="bot-coach-strategy-map-container">
                                <div class="bot-coach-strategy-grid">
                                    <!-- 1行目: 手牌 High (上から順) -->
                                    <div class="bot-coach-strategy-cell cell-attack" id="cell_全力攻撃">全力攻撃</div>
                                    <div class="bot-coach-strategy-cell cell-attack" id="cell_押し気味">押し気味</div>
                                    <div class="bot-coach-strategy-cell cell-normal" id="cell_危険度勝負">危険度勝負</div>
                                    <!-- 2行目: 手牌 Medium -->
                                    <div class="bot-coach-strategy-cell cell-attack" id="cell_積極駒組み">積極駒組み</div>
                                    <div class="bot-coach-strategy-cell cell-normal" id="cell_様子見">様子見</div>
                                    <div class="bot-coach-strategy-cell cell-defend" id="cell_回し打ち">回し打ち</div>
                                    <!-- 3行目: 手牌 Low -->
                                    <div class="bot-coach-strategy-cell cell-normal" id="cell_スリム化">スリム化</div>
                                    <div class="bot-coach-strategy-cell cell-defend" id="cell_撤退準備">撤退準備</div>
                                    <div class="bot-coach-strategy-cell cell-defend" id="cell_完全撤退">完全撤退</div>
                                </div>
                                <div class="bot-coach-strategy-plot-dot" id="botCoachStrategyPlotDot" style="left: 0%; top: 100%;"></div>
                            </div>

                            <div class="bot-coach-strategy-params" id="botCoachStrategyParams"></div>
                            <div class="bot-coach-strategy-threat" id="botCoachStrategyThreat">--</div>
                        </div>
```

##### C. JavaScript描画ロジックの修正（L2733 - L2753 の `renderStrategyDetails` を書き換え）
```javascript
        function renderStrategyDetails(details) {
            const box = document.getElementById('botCoachStrategy');
            const modeEl = document.getElementById('botCoachStrategyMode');
            const paramsEl = document.getElementById('botCoachStrategyParams');
            const threatEl = document.getElementById('botCoachStrategyThreat');
            const plotDot = document.getElementById('botCoachStrategyPlotDot');
            
            if (!details) {
                box.style.display = 'none';
                return;
            }
            box.style.display = 'flex';
            modeEl.innerText = details.mode || '--';

            // 1. 各パラメータの数値表示
            const params = [
                { label: '手牌価値', value: (details.base_attack || 0).toFixed(2) },
                { label: '場の脅威', value: (details.max_threat || 0).toFixed(2) },
                { label: '押し引き度', value: (details.push_score || 0).toFixed(2) }
            ];
            
            let paramsHtml = params.map(p =>
                `<div class="bot-coach-strategy-param"><span class="bot-coach-strategy-param-label">${p.label}</span><span class="bot-coach-strategy-param-value">${p.value}</span></div>`
            ).join('');

            // 適合度が0より大きいモードの内訳リスト
            if (details.fuzzy_scores) {
                const activeScores = Object.entries(details.fuzzy_scores)
                    .filter(([_, score]) => score > 0)
                    .sort((a, b) => b[1] - a[1]);
                if (activeScores.length > 0) {
                    paramsHtml += `<div style="grid-column: span 3; font-size: 0.78rem; border-top: 1px dashed rgba(255,255,255,0.15); padding-top: 6px; margin-top: 6px;">`;
                    paramsHtml += `<div style="font-weight: bold; margin-bottom: 4px; color: #a29bfe;">ファジィ適合度内訳:</div>`;
                    paramsHtml += activeScores.map(([m, s]) => 
                        `<div style="display:flex; justify-content:space-between; margin-bottom: 2px;">` +
                        `<span>${m}</span><span style="font-family: monospace;">${(s * 100).toFixed(0)}%</span>` +
                        `</div>`
                    ).join('');
                    paramsHtml += `</div>`;
                }
            }
            paramsEl.innerHTML = paramsHtml;
            threatEl.innerText = '⚠ 脅威度根拠: ' + (details.threat_reason || '--');

            // 2. 2次元ファジィ戦略マップ（3x3グリッド）上のプロットドット更新
            if (plotDot) {
                // x軸: 脅威度 (0.0=左端, 1.0=右端)
                // y軸: 手牌価値 (0.0=下端, 1.0=上端)。画面表示上は top が 100% - (y * 100)%
                const xPct = Math.max(0, Math.min(100, (details.max_threat || 0) * 100));
                const yPct = Math.max(0, Math.min(100, (1.0 - (details.base_attack || 0)) * 100));
                plotDot.style.left = `${xPct.toFixed(1)}%`;
                plotDot.style.top = `${yPct.toFixed(1)}%`;
            }

            // 3. 現在選択されたセルのハイライト表示
            const allModes = ["全力攻撃", "押し気味", "危険度勝負", "積極駒組み", "様子見", "回し打ち", "スリム化", "撤退準備", "完全撤退"];
            allModes.forEach(m => {
                const cellEl = document.getElementById(`cell_${m}`);
                if (cellEl) {
                    if (m === details.mode) {
                        cellEl.classList.add('cell-active-match');
                    } else {
                        cellEl.classList.remove('cell-active-match');
                    }
                }
            });
        }
```

---

## 検証計画

### 1. 自動単体テスト
`python tools/test_hand.py` を動作させ、9つの戦略モード名のいずれかが戦略モード詳細ログ（例: `"mode": "全力攻撃"`, `"mode": "完全撤退"` など）に正しく書き出されることを確認します。

### 2. 人間打牌との一致率測定
既存の `python tools/extract_mismatches.py` などの測定スクリプトを用い、3モード時代の閾値（攻撃・通常・守備）による一致率データと比較して、2次元ファジィ移行後の打牌一致率がどの程度変化、あるいは向上するかをトラッキングします。
- 一致率が極端に低下した場合は、各メンバーシップ関数の境界パラメータ（`FUZZY_Y_*` / `FUZZY_X_*`）を微調整し、以前の3モード時よりも柔軟な行動ができていることを確認します。
