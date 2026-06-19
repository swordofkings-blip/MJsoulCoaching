# -*- coding: utf-8 -*-
"""
@title ミスマッチパターンの集計
@description mismatches_tenhou_10.txt を読み、
    どの AI 推奨牌が人間に捨てられなかったかをパターン別に集計する。
    「AI は 9s を推したが人間は 3m を切った」みたいな形で、
    スコア差の大きなもの、局の巡目、親/子、字牌 vs 数牌 などを分類する。
"""
from __future__ import annotations

import argparse
import re
from collections import Counter, defaultdict


def parse_mismatches(path: str):
    """
    Returns: list of dict
        {
            'turn': int, 'is_dealer': bool,
            'hand': [...], 'actual': str, 'ai_best': str,
            'scores_top': [(tile, score), ...],
            'doras': [...], 'is_meld': bool,
        }
    """
    with open(path, encoding='utf-8') as f:
        text = f.read()
    blocks = re.split(r'={5,} 不一致 #\d+ \[[^\]]+\] ={5,}', text)[1:]
    out = []
    for blk in blocks:
        blk = blk.strip()
        if not blk:
            continue
        rec = {'is_meld': 'AI判断: 鳴くべき' in blk or '副露した' in blk,
               'is_skip': 'actual: スルーした' in blk}
        m = re.search(r'(\d+)巡目\((\d+)ツモ\)', blk)
        if m:
            rec['turn'] = int(m.group(1))
            rec['tsumo'] = int(m.group(2))
        else:
            rec['turn'] = -1
        rec['is_dealer'] = '(親)' in blk
        m = re.search(r'手牌\((\d+)枚\):\s*([^\n]+)', blk)
        if m:
            rec['hand_size'] = int(m.group(1))
            rec['hand'] = m.group(2).split(',')
        if 'actual: 副露した' in blk:
            m = re.search(r'副露した \(([^)]+)\)', blk)
            rec['actual'] = m.group(1) if m else 'meld?'
            rec['ai_best'] = None
        elif 'actual: スルーした' in blk:
            rec['actual'] = 'スルー'
            rec['ai_best'] = None
        else:
            m = re.search(r'actual:\s*(\S+)\s*\|\s*AI推奨:\s*(\S+)', blk)
            if m:
                rec['actual'] = m.group(1)
                rec['ai_best'] = m.group(2)
            else:
                rec['actual'] = None
                rec['ai_best'] = None
        m = re.search(r'スコア上位:\s*([^\n]+)', blk)
        if m:
            scores = []
            for tile_s, val_s in re.findall(r'([0-9][a-zA-Z]+)\((-?\d+(?:\.\d+)?)\)', m.group(1)):
                scores.append((tile_s, float(val_s)))
            rec['scores_top'] = scores
        m = re.search(r'ドラ:\s*([^\n]+)', blk)
        if m:
            rec['doras'] = [t for t in re.findall(r'[0-9][a-zA-Z]+', m.group(1))]
        out.append(rec)
    return out


def is_honor(tile):
    return tile.endswith('z') or tile in ('0m', '0p', '0s')  # 0m/0p/0s = 赤5 (字牌ではない)


# extract_mismatches.fmt_tile の逆マップ (字牌)
_HONOR_KANJI_TO_Z = {
    '東': '1z', '南': '2z', '西': '3z', '北': '4z',
    '白': '5z', '發': '6z', '中': '7z',
}


def to_tile_id(tile):
    """人間表示の牌(漢字含む) を正規の '1z' 形式に変換"""
    if not tile:
        return tile
    if tile in _HONOR_KANJI_TO_Z:
        return _HONOR_KANJI_TO_Z[tile]
    if re.match(r'^[0-9]+[a-zA-Z]+$', tile):
        return tile
    return tile


def is_red_five(tile):
    return tile.startswith('0')


def is_yaochu(tile):
    if is_red_five(tile):
        return False
    if tile.endswith('z'):
        return True
    n = int(tile[0])
    return n in (1, 9)


