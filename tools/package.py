# -*- coding: utf-8 -*-
"""
@title 配布用パッケージングスクリプト
@description PyInstaller の onedir ビルドで生成された
             雀魂コーチングくん.exe (日本語名のランチャー) と _internal/ ディレクトリ、
             説明書 (README.txt) を抽出し、配布用の ZIP アーカイブを自動生成します。
@usage
    # 1. ビルドを実行 (onedir モード)
    pyinstaller --clean --noconfirm build/forwarder.spec

    # 2. このスクリプトを実行
    python tools/package.py

@output
    dist/雀魂コーチングくん_release/
    ├── 雀魂コーチングくん.exe      # PyInstaller ビルド済みランチャー
    ├── _internal/                  # Python ランタイム + ライブラリ
    │   ├── 雀魂コーチングくん.exe    # 内部ランチャー
    │   ├── *.dll, *.pyd
    │   ├── base_library.zip
    │   ├── templates/              # サーバーテンプレート
    │   ├── majsoul_wrapper/        # パケット解析
    │   └── ...
    └── README.txt                  # 導入マニュアル

    dist/雀魂コーチングくん_release_v1.1.zip
"""

import os
import zipfile
import shutil

PROJECT_NAME = "雀魂コーチングくん"
EXE_NAME = f"{PROJECT_NAME}.exe"
VERSION = "1.1"


def create_distribution_dir():
    """
    配布用ディレクトリを作成 (EXE + _internal/ + README.txt)
    """
    dist_root = f"dist/{PROJECT_NAME}_release"
    if os.path.exists(dist_root):
        shutil.rmtree(dist_root)
    os.makedirs(dist_root)

    # コピー元とコピー先
    # onedir ビルドの出力:
    #   dist/雀魂コーチングくん/雀魂コーチングくん.exe (ランチャー)
    #   dist/雀魂コーチングくん/_internal/ (Python ランタイム + ライブラリ)
    items_to_copy = [
        (f"dist/{PROJECT_NAME}/{EXE_NAME}", EXE_NAME),
        (f"dist/{PROJECT_NAME}/_internal", "_internal"),
        ("docs/README.txt", "README.txt"),
    ]

    print(f"--- 配布用ディレクトリの作成: {dist_root} ---")
    success_count = 0
    for src, arc in items_to_copy:
        if os.path.exists(src):
            dest = os.path.join(dist_root, arc)
            if os.path.isdir(src):
                shutil.copytree(src, dest, dirs_exist_ok=True)
                print(f"  [ディレクトリコピー] {src} -> {dest}")
            else:
                shutil.copy2(src, dest)
                print(f"  [ファイルコピー] {src} -> {dest}")
            success_count += 1
        else:
            print(f"  [エラー] 必須ファイル/ディレクトリが見つかりません: {src}")

    return success_count == len(items_to_copy)


def create_distribution_zip():
    """
    配布用ディレクトリを ZIP 圧縮
    """
    dist_root = f"dist/{PROJECT_NAME}_release"
    zip_filename = f"dist/{PROJECT_NAME}_release_v{VERSION}.zip"

    if not os.path.exists(dist_root):
        print(f"[エラー] 配布用ディレクトリが存在しません: {dist_root}")
        print("先に create_distribution_dir() を実行してください。")
        return False

    print(f"--- 配布用 ZIP の作成: {zip_filename} ---")
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for root, dirs, files in os.walk(dist_root):
                for file in files:
                    file_path = os.path.join(root, file)
                    arc_path = os.path.relpath(file_path, "dist")
                    zipf.write(file_path, arc_path)

        size_mb = os.path.getsize(zip_filename) / 1024 / 1024
        print(f"\n[成功] 配布用パッケージが作成されました: {os.path.abspath(zip_filename)}")
        print(f"  ファイルサイズ: {size_mb:.1f} MB")
        return True
    except Exception as e:
        print(f"\n[エラー] ZIP 作成中に例外が発生: {e}")
        return False


if __name__ == '__main__':
    if create_distribution_dir():
        create_distribution_zip()
