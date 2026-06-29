# ver.2 評価器アーキテクチャ (簡易ガイド)

## 概要
ver.2 は ver.1 の「重み付きスコア加減算方式」を廃止し、**タプル辞書式比較 + モード別優先順位**で打牌を選ぶ。
Akochan 互換 + 玉座の間スタッツ準拠 + コーチング機能強化を目指す。

## コアモジュール (`core/*_v2.py`)

| ファイル | 役割 |
|---------|------|
| `shanten_v2.py` | シャンテン計算 (lru_cache + スレッドローカル) |
| `tactical_rank_v2.py` | 戦術ランク (0-99、切るべき牌の優先度) |
| `ukeire_v2.py` | 良形/愚形に分けた受け入れ計算 |
| `defense_v2.py` | 防御評価 (平沢麻雀パターン、現物/ノーチャンス判定) |
| `dfs_v2.py` | 1 向聴 DFS 期待値 (両面 1.5 倍) |
| `chiitoitsu_v2.py` | 七対子モード |
| `yakuman_v2.py` | 役満モード (国士無双特殊) |
| `strategy_v2.py` | 8 種類モード判定 (Fuzzy 廃止) |
| `evaluator_v2.py` | メイン評価器 (タプル比較) |

## 戦略モード (優先順位順)
1. `KOKUSHI` (国士無双進行中)
2. `YAKUMAN` (役満進行中、国士以外)
3. `URGENT_ATTACK` (終盤 4 位、攻め必須)
4. `CHIITOITSU` (七対子モード条件成立)
5. `FOLD` (2 リーチ以上 + テンパイ未満)
6. `DEFEND` (1 リーチ + テンパイ未満)
7. `ATTACK` (テンパイ or 1 向聴)
8. `BALANCED` (その他)

## タプル比較 (min() 規約)
小さいほど AI が選びたい。

### 通常 (2 向聴以上): 6 層
```python
(shanten_after, rank, -good_ukeire, -bad_ukeire, dora_loss, -safety)
```

### 1 向聴/テンパイ: 5 層 (DFS)
```python
(shanten_after, -dfs, rank, dora_loss, -safety)
```

### モード別オーバーライド
- `URGENT_ATTACK`: `(shanten, -ukeire, ...)` 受入最優先
- `ATTACK`: `(shanten, -ukeire, ...)` 受入優先
- `BALANCED`: `(shanten, rank, ...)` 戦術ランク優先
- `DEFEND`: `(shanten, -safety, ...)` 安全度優先
- `FOLD`: `(-safety, ...)` 安全度最優先

## 使い方

### 基本的な打牌選択
```python
from core.evaluator_v2 import EvaluatorV2

ev = EvaluatorV2(state)  # state は core.game_state.GameState
chosen = ev.best_discard(list(state.my_hand))
```

### コーチング
```python
ev = EvaluatorV2(state)
print(ev.describe_hand_structure())   # "1 向聴 (3 面子 + 2 塔子)"
print(ev.explain_discard(hand, chosen))  # "②戦術ランク: ..."
print(ev.get_mode().name)               # "ATTACK"
```

### MJAI サーバー対戦
```bash
# 1. Akochan サーバー起動 (Docker)
docker run -d --name akochan_srv -p 11600:11600 akochan-docker-app
# 2. ver.2 クライアント接続
python -m tools.mjai_client_v2 --host 127.0.0.1 --port 11600
```

## 設計原則
- **min() 規約 (厳守)**: 符号規約デカデカ明記、小さいほど AI が選びたい
- **3 大トラップ回避**:
  1. デッドレイヤー (層間独立性必須)
  2. 1 枚の絶対王政 (fuzzy_ukeire 禁止)
  3. 符号あべこべバグ
- **7 大トラップ (ルートB)**: 固定バケットはバグ (1 枚差で 2 バケット跨ぎ)、全パターン展開比較を採用
- **動的タプル長**: Python 辞書式比較で正しく動く
- **平沢麻雀パターン理論** 採用 (電将パターンとは別物)
- **DFS スイッチ**: 1 向聴/テンパイで DFS 経路に分岐

## テスト
```bash
python ver2/tests/test_v2_core.py
```
- 33 テスト全合格
- シャンテン、戦術ランク、受入、防御、戦略、Evaluator、describe/explain を網羅

## A/B テスト
```bash
python tools/ab_test_v1_v2.py 1000
```
- ver.1 vs ver.2 最良打牌一致率を測定
- n=500 で 16.8% 一致 (ver.1 は GA チューン済で別アプローチ、ver.2 はタプル比較デフォルト優先度)
- Akochan バトル前の sanity check

## 玉座の間スタッツ準拠
ver.1 の重み (和了率 20-21%, 副露率 31-33%, 平均和了 6466点, 放銃率 12-14%, 立直率 18-19%) を
ver.2 評価器の `should_riichi` 等の判定で再利用 (ver.1 Evaluator 委譲)。

## 既知の制限
- 七対子/役満/国士無双モードは特殊ロジック、他は標準モード
- 鳴き判断は ver.1 委譲 (ver.1 の MELD_GAP_MAX 等の重みを使用)
- 鳴いた後の手牌進行予測は未実装
- 一部の v1 メソッド (record_detail, get_riichi_decision_details) はスタブのみ
