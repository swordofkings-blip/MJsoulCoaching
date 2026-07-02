# -*- coding: utf-8 -*-
"""
@title 天鳳アクション確認スクリプト
@description 天鳳DB から抽出したアクションログを簡易確認するためのデバッグツール。
"""
import sys, sqlite3
sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

DB = r'C:\Users\Daikichi\Documents\code-workspace\雀魂ラッパー_拡散AI\data\raw\tenhou_logs.db'
conn = sqlite3.connect(DB)
cur = conn.cursor()
cur.execute('SELECT id, log FROM logs WHERE is_processed=1 AND was_error=0 LIMIT 1')
row = cur.fetchone()
conn.close()
log_id, log_blob = row
result = tenhou_blob_to_actions(log_blob)
print('type:', type(result))
print('len:', len(result))
for i, item in enumerate(result):
    print('  [%d] type: %s' % (i, type(item)))
    if hasattr(item, '__len__') and not isinstance(item, str):
        print('    len:', len(item))
        if len(item) > 0:
            print('    sample:', list(item)[:2])
    else:
        print('    value:', str(item)[:200])