def categorize(rec):
    if rec.get('is_meld') or rec.get('is_skip'):
        return '副露判断'
    ai_raw = rec.get('ai_best')
    actual_raw = rec.get('actual')
    if not ai_raw or not actual_raw:
        return 'パース失敗'
    ai = to_tile_id(ai_raw)
    actual = to_tile_id(actual_raw)
    tile_re = re.compile(r'^[0-9]+[a-zA-Z]+$')
    if not (tile_re.match(ai) and tile_re.match(actual)):
        return 'other'
    scores_top = rec.get('scores_top', [])
    if not scores_top:
        return 'other'
    best_score = scores_top[0][1]
    actual_score = next((s for t, s in scores_top if t == actual), None)
    if actual_score is None:
        # 漢字スコアの場合の救済
        for tk, sv in scores_top:
            if to_tile_id(tk) == actual:
                actual_score = sv
                break
        if actual_score is None:
            return 'other'
    diff = best_score - actual_score
    score_bucket = '0-100' if diff < 100 else '100-300' if diff < 300 else '300-1000' if diff < 1000 else '1000+'
    return f'score_diff_{score_bucket}'


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--in', dest='inp', default='tools/mismatches_tenhou_10.txt')
    p.add_argument('--out', default=None, help='ファイル出力先(省略時はstdout)')
    args = p.parse_args()

    import io
    import contextlib
    if args.out:
        # ファイルに UTF-8 で出力
        out = open(args.out, 'w', encoding='utf-8', newline='')
        stream = out
    else:
        stream = sys.stdout

    recs = parse_mismatches(args.inp)
    print(f'Total records: {len(recs)}', file=stream)

    # "other" の内訳
    tile_re2 = re.compile(r'^[0-9]+[a-zA-Z]+$')
    other_reasons = Counter()
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        ai_raw = r.get('ai_best')
        actual_raw = r.get('actual')
        if not ai_raw or not actual_raw:
            other_reasons['牌形式でない'] += 1
            continue
        ai = to_tile_id(ai_raw)
        actual = to_tile_id(actual_raw)
        if not (tile_re2.match(ai) and tile_re2.match(actual)):
            other_reasons[f'片方のみ漢字 ai={ai!r} actual={actual!r}'] += 1
            continue
        scores_top = r.get('scores_top', [])
        if not scores_top:
            other_reasons['スコア上位なし'] += 1
            continue
        best_score = scores_top[0][1]
        # 漢字・通常両対応
        actual_score = None
        for tk, sv in scores_top:
            if tk == actual_raw or tk == actual or to_tile_id(tk) == actual:
                actual_score = sv
                break
        if actual_score is None:
            other_reasons['actual スコア欠損'] += 1
    print(f'\n== "other" 内訳 ==', file=stream)
    for k, v in other_reasons.most_common(10):
        print(f'  {k}: {v}', file=stream)

    # カテゴリ別カウント
    cat_counter = Counter(categorize(r) for r in recs)
    print('\n== カテゴリ別件数 ==', file=stream)
    for cat, n in cat_counter.most_common():
        print(f'  {cat}: {n}', file=stream)

    # スコア差ヒストグラム
    diffs = []
    for r in recs:
        scores_top = r.get('scores_top', [])
        if not scores_top:
            continue
        best = scores_top[0][1]
        actual_raw = r.get('actual')
        actual_norm = to_tile_id(actual_raw) if actual_raw else None
        actual_score = next((s for t, s in scores_top if t == actual_raw or t == actual_norm), None)
        if actual_score is None:
            continue
        diffs.append(best - actual_score)
    if diffs:
        print(f'\n== スコア差統計 ==', file=stream)
        print(f'  mean: {sum(diffs)/len(diffs):.1f}', file=stream)
        print(f'  median: {sorted(diffs)[len(diffs)//2]:.1f}', file=stream)
        print(f'  max: {max(diffs):.0f}, min: {min(diffs):.0f}', file=stream)
        print(f'  >=1000 (絶対乖離): {sum(1 for d in diffs if d >= 1000)}', file=stream)
        print(f'  100-1000 (中乖離):  {sum(1 for d in diffs if 100 <= d < 1000)}', file=stream)
        print(f'  <100 (僅差):        {sum(1 for d in diffs if d < 100)}', file=stream)

    # 巡目別
    print('\n== 巡目別ミスマッチ件数 ==', file=stream)
    turn_counter = Counter(r.get('turn', -1) for r in recs)
    for turn in sorted(turn_counter.keys()):
        print(f'  {turn}巡目: {turn_counter[turn]}', file=stream)

    # AI推奨牌タイプ (字牌 vs 数牌)
    print('\n== AI 推奨牌のタイプ ==', file=stream)
    ai_type_counter = Counter()
    tile_re = re.compile(r'^[0-9]+[a-zA-Z]+$')
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        ai_raw = r.get('ai_best')
        if not ai_raw:
            continue
        ai = to_tile_id(ai_raw)
        if not tile_re.match(ai):
            continue
        if is_honor(ai):
            ai_type_counter['字牌'] += 1
        elif is_yaochu(ai):
            ai_type_counter['么九'] += 1
        else:
            ai_type_counter['中張'] += 1
    for t, n in ai_type_counter.most_common():
        print(f'  {t}: {n}', file=stream)

    # 人間打牌のタイプ
    print('\n== 人間打牌のタイプ ==', file=stream)
    actual_type_counter = Counter()
    for r in recs:
        if r.get('is_meld') or r.get('is_skip'):
            continue
        a_raw = r.get('actual')
        if not a_raw:
            continue
        a = to_tile_id(a_raw)
        if not tile_re.match(a):
            continue
        if is_honor(a):
            actual_type_counter['字牌'] += 1
        elif is_yaochu(a):
            actual_type_counter['么九'] += 1
        else:
            actual_type_counter['中張'] += 1
    for t, n in actual_type_counter.most_common():
        print(f'  {t}: {n}', file=stream)

    # 副露判断ミスマッチ
    meld_recs = [r for r in recs if r.get('is_meld')]
    print(f'\n== 副露判断ミスマッチ ({len(meld_recs)} 件) ==', file=stream)
    skip_recs = [r for r in recs if r.get('is_skip')]
    print(f'  人間スルー・AI 鳴く: {len(meld_recs)}', file=stream)
    print(f'  人間スルー・AI スルー: {len(skip_recs)}', file=stream)

    if args.out:
        out.close()


if __name__ == '__main__':
    main()
