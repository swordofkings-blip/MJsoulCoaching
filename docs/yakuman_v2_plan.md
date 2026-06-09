# 役満ロジック v2 実装計画

## v1の問題点

### 1. 進行度の計算が単純すぎる
- **国士無双**: 「10種持っている」≠「近い」。山に残り0枚の牌が必要なら実質不可能
- **四暗刻**: 「暗刻2組」≠「近い」。全て明刻（ポン）なら四暗刻は成立しない
- **大三元**: 三元牌の刻子数だけで判定。対子や山残りを考慮していない

### 2. ボーナスが全牌に乗る
- 役満進行に貢献しない牌にもボーナスが乗る
- 例：国士無双で中張牌を切るべき場面で、ボーナスが正しく反映されない

### 3. 攻撃ブーストが危険
- 役満進行度が高い場合、攻撃度を上げるが、他家がリーチしていると放銃リスクが増す

### 4. シャンテン計算が粗い
- 各役満のシャンテン計算が単純すぎる（例：四暗刻は「4 - 暗刻数」のみ）

### 5. 門前限定役満の副露チェックなし
- **四暗刻**: 副露（ポン・チー）しても四暗刻を狙ってしまう（門前限定なのに）
- **九蓮宝燈**: 同様に門前限定
- **国士無双**: 同様に門前限定

### 6. 清老頭の計算が不正確
- シャンテン計算が「中張牌の枚数」のみで、面子構造を考慮していない
- 成立可能性判定も不正確

### 7. 門前限定役満を狙う時の副露封印なし
- 国士無双・四暗刻・九蓮宝燈を狙っている時に、誤って副露してしまう

---

## v2の改善方針

### 改善1: 進行度の精密化

**国士無双の改善案:**
```
progress = (所持種数 / 13) × (山残り率) × (対子ボーナス)
```
- 所持種数: 0-13種
- 山残り率: 必要な牌が山に残っている割合
- 対子ボーナス: 対子があれば+0.1（テンパイに近い）

**四暗刻の改善案:**
```
progress = (暗刻数 / 4) × (山残り率) × (対子ボーナス)
```
- 暗刻数: 手牌中の3枚組み（ポン済みは除く）
- 山残り率: 暗刻にできる牌が山に残っている割合
- 対子ボーナス: 対子があれば+0.1

**大三元の改善案:**
```
progress = (三元刻子数 / 3) × (山残り率) × (残り三元牌の対子数)
```
- 三元刻子数: 白/發/中 の刻子数
- 山残り率: 三元牌が山に残っている割合
- 残り三元牌の対子数: 対子があれば+0.1

### 改善2: 牌ごとの貢献度判定

**各牌が役満進行に貢献するかを判定:**
```python
def tile_contributes_to_yakuman(tile_id, hand_counts, visible, yakuman_type):
    """指定された牌が役満進行に貢献するか"""
    if yakuman_type == 'kokushi':
        # 老頭・字牌なら貢献、中張牌なら貢献しない
        return tile_id in YAOCHU_IDS
    elif yakuman_type == 'suuankou':
        # 暗刻にできる牌（3枚組みになる牌）なら貢献
        return hand_counts[tile_id] >= 2
    elif yakuman_type == 'daisangen':
        # 三元牌なら貢献
        return tile_id in SANGEN_IDS
    # ... 他の役満も同様
```

### 改善3: 脅威度考慮した攻撃ブースト

**攻撃ブーストの条件:**
```python
def should_boost_attack(yakuman_progress, opponent_threat, push_score):
    """攻撃ブーストすべきか"""
    if opponent_threat > 0.5:
        return False  # 他家が脅威ならブーストしない
    if push_score < 0.3:
        return False  # 押し引きスコアが低いならブーストしない
    return yakuman_progress > 0.5  # 進行度が高い場合のみブースト
```

### 改善4: シャンテン計算の改善

**国士無双のシャンテン計算:**
```python
def kokushi_shanten(hand_counts, visible):
    """国士無双のシャンテン数"""
    owned = sum(1 for i in YAOCHU_IDS if hand_counts[i] >= 1)
    # 対子の有無
    has_pair = any(hand_counts[i] >= 2 for i in YAOCHU_IDS)
    # 必要な種類数
    missing = 13 - owned
    # シャンテン数 = 欠けている種類数 - (対子があれば1)
    shanten = missing - (1 if has_pair else 0)
    return max(0, shanten)
```

**四暗刻のシャンテン計算:**
```python
def suuankou_shanten(hand_counts, visible):
    """四暗刻のシャンテン数"""
    ankou = sum(1 for i in range(34) if hand_counts[i] >= 3)
    # 暗刻にできる対子の数
    pairs = sum(1 for i in range(34) if hand_counts[i] == 2)
    # シャンテン数 = (4 - 暗刻数) - (対子数と残り面子の関係)
    shanten = 4 - ankou - min(pairs, 4 - ankou)
    return max(0, shanten)
```

---

## 実装ファイル

| ファイル | 変更内容 |
|---|---|
| `core/yakuman_evaluator.py` | 進行度計算の精密化、牌貢献度判定の追加、門前チェック追加、清老頭計算修正 |
| `core/evaluator.py` | ボーナス適用の最適化、攻撃ブーストの条件付き化 |
| `config/config_parameters.json` | パラメータの追加・調整 |

## 具体的な修正内容

