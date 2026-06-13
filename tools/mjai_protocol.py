# -*- coding: utf-8 -*-
"""MJAI protocol message builders (server-side)."""
from __future__ import annotations
from typing import List, Optional

HONOR_MAP = {'1z': 'E', '2z': 'S', '3z': 'W', '4z': 'N',
             '5z': 'P', '6z': 'F', '7z': 'C'}
RED5_MAP = {'0m': '5mr', '0p': '5pr', '0s': '5sr'}
BAKAZE = ['E', 'S', 'W', 'N']


def to_mjai(tile: str) -> str:
    return RED5_MAP.get(tile, HONOR_MAP.get(tile, tile))


def start_game() -> dict:
    return {"type": "start_game", "names": ["ai", "ai", "ai", "ai"]}


def start_kyoku(chang: int, ju: int, dora: str, tehais: List[List[str]],
                scores: List[int]) -> dict:
    return {
        "type": "start_kyoku",
        "bakaze": BAKAZE[chang % 4],
        "kyoku": chang * 4 + ju + 1,
        "honba": 0, "kyotaku": 0, "oya": 0,
        "dora_marker": to_mjai(dora),
        "tehais": [[to_mjai(t) for t in h] for h in tehais],
        "scores": scores,
    }


def tsumo(actor: int, pai: str, masked: bool = False) -> dict:
    return {"type": "tsumo", "actor": actor,
            "pai": (pai if not masked else "?")}


def dahai(actor: int, pai: str, tsumogiri: bool = False) -> dict:
    return {"type": "dahai", "actor": actor,
            "pai": to_mjai(pai), "tsumogiri": tsumogiri}


def reach(actor: int) -> dict:
    return {"type": "reach", "actor": actor}


def reach_accepted(actor: int, deltas: List[int], scores: List[int]) -> dict:
    return {"type": "reach_accepted", "actor": actor,
            "deltas": deltas, "scores": scores}


def dora_marker(marker: str) -> dict:
    return {"type": "dora", "dora_marker": to_mjai(marker)}


def pon(actor: int, target: int, pai: str, consumed: List[str]) -> dict:
    return {"type": "pon", "actor": actor, "target": target,
            "pai": to_mjai(pai), "consumed": [to_mjai(t) for t in consumed]}


def chi(actor: int, target: int, pai: str, consumed: List[str]) -> dict:
    return {"type": "chi", "actor": actor, "target": target,
            "pai": to_mjai(pai), "consumed": [to_mjai(t) for t in consumed]}


def daiminkan(actor: int, target: int, pai: str, consumed: List[str]) -> dict:
    return {"type": "daiminkan", "actor": actor, "target": target,
            "pai": to_mjai(pai), "consumed": [to_mjai(t) for t in consumed]}


def ankan(actor: int, consumed: List[str]) -> dict:
    return {"type": "ankan", "actor": actor,
            "consumed": [to_mjai(t) for t in consumed]}


def kakan(actor: int, pai: str, consumed: List[str]) -> dict:
    return {"type": "kakan", "actor": actor,
            "pai": to_mjai(pai), "consumed": [to_mjai(t) for t in consumed]}


def hora(actor: int, target: int, pai: str) -> dict:
    return {"type": "hora", "actor": actor, "target": target,
            "pai": to_mjai(pai)}
