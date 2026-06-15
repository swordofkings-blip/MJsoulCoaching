from __future__ import annotations
import math
import torch
import torch.nn as nn


def cosine_beta_schedule(timesteps: int, s: float = 0.008) -> torch.Tensor:
    steps = timesteps + 1
    x = torch.linspace(0, timesteps, steps, dtype=torch.float32)
    ac = torch.cos(((x / timesteps) + s) / (1 + s) * math.pi * 0.5) ** 2
    ac = ac / ac[0]
    return torch.clamp(1 - (ac[1:] / ac[:-1]), max=0.999)


class D3PMProcess:
    def __init__(self, num_classes: int = 34, timesteps: int = 100, schedule: str = 'cosine'):
        self.K = num_classes
        self.T = timesteps
        betas = cosine_beta_schedule(timesteps) if schedule == 'cosine' \
            else torch.linspace(1e-4, 0.02, timesteps, dtype=torch.float32)
        self.betas = betas
        self.alphas = 1 - betas
        self.alpha_bar = torch.cumprod(self.alphas, dim=0)
        self.Q_bar = self._compute_Q_bar()

    def _compute_Q_bar(self) -> torch.Tensor:
        K, T = self.K, self.T
        eye = torch.eye(K, dtype=torch.float32)
        ones = torch.ones(K, K, dtype=torch.float32) / K
        Q_bar = torch.zeros(T + 1, K, K, dtype=torch.float32)
        Q_bar[0] = eye
        for t in range(1, T + 1):
            a = self.alpha_bar[t - 1]
            Q_bar[t] = a * eye + (1 - a) * ones
        return Q_bar

    def to(self, device):
        self.Q_bar = self.Q_bar.to(device)
        self.betas = self.betas.to(device)
        self.alphas = self.alphas.to(device)
        self.alpha_bar = self.alpha_bar.to(device)
        return self

    def q_sample(self, z_0: torch.Tensor, t: torch.Tensor) -> torch.Tensor:
        Q_t = self.Q_bar[t.clamp(0, self.T)]
        return torch.bmm(z_0.unsqueeze(1).float(), Q_t).squeeze(1)

    def q_posterior_logits(self, z_t: torch.Tensor, z_0_hat: torch.Tensor,
                           t: torch.Tensor) -> torch.Tensor:
        idx = t.clamp(1, self.T)
        Q_t = self.Q_bar[idx]
        Q_tm1 = self.Q_bar[idx - 1]
        num = torch.bmm(z_t.unsqueeze(1).float(), Q_t).squeeze(1) * \
              torch.bmm(z_0_hat.unsqueeze(1).float(), Q_tm1).squeeze(1)
        return num / num.sum(dim=-1, keepdim=True).clamp(min=1e-8)


class TimeEmbedding(nn.Module):
    def __init__(self, dim: int = 32):
        super().__init__()
        half = dim // 2
        freq = torch.exp(-math.log(10000) * torch.arange(half) / (half - 1))
        self.register_buffer('freq', freq)
        self.net = nn.Sequential(nn.Linear(dim, dim * 2), nn.SiLU(), nn.Linear(dim * 2, dim))

    def forward(self, t: torch.Tensor) -> torch.Tensor:
        emb = t.unsqueeze(-1).float() * self.freq.unsqueeze(0)
        emb = torch.cat([torch.sin(emb), torch.cos(emb)], dim=-1)
        return self.net(emb)


class DenoiserNet(nn.Module):
    def __init__(self, state_dim: int = 293, num_classes: int = 34,
                 hidden_dim: int = 512, time_dim: int = 32):
        super().__init__()
        self.time_embed = TimeEmbedding(time_dim)
        self.net = nn.Sequential(
            nn.Linear(state_dim + num_classes + time_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim), nn.ReLU(),
            nn.Linear(hidden_dim, num_classes),
        )

    def forward(self, state: torch.Tensor, noisy: torch.Tensor,
                t: torch.Tensor) -> torch.Tensor:
        return self.net(torch.cat([state, noisy, self.time_embed(t)], dim=-1))


class DiffusionPolicy(nn.Module):
    def __init__(self, state_dim: int = 293, num_classes: int = 34, timesteps: int = 100):
        super().__init__()
        self.K = num_classes
        self.T = timesteps
        self.process = D3PMProcess(num_classes, timesteps)
        self.denoiser = DenoiserNet(state_dim, num_classes)

    @property
    def device(self) -> torch.device:
        return next(self.denoiser.parameters()).device

    def forward(self, state: torch.Tensor) -> torch.Tensor:
        return self.fast_sample(state, steps=10)

    def loss(self, state: torch.Tensor, action: torch.Tensor) -> torch.Tensor:
        self.process.to(self.device)
        B = state.shape[0]
        t = torch.randint(1, self.T + 1, (B,), device=self.device)
        noisy = self.process.q_sample(action.float(), t)
        pred = self.denoiser(state, noisy, t)
        return nn.functional.cross_entropy(pred, action.argmax(dim=-1))

    @torch.no_grad()
    def fast_sample(self, state: torch.Tensor, steps: int = 10) -> torch.Tensor:
        self.process.to(self.device)
        B = state.shape[0]
        z = torch.full((B, self.K), 1.0 / self.K, dtype=torch.float32, device=self.device)
        stride = max(1, self.T // steps)
        for t_i in reversed(range(stride, self.T + 1, stride)):
            t_b = torch.full((B,), t_i, dtype=torch.long, device=self.device)
            pred = torch.softmax(self.denoiser(state, z, t_b), dim=-1)
            if t_i > 1:
                z = self.process.q_posterior_logits(z, pred, t_b)
        return pred

    @torch.no_grad()
    def full_sample(self, state: torch.Tensor) -> torch.Tensor:
        self.process.to(self.device)
        B = state.shape[0]
        z = torch.full((B, self.K), 1.0 / self.K, dtype=torch.float32, device=self.device)
        for t_i in range(self.T, 0, -1):
            t_b = torch.full((B,), t_i, dtype=torch.long, device=self.device)
            pred = torch.softmax(self.denoiser(state, z, t_b), dim=-1)
            if t_i > 1:
                z = self.process.q_posterior_logits(z, pred, t_b)
        return pred
