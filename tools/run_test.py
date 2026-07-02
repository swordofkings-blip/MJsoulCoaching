# -*- coding: utf-8 -*-
"""
@title モジュール単体テストランナー
@description core モジュールの特定テストケースを実行するための簡易エントリポイント。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
os.environ['PYTHONIOENCODING'] = 'utf-8'

# Run test and capture output
import io
old_stdout = sys.stdout
sys.stdout = io.TextIOWrapper(io.BytesIO(), encoding='utf-8')

from test_yakuman_bonus import main
success = main()

sys.stdout.seek(0)
output = sys.stdout.read().decode('utf-8')
sys.stdout = old_stdout

# Write to file
with open('test_result.txt', 'w', encoding='utf-8') as f:
    f.write(output)

# Print summary
for line in output.split('\n'):
    if 'サマリー' in line or line.strip().startswith('[OK]') or line.strip().startswith('[NG]') or '結果:' in line or '点差' in line:
        print(line)

sys.exit(0 if success else 1)
