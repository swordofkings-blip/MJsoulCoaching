# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Tuple, Iterable


MANZU = 'm'
PINZU = 'p'
SOUZU = 's'
JIHAI = 'z'


_TILE_TYPE_COUNT = 34
_TILES_PER_TYPE = 4


MPS_RANGE = list(range(1, 10))
JIHAI_RANGE = list(range(1, 8))


_TILE_STR_TO_ID = {}
for i in MPS_RANGE:
    _TILE_STR_TO_ID[f'{i}{MANZU}'] = i - 1
for i in MPS_RANGE:
    _TILE_STR_TO_ID[f'{i}{PINZU}'] = 9 + (i - 1)
for i in MPS_RANGE:
    _TILE_STR_TO_ID[f'{i}{SOUZU}'] = 18 + (i - 1)
for i in JIHAI_RANGE:
    _TILE_STR_TO_ID[f'{i}{JIHAI}'] = 27 + (i - 1)


_ID_TO_TILE_STR = {v: k for k, v in _TILE_STR_TO_ID.items()}


HONOR_IDS = tuple(range(27, 34))
TERMINAL_IDS = (0, 8, 9, 17, 18, 26)
TERMINAL_AND_HONOR_IDS = set(TERMINAL_IDS) | set(HONOR_IDS)


RED_FIVE_MAP = {
    f'0{MANZU}': 4,
    f'0{PINZU}': 13,
    f'0{SOUZU}': 22,
}


def tile_to_id(tile: str) -> int:
    if tile in _TILE_STR_TO_ID:
        return _TILE_STR_TO_ID[tile]
    if tile in RED_FIVE_MAP:
        return RED_FIVE_MAP[tile]
    raise ValueError(f'Unknown tile string: {tile!r}')


def id_to_tile(tile_id: int) -> str:
    if tile_id in _ID_TO_TILE_STR:
        return _ID_TO_TILE_STR[tile_id]
    raise ValueError(f'Unknown tile id: {tile_id}')


def is_red_five(tile: str) -> bool:
    return tile in RED_FIVE_MAP


def is_honor(tile_id: int) -> bool:
    return tile_id in HONOR_IDS


def is_terminal(tile_id: int) -> bool:
    return tile_id in TERMINAL_IDS


def is_terminal_or_honor(tile_id: int) -> bool:
    return tile_id in TERMINAL_AND_HONOR_IDS


def is_yaochu(tile_id: int) -> bool:
    return is_terminal_or_honor(tile_id)


def hand_to_counts(tiles: Iterable[str]) -> List[int]:
    counts = [0] * _TILE_TYPE_COUNT
    for t in tiles:
        counts[tile_to_id(t)] += 1
    return counts


def counts_to_remaining(counts: List[int]) -> List[int]:
    return [max(0, _TILES_PER_TYPE - c) for c in counts]


def tile_id_next(tile_id: int, step: int = 1) -> int:
    if is_honor(tile_id):
        return -1
    base = (tile_id // 9) * 9
    offset = tile_id - base
    new_offset = offset + step
    if new_offset < 0 or new_offset > 8:
        return -1
    return base + new_offset


def suji_safe_tiles(tile_id: int) -> List[int]:
    if is_honor(tile_id):
        return []
    base = (tile_id // 9) * 9
    offset = tile_id - base
    candidates = []
    if offset - 3 >= 0:
        candidates.append(base + (offset - 3))
    if offset + 3 <= 8:
        candidates.append(base + (offset + 3))
    return sorted(set(candidates))


def validate_tiles(tiles: Iterable[str]) -> bool:
    for t in tiles:
        if t not in _TILE_STR_TO_ID and t not in RED_FIVE_MAP:
            return False
    return True
