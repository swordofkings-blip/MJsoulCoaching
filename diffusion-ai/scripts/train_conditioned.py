#!/usr/bin/env python
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader

from diffusion_ai.dataset import MahjongDiscardDatasetInMemory
from diffusion_ai.conditioned_model import ConditionedMahjongNet

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

    ds_train = MahjongDiscardDatasetInMemory(DATA_DIR, split='train', use_condition=True)
    ds_val = MahjongDiscardDatasetInMemory(DATA_DIR, split='val', use_condition=True)

    loader_train = DataLoader(ds_train, batch_size=16384, shuffle=True)
    loader_val = DataLoader(ds_val, batch_size=16384, shuffle=False)

    model = ConditionedMahjongNet(hidden_dim=1024, num_tiles=34).to(device)
    n = sum(p.numel() for p in model.parameters())
    print(f"Model: {n:,} params, Train: {len(ds_train)}, Val: {len(ds_val)}")

    lr = 0.05
    optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=50)
    criterion = nn.CrossEntropyLoss()

    best_loss = float('inf')

    for epoch in range(50):
        model.train()
        train_loss = correct = total = 0

        for batch in loader_train:
            if len(batch) == 3:
                features, labels, conditions = batch
            else:
                features, labels = batch
                conditions = None
            features, labels = features.to(device), labels.to(device)
            if conditions is not None:
                conditions = conditions.to(device)

            logits = model(features, cond_onehot=conditions, cond_drop_prob=0.1)
            loss = criterion(logits, labels.argmax(dim=1))

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * features.size(0)
            correct += (logits.argmax(dim=1) == labels.argmax(dim=1)).sum().item()
            total += features.size(0)

        scheduler.step()

        model.eval()
        val_loss = val_correct = val_total = 0
        with torch.no_grad():
            for batch in loader_val:
                if len(batch) == 3:
                    features, labels, conditions = batch
                else:
                    features, labels = batch
                    conditions = None
                features, labels = features.to(device), labels.to(device)
                if conditions is not None:
                    conditions = conditions.to(device)

                logits = model(features, cond_onehot=conditions, cond_drop_prob=0.0)
                loss = criterion(logits, labels.argmax(dim=1))

                val_loss += loss.item() * features.size(0)
                val_correct += (logits.argmax(dim=1) == labels.argmax(dim=1)).sum().item()
                val_total += features.size(0)

        train_acc = correct / total
        val_acc = val_correct / val_total
        train_loss /= total
        val_loss /= val_total

        if val_loss < best_loss:
            best_loss = val_loss
            torch.save({
                'epoch': epoch, 'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'val_loss': val_loss, 'val_acc': val_acc,
            }, os.path.join(OUTPUT_DIR, 'best_conditioned.pt'))

        if epoch % 5 == 0 or epoch < 5:
            print(f"  Ep {epoch:3d} | Train loss: {train_loss:.4f} acc: {train_acc:.3f} | "
                  f"Val loss: {val_loss:.4f} acc: {val_acc:.3f}", flush=True)

    print(f"\nBest val loss: {best_loss:.4f}, saved to {OUTPUT_DIR}/best_conditioned.pt")


if __name__ == '__main__':
    train()
