# テスト

サーバー (`server/`)・牌譜処理 (`core/record_normalizer.py` など)・シミュレーターのフロントエンド JS のユニットテストです。
コアロジック (ver.2) のテストは `ver2/tests/` にあります。

## Python (標準ライブラリの unittest、追加パッケージ不要)

```bash
source .venv/bin/activate
python -m unittest discover -s tests -v
```

## JavaScript (Node.js 18 以降の組み込みテストランナー、npm パッケージ不要)

```bash
node --test tests/js/*.test.js
```

ブラウザ用のスクリプトを `node:vm` で読み込み、`tests/js/helpers/browser_env.js` の
最小限の DOM スタブ上で関数を直接呼び出してテストします。
