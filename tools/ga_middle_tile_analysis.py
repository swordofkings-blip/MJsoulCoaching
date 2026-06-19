# -*- coding: utf-8 -*-
"""
@title 中張牌ミスマッチの詳細分析
@description
    ミスマッチのうち中張牌を人間が切ったケースを集計し、
    - どのスート (萬/筒/索) か
    - 数字 (1-9)
    - 場に何枚見えてるか
    - 染め手兆候 (他家がその色を切っているか)
    を分析する。
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict


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
        # 河 (各プレイヤーの捨て牌)
        rivers = {}
        for line in blk.split('\n'):
            m = re.search(r'^\s+(自分|東|南|西|北):\s*(.+)$', line)
            if m:
                who = m.group(1)
                tiles_str = m.group(2)
                tiles = re.findall(r'[0-9][a-zA-Z]+|[\u4e00-\u9fff]', tiles_str)
                rivers[who] = tiles
        rec['rivers'] = rivers
        out.append(rec)
    return out


_HONOR_KANJI = {
    '東': '1z', '南': '2z', '西': '3z', '北': '4z',
    '白': '5z', '發': '6z', '中': '7z',
}


def to_z(t):
    return _HONOR_KANJI.get(t, t)


def parse_tile(tile):
    """'5m' → (5, 'm', 0), '0p' → (5, 'p', 1) (赤5), '1z' → (1, 'z', 0)"""
    if tile in _HONOR_KANJI:
        return (int(_HONOR_KANJI[tile][0]), 'z', 0)
    z = _HONOR_KANJI.get(tile, tile)
    n = int(z[0])
    s = z[1]
    red = 1 if z.startswith('0') else 0
    return (n, s, red)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='inp', default='tools/mismatches_tenhou_10.txt')
    p.add_argument('--out', default='middle_tile_analysis.txt')
    args = p.parse_args()

    recs = parse_mismatches(args.inp)
    out = open(args.out, 'w', encoding='utf-8', newline='')
    s = out
    def w(line=''):
        s.write(line + '\n')

    # 人間が切った中張牌を集計
    middle_discards = []
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        actual = to_z(r.get('actual', ''))
        if not actual.endswith(('m', 'p', 's')) or actual.endswith('z'):
            continue
        if actual[0] in ('1', '9'):
            continue  # 么九除く
        middle_discards.append(r)

    w(f'人間中張切り総数: {len(middle_discards)} 件')

    # スート別
    w('\n== スート別 ==')
    suit_counter = Counter()
    for r in middle_discards:
        actual = to_z(r['actual'])
        suit_counter[actual[1]] += 1
    for k, v in suit_counter.most_common():
        w(f'  {k}: {v}')

    # 数字別
    w('\n== 数字別 ==')
    num_counter = Counter()
    for r in middle_discards:
        actual = to_z(r['actual'])
        num_counter[actual[0]] += 1
    for k in sorted(num_counter.keys()):
        w(f'  {k}: {num_counter[k]}')

    # 巡目別
    w('\n== 巡目別 ==')
    turn_counter = Counter()
    for r in middle_discards:
        turn_counter[r.get('turn', -1)] += 1
    for t in sorted(turn_counter.keys()):
        w(f'  {t}巡: {turn_counter[t]}')

    # AI 推奨との差 (AI はどの牌を推していたか)
    w('\n== 中張切りの AI 推奨トップ3 ==')
    ai_top_counter = Counter()
    for r in middle_discards:
        for tile, _ in r.get('scores_top', [])[:1]:
            ai_top_counter[to_z(tile)] += 1
    for k, v in ai_top_counter.most_common(20):
        w(f'  {k}: {v}')

    # 中張切りのサンプル: 人間/AI の差が大きいもの
    w('\n== 中張切りのサンプル (スコア差 300 以上) ==')
    samples = []
    for r in middle_discards:
        scores_top = r.get('scores_top', [])
        if not scores_top:
            continue
        actual = to_z(r['actual'])
        actual_score = next((s for t, s in scores_top if to_z(t) == actual), None)
        if actual_score is None:
            continue
        best = scores_top[0]
        diff = best[1] - actual_score
        if diff >= 300:
            r['_diff'] = diff
            r['_actual_score'] = actual_score
            samples.append(r)
    w(f'  該当: {len(samples)} 件 (サンプル 20 件表示)')
    for r in samples[:20]:
        hand = ','.join(r.get('hand', []))
        rivers = ' | '.join(f'{k}={to_z(v[0]) if v else "?"}{"x"+str(len(v)) if len(v)>1 else ""}' for k, v in r.get('rivers', {}).items() if v)
        ai_top5 = ' '.join([f'{to_z(t)}({int(s)})' for t, s in r.get('scores_top', [])[:5]])
        w(f"  巡={r.get('turn',-1)} 庄={r.get('seat_str','')} 人間={r['actual']}({int(r['_actual_score'])}) "
          f"推奨={r['ai']} top5={ai_top5}")
        w(f"    手牌: {hand}")
        w(f"    河: {rivers}")

    out.close()
    print(f'wrote: {args.out}')


if __name__ == '__main__':
    main()
