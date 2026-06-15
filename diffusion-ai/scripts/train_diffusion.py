#!/usr/bin/env python
from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

from diffusion_ai.dataset import MahjongDiscardDatasetInMemory
from diffusion_ai.diffusion_policy import DiffusionPolicy

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def get_device():
    if torch.cuda.is_available():
        return torch.device('cuda')
    try:
        import torch_directml
        if torch_directml.is_available():
            print(f"  DirectML: {torch_directml.device_name(0)}")
            return torch_directml.device()
    except ImportError:
        pass
    return torch.device('cpu')


def train():
    device = get_device()
    print(f"Device: {device}")

    ds_train = MahjongDiscardDatasetInMemory(DATA_DIR, split='train')
    ds_val = MahjongDiscardDatasetInMemory(DATA_DIR, split='val')

    loader_train = DataLoader(ds_train, batch_size=1024, shuffle=True)
    loader_val = DataLoader(ds_val, batch_size=1024, shuffle=False)

    input_dim = ds_train.features.shape[1]
    print(f"Input dim: {input_dim}, Train: {len(ds_train)}, Val: {len(ds_val)}")

    model = DiffusionPolicy(state_dim=input_dim, num_classes=34, timesteps=100).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    print(f"Model: DiffusionPolicy | {n_params:,} parameters")

    optimizer = optim.SGD(model.denoiser.parameters(), lr=0.05, momentum=0.9, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=50)

    best_loss = float('inf')

    for epoch in range(50):
        model.train()
        train_loss = 0.0
        n_train = 0

        for features, labels in loader_train:
            features, labels = features.to(device), labels.to(device)
            loss = model.loss(features, labels)

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * features.size(0)
            n_train += features.size(0)

        scheduler.step()

        model.eval()
        val_correct = 0
        val_total = 0
        val_loss = 0.0
        with torch.no_grad():
            for features, labels in loader_val:
                features, labels = features.to(device), labels.to(device)
                loss = model.loss(features, labels)
                val_loss += loss.item() * features.size(0)

                # Fast sampling for accuracy
                pred = model.fast_sample(features, steps=10)
                val_correct += (pred.argmax(dim=-1) == labels.argmax(dim=-1)).sum().item()
                val_total += features.size(0)

        train_loss /= n_train
        val_loss /= val_total
        val_acc = val_correct / val_total

        if val_loss < best_loss:
            best_loss = val_loss
            torch.save({
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'val_loss': val_loss,
                'val_acc': val_acc,
            }, os.path.join(OUTPUT_DIR, 'best_diffusion.pt'))

        if epoch % 5 == 0 or epoch < 5:
            print(f"  Epoch {epoch:3d} | Train loss: {train_loss:.4f} | "
                  f"Val loss: {val_loss:.4f} acc: {val_acc:.3f}", flush=True)

    print(f"\nDone. Best val loss: {best_loss:.4f}")


if __name__ == '__main__':
    train()
