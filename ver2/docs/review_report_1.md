# 雀魂コーチングくん ver.2 コードレビュー報告書

## 概要
ver.2 の「タプルによる辞書式比較」および「巨大 if-else による麻雀セオリーの言語化」という基本方針は、従来の複雑な重みパラメータ調整から解放され、かつコーチング理由の自動生成が容易になるという点で非常に優れた設計です。

しかし、現在 `core/` 下に実装されているソースコードと `ver2/tests/` のテストコードを詳細にレビューした結果、**コンパイルエラー（NameError）、致命的な論理バグ（安全度が機能しない、良形判定の誤り、非標準文字使用によるクラッシュなど）が多数発見され、ユニットテストが 23 件中 10 件失敗する状態**になっています。

また、**テストコード自体にも麻雀ルールや向聴数定義の誤解によるバグが複数混入**しています。

本報告書では、これらのバグの具体的な内容と修正方針をまとめました。

---

## 1. 実装コード側の致命的なバグ・問題点

### ① [evaluator_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/evaluator_v2.py) : モード別タプル順序オーバーライドの未実装
計画書（`implementation-plan.md`）では、状況に応じて `ATTACK`, `DEFEND`, `FOLD`, `URGENT_ATTACK` などのモードごとにタプルの優先順位を入れ替える（例: FOLD では安全度 `-safety` を最優先にする）設計になっていましたが、[evaluator_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/evaluator_v2.py) の `_normal_tuple` は常に同じ順序（`shanten_after` 最優先）のタプルを返しています。これでは「オリ」や「防御」が機能せず、テンパイを目指して危険牌を切り出してしまいます。

### ② [defense_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/defense_v2.py) : 安全度計算の初期化バグ（機能不全）
`_tile_remaining_weights` 内で `weights` が `0.0` の配列で初期化された後、以下の処理が行われています。
```python
    weights = [0.0] * 34
    # ...現物チェック...
    for tid in range(34):
        if weights[tid] == 0.0:
            continue
```
初期値がすべて `0.0` であるため、すべての牌が `continue` され、関数の戻り値は常に `[0.0] * 34` になります。結果として、**他家からリーチがかかっている場合でも、すべての牌の安全度が常に最高値（1000）と判定されてしまい、危険牌を現物と同等に評価してしまう致命的なバグ**となっています。

### ③ [dfs_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/dfs_v2.py) : 非標準の牌文字列使用によるクラッシュ
独自に定義されている `id_to_tile` 関数が、字牌に対して `'E', 'S', 'W', 'N', 'h', 'g', 'r'` という非標準の文字列を返します。
これらを [hand_value.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/hand_value.py) の `estimate_han_advanced` に渡して `tile_to_id` を呼び出すと、`ValueError` を吐いてシステムがクラッシュします。[str_converter.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/str_converter.py) の標準 `id_to_tile` を使う必要があります。

### ④ [chiitoitsu_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/chiitoitsu_v2.py) & [yakuman_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/yakuman_v2.py) : 未定義変数による NameError クラッシュ
`chiitoitsu_tuple` および `yakuman_tuple` 内で、定義されていない `tile_id` 変数を使用しており、実行時に `NameError: name 'tile_id' is not defined` で即時クラッシュします。
引数の `tile` から変換した `discard_id` を渡すように修正する必要があります。

### ⑤ [yakuman_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/yakuman_v2.py) : 役満判定・評価ロジックの不備
- **緑一色（ryuuiisou）判定バグ**: 緑一色で使えない `5s` (22) と `7s` (24) が `ryuu` に含まれている上、`is_honor(tile_id)` が真のときに `9` を返しているため、發以外の全ての字牌（東、南など）が温存対象になってしまいます。
- **役満進行中モードの空振り判定**: `tsuuiisou` (字一色) や `chinroutou` (清老頭) の判定が、すでにアガリ形（14枚すべて揃っている状態）のときしか `possible` にならないため、進行中のモード切替として全く機能していません。

### ⑥ [ukeire_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/ukeire_v2.py) : 良形受け入れ判定（`_is_good_wait`）の論理破綻
`_is_good_wait` は、ツモる牌 `tile_id` の両隣が手牌にあるかという誤った基準で良形待ち判定を行っています。このため、例えば `3m 4m` を持っていて `2m` や `5m` の両面待ち受け入れがある場合でも、ツモ牌の周りに挟む牌がないため `False`（愚形）と判定されてしまい、良形受け入れ枚数の計算が完全に破綻しています。

---

## 2. テストコード側のバグ・不整合

ユニットテスト [test_v2_core.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/ver2/tests/test_v2_core.py) の記述自体にも、ルール誤認やゲーム状態設定のミスによるバグが多数あります。

### ① `test_2_visible_honor_is_rank_0` などの字牌テスト
テストは `1z` (東) のオタ風（客風）としての戦術ランクをテストしようとしていますが、テスト状態がデフォルト（東一局、東家）のままであるため、`1z` は自風かつ場風（ダブ東の役牌）となり、オタ風ではないためテストが落ちています。テストには `2z` (南) や `3z` (西) などを使用すべきです。

### ② `test_chiitoi_4_pairs` の向聴数誤認
七対子の向聴数は `6 - 対子数` です。対子数が 4 個の場合、`6 - 4 = 2` 向聴ですが、テストコードは `3` を期待しているため、アサーションエラーになっています。

### ③ `test_tenpai_dfs_path` の手牌設定ミス
テストで使用されている手牌 `['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','5p','5p']` (14枚) は、4面子1雀頭がすでに完成している**アガリ形**です。
そのため `best_discard` は `_is_winning() == True` により `None`（打牌なし）を返し、テストは `'5p'` を切ることを期待しているため失敗しています。打牌してテンパイになる（14枚で1向聴）の手牌を指定する必要があります。

### ④ `test_genbutsu_is_safe` のリーチ者設定不足
誰もリーチしていないのに、河にある `9m` が安全度 1000 になることを期待しています。本来の安全度計算はリーチ者がいる状況で真価を発揮するため、テスト側でリーチ者を適切に設定するか、リーチなし時の評価ロジックを修正する必要があります。

---

## 3. 推奨アクションプラン

### Step 1: テストケースの修正
まずは正しく麻雀ルールに合致したテストケースに [test_v2_core.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/ver2/tests/test_v2_core.py) を修正し、テストが正しく動作するための基準を整えます。

### Step 2: 各モジュールのバグ修正
1. **[defense_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/defense_v2.py)**: `weights` 配列を `1.0` で初期化し、現物のみ `0.0` に変更。
2. **[dfs_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/dfs_v2.py)**: `id_to_tile` を削除し、[str_converter.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/str_converter.py) の `id_to_tile` に差し替える。
3. **[chiitoitsu_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/chiitoitsu_v2.py) / [yakuman_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/yakuman_v2.py)**: `tile_id` を `discard_id` へ置換。
4. **[ukeire_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/ukeire_v2.py)**: `_is_good_wait` の代わりに、実際にツモ牌を手牌に加えて打牌した後の待ちをシミュレーションして良形待ちになるか判定するロジックに修正。
5. **[yakuman_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/yakuman_v2.py)**: 緑一色・染め手などの判定閾値と対象牌IDを正しく修正。

### Step 3: [evaluator_v2.py](file:///c:/Users/Daikichi/Documents/code-workspace/雀魂コーチングくん/core/evaluator_v2.py) へのモード別タプル適用の実装
`_normal_tuple` をリファクタリングし、`self.get_mode()` に応じて `T_normal`, `T_attack`, `T_defend`, `T_fold` の各タプル構造を返すようにモード別分岐を実装します。
