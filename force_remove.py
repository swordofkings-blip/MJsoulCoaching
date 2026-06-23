"""
@title ロックされたリリースディレクトリを強制削除
@description ファイルロック中でも、個別ファイル削除・長い待機で
             少しずつ削除する
"""
import os
import subprocess
import time
import shutil

def force_remove(path):
    """
    ロックされたファイルを含むディレクトリを強制削除
    """
    if not os.path.exists(path):
        print(f"  [スキップ] {path}: 存在しない")
        return True

    print(f"  [開始] {path} を削除中...")

    # 試行 1: 標準削除
    try:
        shutil.rmtree(path, ignore_errors=True)
        if not os.path.exists(path):
            print(f"  [成功] 標準削除")
            return True
    except Exception as e:
        print(f"  [失敗] 標準削除: {e}")

    # 試行 2: ファイル単位で削除
    print(f"  [試行 2] ファイル単位削除...")
    for root, dirs, files in os.walk(path, topdown=False):
        for f in files:
            fp = os.path.join(root, f)
            try:
                # 読み取り専用解除
                os.chmod(fp, 0o777)
                os.remove(fp)
                print(f"    [削除] {fp}")
            except Exception as e:
                print(f"    [スキップ] {fp}: {e}")
        for d in dirs:
            dp = os.path.join(root, d)
            try:
                os.rmdir(dp)
            except Exception:
                pass

    # 試行 3: rmdir でディレクトリ削除
    try:
        os.rmdir(path)
        if not os.path.exists(path):
            print(f"  [成功] rmdir")
            return True
    except Exception as e:
        print(f"  [失敗] rmdir: {e}")

    # 試行 4: cmd rmdir
    print(f"  [試行 4] cmd rmdir...")
    result = subprocess.run(
        ["cmd", "/c", "rmdir", "/s", "/q", path],
        capture_output=True, text=True
    )
    if not os.path.exists(path):
        print(f"  [成功] cmd rmdir")
        return True

    print(f"  [失敗] 全て失敗: {result.stderr}")
    return False


# 実行
for target in [
    "dist/__tmp_delete",
    "dist/雀魂コーチングくん_release",
]:
    print(f"\n=== {target} ===")
    if force_remove(target):
        print(f"  -> 削除成功")
    else:
        print(f"  -> 削除失敗")

print("\n=== 最終状態 ===")
for d in os.listdir("dist"):
    print(f"  {d}")
