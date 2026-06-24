# -*- coding: utf-8 -*-
"""
雀魂コーチングくん v1.0 リリースパッケージ作成スクリプト

実行内容:
  1. dist/雀魂コーチングくん_release_v1.0/ をクリーンアップ
  2. _internal と exe をコピー
  3. config/ をコピー
  4. data/, logs/ を作成
  ※ gene_variants/ は含めない (開発時の遺伝子チューニング専用)

使い方:
  python tools/build_release.py
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
DIST = ROOT / "dist"
SOURCE_EXE_DIR = DIST / "雀魂コーチングくん"
RELEASE_DIR = DIST / "雀魂コーチングくん_release_v1.0"

def main():
    print("=" * 60)
    print("雀魂コーチングくん v1.0 リリースパッケージ作成")
    print("=" * 60)

    # 1. クリーンアップ
    if RELEASE_DIR.exists():
        print(f"[1/4] リリースディレクトリをクリーン: {RELEASE_DIR.name}")
        shutil.rmtree(RELEASE_DIR)
    RELEASE_DIR.mkdir(parents=True)

    # 2. exe と _internal をコピー
    if not (SOURCE_EXE_DIR / "雀魂コーチングくん.exe").exists():
        print(f"ERROR: {SOURCE_EXE_DIR} が見つかりません。先に pyinstaller を実行してください。")
        sys.exit(1)
    print(f"[2/4] exe + _internal をコピー中...")
    shutil.copytree(SOURCE_EXE_DIR / "_internal", RELEASE_DIR / "_internal")
    shutil.copy2(SOURCE_EXE_DIR / "雀魂コーチングくん.exe", RELEASE_DIR / "雀魂コーチングくん.exe")

    # 3. config をコピー
    print(f"[3/4] config をコピー中...")
    config_dir = ROOT / "config"
    if config_dir.exists():
        shutil.copytree(config_dir, RELEASE_DIR / "config",
                        ignore=shutil.ignore_patterns("*.bak"))

    # 4. data/, logs/ 空ディレクトリ
    print(f"[4/4] data/, logs/ を作成中...")
    (RELEASE_DIR / "data").mkdir(exist_ok=True)
    (RELEASE_DIR / "logs").mkdir(exist_ok=True)

    print()
    print("=" * 60)
    print(f"完了: {RELEASE_DIR}")
    print("=" * 60)
    print()
    for p in sorted(RELEASE_DIR.iterdir()):
        if p.is_dir():
            size = sum(f.stat().st_size for f in p.rglob("*") if f.is_file())
            print(f"  {p.name + '/':30} {size/1024:.1f} KB")
        else:
            print(f"  {p.name:30} {p.stat().st_size/1024:.1f} KB")
    print()

if __name__ == "__main__":
    main()
