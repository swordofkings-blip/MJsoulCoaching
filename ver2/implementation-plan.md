# 雀魂コーチングくん ver.2 実装計画

## 🎯 ゴール
ver.1 の「重み付きスコア加減算方式」を完全廃止し、**タプルによる辞書式比較（lexicographic ordering）** で打牌を評価する麻雀AIに置き換える。

### 副次ゴール
- パラメータ爆発の解消（重み係数 w1, w2, ... の調整作業から解放）
- コーチング機能の強化（タプル比較結果から「なぜその牌を切ったか」を自動生成）
- Akochan 相手に -8.9pt → さらに強い AI へ

---

## 📐 アーキテクチャ概観

```
ver.1 (現状)                        ver.2 (新)
─────────────────────              ─────────────────────
evaluator.py (5100行)               evaluator_v2.py (~400行)
├─ score = Σ(weight × value)        ├─ eval_tuple = (cond1, cond2, ...)
├─ 重み調整に人手が必要                ├─ タプルの順序 = 戦略の性格
├─ 不連続な境界                       ├─ 連続的な遷移（タプルの各層が独立）
└─ ブラックボックス的判断                └─ どの層で勝ったか = 判断理由
```

### ファイル構成案

```
core/
  evaluator_v2.py       # メイン評価器 (タプル比較)
  strategy_v2.py        # モード判定 (threat_count ベース)
  defense_v2.py         # 防御評価 (電将パターン重み)
  shanten_v2.py         # シャンテン計算 (ver.1 から移植)
  garbage_rank_v2.py    # 牌のゴミ度順位 (オタ風→端→役牌→中張)
  
config/
  strategies_v2.json    # モード別タプル順序・閾値
  
tools/
  mjai_client_v2.py     # 新 Evaluator を使うクライアント
  analyze_v2.py         # ver.2 専用スタッツ解析
  
ver2/                    # 実験スクリプト・ベンチマーク
```

---

## 🎲 タプル設計

### 基本形
```python
eval_tuple = (
    shanten_after,              # ① 向聴数 (小さい程良い)
    -effective_ukeire_count,    # ② 受け入れ枚数 (多い程良いので符号反転)
    garbage_rank,               # ③ 牌のゴミ度順位 (小さい程良い)
    -safety_score,              # ④ 安全度 (高い程良いので符号反転)
    -dora_count,                # ⑤ ドラ枚数 (多い程良いので符号反転)
    -yaku_progress_score,       # ⑥ 役進行度
    -red_five_in_hand,          # ⑦ 赤5保持
)
```

### モード別オーバーライド
| モード | 発動条件 | タプル順序 |
|--------|----------|-----------|
| `URGENT_ATTACK` | 終盤4位 + 残り少 | ①向聴 ②受入 ③ドラ ④ゴミ ⑤安全 ⑥役 |
| `ATTACK` | 攻撃力高 & 脅威低 | ①向聴 ②受入 ③役 ④ゴミ ⑤ドラ ⑥安全 |
| `BALANCED` | 通常 | ①向聴 ②受入 ③ゴミ ④役 ⑤ドラ ⑥安全 |
| `DEFEND` | 脅威中 | ①向聴 ②安全 ③受入 ④ゴミ ⑤役 ⑥ドラ |
| `FOLD` | 脅威高 & 手遠い | ①安全 ②ゴミ ③向聴 ④受入 ⑤役 ⑥ドラ |

### 牌のゴミ度順位 (`garbage_rank_v2.py`)
```python
GARBAGE_RANK = {
    # 0 が最も切られやすい、3 が最も残したい
    'otakaze_1': 0,          # 客風 (北など)
    'otakaze_pair': 0,        # 客風対子
    'isolated_19': 1,         # 孤立端牌
    'yakuhai_single': 2,      # 役牌 (自風・場風・三元) 1枚
    'tanki_jikaze': 2,        # 単騎自風
    'tanki_sangen': 2,        # 単騎三元
    'isolated_28': 2,         # 孤立28
    'middle_block': 3,        # 中張牌の搭子
    'ryanmen_kanchan': 3,     # 両面・カンチャン
    'pair': 3,                # 雀頭候補
}
```

---

## 🛡️ 防御評価 (defense_v2.py)

### 平沢麻雀パターン重みを返す単純関数
```python
def safety_score(tile: str, state) -> int:
    """
    @title 平沢麻雀パターン理論による安全度スコア
    @returns 0-1000 (高い程安全)
    """
    if is_genbutsu(tile): return 1000
    
    # 平沢パターン重み (ver.1 から移植、純化)
    weights = hirazawa_tile_weights(state)
    total = sum(weights)
    if total == 0: return 1000
    
    danger = weights[tile_to_id(tile)] / total
    return int(1000 * (1.0 - danger))
```

ver.1 の `_tile_remaining_weights` を `hirazawa_tile_weights` として整理して移植。ヒューリスティック (またぎスジ等) はタプルに含めず、基本の平沢重みだけで判定。ver.1 の `defense_score_for_tile` も流用可。

---

## 🎯 モード判定 (strategy_v2.py)

