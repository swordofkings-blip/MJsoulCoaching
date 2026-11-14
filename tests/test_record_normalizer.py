# -*- coding: utf-8 -*-
"""
@title core/record_normalizer.py のユニットテスト
@description MessageToDict が省略した proto3 のデフォルト値 (seat=0 / chang=0 など) を
             正しく補完できるか、補完してはいけないフィールドを触らないかを確認する。
"""
import copy
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.protobuf.json_format import MessageToDict

from core.record_normalizer import normalize_record, STRIP_KEYS
from majsoul_wrapper.proto import liqi_pb2 as pb


def _wrap(class_name, msg):
    """deep_decode と同じ {"class_name", "data"} 形式で包む"""
    return {'class_name': class_name, 'data': MessageToDict(msg)}


def _make_record():
    """seat=0 / chang=0 / ju=0 / ben=0 を含む、修正前と同じ形の牌譜 JSON を作る"""
    new_round = pb.RecordNewRound(chang=0, ju=0, ben=0, liqibang=0, scores=[25000] * 4)
    new_round.operation.seat = 0
    discard0 = pb.RecordDiscardTile(seat=0, tile='1m', moqie=False, is_liqi=False)
    deal2 = pb.RecordDealTile(seat=2, tile='5p', left_tile_count=68)
    head = MessageToDict(pb.RecordGame(
        uuid='test-uuid',
        accounts=[pb.RecordGame.AccountInfo(seat=0, nickname='East'),
                  pb.RecordGame.AccountInfo(seat=2, nickname='West')],
    ))
    return {
        'head': head,
        'detail_records': {
            'version': 1,
            'actions': [
                {'type': 1, 'result': _wrap('RecordNewRound', new_round)},
                {'type': 1, 'result': _wrap('RecordDiscardTile', discard0)},
                {'type': 1, 'result': _wrap('RecordDealTile', deal2)},
            ],
        },
        'decoded_rounds': [],
    }


class TestPrecondition(unittest.TestCase):
    def test_message_to_dict_omits_default_values(self):
        """前提: MessageToDict は seat=0 などのデフォルト値を出力しない (これが不具合の原因)"""
        d = MessageToDict(pb.RecordDiscardTile(seat=0, tile='1m'))
        self.assertNotIn('seat', d)


class TestNormalizeRecord(unittest.TestCase):
    def setUp(self):
        self.record = normalize_record(_make_record())
        self.actions = self.record['detail_records']['actions']

    def test_fills_seat_zero_in_actions(self):
        self.assertEqual(self.actions[1]['result']['data']['seat'], 0)

    def test_keeps_non_default_values(self):
        data = self.actions[2]['result']['data']
        self.assertEqual(data['seat'], 2)
        self.assertEqual(data['tile'], '5p')
        self.assertEqual(data['leftTileCount'], 68)

    def test_fills_round_info(self):
        data = self.actions[0]['result']['data']
        self.assertEqual((data['chang'], data['ju'], data['ben'], data['liqibang']), (0, 0, 0, 0))

    def test_fills_nested_message_fields(self):
        # operation は存在するサブメッセージなので、その中の seat も補完される
        self.assertEqual(self.actions[0]['result']['data']['operation']['seat'], 0)

    def test_fills_bool_fields(self):
        data = self.actions[1]['result']['data']
        self.assertIs(data['moqie'], False)
        self.assertIs(data['isLiqi'], False)

    def test_fills_head_account_seat(self):
        seats = {a['nickname']: a['seat'] for a in self.record['head']['accounts']}
        self.assertEqual(seats, {'East': 0, 'West': 2})

    def test_does_not_add_repeated_fields(self):
        # Why: 空リストを足すと「キーの存在」で判定しているロジックの意味が変わる
        self.assertNotIn('doras', self.actions[2]['result']['data'])

    def test_does_not_restore_stripped_keys(self):
        # Why: trim_game_record で削除したキーを補完すると実データと異なる値が復活してしまう
        for action in self.actions:
            for key in STRIP_KEYS:
                self.assertNotIn(key, action)
                self.assertNotIn(key, action['result']['data'])

    def test_is_idempotent(self):
        once = copy.deepcopy(self.record)
        self.assertEqual(normalize_record(once), self.record)


class TestNormalizeRecordEdgeCases(unittest.TestCase):
    def test_non_dict_is_returned_as_is(self):
        self.assertIsNone(normalize_record(None))
        self.assertEqual(normalize_record([1, 2]), [1, 2])

    def test_unknown_class_name_is_ignored(self):
        record = {'detail_records': {'actions': [
            {'result': {'class_name': 'NoSuchMessage', 'data': {'foo': 1}}}]}}
        normalize_record(record)
        self.assertEqual(record['detail_records']['actions'][0]['result']['data'], {'foo': 1})

    def test_head_only(self):
        # forwarder の /api/records は head だけを補完する
        head = MessageToDict(pb.RecordGame(accounts=[pb.RecordGame.AccountInfo(seat=0, nickname='A')]))
        normalize_record({'head': head})
        self.assertEqual(head['accounts'][0]['seat'], 0)


if __name__ == '__main__':
    unittest.main()
