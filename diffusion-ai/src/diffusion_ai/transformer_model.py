from __future__ import annotations
import sys, os
import torch
import torch.nn as nn

_this_dir = os.path.dirname(os.path.abspath(__file__))
_src_dir = os.path.dirname(_this_dir)
_parent_dir = os.path.dirname(os.path.dirname(_src_dir))
for p in [_parent_dir, os.path.join(_parent_dir, 'core')]:
    if p not in sys.path:
        sys.path.insert(0, p)

N_TILES = 34
N_SUIT = 9
N_HONOR = 7


class SuitConv(nn.Module):
    """Shared Conv1D across 3 suits: (B, C, 27) → (B, out)."""
    def __init__(self, in_c: int, out_c: int = 32):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_c, out_c, kernel_size=3, padding=1), nn.ReLU(),
            nn.Conv1d(out_c, out_c, kernel_size=3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )

    def forward(self, x):
        B, C, _ = x.shape
        x = x.view(B, C, 3, 9).permute(2, 0, 1, 3).reshape(3 * B, C, 9)
        return self.conv(x).view(3, B, -1).mean(dim=0)


class TransformerMahjongNet(nn.Module):
    """5-token Transformer: suits, honors, river_suits, river_honors, meta."""

    def __init__(self, hidden_dim: int = 256, num_tiles: int = 34,
                 nhead: int = 4, num_layers: int = 2):
        super().__init__()
        self.suit_enc = SuitConv(4, 64)
        self.honor_enc = nn.Sequential(
            nn.Conv1d(4, 32, kernel_size=3, padding=1), nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.rsuit_enc = SuitConv(4, 64)
        self.rhonor_enc = nn.Sequential(
            nn.Conv1d(4, 32, kernel_size=3, padding=1), nn.ReLU(),
            nn.Conv1d(32, 64, kernel_size=3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.meta_net = nn.Sequential(
            nn.Linear(21, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(),
        )
        self.proj = nn.Linear(64, hidden_dim)
        enc = nn.TransformerEncoderLayer(
            hidden_dim, nhead, hidden_dim * 2, 0.1, 'relu', batch_first=True)
        self.transformer = nn.TransformerEncoder(enc, num_layers)
        self.head = nn.Sequential(
            nn.LayerNorm(hidden_dim), nn.Linear(hidden_dim, num_tiles))

    def forward(self, x):
        if isinstance(x, dict):
            return self._forward_s(x['tile_counts'], x['river'], x['meta'])
        return self._forward_f(x)

    def _forward_f(self, x):
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
        tc = torch.stack([hand, visible, meld, dora], dim=1)
        meta = torch.cat([reach, scores, rank, turn, left, seat, oya, ben, kyoku], dim=1)
        return self._forward_s(tc, river, meta)

    def _forward_s(self, tc, river, meta):
        B = tc.shape[0]
        tok = torch.stack([
            self.suit_enc(tc[:, :, :27]),
            self.honor_enc(tc[:, :, 27:]).squeeze(-1),
            self.rsuit_enc(river[:, :, :27]),
            self.rhonor_enc(river[:, :, 27:]).squeeze(-1),
            self.meta_net(meta),
        ], dim=1)  # (B, 5, 64)
        return self.head(self.transformer(self.proj(tok)).mean(dim=1))