### Fuzzy 廃止、純粋カウント
```python
def get_mode(state) -> str:
    n_reach = count_opponent_reach(state)
    my_shanten = calculate_shanten(state)
    my_rank = my_score_rank(state)
    is_last = is_last_round(state)
    is_tenpai = (my_shanten <= 0)
    
    # 4位で終盤 → 全力
    if is_last and my_rank == 3:
        return 'URGENT_ATTACK'
    
    # 役満進行中
    if has_yakuman_progress(state):
        return 'YAKUMAN'
    
    # 七対子モード (条件: 4対子以上 + 両面ターツ2個以下 など)
    if chiitoitsu_mode_applicable(state):
        return 'CHIITOITSU'
    
    # 脅威と進行度で決定
    if n_reach >= 2 and not is_tenpai:
        return 'FOLD'
    if n_reach >= 1 and not is_tenpai:
        return 'DEFEND'
    if my_shanten <= 1:
        return 'ATTACK'
    return 'BALANCED'
```

Fuzzy のメンバーシップ関数とX/Y軸を完全廃止。「カウント」と「if-else」だけ。

---

## 🎓 コーチング機能

### タプル比較から説明文を自動生成
```python
def explain_discard(eval_before, eval_after, tile_discarded) -> str:
    """
    @title 打牌の理由をタプル比較結果から生成
    """
    tier_names = ['シャンテン数', '受け入れ枚数', '牌のゴミ度', '安全度', 'ドラ枚数', '役進行度']
    
    for i, (before, after) in enumerate(zip(eval_before, eval_after)):
        if before != after:
            if i == 0:
                if after < before:
                    return f"①{shanten_desc}シャンテン数が{before}→{after}に減るので切る"
                else:
                    return f"①{shanten_desc}シャンテン数を進めたいため切る (待ちは {tile_discarded})"
            if i == 1:
                return f"①②は同点。有効牌枚数が{before}→{after}枚に増える"
            # ...
    return "全要素同点 (タイ)"
```

### 牌譜解析時のコーチング表示
- 各局面でタプルの各層を表示
- どの層で判断が分かれたかを可視化
- 生徒が「なぜその牌を切ったのか」を完全に理解できる

---

## 📊 移行戦略

### 段階的移行
1. **Phase 1**: `evaluator_v2.py` を実装、ver.1 と比較テスト
2. **Phase 2**: 強さが同等以上なら切り替え
3. **Phase 3**: 強さが劣る場合、デバッグ (タプル比較結果を見てボトルネック特定)
4. **Phase 4**: チューニング完了後、ver.1 のコードを `ver1_legacy/` に移動

### 並行運用
- `tools/mjai_battle_v1.py` (既存) と `tools/mjai_battle_v2.py` (新規) を用意
- 同じ seed で 100 局対戦させて勝率比較

---

## 🧪 テスト計画

### 単体テスト
- `tests/test_evaluator_v2.py`: 各種局面で期待される打牌が返るか
- `tests/test_tuple_order.py`: タプル順序を変更して結果が変わるか
- `tests/test_mode_switch.py`: モード判定の境界条件

### 統合テスト
- `tests/test_akochan_battle.py`: 100 局対 Akochan
- `tests/test_throne_stats.py`: 玉座の間スタッツ準拠の KPI 確認

### 人間の期待値テスト
- 簡単な局面で「人間が切る牌」と「ver.2 が切る牌」を比較
- 10 局くらいのサンプルで定性評価

---

## ⚠️ リスクと対策

| リスク | 影響 | 対策 |
|--------|------|------|
| 受け入れ枚数の過小評価 | 和了率低下 | 牌の種類の幅を評価 (`unique_ukeire`) を②と③の間に追加 |
| 端牌切りすぎ | 三色・一通が消える | 端牌でも色が確定してれば残すロジック |
| 安全度の不足 | 放銃率上昇 | 防御モードでは④を①の上位に移動 |
| 赤5の価値軽視 | 期待打点低下 | ⑦に追加（最下位）だが一定の重み |
| 役満見逃し | トップ獲り損ね | 役満進行検出時は別タプルで評価（special mode） |

---

## 📝 議論ポイント (議論結果)

### 1. タプルの層数
- **目標 6 層、増減 OK**
- 理由: 人間は6階層くらいまでなら読みやすい。それ以上だと結局ブラックボックス化する

### 2. ゴミ度順位と七対子モード
- **9 マトリクス + 七対子モード + 役満モード** の3系統を用意
- 各モードで GARBAGE_RANK を別関数で定義
  - `garbage_rank_standard(state, tile) -> int`
  - `garbage_rank_chiitoitsu(state, tile) -> int`
  - `garbage_rank_yakuman(state, tile) -> int`
- **七対子モード発動条件**:
  - 対子4個以上 ＋ 両面ターツ2個以下
  - 5シャンテン以下で七対子側がシャンテン数的に有利
  - 中盤(5-6巡)以降、4対子＋リャンメンターツ少
  - 生牌字牌・端牌が多く残っている
- **三色**: 3-4% 成立率の難役。GARBAGE_RANK で「色が確定してたら残す」程度の軽い優先度で十分。無理に鳴いて組みに行かない

### 3. 受け入れ枚数の尺度
- **枚数 > 種類** (枚数が主、種類はタイブレーカー)
- ただし 0 枚の種類はカウントしない (死に牌は無視)
- タプルでは: `(-ukeire_count, -unique_ukeire_count)` のように階層化

