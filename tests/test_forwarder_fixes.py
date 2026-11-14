# -*- coding: utf-8 -*-
"""
@title server/forwarder.py の不具合修正に関するユニットテスト
@description
- /api/restart: Windows 以外では os.execve で再起動し、サーバーが停止したままにならない
- 牌譜評価: 評価前に seat=0 などの欠落値を補完する / 失敗時は失敗マーカーを保存する
- 起動時の再評価: 未評価・評価失敗の牌譜だけを再評価する
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


def _make_handler(path):
    """ソケットなしで PacketHandler を作る (BaseHTTPRequestHandler の初期化処理を通さない)"""
    handler = fw.PacketHandler.__new__(fw.PacketHandler)
    handler.path = path
    handler.wfile = io.BytesIO()
    handler._send_json = mock.Mock()
    # Why: os._exit をモックすると後続の分岐 (404 応答) まで進むため、HTTP 応答系もモックする
    handler.send_response = mock.Mock()
    handler.send_header = mock.Mock()
    handler.end_headers = mock.Mock()
    return handler


class _ProcessReplaced(BaseException):
    """本物の os.execve は戻らない (プロセスが置き換わる) ため、テストでは例外で再現する"""


class TestRestart(unittest.TestCase):
    def _post_restart(self, os_name):
        handler = _make_handler('/api/restart')
        with mock.patch.object(fw.os, 'name', os_name), \
                mock.patch.object(fw.os, 'walk', return_value=[]), \
                mock.patch.object(fw.os, 'execve', side_effect=_ProcessReplaced) as execve, \
                mock.patch.object(fw.os, '_exit') as os_exit, \
                mock.patch.object(fw.subprocess, 'Popen') as popen, \
                mock.patch('time.sleep'), \
                mock.patch('builtins.open', mock.mock_open()):
            try:
                handler.do_POST()
            except _ProcessReplaced:
                pass
        return handler, execve, os_exit, popen

    def test_posix_restarts_with_execve(self):
        handler, execve, os_exit, popen = self._post_restart('posix')
        handler._send_json.assert_called_once()
        execve.assert_called_once()
        exe, argv, env = execve.call_args[0]
        self.assertEqual(exe, sys.executable)
        self.assertEqual(argv[-1], os.path.abspath(fw.__file__))
        self.assertEqual(env.get('COACH_RESTARTED'), '1')
        # Windows 専用の creationflags 付き Popen は呼ばない (呼ぶと ValueError で停止していた)
        popen.assert_not_called()
        os_exit.assert_not_called()

    def test_posix_exec_failure_keeps_server_running(self):
        handler = _make_handler('/api/restart')
        with mock.patch.object(fw.os, 'name', 'posix'), \
                mock.patch.object(fw.os, 'walk', return_value=[]), \
                mock.patch.object(fw.os, 'execve', side_effect=OSError('exec failed')), \
                mock.patch.object(fw.os, '_exit') as os_exit, \
                mock.patch('time.sleep'):
            handler.do_POST()
        # exec に失敗しても旧プロセスは終了しない
        os_exit.assert_not_called()

    def test_windows_still_uses_detached_popen(self):
        _, execve, os_exit, popen = self._post_restart('nt')
        execve.assert_not_called()
        popen.assert_called_once()
        self.assertEqual(popen.call_args.kwargs.get('creationflags'), 0x00000008)
        self.assertEqual(popen.call_args.kwargs['env'].get('COACH_RESTARTED'), '1')
        os_exit.assert_called_once_with(0)


class _TempDataDir(unittest.TestCase):
    """_FW_ROOT を一時ディレクトリに差し替える"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.makedirs(os.path.join(self.tmp.name, 'data'))
        patcher = mock.patch.object(fw, '_FW_ROOT', self.tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.addCleanup(self.tmp.cleanup)
        fw._evaluating_uuids.clear()

    def data_path(self, name):
        return os.path.join(self.tmp.name, 'data', name)

    def write_json(self, name, obj):
        with open(self.data_path(name), 'w', encoding='utf-8') as f:
            json.dump(obj, f)


class TestRunRecordEvaluation(_TempDataDir):
    def _write_record_without_seat0(self):
        record = {'head': {}, 'detail_records': {'actions': [
            {'type': 1, 'result': {'class_name': 'RecordDiscardTile', 'data': {'tile': '1m'}}}]}}
        self.write_json('record_u1_trimmed.json', record)
        return self.data_path('record_u1_trimmed.json')

    def test_normalizes_record_before_evaluation(self):
        trimmed = self._write_record_without_seat0()
        captured = {}

        def fake_evaluate(record):
            captured['seat'] = record['detail_records']['actions'][0]['result']['data'].get('seat')
            return {'grades': {}, 'actions': {}}

        with mock.patch('core.record_evaluator.evaluate_record', side_effect=fake_evaluate):
            fw._run_record_evaluation('u1', trimmed)

        self.assertEqual(captured['seat'], 0)
        with open(self.data_path('record_u1_eval.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f), {'grades': {}, 'actions': {}})
        self.assertNotIn('u1', fw._evaluating_uuids)

    def test_failure_writes_marker_and_clears_state(self):
        trimmed = self._write_record_without_seat0()
        with mock.patch('core.record_evaluator.evaluate_record', side_effect=KeyError(None)):
            fw._run_record_evaluation('u1', trimmed)
        with open(self.data_path('record_u1_eval.json'), encoding='utf-8') as f:
            self.assertEqual(json.load(f), {})
        self.assertNotIn('u1', fw._evaluating_uuids)


class _SyncThread:
    """threading.Thread の代わりに start() で即座に target を実行する"""

    def __init__(self, target=None, args=(), daemon=None):
        self.target, self.args = target, args

    def start(self):
        self.target(*self.args)


class TestRetryPendingEvaluations(_TempDataDir):
    def test_retries_only_missing_or_failed(self):
        for uuid in ('done', 'failed', 'missing'):
            self.write_json(f'record_{uuid}_trimmed.json', {'head': {}})
        self.write_json('record_done_eval.json', {'grades': {'0': {'grade': 'A'}}})
        self.write_json('record_failed_eval.json', {})

        with mock.patch.object(fw, '_run_record_evaluation') as run_eval, \
                mock.patch('threading.Thread', _SyncThread):
            fw._retry_pending_evaluations()

        retried = sorted(call.args[0] for call in run_eval.call_args_list)
        self.assertEqual(retried, ['failed', 'missing'])

    def test_no_targets_does_nothing(self):
        self.write_json('record_done_trimmed.json', {'head': {}})
        self.write_json('record_done_eval.json', {'grades': {}})
        with mock.patch.object(fw, '_run_record_evaluation') as run_eval, \
                mock.patch('threading.Thread', _SyncThread):
            fw._retry_pending_evaluations()
        run_eval.assert_not_called()


class TestScheduleRecordEvaluation(_TempDataDir):
    def test_skips_when_already_evaluating(self):
        fw._evaluating_uuids.add('u1')
        with mock.patch('threading.Thread') as thread:
            fw._schedule_record_evaluation('u1', self.data_path('record_u1_trimmed.json'))
        thread.assert_not_called()


class TestTrimGameRecord(unittest.TestCase):
    def test_strips_metadata_keys(self):
        trimmed = fw.trim_game_record({'a': 1, 'passed': 3, 'nested': [{'zhenting': [True], 'tile': '1m'}]})
        self.assertEqual(trimmed, {'a': 1, 'nested': [{'tile': '1m'}]})


if __name__ == '__main__':
    unittest.main()
