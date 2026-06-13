# -*- coding: utf-8 -*-
from __future__ import annotations
import json
import os
import subprocess
import sys
from typing import List, Optional, Tuple

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState

CONTAINER_NAME = 'akochan_srv'
SETUP_JSON = '/opt/akochan/setup_mjai.json'
SYSTEM_EXE = '/opt/akochan/system.exe'
HONOR_MAP = {'1z': 'E', '2z': 'S', '3z': 'W', '4z': 'N',
             '5z': 'P', '6z': 'F', '7z': 'C'}
RED5_MAP = {'0m': '5mr', '0p': '5pr', '0s': '5sr'}
BAKAZE = ['E', 'S', 'W', 'N']

REV_HONOR = {v: k for k, v in HONOR_MAP.items()}
REV_RED5 = {v: k for k, v in RED5_MAP.items()}


def _to_us(tile: str) -> str:
    """
    @title MJAI形式から内部形式への逆変換
    @description MJAI形式の牌文字列 (例: "5mr", "E") を、内部で使われる雀魂形式 (例: "0m", "1z") に逆変換します。
    @param {str} tile - MJAI形式の牌文字列
    @returns {str} 内部形式の牌文字列
    """
    return REV_HONOR.get(tile, REV_RED5.get(tile, tile))


def _t(tile: str) -> str:
    return RED5_MAP.get(tile, HONOR_MAP.get(tile, tile))


def _start_container():
    r = subprocess.run(['docker', 'ps', '--filter', f'name={CONTAINER_NAME}',
                        '--format', '{{.Names}}'], capture_output=True, text=True, timeout=5)
    if CONTAINER_NAME in r.stdout:
        return
    subprocess.run(['docker', 'run', '-d', '--name', CONTAINER_NAME,
                    '--entrypoint', 'sleep', 'akochan-docker-app', 'infinity'],
                   capture_output=True, timeout=30)


def _stop_container():
    subprocess.run(['docker', 'rm', '-f', CONTAINER_NAME], capture_output=True, timeout=10)


def _reset_pipes():
    pass


def _build_events(state: GameState) -> List[dict]:
    events = []
    events.append({"type": "start_game", "kyoku_first": 4, "aka_flag": True})
    kn = state.chang * 4 + state.ju + 1
    events.append({
        "type": "start_kyoku", "bakaze": BAKAZE[state.chang % 4],
        "kyoku": kn, "honba": 0, "kyotaku": 0, "oya": 0,
        "dora_marker": _t(state.doras[0]) if state.doras else '1m',
        "tehais": [[_t(t) for t in hand] for hand in state.initial_hands],
        "scores": state.scores,
    })
    wall = state.wall
    for i in range(state.global_tsumo_count):
        actor = i % 4
        events.append({"type": "tsumo", "actor": actor, "pai": _t(wall[13 * 4 + i])})
        dc = sum(1 for j in range(i + 1) if j % 4 == actor)
        if dc <= len(state.river[actor]):
            events.append({
                "type": "dahai", "actor": actor,
                "pai": _t(state.river[actor][dc - 1]),
                "tsumogiri": False,
            })
    return events


def _call(state: GameState, seat: int) -> Optional[List[dict]]:
    events = _build_events(state)
    input_str = '\n'.join(json.dumps(e, ensure_ascii=False) for e in events)
    try:
        r = subprocess.run(
            ['docker', 'exec', '-i', CONTAINER_NAME, SYSTEM_EXE,
             'pipe', SETUP_JSON, str(seat)],
            input=input_str, capture_output=True, text=True, timeout=30
        )
    except subprocess.TimeoutExpired:
        return None
    if r.returncode != 0:
        return None
    lines = [l.strip() for l in r.stdout.split('\n') if l.strip()]
    if not lines:
        return None
    try:
        return json.loads(lines[-1])
    except json.JSONDecodeError:
        return None


class AkochanPlayer:
    def __init__(self, name: str):
        self.name = name
        self.seat = -1
        self._cache = {}  # key -> (discard_str, decision_list)

    def clone(self, seat: int) -> AkochanPlayer:
        p = AkochanPlayer(self.name)
        p.seat = seat
        return p

    def reset_stats(self):
        self._cache = {}

    def _call_cached(self, state: GameState) -> Optional[List[dict]]:
        if not state.wall:
            return None
        key = (state.chang, state.ju, state.global_tsumo_count)
        if key in self._cache:
            return self._cache[key]
        if not state.wall:
            self._cache[key] = None
            return None
        self._cache[key] = _call(state, self.seat)
        return self._cache[key]

    def decide_discard(self, state: GameState) -> Optional[str]:
        """
        @title 打牌の決定
        @description 現在の局面から、akochanが推奨する打牌を決定して内部形式で返します。
        @param {GameState} state - 現在のゲーム状態
        @returns {Optional[str]} 内部形式の打牌文字列、またはNone
        """
        decs = self._call_cached(state)
        if not decs:
            return None
        for d in decs:
            if d.get("type") == "dahai":
                return _to_us(d["pai"])  # 修正：MJAI形式から内部形式（0mなど）に逆変換します
        return None

    def should_riichi(self, state: GameState) -> bool:
        decs = self._call_cached(state)
        return bool(decs and any(d.get("type") == "reach" for d in decs))

    def choose_riichi_discard(self, state: GameState) -> Optional[str]:
        return self.decide_discard(state)

    def should_kan(self, state: GameState) -> bool:
        decs = self._call_cached(state)
        return bool(decs and any(d.get("type") in ("ankan", "kakan", "daiminkan") for d in decs))

    def should_tsumo(self, state: GameState) -> bool:
        decs = self._call_cached(state)
        if not decs:
            return True
        return any(d.get("type") == "hora" and d.get("actor") == self.seat for d in decs)

    def should_ron(self, state: GameState) -> bool:
        return True

    def should_call_meld(self, state: GameState, call_type: int,
                         tiles: List[str], from_seat: int) -> bool:
        decs = self._call_cached(state)
        if not decs:
            return False
        for d in decs:
            dt = d.get("type")
            if call_type == 2 and dt == "daiminkan":
                return True
            if call_type == 1 and dt == "pon":
                return True
            if call_type == 0 and dt == "chi":
                return True
        return False
