#!/usr/bin/env python
from __future__ import annotations
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader
import numpy as np

from diffusion_ai.dataset import MahjongDiscardDatasetInMemory
from diffusion_ai.structured_model import StructuredMahjongNet
from diffusion_ai.transformer_model import TransformerMahjongNet

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'models')
os.makedirs(OUTPUT_DIR, exist_ok=True)


class DiscardPolicyNet(nn.Module):
    """Flat MLP baseline (286-dim → 256 → 256 → 256 → 34)."""
    def __init__(self, input_dim: int, hidden_dim: int = 256, num_tiles: int = 34):
        super().__init__()
        self.net = nn.Sequential(
            nn.Linear(input_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, hidden_dim),
            nn.ReLU(),
            nn.Linear(hidden_dim, num_tiles),
        )

    def forward(self, x):
        return self.net(x)


def get_device():
    if torch.cuda.is_available():
        return torch.device('cuda')
    try:
        import torch_directml
        if torch_directml.is_available():
            dml = torch_directml.device()
            print(f"  DirectML device: {torch_directml.device_name(0)}")
            return dml
    except ImportError:
        pass
    return torch.device('cpu')


def train(model_type: str = 'mlp', batch_size: int = 1024,
          epochs: int = 50, resume: bool = False):
    import gc
    gc.collect()
    device = get_device()
    print(f"Device: {device}")

    train_dataset = MahjongDiscardDatasetInMemory(DATA_DIR, split='train')
    val_dataset = MahjongDiscardDatasetInMemory(DATA_DIR, split='val')

    train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_dataset, batch_size=batch_size, shuffle=False)

    input_dim = train_dataset.features.shape[1]

    if model_type == 'structured':
        model = StructuredMahjongNet(hidden_dim=2048, num_tiles=34).to(device)
    elif model_type == 'transformer':
        model = TransformerMahjongNet(hidden_dim=512, num_tiles=34, nhead=8, num_layers=4).to(device)
    else:
        model = DiscardPolicyNet(input_dim, hidden_dim=2048, num_tiles=34).to(device)

    lr = 0.05 * (batch_size / 2048) ** 0.5
    optimizer = optim.SGD(model.parameters(), lr=lr, momentum=0.9, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    criterion = nn.CrossEntropyLoss()

    start_epoch = 0
    best_val_loss = float('inf')

    # Resume from checkpoint
    ckpt_path = os.path.join(OUTPUT_DIR, 'best_model.pt')
    if resume and os.path.exists(ckpt_path):
        ckpt = torch.load(ckpt_path, map_location=device)
        model.load_state_dict(ckpt['model_state_dict'])
        optimizer.load_state_dict(ckpt['optimizer_state_dict'])
        start_epoch = ckpt.get('epoch', 0) + 1
        best_val_loss = ckpt.get('val_loss', float('inf'))
        if 'scheduler_state_dict' in ckpt:
            scheduler.load_state_dict(ckpt['scheduler_state_dict'])
        print(f"Resumed from epoch {ckpt.get('epoch', 0)}")

    print(f"Model: {model.__class__.__name__} | {sum(p.numel() for p in model.parameters()):,} parameters")
    print(f"Input dim: {input_dim}, Batch: {batch_size}, LR: {lr:.5f}")
    print(f"Train: {len(train_dataset)}, Val: {len(val_dataset)}")

    for epoch in range(start_epoch, epochs):
        model.train()
        train_loss = 0.0
        train_correct = 0
        train_total = 0

        for features, labels in train_loader:
            features, labels = features.to(device), labels.to(device)
            logits = model(features)
            loss = criterion(logits, labels.argmax(dim=1))

            optimizer.zero_grad()
            loss.backward()
            optimizer.step()

            train_loss += loss.item() * features.size(0)
            preds = logits.argmax(dim=1)
            train_correct += (preds == labels.argmax(dim=1)).sum().item()
            train_total += features.size(0)

        scheduler.step()

        model.eval()
        val_loss = 0.0
        val_correct = 0
        val_total = 0
        with torch.no_grad():
            for features, labels in val_loader:
                features, labels = features.to(device), labels.to(device)
                logits = model(features)
                loss = criterion(logits, labels.argmax(dim=1))
                val_loss += loss.item() * features.size(0)
                preds = logits.argmax(dim=1)
                val_correct += (preds == labels.argmax(dim=1)).sum().item()
                val_total += features.size(0)

        train_loss /= train_total
        val_loss /= val_total
        train_acc = train_correct / train_total
        val_acc = val_correct / val_total

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            best_val_acc = val_acc
            checkpoint = {
                'epoch': epoch,
                'model_state_dict': model.state_dict(),
                'optimizer_state_dict': optimizer.state_dict(),
                'scheduler_state_dict': scheduler.state_dict(),
                'val_loss': val_loss,
                'val_acc': val_acc,
                'input_dim': input_dim,
            }
            torch.save(checkpoint, os.path.join(OUTPUT_DIR, 'best_model.pt'))

        if epoch % 5 == 0 or epoch < 5:
            print(f"  Epoch {epoch:3d} | Train loss: {train_loss:.4f} acc: {train_acc:.3f} | "
                  f"Val loss: {val_loss:.4f} acc: {val_acc:.3f}", flush=True)

    print(f"\nDone. Best model saved to {OUTPUT_DIR}/best_model.pt")
    print(f"  Best val loss: {best_val_loss:.4f}")
    print(f"  Best val accuracy: {best_val_acc:.3f}")


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--model', choices=['mlp', 'structured', 'transformer'], default='structured')
    parser.add_argument('--batch-size', type=int, default=1024)
    parser.add_argument('--epochs', type=int, default=50)
    parser.add_argument('--resume', action='store_true', help='Resume from best_model.pt')
    args = parser.parse_args()
    train(model_type=args.model, batch_size=args.batch_size,
          epochs=args.epochs, resume=args.resume)
