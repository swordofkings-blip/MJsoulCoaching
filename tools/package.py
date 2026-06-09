# -*- coding: utf-8 -*-
"""
@title 配布用パッケージングスクリプト
@description ビルド済みの実行ファイル（forwarder.exe）と説明書（README.md）を抽出し、配布用のZIPアーカイブを自動生成します。
"""

import os
import zipfile

def create_distribution_zip():
    # 生成するZIPファイルの名前
    zip_filename = "majsoul_simulator_release.zip"
    
    # アーカイブに含めるファイルのマップ {実ファイルパス: ZIP内での配置パス}
    # 意図：PyInstallerのonefileビルドにより、テンプレート等はすべてEXE内に内包されているため、
    # 動作に必要なのはEXE本体と説明書のみです。
    files_to_include = {
        "dist/forwarder.exe": "forwarder.exe",
        "README.txt": "README.txt"
    }

    print(f"--- 配布用ZIPの作成を開始します: {zip_filename} ---")
    
    success_count = 0
    try:
        with zipfile.ZipFile(zip_filename, 'w', zipfile.ZIP_DEFLATED) as zipf:
            for src_path, arc_path in files_to_include.items():
                if os.path.exists(src_path):
                    zipf.write(src_path, arc_path)
                    print(f"  [追加成功] {src_path} -> {arc_path}")
                    success_count += 1
                else:
                    print(f"  [エラー] 必須ファイルが見つかりません: {src_path}")
                    
        if success_count == len(files_to_include):
            print("\n[成功] 配布用パッケージが正常に作成されました！")
            print(f"出力ファイル: {os.path.abspath(zip_filename)}")
        else:
            print(f"\n[警告] 一部のファイルが不足しています（作成数: {success_count}/{len(files_to_include)}）")
            
    except Exception as e:
        print(f"\n[エラー] ZIP作成中に例外が発生しました: {e}")

if __name__ == '__main__':
    create_distribution_zip()
