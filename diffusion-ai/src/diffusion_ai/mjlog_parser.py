from __future__ import annotations
import re
from typing import List, Tuple

TENHOU_ID_OFFSETS = [0, 36, 72, 108]
AKA_DORA = {16: '0m', 52: '0p', 88: '0s'}
TILE_NAMES = [
    '1m','2m','3m','4m','5m','6m','7m','8m','9m',
    '1p','2p','3p','4p','5p','6p','7p','8p','9p',
    '1s','2s','3s','4s','5s','6s','7s','8s','9s',
    '1z','2z','3z','4z','5z','6z','7z',
]
DRAW_RE = re.compile(r'^([TUVW])(\d+)$')
DISCARD_RE = re.compile(r'^([DEFG])(\d+)$')
DRAW_MAP = {'T': 0, 'U': 1, 'V': 2, 'W': 3}
DISCARD_MAP = {'D': 0, 'E': 1, 'F': 2, 'G': 3}


def tenhou_to_tile_str(val: int) -> str:
    if val in AKA_DORA:
        return AKA_DORA[val]
    for si, off in enumerate(TENHOU_ID_OFFSETS):
        if val < off + 36:
            num = (val - off) // 4 + 1
            return f"{num}{'mps'[si]}" if si < 3 else f"{num}z"
    return f"?{val}"


def tenhou_tile_id(tenhou_val: int) -> int:
    """Convert Tenhou 0-135 encoding to 34-tile ID."""
    for si, off in enumerate(TENHOU_ID_OFFSETS):
        if tenhou_val < off + 36:
            return (tenhou_val - off) // 4 + (0 if si < 3 else 27)
    return 0


def decode_meld(m_val: int) -> dict:
    """Decode Tenhou mjlog <N m='...'> value.
    
    Bit layout:
      bits 0-4:  called tile value (0-135, but only 0-33 meaningful)
      bits 5-6:  source player relative to melder (0=shimo, 1=toi, 2=kami)
      bits 7-8:  meld type (0=chii, 1=pon, 2=daiminkan, 3=ankan)
      bits 9-10: for chii: position of called tile in sequence (0=left, 1=middle, 2=right)
    
    Returns dict with: type, called_tile_str, called_tile_val, source_rel, raw_type
    """
    called_val = m_val & 0x1F
    source_rel = (m_val >> 5) & 0x3
    meld_type = (m_val >> 7) & 0x3
    chi_pos = (m_val >> 9) & 0x3 if meld_type == 0 else 0

    return {
        'type': meld_type,
        'called': called_val,
        'called_str': tenhou_to_tile_str(called_val),
        'called_id': tenhou_tile_id(called_val),
        'source_rel': source_rel,
        'chi_pos': chi_pos,
    }


def build_meld_params(m_val: int, who: int) -> Tuple[int, int, List[str], List[int]]:
    """Build (type_, seat, tiles, froms) for GameState.on_chi_peng_gang.
    
    For ankan, returns (type_, seat, tile_str) for on_an_gang_add_gang.
    """
    d = decode_meld(m_val)
    caller = who
    discarder = (caller + 4 - d['source_rel']) % 4 \
        if d['type'] == 0 else (caller + d['source_rel']) % 4

    if d['type'] == 0:  # chii
        # Chii can only be called from kamicha
        discarder = (caller + 4 - 1) % 4
        ct = d['called_str']
        cid = d['called_id']
        pos = d['chi_pos']
        # Determine the 3-tile sequence
        base = (cid // 9) * 9
        off = cid % 9 - pos
        tile_a = TILE_NAMES[base + off] if 0 <= off < 7 else ct
        tile_b = TILE_NAMES[base + off + 1] if 0 <= off + 1 < 9 else ct
        tile_c = TILE_NAMES[base + off + 2] if 0 <= off + 2 < 9 else ct

        tiles = [tile_a, tile_b, tile_c]
        froms = [
            discarder if t == d['called_str'] else caller
            for t in tiles
        ]
        return (0, caller, tiles, froms)

    elif d['type'] == 1:  # pon
        tiles = [d['called_str'], d['called_str'], d['called_str']]
        froms = [discarder, caller, caller]
        return (1, caller, tiles, froms)

    elif d['type'] == 2:  # daiminkan
        tiles = [d['called_str'], d['called_str'], d['called_str'], d['called_str']]
        froms = [discarder, caller, caller, caller]
        return (2, caller, tiles, froms)

    elif d['type'] == 3:  # ankan
        return (3, caller, d['called_str'], [])

    return (-1, caller, [], [])

def parse_final_scores(root) -> list[int]:
    for tag in ['RYUUKYOKU', 'AGARI']:
        for elem in reversed(list(root)):
            if elem.tag in ('AGARI', 'RYUUKYOKU'):
                owari = elem.get('owari')
                if owari:
                    parts = owari.split(',')
                    return [int(float(parts[i])) for i in range(0, 8, 2)]
                sc = elem.get('sc')
                if sc:
                    parts = sc.split(',')
                    return [int(parts[i]) for i in range(0, 8, 2)]
    return [25000] * 4

def compute_ranks(scores: list[int]) -> list[int]:
    order = sorted(range(4), key=lambda i: -scores[i])
    ranks = [0] * 4
    for r, seat in enumerate(order):
        ranks[seat] = r
    return ranks

def build_rank_onehot(rank: int) -> list[float]:
    onehot = [0.0] * 4
    onehot[rank] = 1.0
    return onehot
