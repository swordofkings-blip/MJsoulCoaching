# ダマテン警戒 改良案

## 現状
- `evaluator.py` に `_damaten_tenpai_score()` を追加済み（連続ツモ切り、手出し検出、字牌手出し）
- `defense_score_for_tile()` 内でダマテン警戒ペナルティ適用
- ただし非リーチ時の守備は「現物かどうか」しか見ていない

## 改良案

### 1. 牌単体の危険度評価（軽量デンノー）
ダマテン対局者に対しても、リーチ者と同じ `_tile_remaining_weights` を使って
牌ごとの危険度を評価する。スジ/またぎ/カベ/ノーチャンスを加味。

→ `evaluator.py` の非リーチパスに以下を追加（GA稼働中で編集中、後で続き）：

```python
# ダマテン警戒: 牌単体の危険度をデンノー軽量版で評価
for s in range(4):
    if s == my_seat or reach_states[s].is_reach:
        continue
    pstats = _player_stats_for_seat(s)
    dr = pstats.get("damaten_rate", 0.15)
    ts = _damaten_tenpai_score(s)
    if dr * ts < 0.05:
        continue
    if tile_id in _genbutsu_ids_for_seat(s):
        continue
    if tile_id in _no_chance_ids() and not is_honor(tile_id):
        continue
    # スジ判定
    is_musuji = True
    for rt in river[s]:
        if not is_honor(tile_to_id(rt)):
            for st in suji_safe_tiles(tile_to_id(rt)):
                if st == tile_id:
                    is_musuji = False; break
        if not is_musuji: break
    mult = 1.3 if is_musuji else 1.0
    penalty = int(200 * dr * ts * mult)
    meld_score_adjust -= penalty
```

### 2. ダマテン対局者の手牌推定
- ツモ切りが続く場合、手牌がほとんど決まっている（テンパイ）と推定
- 河に捨てられた牌のスジを安全と判定
- 残り枚数が少ない牌ほど危険（待ちに使われている可能性）

### 3. ダマテン対局者の打点推定
- 副露がある場合：役牌・ドラの枚数から打点推定
- 門前の場合：ドラ表示牌の見え枚数から推定
- 打点が高いほど警戒（リーチと同じ防御スコアに近づける）

### 4. `strategy_manager.py` の threat 推定改善
- 門前ダマの `dama_scale` を damaten_rate で補正する実装は完了済み
- さらにツモ切りパターンを threat に反映する

## 優先順位
1. 牌単体危険度評価（最も効果大、コード変更のみ）
2. 打点推定（config パラメータ追加が必要）
3. ダマテン対局者の手牌推定（精度は出にくい）
