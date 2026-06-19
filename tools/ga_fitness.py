# -*- coding: utf-8 -*-
"""
@title GA fitness 評価スクリプト
@description
    GA (遺伝的アルゴリズム) の 1 個体の fitness を、
    tools/_log_ids_ga.txt に列挙された固定 10 ログでの
    OurAI vs 人間打牌の一致率として計算する。

    個体 = パラメータ dict (config_parameters.json 形式)。
    このスクリプトは 1 個体を受け取り、fitness (総合一致率) を返す。

    GA ループから subprocess として呼ばれることを想定。
    python tools/ga_fitness.py <params_json> [out_json]
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


DEFAULT_GA_ID_FILE = os.path.join(THIS_DIR, '_log_ids_ga.txt')


def _worker_process_blob(args):
    log_id, blob, params = args
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0:
            return (log_id, 0, 0, 0, 0, 0, 'no_rounds')
        _lines, td, dm, tm, mm, _fname = process_dict(json_dict, params)
        return (log_id, n_rounds, td, dm, tm, mm, 'ok')
    except Exception as e:
        return (log_id, 0, 0, 0, 0, 0, f'err:{type(e).__name__}:{e}')


def _load_ids(id_file: str) -> list:
    if not os.path.exists(id_file):
        return []
    with open(id_file, encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def _load_blobs(db_path: str, ids: list) -> list:
    if not ids:
        return []
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    placeholders = ','.join('?' * len(ids))
    cur.execute(
        f'SELECT id, log FROM logs WHERE id IN ({placeholders}) '
        f'AND is_processed=1 AND was_error=0 AND num_players=4',
        ids,
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def evaluate_fitness(params: dict, id_file: str = DEFAULT_GA_ID_FILE, db_path: str = None,
                     workers: int = None, verbose: bool = False) -> dict:
    """
    @title 1 個体の fitness 評価
    @description 固定 ID リストの 10 ログに対して process_dict を実行し、
        総合一致率 (= (捨牌一致 + 副露一致) / 総数) を fitness として返す。
    @param {dict} params - 評価対象のパラメータ
    @param {str} id_file - 固定 ID リストファイル
    @param {str} db_path - 天鳳 DB パス
    @param {int} workers - 並列ワーカー数 (None なら自動)
    @param {bool} verbose - 進捗出力
    @returns {dict} {fitness, discard_total, discard_match, meld_total, meld_match, logs_ok, time}
    """
    if db_path is None:
        db_path = os.path.join(ROOT_DIR, 'diffusion-ai', 'data', 'raw', 'tenhou_logs.db')
    if workers is None:
        workers = max(1, (os.cpu_count() or 4) - 1)

    ids = _load_ids(id_file)
    if not ids:
        raise FileNotFoundError(f'No IDs in {id_file}')
    rows = _load_blobs(db_path, ids)
    if not rows:
        raise FileNotFoundError(f'No logs found for IDs in {id_file}')

    work_items = [(r[0], r[1], params) for r in rows]
    t0 = time.time()
    sum_td = 0
    sum_dm = 0
    sum_tm = 0
    sum_mm = 0
    logs_ok = 0

    with ProcessPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_worker_process_blob, item) for item in work_items]
        for fut in as_completed(futures):
            log_id, n_rounds, td, dm, tm, mm, status = fut.result()
            if status == 'ok':
                logs_ok += 1
                sum_td += td
                sum_dm += dm
                sum_tm += tm
                sum_mm += mm

    elapsed = time.time() - t0
    total = sum_td + sum_tm
    match = sum_dm + sum_mm
    fitness = match / total if total else 0.0
    return {
        'fitness': fitness,
        'discard_total': sum_td,
        'discard_match': sum_dm,
        'meld_total': sum_tm,
        'meld_match': sum_mm,
        'overall_total': total,
        'overall_match': match,
        'logs_ok': logs_ok,
        'logs_requested': len(ids),
        'elapsed_sec': elapsed,
    }


if __name__ == '__main__':
    p = argparse.ArgumentParser(description='GA fitness 評価')
    p.add_argument('params_json', help='評価対象のパラメータ JSON ファイルパス')
    p.add_argument('out_json', nargs='?', default=None, help='結果 JSON の保存先 (省略時は stdout)')
    p.add_argument('--id-file', default=DEFAULT_GA_ID_FILE)
    p.add_argument('--db', default=None)
    p.add_argument('--workers', type=int, default=None)
    p.add_argument('--verbose', action='store_true')
    args = p.parse_args()

    with open(args.params_json, encoding='utf-8') as f:
        params = json.load(f)
    result = evaluate_fitness(params, args.id_file, args.db, args.workers, args.verbose)
    if args.out_json:
        with open(args.out_json, 'w', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
