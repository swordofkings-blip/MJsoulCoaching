# -*- mode: python ; coding: utf-8 -*-
# 雀魂コーチングくん - forwarder.exe ビルド設定
# ビルドコマンド: pyinstaller build/forwarder.spec
# 注: onedir モードで再起動時のリソース抽出問題を回避

import os
from PyInstaller.utils.hooks import collect_submodules

# spec ファイルのディレクトリを基準とした絶対パス
SPEC_DIR = os.path.dirname(os.path.abspath(SPEC))
ROOT_DIR = os.path.dirname(SPEC_DIR)  # プロジェクトのルート

hiddenimports = [
    'majsoul_wrapper.liqi',
    'majsoul_wrapper.proto.liqi_pb2',
    'core.sapk_api',
    'core.game_state',
    'core.evaluator',
    'core.str_converter',
    'core.hand_value',
    'core.yakuman_evaluator',
    'core.yaku_detector',
    'core.scoring',
    'core.opponent_model',
    'core.fuzzy_logic',
    'core.strategy_manager',
    'core.bayesian_tenpai',
    'core.ast_parser',
]
hiddenimports += collect_submodules('majsoul_wrapper')
hiddenimports += collect_submodules('core')

# データファイル: サーバーテンプレート + ブラウザフック + majsoul_wrapper/proto の JSON + 設定ファイル
# Why: majsoul_hook.js (Tampermonkey ユーザースクリプト) は
# /majsoul_hook.user.js エンドポイントで配信されるため、バンドルに含める必要がある。
# onedir モードでは _internal/ 内に配置される。
# 設定ファイル (config/) は forwarder.py が実行時に ../config/ から読み込むため、
# onedir 出力ディレクトリに含める必要がある (PyInstaller バンドルではない)。
datas = [
    (os.path.join(ROOT_DIR, 'server', 'templates'), 'templates'),
    (os.path.join(ROOT_DIR, 'server', 'majsoul_hook.js'), '.'),
    (os.path.join(ROOT_DIR, 'majsoul_wrapper', 'proto', 'liqi.json'), os.path.join('majsoul_wrapper', 'proto')),
    (os.path.join(ROOT_DIR, 'majsoul_wrapper', 'proto', 'liqi.proto'), os.path.join('majsoul_wrapper', 'proto')),
]

a = Analysis(
    [os.path.join(ROOT_DIR, 'server', 'forwarder.py')],
    pathex=[ROOT_DIR],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

# Why: COLLECT を使って onedir 形式でビルド。
# onefile だと再起動時に forwarder.pkg の展開が失敗して 500 エラーになるが、
# onedir なら _internal/ ディレクトリに展開済みなので再起動が安定する。
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='雀魂コーチングくん',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='雀魂コーチングくん',
)
