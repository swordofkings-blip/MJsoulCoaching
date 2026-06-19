# -*- coding: utf-8 -*-
"""
@title 人間打牌ルールの詳細分析
@description
    mismatches_tenhou_10.txt を読み、人間が字牌を切ったケースと
    中張牌を切ったケースで、シャンテン数・ドラ・手牌構成にどういう
    違いがあるかを分析する。
    人間が「字牌を切る」と判断した条件と「中張牌を切る」と判断した
    条件の差を明確にする。
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict
import sys


def parse_mismatches(path: str):
    with open(path, encoding='utf-8') as f:
        text = f.read()
    blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]
    out = []
    for blk in blocks:
        rec = {}
        m = re.search(r'(\d+)巡目\((\d+)ツモ\)', blk)
        if m:
            rec['turn'] = int(m.group(1))
        else:
            rec['turn'] = -1
        rec['is_dealer'] = '(親)' in blk
        m = re.search(r'手牌\((\d+)枚\):\s*([^\n]+)', blk)
        if m:
            rec['hand'] = m.group(2).split(',')
        else:
            rec['hand'] = []
        m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
        if m:
            rec['actual'] = m.group(1)
            rec['ai'] = m.group(2)
        m = re.search(r'ドラ:\s*([^\n]+)', blk)
        if m:
            rec['doras'] = re.findall(r'[0-9][a-zA-Z]+', m.group(1))
        else:
            rec['doras'] = []
        m = re.search(r'点数:\s*\[([^\]]+)\]', blk)
        if m:
            try:
                rec['scores'] = [int(x.strip()) for x in m.group(1).split(',')]
            except ValueError:
                rec['scores'] = []
        m = re.search(r'スコア上位:\s*([^\n]+)', blk)
        if m:
            scores = []
            for tile_s, val_s in re.findall(r'([0-9][a-zA-Z]+|[\u4e00-\u9fff])\((-?\d+(?:\.\d+)?)\)', m.group(1)):
                scores.append((tile_s, float(val_s)))
            rec['scores_top'] = scores
        out.append(rec)
    return out


_HONOR_KANJI = {
    '東': '1z', '南': '2z', '西': '3z', '北': '4z',
    '白': '5z', '發': '6z', '中': '7z',
}


def to_z(tile):
    if not tile:
        return tile
    return _HONOR_KANJI.get(tile, tile)


def is_honor(tile):
    if not tile:
        return False
    z = to_z(tile)
    return z.endswith('z')


def is_terminal_or_honor(tile):
    if is_honor(tile):
        return True
    if not tile:
        return False
    z = to_z(tile)
    n = int(z[0])
    return n in (1, 9)


def count_honor_in_hand(hand):
    return sum(1 for t in hand if is_honor(t))


def count_yaochu_in_hand(hand):
    return sum(1 for t in hand if is_terminal_or_honor(t))


def hand_breakdown(hand):
    """手牌を字牌・役牌(役)・ドラ(現物)・么九・中張に分類"""
    from collections import Counter
    cnts = Counter()
    for t in hand:
        z = to_z(t)
        if z.endswith('z'):
            cnts['honor'] += 1
            if z in ('5z', '6z', '7z'):
                cnts['yakuhai'] += 1
        elif z[0] in ('1', '9'):
            cnts['terminal'] += 1
        else:
            cnts['middle'] += 1
    return dict(cnts)


def shanten_approx(hand):
    """超概算: 4面子+1雀頭が必要。13枚なら面子=4,雀頭=1"""
    from collections import Counter
    counts = Counter()
    for t in hand:
        z = to_z(t)
        if z.endswith('z'):
            counts[27 + (int(z[1]) - 1) if len(z) > 1 and z[1].isdigit() else 0] += 1
        else:
            n = int(z[0])
            if z.endswith('m'):
                counts[n - 1] += 1
            elif z.endswith('p'):
                counts[9 + n - 1] += 1
            elif z.endswith('s'):
                counts[18 + n - 1] += 1
    return sum(min(c, 2) for c in counts.values())


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='inp', default='tools/mismatches_tenhou_10.txt')
    p.add_argument('--out', default='human_discard_analysis.txt')
    args = p.parse_args()

    recs = parse_mismatches(args.inp)
    out = open(args.out, 'w', encoding='utf-8', newline='')
    s = out

    def w(line=''):
        s.write(line + '\n')

    # 人間が「字牌を切った」「么九牌を切った」「中張を切った」ケースに分類
    human_honor = []
    human_yaochu = []
    human_middle = []
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        actual = r.get('actual')
        if not actual:
            continue
        z = to_z(actual)
        if not (re.match(r'^[0-9]+[a-zA-Z]+$', z) or is_honor(z)):
            continue
        if is_honor(z):
            human_honor.append(r)
        elif is_terminal_or_honor(z):
            human_yaochu.append(r)
        else:
            human_middle.append(r)

    w('== 人間打牌タイプ別件数 ==')
    w(f'  字牌: {len(human_honor)}')
    w(f'  么九(数牌): {len(human_yaochu)}')
    w(f'  中張: {len(human_middle)}')

    w('\n== 人間が字牌を切ったケースの手牌構成 (局形・字牌枚数・ドラ枚数) ==')
    w('turn, dealer, hand_size, honor_in_hand, yaochu_in_hand, middle_in_hand, dora_count, scores_top_actual, scores_top_actual_val')
    honor_turn_dist = Counter()
    for r in human_honor:
        bd = hand_breakdown(r.get('hand', []))
        dora_count = 0
        for t in r.get('hand', []):
            for d in r.get('doras', []):
                if to_z(t) == d:
                    dora_count += 1
        actual_z = to_z(r.get('actual'))
        actual_score = None
        for tk, sv in r.get('scores_top', []):
            if to_z(tk) == actual_z:
                actual_score = sv
                break
        honor_turn_dist[r.get('turn', -1)] += 1
        w(f"  {r.get('turn',-1)}, {r.get('is_dealer', False)}, {len(r.get('hand',[]))}, {bd.get('honor',0)}, {bd.get('terminal',0)+bd.get('honor',0)}, {bd.get('middle',0)}, {dora_count}, {r.get('actual')}, {actual_score}")
    w('\n  字牌切り: 巡目別件数')
    for t in sorted(honor_turn_dist.keys()):
        w(f'    {t}巡: {honor_turn_dist[t]}')

    w('\n== 人間が么九を切ったケース ==')
    yaochu_turn_dist = Counter()
    for r in human_yaochu:
        bd = hand_breakdown(r.get('hand', []))
        actual_z = to_z(r.get('actual'))
        yaochu_turn_dist[r.get('turn', -1)] += 1
    for t in sorted(yaochu_turn_dist.keys()):
        w(f'  {t}巡: {yaochu_turn_dist[t]}')

    w('\n== 人間が中張を切ったケース ==')
    middle_turn_dist = Counter()
    for r in human_middle:
        bd = hand_breakdown(r.get('hand', []))
        middle_turn_dist[r.get('turn', -1)] += 1
    for t in sorted(middle_turn_dist.keys()):
        w(f'  {t}巡: {middle_turn_dist[t]}')

    # AI推奨 vs 人間の差
    w('\n== AI推奨と人間打牌の組合せ (人間スルー以外) ==')
    combos = Counter()
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        ai_raw = r.get('ai')
        actual_raw = r.get('actual')
        if not ai_raw or not actual_raw:
            continue
        ai = to_z(ai_raw)
        actual = to_z(actual_raw)
        if not re.match(r'^[0-9]+[a-zA-Z]+$', ai):
            continue
        if not re.match(r'^[0-9]+[a-zA-Z]+$', actual):
            continue
        ai_type = 'honor' if is_honor(ai) else 'yaochu' if is_terminal_or_honor(ai) else 'middle'
        actual_type = 'honor' if is_honor(actual) else 'yaochu' if is_terminal_or_honor(actual) else 'middle'
        combos[(ai_type, actual_type)] += 1
    for k, v in combos.most_common():
        w(f'  AI={k[0]:8s} → 人間={k[1]:8s}: {v}')

    # 浮き字牌 (= 手牌内で ID 1-2 枚) を切ったケース
    w('\n== 「浮き字牌」(手牌内 1-2 枚) を人間が切ったケース ==')
    for r in human_honor:
        z = to_z(r['actual'])
        cnt = sum(1 for t in r.get('hand', []) if to_z(t) == z)
        if cnt <= 2:
            bd = hand_breakdown(r.get('hand', []))
            if r.get('turn', -1) <= 6 and bd.get('honor', 0) >= 3:
                dora_count = sum(1 for t in r.get('hand', []) for d in r.get('doras', []) if to_z(t) == d)
                w(f"  巡={r.get('turn'):>2} 庄={r.get('is_dealer')} 手牌内{to_z(r['actual'])}数={cnt} "
                  f"字牌={bd.get('honor',0)}枚 中張={bd.get('middle',0)}枚 ドラ={dora_count}枚 "
                  f"手牌={','.join(r.get('hand',[]))} 推奨={r.get('ai')}")

    out.close()
    print(f'wrote: {args.out}')


if __name__ == '__main__':
    main()