### 4. 役満進行の特別扱い
- **別タプルに切替** (ver.2 設計通り)
- 役満モード発動: 国士無双・四暗刻・大四喜・小四喜・大三元・字一色・清老頭・九蓮宝燈・四槓子
- 各役満で特殊タプル (例: 国士無双は「么九牌を絶対残す」タプル)

### 5. コーチングの粒度
- **各打牌で必ず説明** を採用
- スキップ・要約は UI 側で実装
- 理由は「タプルの何層目で勝ったか」を日本語で生成

### 6. ver.1 資産
- **平沢麻雀パターン理論 (※ 電将パターンと混同しない)** を採用
- 1シャンテンDFS は高速なので v2 でも呼び出し関数として残す
- ver.1 コードは `ver1_legacy/` ディレクトリに完全移動 (削除しない)
- コア計算 (シャンテン・受け入れ計算) は v2 で再実装 or 移植

### 7. テストケース
- **天鳳ログ1万局から局面ピックアップ** (人間プロの実戦譜)
- テストカテゴリ:
  1. 東1局 配牌 (基本動作)
  2. 染め手進行中 (特殊分岐)
  3. 4位オーラス (緊急モード)
  4. 1シャンテン (DFSとの複合)
  5. 役満進行 (役満モード切替)
  6. 七対子移行 (4対子局面)
- 各テストケースで「人間プロの平均打牌」と「ver.2 の打牌」を比較

---

## 🚀 スケジュール感

| Week | マイルストーン |
|------|---------------|
| Week 1 | 設計 + 単体テスト |
| Week 2 | 統合テスト + 人間比較 |
| Week 3 | Akochan バトル + 調整 |
| Week 4 | コーチング機能 + ドキュメント |

---

## 💬 フリーディスカッション欄

### 第1ラウンド議論 (2026-06-28)

**user の意見**:
1. ✅ 6 層目標、増減 OK
2. ✅ 七対子モード + 役満モードを別系統で。GARBAGE_RANK を mode ごとに関数化。三色は軽く意識 (3-4%)
3. ✅ 枚数 > 種類、種類多いほど良い (0枚はカウントしない)
4. ✅ 役満は別タプル切替
5. ✅ 全打牌で説明生成
6. ✅ 平沢麻雀パターン理論を採用 (電将パターンとは別物)。1シャンテンDFSも残す
7. ✅ 天鳳ログ1万局から局面ピックアップ

**次ラウンド議論したいこと**:
- 七対子モード発動条件の細部 (中盤5-6巡とは具体的に？巡目と対子数の優先度)
- 役満モードの一覧 (どの役満で別タプルにする？優先度順)
- 三色の "色が確定したら残す" ロジックの詳細
- 「点数が同点の場合の比較順位」の取り扱い
- 赤5・ドラの優先順位 (タプルのどこに置く？)
- 1人用モード (デバッグ用) を最初に作るか

### メモ
- ver.1 の `defense_score_for_tile` は採用する。`_tile_remaining_weights` を `hirazawa_tile_weights` に改名
- ver.1 の `_run_1shanten_dfs` は残す。タプルの代わりに使う「1向聴専用オーバーライド」
- 旧コードは `ver1_legacy/` に完全移動 (git で参照可能に)
- 天鳳ログ取得方法: `wget https://tenhou.net/0/log/...` で mjson 形式取得可能 (要調査)

</content>
</invoke>
### 第2ラウンド議論 (2026-06-28)

**user の追加回答**:

A. **七対子モード**:
- 巡目 4-7 で GA 調整可能、デフォルト 6
- 「4対子+リャンメン少」検出
- 2 つの発動条件は **並列 (OR)**

B. **役満モード**:
- 全部別タプルで考えると複合役満が大変
- 検討必要 → **次ラウンドで継続**

C. **三色の「色確定」判定**:
- 例1: 萬子123, 筒子123, 索子258 + 孤立字牌 → 2,8は三色考慮で残す
- 例2: 萬子123, 筒子12, 索子258 → 2 は三色同順の一部 → 残す
- **同順位時の tiebreaker として三色考慮** で実装
- 詳細要検討

D. **ドラ vs 受け入れ**:
- 状況により優先度入れ替わる
- 3翻以上確定の手役があればドラ < 受け入れ
- **要検討** (タプルにどう入れるか)

E. **1人モードから着手** (確認)

F. **天鳳ツール既にある**:
- 	enhou_xml_to_actions.py - XML→actions JSON 変換
- 	enhou_process_dict.py - 牌譜処理
- 	enhou_match_rate.py - 一致率測定
- 	enhou_battle.py - バトル
- evaluate_parameter_fitness.py - 評価ツール
- これらを ver.2 でも活用

### 設計案 (C. 三色 tiebreaker の実装イメージ)

\\\python
def garbage_rank_standard(state, tile) -> int:
    base_rank = _base_garbage_rank(tile)  # 通常のゴミ度
    
    # 三色同順: 色が確定してたら同順位の牌を温存側に倒す
    if is_sanshoku_forming(state, tile):
        return base_rank + 1
    return base_rank
