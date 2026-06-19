# -*- coding: utf-8 -*-
"""
@title トップ5外ミスマッチの中身調査
@description
    "actual スコア欠損" 684 件 = 人間が切った牌が AI top 5 外のケース。
    具体的に「AI が何を top 5 にしていたか」「人間は何を切っていたか」を分析。
"""
from __future__ import annotations

import argparse
import re
from collections import Counter


def parse_mismatches(path: str):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]
    out = []
    for blk in blocks:
        rec = {}
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
        else:
            rec['hand'] = []
        m = re.search(r'点数:\s*\[([^\]]+)\]', blk)
        if m:
            try:
                rec['scores'] = [int(x.strip()) for x in m.group(1).split(',')]
            except ValueError:
                rec['scores'] = []
        m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
        if m:
            rec['actual'] = m.group(1)
            rec['ai'] = m.group(2)
        m = re.search(r'スコア上位:\s*([^\n]+)', blk)
        if m:
            scores = []
            for tile_s, val_s in re.findall(r'([0-9][a-zA-Z]+|[\u4e00-\u9fff])\((-?\d+(?:\.\d+)?)\)', m.group(1)):
                scores.append((tile_s, float(val_s)))
            rec['scores_top'] = scores
        else:
            rec['scores_top'] = []
        out.append(rec)
    return out


_HONOR_KANJI = {
    '東': '1z', '南': '2z', '西': '3z', '北': '4z',
    '白': '5z', '發': '6z', '中': '7z',
}


def to_z(t):
    return _HONOR_KANJI.get(t, t)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='inp', default='tools/mismatches_tenhou_10.txt')
    p.add_argument('--out', default='top5_out_analysis.txt')
    args = p.parse_args()

    recs = parse_mismatches(args.inp)
    out = open(args.out, 'w', encoding='utf-8', newline='')
    s = out
    def w(line=''):
        s.write(line + '\n')

    # actual スコア欠損: top 5 に actual がない
    top5_out = []
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        actual_raw = r.get('actual')
        if not actual_raw:
            continue
        actual = to_z(actual_raw)
        scores_top = r.get('scores_top', [])
        if not scores_top:
            continue
        # actual が top 5 にない
        top_tiles = [to_z(t) for t, _ in scores_top]
        if actual not in top_tiles:
            top5_out.append(r)

    w(f'AI top 5 外ミスマッチ総数: {len(top5_out)} 件')

    # human 牌タイプ別
    w('\n== 人間牌タイプ別 (top 5 外) ==')
    type_counter = Counter()
    for r in top5_out:
        actual = to_z(r['actual'])
        if actual.endswith('z'):
            type_counter['字牌'] += 1
        elif actual[0] in ('1', '9') and not actual.endswith('z'):
            type_counter['么九'] += 1
        else:
            type_counter['中張'] += 1
    for k, v in type_counter.most_common():
        w(f'  {k}: {v}')

    # 字牌を切ったケースの内訳
    w('\n== 字牌を切ったケース (手牌構成) ==')
    w('turn, seat, hand, ai_top5, actual')
    honor_recs = [r for r in top5_out if to_z(r['actual']).endswith('z')]
    for r in honor_recs[:30]:
        ai_top5 = ' '.join([f'{to_z(t)}({int(s)})' for t, s in r.get('scores_top', [])[:5]])
        w(f"  {r.get('turn',-1)} 巡 {r.get('seat_str','')} 人間={r['actual']} 推奨={r['ai']} top5={ai_top5}")

    out.close()
    print(f'wrote: {args.out}')


if __name__ == '__main__':
    main()
