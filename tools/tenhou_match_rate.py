# -*- coding: utf-8 -*-
"""
@title 天鳳DB一括打牌一致率測定
@description
    diffusion-ai/data/raw/tenhou_logs.db の天鳳牌譜を使って、
    OurAI の打牌/副露判断と人間の打牌/副露判断の一致率を測定する。

    内部で各ログを actions-JSON に変換し、tools/extract_mismatches.py の
    process_file() を流用してスコア集計する。並列ワーカーで高速化。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, THIS_DIR)

from tenhou_xml_to_actions import tenhou_blob_to_actions
from tenhou_process_dict import process_dict


# ------------------------------------------------------------
# worker 関数 (pickleable な module-level 関数でなければならない)
# ------------------------------------------------------------

def _worker_process_blob(args):
    """
    1つの天鳳ログ blob を受け取り、process_dict を呼んで
    (log_id, n_rounds, total_discard, discard_match,
     total_meld, meld_match, status) を返す。
    """
    log_id, blob, params = args
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0:
            return (log_id, 0, 0, 0, 0, 0, 'no_rounds')
        _lines, td, dm, tm, mm, _fname = process_dict(json_dict, params)
        return (log_id, n_rounds, td, dm, tm, mm, 'ok')
    except Exception as e:
        return (log_id, 0, 0, 0, 0, 0, f'err:{type(e).__name__}:{e}')


def _load_params():
    with open(os.path.join(ROOT_DIR, 'config', 'config_parameters.json'), encoding='utf-8') as f:
        return json.load(f)


def _query_logs(db_path: str, limit: int, offset: int, only_ok: bool, is_tonpu, id_file: str = None):
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    if id_file:
        with open(id_file, encoding='utf-8') as f:
            ids = [line.strip() for line in f if line.strip()]
        if not ids:
            conn.close()
            return []
        placeholders = ','.join('?' * len(ids))
        where = [f'id IN ({placeholders})']
        if only_ok:
            where.append('is_processed=1 AND was_error=0')
        if is_tonpu is not None:
            where.append(f'is_tonpu={1 if is_tonpu else 0}')
        where.append('num_players=4')
        where_str = ' AND '.join(where)
        sql = f'SELECT id, log FROM logs WHERE {where_str}'
        cur.execute(sql, ids)
    else:
        where = []
        if only_ok:
            where.append('is_processed=1 AND was_error=0')
        if is_tonpu is not None:
            where.append(f'is_tonpu={1 if is_tonpu else 0}')
        where.append('num_players=4')
        where_str = ' AND '.join(where)
        sql = f'SELECT id, log FROM logs WHERE {where_str} ORDER BY id LIMIT {limit} OFFSET {offset}'
        cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


# ------------------------------------------------------------
# メイン
# ------------------------------------------------------------
def main():
    p = argparse.ArgumentParser(description='天鳳DB一括一致率測定')
    p.add_argument('--db', default=os.path.join(ROOT_DIR, 'diffusion-ai', 'data', 'raw', 'tenhou_logs.db'))
    p.add_argument('--limit', type=int, default=100, help='処理するログ件数の上限')
    p.add_argument('--offset', type=int, default=0, help='スキップするログ件数')
    p.add_argument('--id-file', default=None, help='IDリストファイル(改行区切り)。指定時はlimit/offsetより優先')
    p.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 4) - 1), help='並列ワーカー数')
    p.add_argument('--tonpu', choices=['include', 'exclude', 'only'], default='exclude')
    p.add_argument('--out', default='match_rate_summary.json', help='集計結果の保存先')
    p.add_argument('--progress-every', type=int, default=5, help='進捗出力の頻度')
    args = p.parse_args()

    is_tonpu = None
    if args.tonpu == 'exclude':
        is_tonpu = 0
    elif args.tonpu == 'only':
        is_tonpu = 1

    if args.id_file:
        print(f'[setup] db={args.db} id_file={args.id_file} workers={args.workers} tonpu={args.tonpu}')
    else:
        print(f'[setup] db={args.db} limit={args.limit} offset={args.offset} workers={args.workers} tonpu={args.tonpu}')
    rows = _query_logs(args.db, args.limit, args.offset, True, is_tonpu, args.id_file)
    if not rows:
        print('[error] no logs found')
        sys.exit(1)
    total_size = sum(len(r[1]) for r in rows)
    print(f'[setup] {len(rows)} logs, total blob={total_size/1024/1024:.1f} MB')

    params = _load_params()

    work_items = [(r[0], r[1], params) for r in rows]

    t0 = time.time()
    completed = 0
    sum_rounds = 0
    sum_td = 0
    sum_dm = 0
    sum_tm = 0
    sum_mm = 0
    err_logs = []
    per_log = []

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        futures = {ex.submit(_worker_process_blob, item): item[0] for item in work_items}
        for future in as_completed(futures):
            log_id, n_rounds, td, dm, tm, mm, status = future.result()
            completed += 1
            if status == 'ok':
                sum_rounds += n_rounds
                sum_td += td
                sum_dm += dm
                sum_tm += tm
                sum_mm += mm
                per_log.append({
                    'id': log_id, 'status': 'ok', 'rounds': n_rounds,
                    'discard_total': td, 'discard_match': dm,
                    'meld_total': tm, 'meld_match': mm,
                })
            else:
                err_logs.append((log_id, status))
                per_log.append({'id': log_id, 'status': status})
            if completed % args.progress_every == 0 or completed == len(work_items):
                elapsed = time.time() - t0
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(work_items) - completed) / rate if rate > 0 else 0
                pct_d = f'{sum_dm / sum_td * 100:.1f}%' if sum_td else 'N/A'
                pct_m = f'{sum_mm / sum_tm * 100:.1f}%' if sum_tm else 'N/A'
                print(
                    f'[{completed}/{len(work_items)}] elapsed={elapsed:.1f}s '
                    f'rate={rate:.2f}/s eta={eta:.1f}s '
                    f'disc={sum_dm}/{sum_td}({pct_d}) meld={sum_mm}/{sum_tm}({pct_m})',
                    flush=True,
                )

    elapsed = time.time() - t0
    print('\n' + '=' * 40)
    print('集計')
    print('=' * 40)
    print(f'ログ件数: {len(rows)} (処理成功 {len(rows) - len(err_logs)}, エラー {len(err_logs)})')
    print(f'局数合計: {sum_rounds}')
    print(f'捨牌: {sum_dm}/{sum_td} = {sum_dm/sum_td*100:.2f}%' if sum_td else '捨牌: 0')
    print(f'副露: {sum_mm}/{sum_tm} = {sum_mm/sum_tm*100:.2f}%' if sum_tm else '副露: 0')
    total = sum_td + sum_tm
    match_total = sum_dm + sum_mm
    print(f'総合: {match_total}/{total} = {match_total/total*100:.2f}%' if total else '総合: 0')
    print(f'処理時間: {elapsed:.1f}s ({(elapsed/len(rows)):.2f}s/ログ)')

    summary = {
        'log_count': len(rows),
        'log_count_ok': len(rows) - len(err_logs),
        'log_count_error': len(err_logs),
        'errors': err_logs[:20],
        'rounds_total': sum_rounds,
        'discard_total': sum_td,
        'discard_match': sum_dm,
        'meld_total': sum_tm,
        'meld_match': sum_mm,
        'overall_total': total,
        'overall_match': match_total,
        'elapsed_sec': elapsed,
        'sec_per_log': elapsed / len(rows) if rows else 0,
        'workers': args.workers,
        'per_log': per_log,
    }
    with open(args.out, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'集計結果: {args.out}')


if __name__ == '__main__':
    main()
