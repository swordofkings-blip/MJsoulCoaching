from __future__ import annotations
import sys, os
import numpy as np
import torch

_this_dir = os.path.dirname(os.path.abspath(__file__))
_parent_dir = os.path.dirname(os.path.dirname(_this_dir))
for p in [_parent_dir, os.path.join(_parent_dir, 'core')]:
    if p not in sys.path:
        sys.path.insert(0, p)

from core.game_state import GameState
from core.evaluator import Evaluator as CoachIEvaluator


class RejectionSampler:
    """Wraps a policy model with coach-I validation (and optional CFG)."""

    def __init__(self, policy_model: torch.nn.Module, params: dict = None,
                 reject_threshold: float = 400.0, max_attempts: int = 5,
                 fallback_to_coach: bool = True, legality_only: bool = False):
        self.policy = policy_model
        self.params = params or {}
        self.reject_threshold = reject_threshold
        self.max_attempts = max_attempts
        self.fallback = fallback_to_coach
        self.legality_only = legality_only

    def decide(self, state: GameState) -> tuple[str, str]:
        return self._decide(state)

    def decide_with_cfg(self, state: GameState, target_rank: int = 0,
                        guidance: float = 2.0) -> tuple[str, str]:
        c = np.zeros(4, dtype=np.float32)
        c[target_rank] = 1.0
        return self._decide(state, rank_cond=c, guidance=guidance)

    def _decide(self, state: GameState, rank_cond: np.ndarray | None = None,
                guidance: float = 1.0) -> tuple[str, str]:
        hand = list(state.my_hand)
        if not hand:
            return '', 'empty'

        from core.str_converter import tile_to_id
        legal = set(hand)

        for _ in range(self.max_attempts):
            self.policy.eval()
            with torch.no_grad():
                feat = self._encode(state)
                has_cfg = hasattr(self.policy, 'guided_forward')
                has_cond = hasattr(self.policy, 'cond_embed')

                if has_cfg and rank_cond is not None and guidance > 1.0:
                    ct = torch.from_numpy(rank_cond).float().unsqueeze(0).to(feat.device)
                    logits = self.policy.guided_forward(feat.unsqueeze(0), ct, guidance)
                elif has_cond:
                    ct = torch.from_numpy(rank_cond).float().unsqueeze(0).to(feat.device) if rank_cond is not None else None
                    logits = self.policy(feat.unsqueeze(0), cond_onehot=ct)
                elif hasattr(self.policy, 'fast_sample'):
                    logits = self.policy.fast_sample(feat.unsqueeze(0))
                else:
                    logits = self.policy(feat.unsqueeze(0))

                probs = torch.softmax(logits.squeeze(0), dim=-1).cpu().numpy()

            scores = {t: float(probs[tile_to_id(t)]) for t in legal}
            best = max(scores, key=scores.get)

            if not self.legality_only:
                cs = self._coach_score(state, best, hand)
                if cs >= self.reject_threshold:
                    return best, 'diffusion'
            else:
                return best, 'diffusion'

        if self.fallback:
            return self._coach_best(state, hand), 'coach'
        return best, 'diffusion'

    def _encode(self, state: GameState) -> torch.Tensor:
        from diffusion_ai.feature_encoder import FeatureEncoder
        f = FeatureEncoder().encode(state)
        d = next(self.policy.parameters()).device
        return torch.from_numpy(f).float().to(d)

    def _coach_score(self, state: GameState, tile: str, hand) -> float:
        try:
            return float(CoachIEvaluator(state, self.params).evaluate_tile(tile))
        except Exception:
            return 0.0

    def _coach_best(self, state: GameState, hand) -> str:
        try:
            r = CoachIEvaluator(state, self.params).best_discard(hand)
            return r if r else hand[0]
        except Exception:
            return hand[0]
