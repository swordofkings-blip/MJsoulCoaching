from __future__ import annotations
import json
import os
from typing import Optional, Tuple

import numpy as np
import torch
from torch.utils.data import Dataset


class MahjongDiscardDataset(Dataset):
    def __init__(self, data_dir: str, split: str = 'train', train_ratio: float = 0.8):
        features_path = os.path.join(data_dir, 'features.npy')
        labels_path = os.path.join(data_dir, 'labels.npy')

        if not os.path.exists(features_path):
            raise FileNotFoundError(
                f"features.npy not found at {features_path}. "
                "Run scripts/build_dataset.py first."
            )

        features = np.load(features_path, mmap_mode='r')
        labels = np.load(labels_path, mmap_mode='r')

        n = len(features)
        split_idx = int(n * train_ratio)

        if split == 'train':
            self.features = torch.from_numpy(features[:split_idx].copy()).float()
            self.labels = torch.from_numpy(labels[:split_idx].copy()).float()
        elif split == 'val':
            self.features = torch.from_numpy(features[split_idx:].copy()).float()
            self.labels = torch.from_numpy(labels[split_idx:].copy()).float()
        else:
            self.features = torch.from_numpy(features.copy()).float()
            self.labels = torch.from_numpy(labels.copy()).float()

    def __len__(self) -> int:
        return len(self.features)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        return self.features[idx], self.labels[idx]


class MahjongDiscardDatasetInMemory(Dataset):
    def __init__(self, data_dir: str, split: str = 'train', train_ratio: float = 0.8,
                 use_condition: bool = False):
        import numpy as np
        features_path = os.path.join(data_dir, 'features.npy')
        labels_path = os.path.join(data_dir, 'labels.npy')

        if not os.path.exists(features_path):
            raise FileNotFoundError(
                f"features.npy not found at {features_path}. "
                "Run scripts/build_dataset.py first."
            )

        features = np.load(features_path, mmap_mode='r')
        labels = np.load(labels_path, mmap_mode='r')

        n = len(features)
        split_idx = int(n * train_ratio)

        if split == 'train':
            self.features = torch.from_numpy(features[:split_idx].copy()).float()
            self.labels = torch.from_numpy(labels[:split_idx].copy()).float()
        elif split == 'val':
            self.features = torch.from_numpy(features[split_idx:].copy()).float()
            self.labels = torch.from_numpy(labels[split_idx:].copy()).float()
        else:
            self.features = torch.from_numpy(features.copy()).float()
            self.labels = torch.from_numpy(labels.copy()).float()

        # Load conditions if available
        self.use_condition = use_condition
        cond_path = os.path.join(data_dir, 'conditions.npy')
        if use_condition and os.path.exists(cond_path):
            conds = np.load(cond_path, mmap_mode='r')
            if split == 'train':
                self.conditions = torch.from_numpy(conds[:split_idx].copy()).float()
            elif split == 'val':
                self.conditions = torch.from_numpy(conds[split_idx:].copy()).float()
            else:
                self.conditions = torch.from_numpy(conds.copy()).float()
        else:
            self.conditions = None

    def __len__(self) -> int:
        return len(self.features)

    def __getitem__(self, idx: int):
        if self.conditions is not None:
            return self.features[idx], self.labels[idx], self.conditions[idx]
        return self.features[idx], self.labels[idx]
