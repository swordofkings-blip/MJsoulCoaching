from __future__ import annotations
import sys
import os
from typing import List, Optional
import numpy as np

_this_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_this_dir)           # src/
_parent_dir = os.path.dirname(os.path.dirname(_src_dir))  # 雀魂ラッパー/
for p in [_parent_dir, os.path.join(_parent_dir, 'core')]:
    if p not in sys.path:
        sys.path.insert(0, p)

from str_converter import tile_to_id, is_honor

N_TILES = 34


class FeatureEncoder:
    def __init__(self, max_hand_size: int = 14):
        self.max_hand_size = max_hand_size

    def encode(self, state) -> np.ndarray:
        hand_counts = np.array(state.my_hand_counts(), dtype=np.float32)
        visible = np.array(state.all_visible_counts(), dtype=np.float32)
        visible_excl_hand = np.maximum(0, visible - hand_counts)

        own_meld_tiles = np.zeros(N_TILES, dtype=np.float32)
        for m in state.my_melds:
            for t in m.tiles:
                own_meld_tiles[tile_to_id(t)] += 1.0

        river_binary = np.zeros((4, N_TILES), dtype=np.float32)
        for seat in range(4):
            for t in state.river[seat]:
                river_binary[seat, tile_to_id(t)] = 1.0

        dora_indicators = np.zeros(N_TILES, dtype=np.float32)
        for d in state.doras:
            dora_indicators[tile_to_id(d)] += 1.0

        reach_flags = np.array([rs.is_reach for rs in state.reach_states], dtype=np.float32)

        scores = np.array(state.scores, dtype=np.float32) / 100000.0

        turn = np.array([state.tsumo_count / 100.0], dtype=np.float32)
        left_tiles = np.array([state.left_tile_count / 70.0], dtype=np.float32)

        seat_onehot = np.zeros(4, dtype=np.float32)
        seat_onehot[state.my_seat] = 1.0

        # 順位 (0=top, 3=last)
        rank_onehot = np.zeros(4, dtype=np.float32)
        rank_onehot[state.my_score_rank()] = 1.0

        # 親番
        oya_flag = np.array([1.0 if state.is_oya() else 0.0], dtype=np.float32)

        # ベン (積み棒)
        ben = np.array([state.ben / 4.0], dtype=np.float32)

        # 局数 (0-15)
        kyoku = np.array([(state.chang * 4 + state.ju) / 15.0], dtype=np.float32)

        features = np.concatenate([
            hand_counts,           # 34
            visible_excl_hand,     # 34
            own_meld_tiles,        # 34
            river_binary.flatten(),# 136
            dora_indicators,       # 34
            reach_flags,           # 4
            scores,                # 4
            rank_onehot,           # 4
            turn,                  # 1
            left_tiles,            # 1
            seat_onehot,           # 4
            oya_flag,              # 1
            ben,                   # 1
            kyoku,                 # 1
        ])
        return features

    @property
    def feature_dim(self) -> int:
        dummy = np.zeros(34, dtype=np.float32)
        return (34+34+34+136+34+4+4+4+1+1+1+4+1+1)


class LabelEncoder:
    @staticmethod
    def discard_label(hand: List[str], chosen_tile: str) -> np.ndarray:
        label = np.zeros(N_TILES, dtype=np.float32)
        chosen_id = tile_to_id(chosen_tile)
        label[chosen_id] = 1.0
        return label

    @staticmethod
    def riichi_label(is_riichi: bool) -> np.ndarray:
        return np.array([1.0 if is_riichi else 0.0], dtype=np.float32)

    @staticmethod
    def meld_label(should_meld: bool) -> np.ndarray:
        return np.array([1.0 if should_meld else 0.0], dtype=np.float32)
