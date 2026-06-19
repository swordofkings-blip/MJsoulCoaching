# -*- coding: utf-8 -*-
"""
@title 副露ミスマッチの分類分析
@description
    273 件の副露ミスマッチ (人間スルー・AI 鳴く) を、
    鳴こうとした牌の種類で分解してカウントする。
    - 自風牌ポン
    - 場風牌ポン
    - オタ風ポン (これがあるべきではない)
    - 三元牌ポン
    - チー (序盤に多いはず)
"""
from __future__ import annotations

import argparse
import re
from collections import Counter
import json


def parse_mismatches(path: str):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]
    out = []
    for blk in blocks:
        rec = {}
        m = re.search(r'北家|東家|南家|西家|(\d+)家', blk)
        m = re.search(r'東家|南家|西家|北家', blk)
        if m:
            rec['seat_str'] = m.group(0)
        m = re.search(r'(\d+)巡目\((\d+)ツモ\)', blk)
        if m:
            rec['turn'] = int(m.group(1))
        else:
            rec['turn'] = -1
        m = re.search(r'手牌\((\d+)枚\):\s*([^\n]+)', blk)
        if m:
            rec['hand'] = m.group(2).split(',')
        m = re.search(r'点数:\s*\[([^\]]+)\]', blk)
        if m:
            try:
                rec['scores'] = [int(x.strip()) for x in m.group(1).split(',')]
            except ValueError:
                rec['scores'] = []
        if 'AI判断: 鳴くべき' in blk:
            m = re.search(r'\(([^)]+)\)', blk.split('AI判断: 鳴くべき')[1].split('\n')[0])
            if m:
                rec['meld_call'] = m.group(1)
            out.append(rec)
    return out


# extract_mismatches.CALL_NAMES と整合
CALL_NAMES = {0: 'チー', 1: 'ポン', 2: '大明槓', 3: '暗槓', 4: '加槓', 5: '抜き'}

# tile ID to honor: 27=東, 28=南, 29=西, 30=北, 31=白, 32=發, 33=中
ID_TO_HONOR_NAME = {
    27: '東', 28: '南', 29: '西', 30: '北',
    31: '白', 32: '發', 33: '中',
}

# display name -> tile id (mismatches file uses kanji)
KANJI_TO_ID = {
    '東': 27, '南': 28, '西': 29, '北': 30,
    '白': 31, '發': 32, '中': 33,
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='inp', default='tools/mismatches_tenhou_10.txt')
    p.add_argument('--out', default='meld_mismatch_breakdown.txt')
    args = p.parse_args()

    recs = parse_mismatches(args.inp)
    out = open(args.out, 'w', encoding='utf-8', newline='')
    def w(line=''):
        out.write(line + '\n')

    w(f'総副露ミスマッチ: {len(recs)} 件')

    # 副露タイプ別カウント
    by_type = Counter()
    for r in recs:
        call = r.get('meld_call', '')
        if not call:
            continue
        if 'チー' in call:
            by_type['チー'] += 1
        elif 'ポン' in call or '大明槓' in call:
            by_type['ポン/カン'] += 1
        else:
            by_type['other'] += 1
    w(f'\n副露タイプ別: {dict(by_type)}')

    # ポンの対象牌別に分類
    w('\n== ポン/カン 対象牌の分類 ==')
    pon_recs = [r for r in recs if 'ポン' in r.get('meld_call', '') or '大明槓' in r.get('meld_call', '')]
    by_target = Counter()
    by_target_and_turn = Counter()
    for r in pon_recs:
        call = r.get('meld_call', '')
        # call 例: "ポン 中 中 中" → 漢字部分を取り出す
        m = re.search(r'[チーポン大明槓暗槓加槓抜き]\s+([\u4e00-\u9fff])\s', call)
        if not m:
            continue
        target_kanji = m.group(1)
        target_id = KANJI_TO_ID.get(target_kanji)
        if target_id is None:
            continue
        # 席を判定
        seat_str = r.get('seat_str', '')
        seat_idx = {'東家': 0, '南家': 1, '西家': 2, '北家': 3}.get(seat_str, -1)
        if seat_idx < 0:
            continue
        # 自風 (ju から)
        # ju=0(東場) → 席 0 が東(27), 1 が南(28), 2 が西(29), 3 が北(30)
        # ju=1(南場) → 席 0 が南(28), 1 が西(29), 2 が北(30), 3 が東(27)
        ju = -1
        # ju の決定: 点数から推定できないので、ここでは ju=0/1/2/3 をすべて試して
        # 自風が一致しないものをオタ風候補とする
        ju_offsets = [0, 1, 2, 3]
        is_jikaze = False
        is_bakaze = False
        for ju_test in ju_offsets:
            jikaze_id = 27 + ((seat_idx - ju_test) % 4)
            bakaze_id = 27 + (ju_test % 4)
            if target_id == jikaze_id:
                is_jikaze = True
                ju = ju_test
                break
            if target_id == bakaze_id:
                is_bakaze = True
                ju = ju_test
                break
        if is_jikaze:
            kind = '自風'
        elif is_bakaze:
            kind = '場風'
        elif target_id in (31, 32, 33):
            kind = '三元牌'
        else:
            kind = 'オタ風'
        by_target[kind] += 1
        by_target_and_turn[(kind, r.get('turn', -1))] += 1
    for k, v in by_target.most_common():
        w(f'  {k}: {v}')
    w('\n  巡目別:')
    for (k, t), v in sorted(by_target_and_turn.items()):
        w(f'    {k} 巡={t}: {v}')

    # チーの巡目別
    w('\n== チーの巡目別 ==')
    chi_turn_dist = Counter()
    for r in recs:
        if 'チー' in r.get('meld_call', ''):
            chi_turn_dist[r.get('turn', -1)] += 1
    for t in sorted(chi_turn_dist.keys()):
        w(f'  {t}巡: {chi_turn_dist[t]}')

    # オタ風ポン/大明槓の最初の 5 件のサンプル
    w('\n== オタ風ポン サンプル (5件) ==')
    sample_count = 0
    for r in pon_recs:
        call = r.get('meld_call', '')
        m = re.search(r'[チーポン大明槓暗槓加槓抜き]\s+([\u4e00-\u9fff])\s', call)
        if not m:
            continue
        target_kanji = m.group(1)
        target_id = KANJI_TO_ID.get(target_kanji)
        if target_id is None or not (27 <= target_id <= 30):
            continue
        # 自風/場風かを判定
        seat_str = r.get('seat_str', '')
        seat_idx = {'東家': 0, '南家': 1, '西家': 2, '北家': 3}.get(seat_str, -1)
        if seat_idx < 0:
            continue
        ju_offsets = [0, 1, 2, 3]
        kind = '?'
        for ju_test in ju_offsets:
            jikaze_id = 27 + ((seat_idx - ju_test) % 4)
            bakaze_id = 27 + (ju_test % 4)
            if target_id == jikaze_id:
                kind = '自風'
                break
            if target_id == bakaze_id:
                kind = '場風'
                break
        if kind in ('自風', '場風'):
            continue
        sample_count += 1
        if sample_count > 5:
            break
        w(f"  巡={r.get('turn',-1)} 席={r.get('seat_str','')} 牌={target_kanji} 手牌={','.join(r.get('hand',[]))}")

    out.close()
    print(f'wrote: {args.out}')


if __name__ == '__main__':
    main()
