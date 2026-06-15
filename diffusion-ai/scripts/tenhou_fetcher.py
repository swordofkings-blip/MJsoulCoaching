#!/usr/bin/env python
"""
天鳳牌譜取得スクリプト

Usage:
    python scripts/tenhou_fetcher.py fetch LOG_ID
    python scripts/tenhou_fetcher.py list-files
    python scripts/tenhou_fetcher.py download-file sca20260402.log.gz

動作確認済みエンドポイント (2026年6月時点):
  - https://tenhou.net/sc/raw/list.cgi         (直近7日間のファイル一覧)
  - https://tenhou.net/sc/raw/list.cgi?old     (今年1/1からのファイル一覧)
  - https://tenhou.net/sc/raw/dat/{filename}   (日別ログファイル .log.gz)
  - https://tenhou.net/0/log/?{log_id}         (個別牌譜 mjlog XML)

推奨ツール:
  houou-logs (https://github.com/Apricot-S/houou-logs) が上記をすべて
  カバーするMITライセンスのPythonツールとしてメンテナンスされています。
  pip install で直接インストール可能。
"""
from __future__ import annotations
import argparse
import gzip
import io
import os
import re
import sys
import time
from pathlib import Path

import requests

OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'data' / 'raw'
LOG_DIR = OUTPUT_DIR / 'tenhou_logs'
DAILY_LOG_DIR = OUTPUT_DIR / 'tenhou_daily'

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}
BASE_URL = "https://tenhou.net/sc/raw"
LOG_API = "https://tenhou.net/0/log"
DAT_URL = f"{BASE_URL}/dat"


def fetch_text(url: str, timeout: float = 15.0) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.text
    except Exception:
        pass
    return None


def fetch_binary(url: str, timeout: float = 30.0) -> bytes | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        if resp.status_code == 200:
            return resp.content
    except Exception:
        pass
    return None


def cmd_fetch_log(args):
    log_id = args.log_id
    url = f"{LOG_API}/?{log_id}"
    print(f"Fetching: {url}")
    content = fetch_text(url)
    if content and 'mjlog' in content:
        outpath = LOG_DIR / f"{log_id}.xml"
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(outpath, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"  Saved: {outpath} ({len(content)} bytes)")
    else:
        print(f"  Failed (no mjlog content in response)")


def cmd_list_files(args):
    url = f"{BASE_URL}/list.cgi"
    if args.old:
        url += "?old"
    text = fetch_text(url)
    if not text:
        print("Failed to fetch file index")
        return
    for m in re.finditer(r"file\s*:\s*'([^']+)'\s*,\s*size\s*:\s*(\d+)", text):
        print(f"  {m.group(1)}  ({int(m.group(2))/1024:.0f} KB)")


def cmd_download_file(args):
    filename = args.filename
    url = f"{DAT_URL}/{filename}"
    print(f"Downloading: {url}")
    data = fetch_binary(url)
    if not data or len(data) < 100:
        print("  Failed or empty response")
        return
    DAILY_LOG_DIR.mkdir(parents=True, exist_ok=True)
    outpath = DAILY_LOG_DIR / filename
    with open(outpath, 'wb') as f:
        f.write(data)
    print(f"  Saved: {outpath} ({len(data)} bytes)")

    if filename.endswith('.log.gz'):
        try:
            decompressed = gzip.decompress(data)
            entries = decompressed.decode('utf-8')
            log_ids = re.findall(r'[0-9]+gm[0-9a-f\-]+', entries)
            print(f"  Contained {len(log_ids)} game log IDs")
            for lid in log_ids[:5]:
                print(f"    {lid}")
            if len(log_ids) > 5:
                print(f"    ... and {len(log_ids) - 5} more")
        except Exception as e:
            print(f"  Could not parse: {e}")


def cmd_extract_ids(args):
    filename = args.filename
    filepath = DAILY_LOG_DIR / filename
    if not filepath.exists():
        print(f"File not found: {filepath}")
        return
    with open(filepath, 'rb') as f:
        decompressed = gzip.decompress(f.read())
    entries = decompressed.decode('utf-8')
    log_ids = re.findall(r'[0-9]+gm[0-9a-f\-]+', entries)
    for lid in log_ids:
        print(lid)


def cmd_list_sources(args):
    print("天鳳データソース (2026年6月 確認済):")
    print()
    print("  [1] 天鳳直近牌譜一覧")
    print("      https://tenhou.net/sc/raw/list.cgi")
    print("      (→ python scripts/tenhou_fetcher.py list-files)")
    print()
    print("  [2] 今年の牌譜一覧")
    print("      https://tenhou.net/sc/raw/list.cgi?old")
    print("      (→ python scripts/tenhou_fetcher.py list-files --old)")
    print()
    print("  [3] 日別ログファイル")
    print("      https://tenhou.net/sc/raw/dat/scaYYYYMMDD.log.gz")
    print("      (→ python scripts/tenhou_fetcher.py download-file sca20260402.log.gz)")
    print()
    print("  [4] 個別牌譜")
    print("      https://tenhou.net/0/log/?{log_id}")
    print("      (→ python scripts/tenhou_fetcher.py fetch {log_id})")
    print()
    print("  外部ツール:")
    print("  - houou-logs: https://github.com/Apricot-S/houou-logs")
    print("    pip install で導入推奨。list.cgi→日別→個別の全工程を自動化。")
    print("  - Kaggle: trongdt/japanese-mahjong-board-states")
    print("  - MahjongLM: https://github.com/MitsuhiroTaniguchi/MahjongLM")


def main():
    parser = argparse.ArgumentParser(description="天鳳牌譜取得スクリプト")
    sub = parser.add_subparsers(dest='command')

    p_fetch = sub.add_parser('fetch', help='個別牌譜をlog_id指定で取得')
    p_fetch.add_argument('log_id', type=str)

    p_list = sub.add_parser('list-files', help='list.cgi から日別ログファイル一覧を取得')
    p_list.add_argument('--old', action='store_true', help='今年1/1からの一覧')

    p_dl = sub.add_parser('download-file', help='日別ログファイルをダウンロード')
    p_dl.add_argument('filename', type=str, help='例: sca20260402.log.gz')

    p_extract = sub.add_parser('extract-ids', help='日別ログからlog_id一覧を抽出')
    p_extract.add_argument('filename', type=str)

    sub.add_parser('list-sources', help='データソース一覧')

    args = parser.parse_args()
    if args.command == 'fetch':
        cmd_fetch_log(args)
    elif args.command == 'list-files':
        cmd_list_files(args)
    elif args.command == 'download-file':
        cmd_download_file(args)
    elif args.command == 'extract-ids':
        cmd_extract_ids(args)
    elif args.command == 'list-sources':
        cmd_list_sources(args)
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
