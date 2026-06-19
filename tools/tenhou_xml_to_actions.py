# -*- coding: utf-8 -*-
"""
@title Tenhou XML → actions-JSON 変換
@description
    diffusion-ai/data/raw/tenhou_logs.db に格納された gzip 圧縮の
    天鳳 mjloggm XML を、tools/extract_mismatches.py が受け付ける
    既存の actions 形式 JSON に変換する。
"""
from __future__ import annotations

import gzip
import re
import sys
import urllib.parse
from typing import Iterable, List, Optional, Tuple

# 萬子・筒子・索子の文字と字牌
_TILE_LETTERS = ['m', 'p', 's', 'z']


def tile_id_to_str(tile_id: int) -> str:
    """Tenhou の牌 ID (0-135) を "1m"/"0m" 等の文字列に変換"""
    tile_id = int(tile_id)
    num = tile_id // 4
    suit = num // 9
    rank = num % 9 + 1
    return f'{rank}{_TILE_LETTERS[suit]}'


def decode_red(tile_id: int) -> str:
    """赤5を "0m"/"0p"/"0s" に変換。通常5は "5m" 等。"""
    tile_id = int(tile_id)
    num = tile_id // 4
    if num % 9 == 4 and tile_id % 4 == 0:
        return f'0{_TILE_LETTERS[num // 9]}'
    return tile_id_to_str(tile_id)


