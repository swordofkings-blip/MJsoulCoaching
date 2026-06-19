# -*- coding: utf-8 -*-
"""
@title Best params での天鳳 10 ログミスマッチ分析
@description
    GA で見つかった best params を 10 ログに適用し、
    tools/extract_mismatches.py の process_file で全ミスマッチを
    mismatches_tenhou_10.txt に出力する。
    ミスマッチパターンを観察して、ルール追加や GA パラメータ拡張のヒントにする。
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, THIS_DIR)

from tools.ga_tune import expand_params
from tools.ga_fitness import _load_ids, _load_blobs
from tools.extract_mismatches import process_file


DEFAULT_GA_ID_FILE = os.path.join(THIS_DIR, '_log_ids_ga.txt')
STATE_FILE = os.path.join(THIS_DIR, 'ga_tenhou_state.json')
DB_PATH = os.path.join(ROOT_DIR, 'diffusion-ai', 'data', 'raw', 'tenhou_logs.db')
MISMATCH_FILE = os.path.join(THIS_DIR, 'mismatches_tenhou_10.txt')
SUMMARY_FILE = os.path.join(THIS_DIR, 'mismatches_tenhou_10_summary.json')


def process_one(args):
    log_id, blob, params, tmp_path = args
    try:
        from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0:
            return (log_id, 0, 0, 0, 0, 0, [], 'no_rounds')
        import tempfile
        if tmp_path is None:
            tmpdir = tempfile.mkdtemp(prefix='mm_')
            tmp_path = os.path.join(tmpdir, f'{log_id}.json')
        with open(tmp_path, 'w', encoding='utf-8') as f:
            json.dump(json_dict, f, ensure_ascii=False)
        lines, td, dm, tm, mm, fname = process_file(tmp_path, params)
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        return (log_id, n_rounds, td, dm, tm, mm, lines, 'ok')
    except Exception as e:
        return (log_id, 0, 0, 0, 0, 0, [], f'err:{type(e).__name__}:{e}')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--state', default=STATE_FILE)
    p.add_argument('--id-file', default=DEFAULT_GA_ID_FILE)
    p.add_argument('--db', default=DB_PATH)
    p.add_argument('--out', default=MISMATCH_FILE)
    p.add_argument('--summary', default=SUMMARY_FILE)
    p.add_argument('--workers', type=int, default=max(1, (os.cpu_count() or 4) - 1))
    p.add_argument('--top-params', type=int, default=1, help='上位 N 個体を解析 (default: 最良 1 個体)')
    args = p.parse_args()

    with open(args.state, encoding='utf-8') as f:
        state = json.load(f)
    with open(os.path.join(ROOT_DIR, 'config', 'config_parameters.json'), encoding='utf-8') as f:
        base_params = json.load(f)

    top_individuals = state['pop'][:args.top_params]
    print(f'[mismatch] analyzing top {args.top_params} individuals on '
          f'{len(_load_ids(args.id_file))} logs')

    rows = _load_blobs(args.db, _load_ids(args.id_file))
    all_lines = []
    summary = {'individuals': []}

    for idx, ind in enumerate(top_individuals):
        flat = ind['flat']
        expanded = expand_params(flat, base_params)
        ga_fitness = ind.get('fitness')
        print(f'\n[ind {idx}] GA fitness={ga_fitness*100:.2f}%')
        work_items = [(r[0], r[1], expanded, None) for r in rows]
        t0 = time.time()
        with ProcessPoolExecutor(max_workers=args.workers) as ex:
            futures = [ex.submit(process_one, item) for item in work_items]
            for fut in as_completed(futures):
                log_id, n_rounds, td, dm, tm, mm, lines, status = fut.result()
                if status == 'ok':
                    print(f'  {log_id}: rounds={n_rounds} disc={dm}/{td} meld={mm}/{tm} mismatches={len(lines)//15}')
                    all_lines.extend([f'===== {log_id} (ind {idx}) ====='] + lines)
        elapsed = time.time() - t0
        ind_summary = {
            'fitness_ga': ga_fitness,
            'mismatch_count': len([l for l in all_lines if '=====' in l]),
            'elapsed_sec': elapsed,
        }
        summary['individuals'].append(ind_summary)

    with open(args.out, 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_lines))
    with open(args.summary, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    print(f'\n[mismatch] wrote {args.out}')
    print(f'[mismatch] wrote {args.summary}')


if __name__ == '__main__':
    main()