\\\

つまり「同 rank なら三色牌が残る」効果が自然に得られる。Garbage_rank の値の範囲を 0-9 に拡張して、
- 0 = 真っ先に切る
- 9 = 絶対残す
の連続値にすることで、同値判定が tiebreaker として機能する。

### 設計案 (B. 複合役満の扱い - 案1)

**複数役満候補の OR 評価**:
\\\python
def evaluate_yakuman(state, tile) -> Tuple:
    candidates = []
    for yakuman_type in detect_yakumans(state):
        # 各役満の special tuple を生成
        candidates.append(yakuman_tuple(yakuman_type, state, tile))
    # 最良の tuple を返す
    return min(candidates)
\\\

これで:
- 複合役満 (大四喜+字一色など) は両方の役満の tuple を計算 → 緩い方を採用
- シンプルな役満は 1 つの tuple のみ
- 役満候補なし → 通常モードにフォールバック

**案2 (シンプル)**: 役満は全部同一タプル (?九牌絶対残し、字牌絶対残し等)。複雑な判定は捨てる。

→ 次ラウンド議論テーマ


### 第3ラウンド議論 (2026-06-28)

**確定事項**:
- ? B: 役満は案B (共通タプル) + **国士無双だけは特殊タプル**
- ? D: ドラ層はモード別配置 (URGENT=②, ATTACK=④ など)

### 未確定事項の洗い出し

#### 1. シャンテン計算の扱い
- ver.1 の ShantenCalculator (lru_cache + スレッドローカル) をそのまま使う？
- 速度十分か (ver.1 で動いている実績あり)
- **結論: そのまま移植 (ver.1 同等実装)**

#### 2. 国士無双の特殊タプル
- ?九牌 (1,9,字) を絶対残す
- 単騎候補 (1,9,字) は 2 枚持ちを優先
- 牌のゴミ度: 0 (絶対残す) = 9 に
- **タプル案**:
\\\
KOKUSHI_TUPLE = (
    shanten_after,           # ①
    -ukeire_count,           # ②
    -yaochu_count,           # ③ 幺九牌保持数 (多いほど良い)
    -pair_yaochu_count,      # ④ 幺九対子数 (単騎候補)
    garbage_rank,            # ⑤ 通常ゴミ度
)
\\\

#### 3. 七対子モードの特殊タプル
- 対子を温存、孤立牌を切る
- 牌のゴミ度: 対子 < 1枚孤立
- **タプル案**:
\\\
CHIITOITSU_TUPLE = (
    shanten_after,           # ①
    -ukeire_count,           # ②
    -pair_count,             # ③ 対子数 (多いほど良い)
    -pair_quality,           # ④ 役牌・ドラ対子の重み
    garbage_rank,            # ⑤ 通常の孤立牌ゴミ度
)
\\\

#### 4. 1人モード (デバッグ用) の必要性
- **最小限**: 1シャンテン以降の手効率だけ
- 防御評価なし、役満なし
- 純粋にシャンテン縮小を評価
- デバッグ時に「タプルの各層が正しい順序で動いてるか」確認

#### 5. 異常状態のハンドリング
- 手牌枚数不正 (14枚でない) → ver.1 と同じく False 返す
- 赤5関連 (0m, 0p, 0s) → 通常牌として扱う
- カン時のフリテン → 別途対応

#### 6. ver.1 機能のうち「捨てない」もの
- _run_1shanten_dfs (1向聴時の期待値オーバーライド)
- _tile_remaining_weights (平沢パターンとして移植)
- defense_score_for_tile (防御評価の本体)
- _estimate_riichi_han_actual (立直判断の翻数計算)

#### 7. 捨てない機能
- fuzzy_logic (Fuzzy 推論) → 完全廃止
- _hand_value_bonus (加減算の嵐) → 完全廃止
- MeldSealTracker (例外判定) → ver.2 では条件分岐で吸収
- YakumanEvaluator (役満評価) → ver.2 では tuple 化

#### 8. テストの粒度
- ユニットテスト: シャンテン計算、受入計算、ゴミ度順位、モード判定
- 統合テスト: 1人麻雀 (東風) 完走
- 人間比較: 天鳳ログ 100 局で打牌一致率 60% 以上
- 性能: 1局 5 秒以内

#### 9. 人間比較テスト (ver.2 評価基準)
- 5 段階評価:
  - ★5: 一致率 80%+ かつ打点が同等
  - ★4: 一致率 70%+ かつ打点が同等
  - ★3: 一致率 60%+
  - ★2: 一致率 50%+
  - ★1: 一致率 50% 未満

#### 10. 1局に何回モード切替が起こるか
- 通常: 1-2 回 (序盤の七対子判定、中盤の攻守判定)
- 異常: 5-10 回 (Fuzzy 廃止で減るはず)
- **重要**: モード切替のたびにタプルの優先度が変わる → 棋譜に記録

#### 11. UI 連携
- 牌譜再生時に「ver.2 が打った牌」「タプルの層名」「実際の差分」を表示
- 学習モード: 「ここで別の牌を切るとどうなる?」をシミュレーション
- **MVP**: ログファイル出力のみ (UI は次フェーズ)

