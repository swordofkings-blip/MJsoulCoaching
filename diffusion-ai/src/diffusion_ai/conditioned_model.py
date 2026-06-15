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


class SuitConv(nn.Module):
    def __init__(self, in_c: int = 4, out_c: int = 64):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_c, out_c, 3, padding=1), nn.ReLU(),
            nn.Conv1d(out_c, out_c, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )

    def forward(self, x):
        B, C, _ = x.shape
        x = x.view(B, C, 3, 9).permute(2, 0, 1, 3).reshape(3 * B, C, 9)
        return self.conv(x).view(3, B, -1).mean(dim=0)


class ConditionedMahjongNet(nn.Module):
    """Structured model + CFG conditioning on final rank."""

    def __init__(self, hidden_dim: int = 1024, num_tiles: int = 34,
                 num_conditions: int = 4, cond_dim: int = 64):
        super().__init__()
        self.num_conditions = num_conditions

        # Condition embedding
        self.cond_embed = nn.Embedding(num_conditions + 1, cond_dim)  # +1 for null/uncond
        self.cond_null_id = num_conditions  # index for unconditional

        # Feature encoders
        self.suit_enc = SuitConv(4, 64)
        self.honor_enc = nn.Sequential(
            nn.Conv1d(4, 32, 3, padding=1), nn.ReLU(),
            nn.Conv1d(32, 64, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.rsuit_enc = SuitConv(4, 64)
        self.rhonor_enc = nn.Sequential(
            nn.Conv1d(4, 32, 3, padding=1), nn.ReLU(),
            nn.Conv1d(32, 64, 3, padding=1), nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),
        )
        self.meta_net = nn.Sequential(
            nn.Linear(21, 64), nn.ReLU(), nn.Linear(64, 64), nn.ReLU(),
        )

        fusion_in = 64 * 5 + cond_dim
        self.fusion = nn.Sequential(
            nn.Linear(fusion_in, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, num_tiles),
        )

    def forward(self, x, cond_onehot=None, cond_id=None, cond_drop_prob: float = 0.0):
        """
        Args:
            x: (B, 293) or dict with tile_counts, river, meta
            cond_onehot: (B, 4) one-hot rank labels [0,1,2,3], or None
            cond_id: (B,) long tensor of class indices (alternative to cond_onehot)
            cond_drop_prob: probability to replace condition with null (for CFG)
        """
        if isinstance(x, dict):
            feat = self._encode_structured(x['tile_counts'], x['river'], x['meta'])
        else:
            feat = self._encode_flat(x)

        B = feat.shape[0]

        # Build condition embedding
        if cond_id is None and cond_onehot is not None:
            cond_id = cond_onehot.argmax(dim=-1)  # (B,)

        if cond_id is None:
            cond_emb = self.cond_embed.weight[self.cond_null_id].expand(B, -1)
        else:
            # CFG dropout: randomly replace with null
            if self.training and cond_drop_prob > 0:
                drop_mask = torch.rand(B, device=cond_id.device) < cond_drop_prob
                cond_id = cond_id.clone()
                cond_id[drop_mask] = self.cond_null_id
            cond_emb = self.cond_embed(cond_id)

        combined = torch.cat([feat, cond_emb], dim=-1)
        return self.fusion(combined)

    def _encode_structured(self, tc, river, meta):
        tok = torch.cat([
            self.suit_enc(tc[:, :, :27]),
            self.honor_enc(tc[:, :, 27:]).squeeze(-1),
            self.rsuit_enc(river[:, :, :27]),
            self.rhonor_enc(river[:, :, 27:]).squeeze(-1),
            self.meta_net(meta),
        ], dim=-1)
        return tok

    def _encode_flat(self, x):
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
        return self._encode_structured(tc, river, meta)

    @torch.no_grad()
    def guided_forward(self, x, cond_onehot, guidance_scale: float = 2.0):
        """Classifier-Free Guidance inference.
        
        score = guidance_scale * cond_logits + (1 - guidance_scale) * uncond_logits
        """
        uncond = self.forward(x, cond_id=None)
        cond = self.forward(x, cond_onehot=cond_onehot, cond_drop_prob=0.0)
        return guidance_scale * cond + (1.0 - guidance_scale) * uncond
