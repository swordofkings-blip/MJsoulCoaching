# -*- coding: utf-8 -*-
"""
@title 牌譜の AI 評価状態 (eval_status) のユニットテスト
@description トップページで「分析中」「分析失敗」を表示するための状態判定と、/api/records の出力を確認する。
"""
import io
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, 'server'))

import forwarder as fw  # noqa: E402


class _TempDataDir(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, 'data'))
        patcher = mock.patch.object(fw, '_FW_ROOT', self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        fw._evaluating_uuids.clear()
        self.addCleanup(fw._evaluating_uuids.clear)

    def write_json(self, name, obj):
        with open(os.path.join(self.tmp.name, 'data', name), 'w', encoding='utf-8') as f:
            json.dump(obj, f)


class TestGetEvalStatus(_TempDataDir):
    def test_pending_when_eval_file_missing(self):
        self.assertEqual(fw._get_eval_status('u1'), 'pending')

    def test_pending_while_evaluating_even_if_old_marker_exists(self):
        # 再評価中は、前回の失敗マーカーが残っていても「分析中」とする
        self.write_json('record_u1_eval.json', {})
        fw._evaluating_uuids.add('u1')
        self.assertEqual(fw._get_eval_status('u1'), 'pending')

    def test_failed_when_marker(self):
        self.write_json('record_u1_eval.json', {})
        self.assertEqual(fw._get_eval_status('u1'), 'failed')

    def test_done_when_result_exists(self):
        self.write_json('record_u1_eval.json', {'grades': {'0': {'grade': 'A'}}, 'actions': {}})
        self.assertEqual(fw._get_eval_status('u1'), 'done')


class TestApiRecordsEvalStatus(_TempDataDir):
    def _get_records(self):
        handler = fw.PacketHandler.__new__(fw.PacketHandler)
        handler.path = '/api/records'
        handler.wfile = io.BytesIO()
        handler.send_response = mock.Mock()
        handler.send_header = mock.Mock()
        handler.end_headers = mock.Mock()
        handler._set_cors_headers = mock.Mock()
        handler.do_GET()
        return {r['uuid']: r for r in json.loads(handler.wfile.getvalue().decode('utf-8'))}

    def test_each_record_has_eval_status(self):
        for uuid in ('done', 'failed', 'pending'):
            self.write_json(f'record_{uuid}_trimmed.json', {'head': {'uuid': uuid, 'accounts': []}})
        self.write_json('record_done_eval.json', {'grades': {}, 'actions': {}})
        self.write_json('record_failed_eval.json', {})

        records = self._get_records()
        self.assertEqual({u: r['eval_status'] for u, r in records.items()},
                         {'done': 'done', 'failed': 'failed', 'pending': 'pending'})


if __name__ == '__main__':
    unittest.main()