#### 12. 段階リリース計画
- α (Week 1-2): 1人麻雀、ユニットテストのみ
- β (Week 3): 4人麻雀、Akochan 対戦
- γ (Week 4): 人間プロ比較 (天鳳ログ)
- リリース: 全機能統合、ドキュメント整備

#### 13. 開発順序 (Todo)
1. core/shanten_v2.py - シャンテン計算移植
2. core/garbage_rank_v2.py - ゴミ度順位 (mode 別)
3. core/defense_v2.py - 防御評価 (平沢パターン)
4. core/strategy_v2.py - モード判定
5. core/evaluator_v2.py - メイン評価器 (タプル比較)
6. core/chiitoitsu_v2.py - 七対子特殊タプル
7. core/yakuman_v2.py - 役満共通タプル + 国士無双特殊
8. 	ools/mjai_client_v2.py - 1人麻雀クライアント
9. 	ools/mjai_battle_v2.py - 4人麻雀 (Akochan 対戦)
10. 	ests/test_*.py - ユニットテスト
11. 	ools/tenhou_compare_v2.py - 人間比較ツール

#### 14. パラメータ調整の動線
- ver.1 は GA で 16 パラメータを調整
- ver.2 は何個? → **最小限** (mode 判定の臒l + ゴミ度順位の数値) を **1-2 個** に
- GA を使わず手動調整 (タプル式なら調整箇所が少ない)

#### 15. ドキュメンテーション
- 設計書 (この実装計画書) - 常に最新に
- API リファレンス (関数ごとに docstring 充実)
- 牌譜例: テストケース毎の期待打牌
- 人間比較レポート (γ フェーズで自動生成)

#### 16. 想定Q&A (FAQ)
- Q: タプルの層が同点の場合は？
  - A: 自然な比較なのでランダム。stable sort で再現性確保
- Q: なぜ向聴数を最優先？
  - A: 人間が遠い手で組むときもまずは前進を選ぶから
- Q: 7層目以降の特殊判断 (赤5, 一発, カン) は？
  - A: 9 層目以降の特殊フラグとして 0/1 追加 (ver.2 設計 6 層 + 拡張)

#### 17. バグ対策
- 「同 rank で大量に候補がある」場合の処理時間 → 候補を最大 10 個に絞る
- 「特殊モード (役満) なのに通常ゴミ度が作用」→ 役満モードでは通常ゴミ度を完全にバイパス
- 「天鳳ログのパース失敗」→ try/except で握りつぶし、ログだけ残す


### 第3.5ラウンド議論 (2026-06-28)

**user から 3大トラップの指摘**:

#### 罠1: デッドレイヤー (幽霊層)
- 七対子タプル (shanten, -ukeire, -pair, -pair_quality, garbage) の問題:
  - 七対子のシャンテン数 = 6 - 対子数 なので、shanten 層で勝敗がつくと pair 層は永久に読まれない
  - 国士タプルの -yaochu, -pair_yaochu も同じ理由
- **対策**: 層間の独立性を保証する設計にする

#### 罠2: 1枚の絶対王政リスク (最重要)
- 通常タプル (向聴数, -受入, ゴミ度, -安全度, -ドラ, -役進行) の問題:
  - 受入が 11→12 に増えるとドラ親ダブルリーチ無筋を 100% 切る
  - 4-6 層が永久に読まれない
  - ベタオリ以外で安全度完全無効化
