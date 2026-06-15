from __future__ import annotations
import sys
import os
import numpy as np
import torch
import torch.nn as nn

_this_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_this_dir)
_parent_dir = os.path.dirname(os.path.dirname(_src_dir))
for p in [_parent_dir, os.path.join(_parent_dir, 'core')]:
    if p not in sys.path:
        sys.path.insert(0, p)

from str_converter import tile_to_id


N_TILES = 34
N_SUIT = 9
N_HONOR = 7


def _to_tensor(x, dtype=torch.float32):
    if isinstance(x, np.ndarray):
        return torch.from_numpy(x).to(dtype)
    return torch.tensor(x, dtype=dtype)


class StructuredFeatureEncoder:
    def encode(self, state) -> dict:
        """Returns a dict of structured tensors for the model."""
        hand = _to_tensor(state.my_hand_counts())
        visible = _to_tensor(state.all_visible_counts())
        visible_excl_hand = torch.clamp(visible - hand, 0)

        own_meld = torch.zeros(N_TILES)
        for m in state.my_melds:
            for t in m.tiles:
                own_meld[tile_to_id(t)] += 1

        dora = torch.zeros(N_TILES)
        for d in state.doras:
            dora[tile_to_id(d)] += 1

        # Tile counts: (4_channels, 34)
        tile_counts = torch.stack([hand, visible_excl_hand, own_meld, dora])

        # River: (4_players, 34)
        river = torch.zeros(4, N_TILES)
        for seat in range(4):
            for t in state.river[seat]:
                river[seat, tile_to_id(t)] = 1.0

        # Meta
        reach = _to_tensor([rs.is_reach for rs in state.reach_states])
        scores = _to_tensor(state.scores) / 100000.0
        turn = _to_tensor([state.tsumo_count / 100.0])
        left = _to_tensor([state.left_tile_count / 70.0])
        seat = torch.zeros(4)
        seat[state.my_seat] = 1.0
        meta = torch.cat([reach, scores, turn, left, seat])

        return {
            'tile_counts': tile_counts,  # (4, 34)
            'river': river,              # (4, 34)
            'meta': meta,                # (14,)
        }

    @property
    def dims(self):
        """Return output dimensions for model construction."""
        return {
            'tile_counts': (4, 34),
            'river': (4, 34),
            'meta': 14,
        }


class SuitBlock(nn.Module):
    """Processes 3 suits with shared weights: (batch, C, 3*9) → (batch, out)"""
    def __init__(self, in_channels: int, out_channels: int = 32):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_channels, out_channels, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.Conv1d(out_channels, out_channels, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.out = out_channels

    def forward(self, x):
        B, C, _ = x.shape
        # x: (B, C, 27) where 27 = 3 suits × 9 ranks
        x = x.view(B, C, 3, 9)
        # Share conv across suits: treat suit as batch dimension
        x = x.permute(2, 0, 1, 3)     # (3, B, C, 9)
        x = x.reshape(3 * B, C, 9)    # (3B, C, 9)
        x = self.conv(x)              # (3B, out, 1)
        x = x.view(3, B, -1)          # (3, B, out)
        x = x.mean(dim=0)             # (B, out) — average over suits
        return x


class HonorBlock(nn.Module):
    """Processes 7 honors: (batch, C, 7) → (batch, out)"""
    def __init__(self, in_channels: int, out_channels: int = 16):
        super().__init__()
        self.net = nn.Sequential(
            nn.Conv1d(in_channels, out_channels, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )

    def forward(self, x):
        return self.net(x).squeeze(-1)


class StructuredMahjongNet(nn.Module):
    def __init__(self, hidden_dim: int = 256, num_tiles: int = 34):
        super().__init__()

        # Tile counts: (4, 34) → split into suits(4,27) + honors(4,7)
        self.suit_block = SuitBlock(in_channels=4, out_channels=32)
        self.honor_conv = nn.Sequential(
            nn.Conv1d(4, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )

        # River: (4, 34) → split into suits(4,27) + honors(4,7)
        self.river_suit = SuitBlock(in_channels=4, out_channels=32)
        self.river_honor = nn.Sequential(
            nn.Conv1d(4, 16, kernel_size=3, padding=1),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )

        # Meta: (14,)
        self.meta_net = nn.Sequential(
            nn.Linear(21, 32),
            nn.ReLU(),
        )

        # Fusion
        fusion_in = 32 + 16 + 32 + 16 + 32
        self.fusion = nn.Sequential(
            nn.Linear(fusion_in, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, num_tiles),
        )

    def forward(self, x):
        # Parse input: if flat vector, split into components
        if isinstance(x, dict):
            return self._forward_structured(x)
        return self._forward_flat(x)

    def _forward_flat(self, x):
        """Convert flat feature vector to structured and forward."""
        n = x.shape[1]
        off = 0
        hand = x[:, off:off+34]; off += 34
        visible = x[:, off:off+34]; off += 34
        meld = x[:, off:off+34]; off += 34
        river = x[:, off:off+136].view(-1, 4, 34); off += 136
        dora = x[:, off:off+34]; off += 34
        reach = x[:, off:off+4]; off += 4
        scores = x[:, off:off+4]; off += 4
        rank = x[:, off:off+4]; off += 4
        turn = x[:, off:off+1]; off += 1
        left = x[:, off:off+1]; off += 1
        seat = x[:, off:off+4]; off += 4
        oya = x[:, off:off+1]; off += 1
        ben = x[:, off:off+1]; off += 1
        kyoku = x[:, off:off+1]; off += 1

        tile_counts = torch.stack([hand, visible, meld, dora], dim=1)
        meta = torch.cat([reach, scores, rank, turn, left, seat, oya, ben, kyoku], dim=1)

        return self._forward_structured({'tile_counts': tile_counts, 'river': river, 'meta': meta})

    def _forward_structured(self, s):
        tc = s['tile_counts']  # (B, 4, 34)
        rv = s['river']        # (B, 4, 34)
        mt = s['meta']         # (B, 14)

        # Tile suits: 3 suits × 9 ranks
        tc_suits = tc[:, :, :27]    # (B, 4, 27)
        tc_honors = tc[:, :, 27:]   # (B, 4, 7)
        suit_feat = self.suit_block(tc_suits)
        honor_feat = self.honor_conv(tc_honors).squeeze(-1)

        # River
        rv_suits = rv[:, :, :27]
        rv_honors = rv[:, :, 27:]
        rv_suit_feat = self.river_suit(rv_suits)
        rv_honor_feat = self.river_honor(rv_honors).squeeze(-1)

        # Meta
        meta_feat = self.meta_net(mt)

        # Fuse
        combined = torch.cat([suit_feat, honor_feat, rv_suit_feat, rv_honor_feat, meta_feat], dim=1)
        return self.fusion(combined)