def decode_meld(m: int) -> Tuple[int, List[str], List[int], List[int]]:
    """
    Tenhou Nタグの m 属性から (type, tiles, froms, tile_states) を復元。
    type: 0=チー, 1=ポン, 2=大明槓, 3=暗槓, 4=加槓
    """
    data = int(m)
    from_player = data & 0x3
    if data & 0x4:
        # チー
        t0, t1, t2 = (data >> 3) & 0x3, (data >> 5) & 0x3, (data >> 7) & 0x3
        base_and_called = data >> 10
        called = base_and_called % 3
        base = base_and_called // 3
        base = (base // 7) * 9 + base % 7
        ids = [
            4 * (base + 0) + t0,
            4 * (base + 1) + t1,
            4 * (base + 2) + t2,
        ]
        tiles = [tile_id_to_str(i) for i in ids]
        # froms: 鳴いた牌(called) は他家から、その他は自分
        froms = [from_player if i == called else -1 for i in range(3)]
        tile_states = [0] * 3
        return 0, tiles, froms, tile_states
    if data & 0x18:
        # ポン / 加槓
        t4 = (data >> 5) & 0x3
        t_order = ((1, 2, 3), (0, 2, 3), (0, 1, 3), (0, 1, 2))[t4]
        base_and_called = data >> 9
        called = base_and_called % 3
        base = base_and_called // 3
        ids = [4 * base + t_order[0], 4 * base + t_order[1], 4 * base + t_order[2]]
        if data & 0x8:
            # ポン
            tiles = [tile_id_to_str(i) for i in ids]
            froms = [from_player if i == called else -1 for i in range(3)]
            tile_states = [0] * 3
            return 1, tiles, froms, tile_states
        # 加槓 (chakan)
        tiles = [tile_id_to_str(i) for i in ids] + [tile_id_to_str(4 * base + t4)]
        froms = [from_player if i == called else -1 for i in range(3)] + [-1]
        tile_states = [0] * 4
        return 4, tiles, froms, tile_states
    if data & 0x20:
        # 抜き(nuki) - 北抜き
        tile_id = data >> 8
        return 5, [tile_id_to_str(tile_id)], [-1], [0]
    # カン
    base_and_called = data >> 8
    if from_player:
        called = base_and_called % 4
    else:
        called = -1
    base = base_and_called // 4
    ids = [4 * base, 1 + 4 * base, 2 + 4 * base, 3 + 4 * base]
    tiles = [tile_id_to_str(i) for i in ids]
    froms = [from_player] * 4
    tile_states = [0] * 4
    return 2, tiles, froms, tile_states


def _draw_seat(tag: str) -> int:
    """T/U/V/W → 0/1/2/3"""
    return ord(tag[0]) - ord('T')


def _discard_seat(tag: str) -> int:
    """D/E/F/G → 0/1/2/3"""
    return ord(tag[0]) - ord('D')


def tenhou_xml_to_actions(xml: str) -> Tuple[dict, int]:
    """
    @title 天鳳XMLをactions-JSON形式に変換
    @description mjloggm XML を extract_mismatches.py が読める
        {head, detail_records:{actions:[...]}} の形式に変換する。
    @param {str} xml - mjloggm XML 文字列
    @returns {tuple} (json_dict, num_rounds) - 変換後のJSONと局数
    """
    # 1) round ブロックに分割。 <INIT> ... <AGARI|RYUUKYOKU> までが1局
    #    タグ列を順番にスキャンする。
    tag_re = re.compile(r'<([A-Z][A-Z0-9]*)\b([^>]*?)(/?)>')

    actions: List[dict] = []
    scores = [25000] * 4
    chang = 0
    ju = 0
    num_rounds = 0

    # 現在処理中の局の状態
    cur_round: Optional[dict] = None
    cur_doras: List[str] = []
    cur_oya: int = 0
    cur_hands: List[List[str]] = [[] for _ in range(4)]
    cur_ben = 0
    cur_liqibang = 0
    cur_left_tiles = 70

    # アクションの追跡用フラグ
    last_event: Optional[str] = None  # 'draw' / 'discard' / 'naki' / 'reach1' / 'reach2' / 'init'
    last_seat: int = -1
    pending_reach_seat: int = -1
    awaiting_discard: List[bool] = [False] * 4  # 鳴きの直後に切るフラグ

    def emit(action: dict):
        actions.append(action)

    def flush_round_end():
        nonlocal cur_round
        if cur_round is None:
            return
        cur_round = None

    for m in tag_re.finditer(xml):
        tag_name = m.group(1)
        attrs_str = m.group(2)
        self_close = m.group(3) == '/'
        attrs = dict(re.findall(r'(\w+)="([^"]*)"', attrs_str))

        if tag_name == 'SHUFFLE' or tag_name == 'GO' or tag_name == 'TAIKYOKU' or tag_name == 'UN' or tag_name == 'BYE':
            continue

        if tag_name == 'INIT':
            flush_round_end()
            num_rounds += 1
            seed = attrs['seed'].split(',')
            round_num = int(seed[0])  # 0-based
            cur_ben = int(seed[1])
            cur_liqibang = int(seed[2])
            dora_indicator = int(seed[5]) if len(seed) > 5 else None
            cur_oya = int(attrs['oya'])
            scores = [int(x) * 100 for x in attrs['ten'].split(',')]
            cur_hands = []
            for s in range(4):
                key = f'hai{s}'
                if key in attrs:
                    hand_ids = [int(x) for x in attrs[key].split(',')]
                    cur_hands.append([tile_id_to_str(i) for i in hand_ids])
                else:
                    cur_hands.append([])
            cur_doras = [tile_id_to_str(dora_indicator)] if dora_indicator is not None else []
            cur_left_tiles = 70

            # chang, ju を round_num から算出
            # seedの0要素 = (chang*4 + ju) - 1; 牌譜の "東1" 開始時 round_num=0
            # extract_mismatches.py に合わせて ju = round_num % 4, chang = round_num // 4
            chang = round_num // 4
            ju = round_num % 4

            data = {
                'chang': chang,
                'ju': ju,
                'ben': cur_ben,
                'liqibang': cur_liqibang,
                'leftTileCount': cur_left_tiles,
                'doras': list(cur_doras),
                'scores': list(scores),
                'tiles0': list(cur_hands[0]),
                'tiles1': list(cur_hands[1]),
                'tiles2': list(cur_hands[2]),
                'tiles3': list(cur_hands[3]),
                'operation': {'seat': cur_oya},
            }
            emit({'type': 1, 'result': {'class_name': 'RecordNewRound', 'data': data}})
            cur_round = {'oya': cur_oya, 'doras': list(cur_doras)}
            last_event = 'init'
            pending_reach_seat = -1
            awaiting_discard = [False] * 4
            continue

        if tag_name == 'DORA':
            dora_id = int(attrs['hai'])
            cur_doras.append(tile_id_to_str(dora_id))
            # 既存の RecordAnGangAddGang と同じ形で dora だけ更新する action はないので、
            # ダミーの RecordNewRound 風 action を出す(extract_mismatches.py の
            #  'doras' in d チェックで拾われる)
            emit({
                'type': 1,
                'result': {
                    'class_name': 'RecordAnGangAddGang',
                    'data': {
                        'type': 0,
                        'seat': -1,
                        'tiles': '0m',  # dummy
                        'doras': list(cur_doras),
                    },
                },
            })
            last_event = 'dora'
            continue

        if tag_name == 'REACH':
            who = int(attrs['who'])
            step = int(attrs.get('step', '1'))
            if step == 1:
                pending_reach_seat = who
                last_event = 'reach1'
                last_seat = who
            else:
                last_event = 'reach2'
                last_seat = who
            continue

        if len(tag_name) >= 2 and tag_name[0] in 'TUVW' and self_close:
            seat = _draw_seat(tag_name)
            tile_id = int(tag_name[1:])
            tile = tile_id_to_str(tile_id)
            cur_left_tiles = max(0, cur_left_tiles - 1)
            data = {
                'seat': seat,
                'tile': tile,
                'leftTileCount': cur_left_tiles,
            }
            emit({'type': 1, 'result': {'class_name': 'RecordDealTile', 'data': data}})
            last_event = 'draw'
            last_seat = seat
            awaiting_discard[seat] = False
            continue

        if len(tag_name) >= 2 and tag_name[0] in 'DEFG' and self_close:
            seat = _discard_seat(tag_name)
            tile_id = int(tag_name[1:])
            tile = tile_id_to_str(tile_id)
            is_liqi = (pending_reach_seat == seat)
            pending_reach_seat = -1
            moqie = (last_event == 'draw' and last_seat == seat)
            data = {
                'seat': seat,
                'tile': tile,
                'isLiqi': is_liqi,
                'moqie': moqie,
            }
            emit({'type': 1, 'result': {'class_name': 'RecordDiscardTile', 'data': data}})
            last_event = 'discard'
            last_seat = seat
            continue

        if tag_name == 'N':
            who = int(attrs['who'])
            m_val = int(attrs['m'])
            call_type, tiles, froms, tile_states = decode_meld(m_val)
            # 鳴いた後はその人が牌を捨てる(tsumoじゃない)
            data = {
                'seat': who,
                'type': call_type,
                'tiles': tiles,
                'froms': froms,
                'tileStates': tile_states,
            }
            emit({'type': 1, 'result': {'class_name': 'RecordChiPengGang', 'data': data}})
            last_event = 'naki'
            last_seat = who
            awaiting_discard = [False] * 4
            awaiting_discard[who] = True
            continue

        if tag_name == 'AGARI':
            who = int(attrs['who'])
            from_who = int(attrs['fromWho'])
            hai = [tile_id_to_str(int(x)) for x in attrs['hai'].split(',')]
            hu_tile = tile_id_to_str(int(attrs['machi']))
            zimo = (who == from_who)
            data = {
                'hules': [
                    {
                        'hand': hai,
                        'ming': [],
                        'huTile': hu_tile,
                        'seat': who,
                        'zimo': zimo,
                        'doras': list(cur_doras),
                    }
                ],
            }
            emit({'type': 1, 'result': {'class_name': 'RecordHule', 'data': data}})
            last_event = 'agari'
            last_seat = -1
            continue

        if tag_name == 'RYUUKYOKU':
            data = {}
            emit({'type': 1, 'result': {'class_name': 'RecordNoTile', 'data': data}})
            last_event = 'ryuukyoku'
            last_seat = -1
            continue

    json_dict = {
        'head': {
            'uuid': 'tenhou_db_log',
            'startTime': 0,
        },
        'detail_records': {
            'actions': actions,
        },
    }
    return json_dict, num_rounds


def tenhou_blob_to_actions(blob: bytes) -> Tuple[dict, int]:
    """DBから取り出した gzip 圧縮 blob を JSON dict に変換"""
    xml = gzip.decompress(blob).decode('utf-8')
    return tenhou_xml_to_actions(xml)


if __name__ == '__main__':
    import sqlite3, json
    if len(sys.argv) < 2:
        print('usage: tenhou_xml_to_actions.py <xml-or-db>')
        sys.exit(1)
    path = sys.argv[1]
    if path.endswith('.db'):
        conn = sqlite3.connect(path)
        cur = conn.cursor()
        cur.execute("SELECT id, log FROM logs WHERE is_processed=1 AND was_error=0 LIMIT 1")
        row = cur.fetchone()
        d, n = tenhou_blob_to_actions(row[1])
        print(f'log={row[0]} rounds={n} actions={len(d["detail_records"]["actions"])}')
        print(json.dumps(d, ensure_ascii=False, indent=2)[:2000])
    else:
        with open(path, encoding='utf-8') as f:
            xml = f.read()
        d, n = tenhou_xml_to_actions(xml)
        print(f'rounds={n} actions={len(d["detail_records"]["actions"])}')
        print(json.dumps(d, ensure_ascii=False, indent=2)[:2000])