- **対策**: 受入をバケット化 (fuzzy_ukeire = ukeire // 4) して 1-2 枚の差を tie にする

#### 罠3: 符号のあべこべバグ
- -ドラ を min() すると -1 < 0 で「ドラを捨てる」が選ばれる
- **対策**: 符号規約をデカデカとコメントで明記

### 修正版タプル設計

#### 符号規約 (厳守)
- **min() で打牌を選ぶ**
- **小さいほど良い (AI が選びたい)**
- **「多いほど良い」値は符号反転する**
- 各層の意味と符号を必ず docstring に明記

#### 国士無双タプル (修正版)
\\\
T_kokushi(t) = (
    shanten_after,           # ① 小=良い
    -ukeire,                  # ② 大=良い (反転)
    is_yaochu(t),             # ③ 幺九牌=1, 中張=0 (min で 0 が優先 = 中張から切る) ?
    -safety(t),               # ④ 大=良い (反転、念のため)
)
\\\

#### 七対子タプル (修正版)
\\\
T_chiitoi(t) = (
    shanten_after,           # ① 小=良い
    -ukeire,                  # ② 大=良い (反転)
    -tanki_quality(t),        # ③ 強い単騎候補を残す (大=残したい)
    garbage_rank(t),          # ④ 通常のゴミ度
)
\\\

注: 元の -pair は削除 (デッドレイヤー)
代わりに「tanki_quality (単騎候補の質)」を採用:
- 既に手牌にある 1, 9, 字 の数を評価
- これらを崩す捨て牌はペナルティ

#### 通常タプル (修正版: 5層)
\\\
T_normal(t) = (
    shanten_after,                  # ①
    block_shortage,                 # ② 5 - 現在のブロック数 (0 が理想)
    -fuzzy_ukeire,                  # ③ -(ukeire // 4) (バケット化で 1-2 枚の差を tie 化)
    dora_loss,                      # ④ ドラ捨て枚数 (小=良い、符号反転なし)
    garbage_rank(t),                # ⑤ 0=真っ先に切る, 9=絶対残す
)
\\\

#### 攻撃モード (URGENT_ATTACK)
\\\
T_urgent(t) = (
    shanten_after,
    -fuzzy_ukeire,                  # 受入を最優先
    dora_loss,                      # ドラ絶対残し
    block_shortage,
    garbage_rank(t),
)
\\\

#### 防御モード (DEFEND)
\\\
T_defend(t) = (
    shanten_after,
    -safety(t),                     # 安全度を最優先
    garbage_rank(t),
    -ukeire,                        # 受入は度外視
    dora_loss,
)
\\\

#### 折りモード (FOLD)
\\\
T_fold(t) = (
    -safety(t),                     # 安全度を最優先
    garbage_rank(t),                # ゴミ牌優先
    shanten_after,                  # 向聴数は度外視
    dora_loss,
    -ukeire,                        # 受入度外視
)
\\\

### 設計確認: 一致率 vs 質
- **一致率**: 天鳳ログ 100 局で打牌一致率 60% 以上
- **質**: 打点・放銃率・和了率で評価
  - 一致してないけど「AI の判断の方が人間より良い」場合は質を優先
  - 例: 人間は待ち読みが悪くて放銃したが AI は安全牌を切った

### 段取り
1. 修正版タプル設計で実装開始
2. core/evaluator_v2.py から書き起こし
3. 1人麻雀で動作確認
4. 4 人麻雀 (Akochan) でテスト

### メモ
- 符号規約 (min() 規約) を各関数の docstring に必ず明記
- タプルの要素数 5 層に削減 (元の 6 層案から 1 層減)
- block_shortage は人間が見るセオリーそのもの (2 シャンテンで「あと 3 ブロック要るね」)
- fuzzy_ukeire = ukeire // 4 でバケット化
- 国士無双は is_yaochu (0/1) で min() 規約と一致


### 第4ラウンド議論 (2026-06-28)

**user の指摘**: 固定バケット化は㩁B**全パターン書き出し比較** で実装する。

#### バケット化の罠 (確認)
- 8→9 ukeire で 1 枚差なのにバケット跨ぎで評価が反転
- 6→8 ukeire で 1.33 倍差を完全無視
- **罠2 (1 枚の独裁) を別の形で再発する**

#### user 提案: 全パターン書き出し比較
「受け入れ枚数をバケツで丸めるのをやめて、手牌の要素そのものを細かく分解 (展開) してタプルに並べる」

\\\
セオリー全展開タプル = (
    ① 向聴数,
    ② 良形受入枚数,     # 両面・3 面張 (反転)
    ③ 愚形受入枚数,     # カンチャン・ペンチャン・単騎 (反転)
    ④ 牌の戦術ランク,    # 0-9 で人間セオリー通り
    ⑤ 危険度,
)
\\\

#### user 提案: 戦術的切りやすさランク (全パターン書き出し)

| ランク | 牌の条件 | 戦術的セオリー |
|--------|---------|---------------|
| 0 | 2枚切れ以上の字牌 | 完全安全 |
| 1 | 1枚切れのオタ風・客風 | 最速で処分 |
| 2 | 孤立した端牌 (1・9) | 最も発展性なし |
| 3 | 生牌 (0枚見え) のオタ風・客風 | 重なるリスクあり |
| 4 | 1枚切れの役牌 (三元・場風・自風) | 安牌として少し抱え |
| 5 | 孤立した 2・8 | 1・9 より両面変化あり |
| 6 | 生牌の役牌 | 鳴かれる打点リスク |
| 7+ | 中張牌 (3?7) の搭子 | 手作りの核心 |

### 議論する論点: 戦術ランクの細かさ

ルートB (全パターン書き出し) を採用する場合、ランクの細かさが重要。

#### 案1: 0-9 スケール (user 提案)
- メリット: シンプル、覚えやすい
- デメリット: 「孤立 2 と孤立 9 の中間」がない

#### 案2: 0-15 スケール (拡張)
- 例: 5 の中間に「5a: ドラ表示牌隣接の孤立 28」「5b: 普通の孤立 28」
- メリット: より細かい区別
- デメリット: 設計が複雑化

#### 案3: ランク関数化 (function returning int)
\\\python
def tactical_discard_rank(state, tile) -> int:
    # あらゆる条件を考慮して 0-99 の整数を返す
    # 整数そのものに意味はない、順序だけが重要
    if is_2_visible_honor(state, tile): return 0
    if is_1_visible_otakaze(state, tile): return 1
    if is_isolated_terminal(state, tile): return 2
    # ... 50+ 個の条件 ...
    return 99
\\\
- メリット: 関数が「麻雀セオリーの言語化」になる、保守しやすい
- デメリット: 関数が肥大化

### 議論する論点: 受入の分解

#### 案A: 分解しない (受入をそのまま入れる)
\\\
T_normal(t) = (
    shanten_after,         # ①
    tactical_rank(t),      # ② 0-15
    -ukeire,               # ③ (1-tile 差が問題)
    dora_loss,             # ④
    -safety(t),            # ⑤
)
\\\

#### 案B: 良形/愚形に分解
\\\
T_normal(t) = (
    shanten_after,         # ①
    tactical_rank(t),      # ② 0-15
    -good_ukeire,          # ③ 両面・三面張 (反転)
    -bad_ukeire,           # ④ カンチャン・ペンチャン・単騎 (反転)
    dora_loss,             # ⑤
    -safety(t),            # ⑥
)
\\\

#### 案C: 戦術ランクを細分化して受入を単一に
- tactical_rank に「孤立だが両面変化あり (rank 5a)」「孤立で両面変化なし (rank 5b)」を含める
- ukeire は単一 (-ukeire) だが tactical_rank が既に 1-tile 差を吸収

### 議論する論点: 役満関連

- 国士無双は案A (特殊タプル) 確定
- 役満共通タプルは引き続き (shanten, -ukeire, -yakuman_progress, garbage_special) で
- **役満の「garbage_special」** = 国士無双以外の役満で守るべき牌の特殊ランク
  - 大四喜: 風牌絶対残し
  - 大三元: 三元牌絶対残し
  - 字一色: 字牌絶対残し
  - 清老頭: 1,9 牌絶対残し
  - 九蓮宝燈: 1色+1-9 全部必要
  - 四暗刻: 4 組の暗刻
  - 四槓子: 4 組の槓子

これは個別関数で実装。例:
\\\python
def garbage_special_yakuman(yakuman_type, state, tile) -> int:
    if yakuman_type == 'daisuushii':
        if is_kaze(tile): return 9  # 風牌は絶対残す
    elif yakuman_type == 'daisangen':
        if is_sangen(tile): return 9
    ...
    return 0
\\\

### 次のアクション
1. 戦術ランク関数 (案3: function returning int) を採用
2. 受入の分解は **案C** (戦術ランク細分化 + ukeire 単一) で簡潔に
3. 7 タプル層 (5 + 国士 + 役満共通) を実装

### 確認事項
- 戦術ランク関数の細かさ: 0-9 で十分? 0-15 必要? **user の見解は?**
- 役満の個別特殊関数を 9 個全部作る? **それとも 共通 + 例外のみ?**


### 実装ファイル構成 (詳細)

\\\
core/
  shanten_v2.py          # シャンテン計算 (ver.1 から移植, lru_cache + スレッドローカル)
  ukeire_v2.py           # 受け入れ計算 (良形・愚形に分解する関数)
  tactical_rank_v2.py    # 戦術ランク (牌の切りやすさ 0-99、麻雀セオリーの言語化)
  defense_v2.py          # 防御評価 (平沢パターン + 安全度スコア)
  yakuman_v2.py          # 役満検出 + 特殊タプル (国士無双/字一色/大三元/etc)
  chiitoitsu_v2.py       # 七対子モード判定 + 特殊タプル
  strategy_v2.py         # モード判定 (URGENT/ATTACK/DEFEND/FOLD/YAKUMAN/CHIITOITSU/KOKUSHI)
  evaluator_v2.py        # メイン評価器: 各タプル比較 + コーチング生成
  mode_templates_v2.py   # モード別タプル定義 (JSON から読む or ハードコード)

config/
  strategies_v2.json    # モード別タプル順序・臒l

tools/
  mjai_client_v2.py      # 1 人麻雀 (4-人麻雀インターフェース)
  mjai_battle_v2.py      # 4 人麻雀 + Akochan 対戦
  tenhou_compare_v2.py   # 人間プロ比較ツール
  analyze_v2.py          # スタッツ解析

ver2/
  implementation-plan.md
  tests/                  # テストケース
\\\

### 実装開始の判断
1. **戦術ランク関数の細かさ** (0-9 vs 0-99) ? 未決
2. **受入の扱い** (案A/B/C) ? 未決
3. **役満の個別対応** (9 個 vs 例外のみ) ? 未決
4. **タプル層数** (5 vs 6) ? 未決
5. **1 人モードのテストケース** (どんな局面?) ? 未決

### 簡易実装ロードマップ
- Day 1: shanten_v2.py, 	actical_rank_v2.py (骨格)
- Day 2: ukeire_v2.py (良形・愚形分解), defense_v2.py (平沢パターン)
- Day 3: chiitoitsu_v2.py, yakuman_v2.py, strategy_v2.py
- Day 4: evaluator_v2.py (タプル比較 + コーチング)
- Day 5: mjai_client_v2.py (1 人麻雀)
- Day 6-7: テスト・Akochan 対戦
- Day 8: 人間プロ比較


### 第5ラウンド議論 (2026-06-28) - 最終決定

**確定事項 (user 回答)**:
1. ? **戦術ランク: 0-99 (function)** - 麻雀セオリーの言語化、後で概念追加可
2. ? **受入: 案B (good_ukeire / bad_ukeire 2 層)** - 6層になるがセオリー的に正しい
3. ? **役満: 共通 + グループ化** - 字牌系/幺九系/一色系の3-4 グループ
4. ? **タプル層数: 柔軟** - 必要な分だけ、気にしなくて良し

**最終タプル設計**:

\\\python
# 通常モード (5-6 層)
T_normal(t) = (
    shanten_after,         # ① 向聴数
    tactical_rank(t),      # ② 戦術ランク (0-99、麻雀セオリー言語化)
    -good_ukeire,          # ③ 良形受入 (両面・三面張)
    -bad_ukeire,           # ④ 愚形受入 (カンチャン・ペンチャン・単騎)
    dora_loss,             # ⑤ ドラ損失枚数
    -safety(t),            # ⑥ 安全度
)

# 攻撃モード (受入優先)
T_attack(t) = (
    shanten_after,
    -good_ukeire,          # 良形受入を上に
    -bad_ukeire,
    tactical_rank(t),
    dora_loss,
    -safety(t),
)

# 防御モード (安全優先)
T_defend(t) = (
    shanten_after,
    -safety(t),            # 安全度を上に
    tactical_rank(t),
    -good_ukeire,
    -bad_ukeire,
    dora_loss,
)

# 折りモード
T_fold(t) = (
    -safety(t),
    tactical_rank(t),
    shanten_after,
    -good_ukeire,
    -bad_ukeire,
    dora_loss,
)

# 七対子モード
T_chiitoi(t) = (
    shanten_after,
    -ukeire,               # 対子候補の種類数
    -pair_quality,         # 対子の質 (役牌/ドラ)
    tactical_rank(t),
    dora_loss,
)

# 国士無双モード
T_kokushi(t) = (
    shanten_after,
    -yaochu_count,         # 幺九牌保持数
    -pair_yaochu_count,    # 幺九対子数
    -ukeire,
    is_yaochu(t),          # 0/1 (中張優先)
    -safety(t),
)

# 役満共通モード
T_yakuman(t) = (
    shanten_after,
    -yakuman_progress,
    -ukeire,
    yakuman_garbage_special(t),  # 0-9 (大=残す)
    dora_loss,
    -safety(t),
)
\\\

**実装開始宣言**。以下を順番に実装:
1. core/shanten_v2.py
2. core/tactical_rank_v2.py
3. core/ukeire_v2.py
4. core/defense_v2.py
5. core/chiitoitsu_v2.py
6. core/yakuman_v2.py
7. core/strategy_v2.py
8. core/evaluator_v2.py
9. 	ools/mjai_client_v2.py
10. テスト + Akochan 対戦


### 第6ラウンド議論 (2026-06-28) - AI レビュー指摘対応

**指摘 1: 1 シャンテン DFS の居場所が消えている**
- ver.1 では _run_1shanten_dfs が「良形+打点」の先読みを担っていた
- ver.2 基本形ではこの機能が消えていた
- **修正: 動的タプルスイッチで対応**
  - shanten_after <= 1: 5 層タプル (向聴, -DFS, 戦術ランク, ドラ損失, -安全)
  - shanten_after >= 2: 6 層タプル (向聴, 戦術ランク, -良形, -愚形, ドラ損失, -安全)
- DFS 期待値の意味: 「切った後に良形×打点の期待値」大きいほど良い
- **新ファイル**: core/dfs_v2.py に ver.1 の DFS を移植

**指摘 2: GARBAGE_RANK は「辞書」ではなく「判定関数」として定義する**
- 辞書だと「同じ牌に対してどのラベルを当てるか」で優先順位バグる
- 例: 「1 枚切れのオタ風 = ドラ」 のような場合、辞書の key 引きだとバグる
- **修正: 1 つの巨大な if-else 関数として実装**
  - 	actical_discard_rank() は 1 つの関数で全て判定
  - 各 if ブロックに麻雀セオリーのコメント (言語化)
  - 上から順に評価されるので優先順位が明示

**最終タプル設計 (動的)**:

\\\python
# 1 向聴/テンパイ (5 層)
T_dfs(t) = (
    shanten_after,      # ①
    -dfs_score,          # ② ver.1 の最強武器、良形×打点
    tactical_rank(t),   # ③ 0-99
    dora_loss,           # ④
    -safety(t),          # ⑤
)

# 2 向聴以上 (6 層)
T_normal(t) = (
    shanten_after,      # ①
    tactical_rank(t),   # ② 0-99
    -good_ukeire,       # ③ 両面・三面張
    -bad_ukeire,        # ④ カンチャン・ペンチャン・単騎
    dora_loss,          # ⑤
    -safety(t),         # ⑥
)
\\\

タプル長が違うので Python の辞書式比較で正しく動く:
- 1 向聴 vs 2 向聴: ①shanten で判定 (前者勝ち)
- 1 向聴同士: ②DFS で判定
- 2 向聴同士: ②戦術ランクで判定

**実装済みファイル** (Day 1-6):
- \core/shanten_v2.py\ ?
- \core/tactical_rank_v2.py\ ? (if-else 関数版に refactor)
- \core/ukeire_v2.py\ ?
- \core/defense_v2.py\ ?
- \core/dfs_v2.py\ ? (ver.1 から移植)
- \core/chiitoitsu_v2.py\ ?
- \core/yakuman_v2.py\ ?
- \core/strategy_v2.py\ ?
- \core/evaluator_v2.py\ ? (DFS スイッチ追加)

**次のステップ**:
- \	ools/mjai_client_v2.py\ を作成
- 1 人麻雀で動作確認
- 4 人麻雀 (Akochan 対戦)