### 四暗刻の修正
```python
def _eval_suuankou(self, hand_counts, melds, visible):
    # 門前チェック: 副露があれば四暗刻は成立しない
    has_open_meld = any(m.is_open for m in melds)
    if has_open_meld:
        return YakumanResult(name='四暗刻', progress=0.0, shanten=99, is_possible=False)
    
    # 暗刻数をカウント
    ankou_count = sum(1 for i in range(34) if hand_counts[i] >= 3)
    # 対子数をカウント（暗刻に変換可能な対子）
    pair_count = sum(1 for i in range(34) if hand_counts[i] == 2)
    
    shanten = 4 - ankou_count - min(pair_count, 4 - ankou_count)
    progress = ankou_count / 4.0
    # ...
```

### 清老頭の修正
```python
def _eval_chinroutou(self, hand_counts, melds, visible):
    # 老頭牌の枚数
    terminal_count = sum(hand_counts[i] for i in range(27) if is_terminal(i))
    # 中張牌の枚数（これらを老頭牌に置き換える必要がある）
    non_terminal_count = sum(hand_counts[i] for i in range(27) if not is_terminal(i))
    
    # シャンテン計算: 中張牌を老頭牌に置き換える必要がある
    shanten = non_terminal_count
    
    # 成立可能性: 必要な老頭牌が山に残っているか
    # 各老頭牌が最低1枚必要（面子+雀頭を構成するために）
    required_terminals = [i for i in range(27) if is_terminal(i)]
    impossible = False
    for tid in required_terminals:
        if hand_counts[tid] >= 1:
            continue
        remaining = 4 - visible[tid]
        if remaining <= 0:
            impossible = True
            break
    
    progress = terminal_count / 14.0  # 14枚中何枚が老頭牌か
    # ...
```

### 門前限定役満のチェック追加
```python
def evaluate_all(self):
    hand_counts = self.state.my_hand_counts()
    visible = self.state.all_visible_counts()
    melds = self.state.my_melds
    
    # 門前チェック
    has_open_meld = any(m.is_open for m in melds)
    
    results = {}
    results['kokushi'] = self._eval_kokushi(hand_counts, visible)
    results['suuankou'] = self._eval_suuankou(hand_counts, melds, visible)
    results['daisangen'] = self._eval_daisangen(hand_counts, melds, visible)
    results['tsuuiisou'] = self._eval_tsuuiisou(hand_counts, melds, visible)
    results['chinroutou'] = self._eval_chinroutou(hand_counts, melds, visible)
    results['chuuren'] = self._eval_chuuren(hand_counts, visible)
    results['daisuushii'] = self._eval_daisuushii(hand_counts, melds, visible)
    results['shousuushii'] = self._eval_shousuushii(hand_counts, melds, visible)
    results['ryuuiisou'] = self._eval_ryuuiisou(hand_counts, melds, visible)
    results['suukantsu'] = self._eval_suukantsu(melds, visible)
    
    # 門前限定役満の無効化
    if has_open_meld:
        results['kokushi'].is_possible = False
        results['suuankou'].is_possible = False
        results['chuuren'].is_possible = False
    
    return results
```

### 副露封印モードの実装

**対象役満（門前限定）:**
- 国士無双
- 四暗刻
- 九蓮宝燈

**封印条件:**
- 役満進行度 > 0.5 AND シャンテン数 <= 2
- 門前限定役満が最良の候補

**実装場所:** `strategy_manager.py` or `evaluator.py`

```python
def should_seal_melds(self) -> bool:
    """副露封印モード是否"""
    from yakuman_evaluator import YakumanEvaluator
    
    evaluator = YakumanEvaluator(self.state)
    results = evaluator.evaluate_all()
    
    # 門前限定役満のシーケンス
    CLOSED_ONLY_YAKUMAN = ['kokushi', 'suuankou', 'chuuren']
    
    best_progress = 0.0
    best_is_closed_only = False
    
    for name, result in results.items():
        if not result.is_possible:
            continue
        if result.shanten > 2:
            continue
        if result.progress > best_progress:
            best_progress = result.progress
            best_is_closed_only = name in CLOSED_ONLY_YAKUMAN
    
    # 進行度が高く、門前限定役満が最良なら封印
    return best_progress >= 0.5 and best_is_closed_only
```

**使用場所:** ポン・チーの判定時に呼び出し
```python
# strategy_manager.py or evaluator.py
if self.should_seal_melds():
    # 副露しない
    return False
```

## 新規パラメータ

```json
"yakuman_strategy": {
  "YAKUMAN_TILE_CONTRIBUTION_ENABLED": true,
  "YAKUMAN_ATTACK_BOOST_DEFENSE_THRESHOLD": 0.5,
  "YAKUMAN_ATTACK_BOOST_PUSH_THRESHOLD": 0.3,
  "YAKUMAN_KOKUSHI_PAIR_BONUS": 0.1,
  "YAKUMAN_SUUANKOU_PAIR_BONUS": 0.1,
  "YAKUMAN_DAISANGEN_PAIR_BONUS": 0.1,
  "YAKUMAN_WALL_REMAINING_WEIGHT": 0.3,
  "YAKUMAN_OWNED_TYPES_WEIGHT": 0.7
}
```

## テスト方法

1. 各役満の1-3向聴・テンパイでスコアが正しく反映されるか
2. 山残り牌が少ない場合に進行度が下がるか
3. 他家が脅威の場合に攻撃ブーストが抑制されるか
4. 牌貢献度判定が正しく動作するか

## 期待効果

- **v1**: 60点 → **v2**: 80点（目標）
- 特に「役満に近い時に正しい牌を選ぶ」精度が向上
- 他家が脅威の場合の防御判断が改善
