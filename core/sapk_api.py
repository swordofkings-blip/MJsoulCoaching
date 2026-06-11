# -*- coding: utf-8 -*-
import time
from typing import Dict, Optional

import requests


DEFAULT_STATS = {
    "win_rate": 0.22,
    "deal_in_rate": 0.12,
    "call_rate": 0.33,
    "riichi_rate": 0.20,
    "damaten_rate": 0.15,
}

KEY_MAP = {
    "win_rate": "和牌率",
    "deal_in_rate": "放铳率",
    "call_rate": "副露率",
    "riichi_rate": "立直率",
    "damaten_rate": "默听率",
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://amae-koromo.sapk.ch/",
}


def fetch_player_stats(nickname: str) -> Dict[str, float]:
    try:
        search_url = f"https://5-data.amae-koromo.com/api/v2/pl4/search_player/{nickname}"
        resp = requests.get(search_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return dict(DEFAULT_STATS)

        players = resp.json()
        if not players:
            return dict(DEFAULT_STATS)

        player_id = players[0].get("id")
        if not player_id:
            return dict(DEFAULT_STATS)

        now_ms = int(time.time() * 1000)
        year_ago_ms = now_ms - 31536000000
        stats_url = f"https://5-data.amae-koromo.com/api/v2/pl4/player_extended_stats/{player_id}/{year_ago_ms}/{now_ms}?mode=16"
        resp = requests.get(stats_url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return dict(DEFAULT_STATS)

        data = resp.json()
        if not data:
            return dict(DEFAULT_STATS)

        return {
            "win_rate": data.get(KEY_MAP["win_rate"], DEFAULT_STATS["win_rate"]),
            "deal_in_rate": data.get(KEY_MAP["deal_in_rate"], DEFAULT_STATS["deal_in_rate"]),
            "call_rate": data.get(KEY_MAP["call_rate"], DEFAULT_STATS["call_rate"]),
            "riichi_rate": data.get(KEY_MAP["riichi_rate"], DEFAULT_STATS["riichi_rate"]),
            "damaten_rate": data.get(KEY_MAP["damaten_rate"], DEFAULT_STATS["damaten_rate"]),
        }
    except Exception:
        return dict(DEFAULT_STATS)
