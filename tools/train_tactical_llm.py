# -*- coding: utf-8 -*-
"""
@title 戦術LLM (TacticalTransformer) 学習スクリプト
@description 前処理済みのトークンデータを用いて、PyTorchによる
              戦術決定極小Transformerモデルの学習、バリデーション、およびウェイト保存を行います。
"""
from __future__ import annotations
import json
import os
import sys
from typing import List, Optional, Tuple

import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Dataset

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.tactical_llm import TacticalTransformer, build_model

# ──────────────────────────────────────────────
# ハイパーパラメータ（ハードコード値のドキュメント化）
# ──────────────────────────────────────────────
# batch_size: メモリ制限により64。GPUが16GB以上なら128に増やして良い。
BATCH_SIZE = 64
# learning_rate: 極小Transformerには 1e-3 が安定（AdamW標準）。
LEARNING_RATE = 1e-3
# weight_decay: L2正則化相当。過学習防止用。0.01 が一般的。
WEIGHT_DECAY = 0.01
# num_epochs: 最大エポック数。early_stopping_patience で早期打ち切り。
NUM_EPOCHS = 50
# warmup_steps: 学習初期の不安定を回避するための線形ウォームアップ。
WARMUP_STEPS = 1000
# early_stopping_patience: バリデーション損失がNエポック改善しなければ停止。
EARLY_STOPPING_PATIENCE = 5
# val_split: バリデーションに割り当てる割合。
VAL_SPLIT = 0.1
# dropout: 過学習防止。d_model=64 の小さなモデルには 0.1 で十分。
DROPOUT = 0.1

# データディレクトリ
NPY_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'tokenized_npy')
MODEL_OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'models')
os.makedirs(MODEL_OUTPUT_DIR, exist_ok=True)


class TacticalUnlikelihoodLoss(nn.Module):
    """
    @title 非尤度損失（教師＋反面教師ハイブリッド）
    @description 教師サンプル(is_teacher=1)は CrossEntropy で正の学習、
                 反面教師(is_teacher=0)は Unlikelihood Loss で
                 そのモードを選ぶ確率を下げる方向に勾配を流す。
    Why: 4位や失点につながる打牌を「避けるべき行動」として学習させる。
         単純にデータを捨てるより効率的で、モデルの判断精度が向上する。
    """

    def __init__(self):
        super().__init__()
        self.ce = nn.CrossEntropyLoss(reduction='none')

    def forward(self, logits: torch.Tensor, targets: torch.Tensor,
                is_teacher: torch.Tensor) -> torch.Tensor:
        ce_loss = self.ce(logits, targets)
        probs = torch.softmax(logits, dim=-1)
        target_probs = torch.gather(probs, dim=1, index=targets.unsqueeze(1)).squeeze(1)
        # 反面教師: ターゲットクラスの確率を極小化(-log(1-p))
        unlikelihood_loss = -torch.log(1.0 - target_probs + 1e-7)
        loss = is_teacher * ce_loss + (1.0 - is_teacher) * unlikelihood_loss
        return loss.mean()


class TacticalDataset(Dataset):
    """@title numpyバッチからのデータセット読み込み（教師フラグ対応）"""

    def __init__(self, npy_dir: str, split: str = 'train', val_split: float = VAL_SPLIT):
        meta_path = os.path.join(npy_dir, 'meta.json')
        with open(meta_path, 'r', encoding='utf-8') as f:
            self.meta = json.load(f)
        self.npy_dir = npy_dir
        self.val_split = val_split
        self.split = split
        self._load_data()

    def _load_data(self):
        num_batches = self.meta['num_batches']
        all_inputs = []
        all_masks = []
        all_labels = []
        all_stats = []
        all_teacher = []

        max_width = 0
        for i in range(num_batches):
            inp = np.load(os.path.join(self.npy_dir, f'input_ids_{i:04d}.npy'), mmap_mode='r')
            max_width = max(max_width, inp.shape[1])

        pad_id = self.meta.get('pad_token_id', 0)
        for i in range(num_batches):
            inputs = np.load(os.path.join(self.npy_dir, f'input_ids_{i:04d}.npy'), mmap_mode='r')
            masks = np.load(os.path.join(self.npy_dir, f'attn_masks_{i:04d}.npy'), mmap_mode='r')
            labels = np.load(os.path.join(self.npy_dir, f'labels_{i:04d}.npy'), mmap_mode='r')
            stats = np.load(os.path.join(self.npy_dir, f'stats_{i:04d}.npy'), mmap_mode='r')
            tpath = os.path.join(self.npy_dir, f'teacher_{i:04d}.npy')
            teacher = np.load(tpath) if os.path.exists(tpath) else np.ones(len(labels))

            cur_w = inputs.shape[1]
            if cur_w < max_width:
                pad_len = max_width - cur_w
                inputs = np.pad(inputs, ((0, 0), (0, pad_len)), constant_values=pad_id)
                masks = np.pad(masks, ((0, 0), (0, pad_len)), constant_values=0)

            all_inputs.append(torch.from_numpy(inputs))
            all_masks.append(torch.from_numpy(masks))
            all_labels.append(torch.from_numpy(labels))
            all_stats.append(torch.from_numpy(stats))
            all_teacher.append(torch.from_numpy(teacher))

        inputs = torch.cat(all_inputs, dim=0)
        masks = torch.cat(all_masks, dim=0)
        labels = torch.cat(all_labels, dim=0)
        stats = torch.cat(all_stats, dim=0)
        teacher = torch.cat(all_teacher, dim=0)

        num = len(inputs)
        indices = torch.randperm(num)
        split_idx = int(num * (1 - self.val_split))

        if self.split == 'train':
            self.inputs = inputs[indices[:split_idx]]
            self.masks = masks[indices[:split_idx]]
            self.labels = labels[indices[:split_idx]]
            self.stats = stats[indices[:split_idx]]
            self.teacher = teacher[indices[:split_idx]]
        else:
            self.inputs = inputs[indices[split_idx:]]
            self.masks = masks[indices[split_idx:]]
            self.labels = labels[indices[split_idx:]]
            self.stats = stats[indices[split_idx:]]
            self.teacher = teacher[indices[split_idx:]]

    def __len__(self) -> int:
        return len(self.labels)

    def __getitem__(self, idx: int):
        return (self.inputs[idx], self.masks[idx], self.labels[idx].long(),
                self.stats[idx], self.teacher[idx])


def collate_fn(batch):
    """バッチ内で系列長が異なる場合のパディング（教師フラグ含む）"""
    input_ids = torch.stack([b[0] for b in batch], dim=1)
    attn_masks = torch.stack([b[1] for b in batch], dim=0)
    labels = torch.stack([b[2] for b in batch])
    stats = torch.stack([b[3] for b in batch])
    teacher = torch.stack([b[4] for b in batch])
    return input_ids, attn_masks, labels, stats, teacher


def train_epoch(model: nn.Module, loader: DataLoader, optimizer: optim.Optimizer,
                scheduler, criterion, device: torch.device) -> float:
    """@title 1エポックの学習（Unlikelihood Loss対応）"""
    model.train()
    total_loss = 0.0
    num_batches = 0

    for input_ids, attn_masks, labels, stats_vec, is_teacher in loader:
        input_ids = input_ids.to(device)
        attn_masks = attn_masks.to(device)
        labels = labels.to(device)
        stats_vec = stats_vec.to(device)
        is_teacher = is_teacher.to(device)

        optimizer.zero_grad()
        logits = model(input_ids, attention_mask=attn_masks, stats_features=stats_vec)
        loss = criterion(logits, labels, is_teacher)
        loss.backward()
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimizer.step()
        scheduler.step()

        total_loss += loss.item()
        num_batches += 1

    return total_loss / num_batches


def evaluate(model: nn.Module, loader: DataLoader, device: torch.device) -> Tuple[float, float]:
    """@title バリデーション評価
    @returns {(float, float)} (平均損失, 正解率)
    """
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0
    criterion = nn.CrossEntropyLoss()

    with torch.no_grad():
        for input_ids, attn_masks, labels, stats_vec, _ in loader:
            input_ids = input_ids.to(device)
            attn_masks = attn_masks.to(device)
            labels = labels.to(device)
            stats_vec = stats_vec.to(device)

            logits = model(input_ids, attention_mask=attn_masks, stats_features=stats_vec)
            loss = criterion(logits, labels)
            total_loss += loss.item()

            preds = logits.argmax(dim=-1)
            correct += (preds == labels).sum().item()
            total += labels.size(0)

    avg_loss = total_loss / len(loader)
    accuracy = correct / total if total > 0 else 0.0
    return avg_loss, accuracy


def train():
    """@title メイン学習ループ"""
    print("[train] データセット読み込み中...")
    train_dataset = TacticalDataset(NPY_DIR, split='train')
    val_dataset = TacticalDataset(NPY_DIR, split='val')

    train_loader = DataLoader(train_dataset, batch_size=BATCH_SIZE, shuffle=True,
                               collate_fn=collate_fn, num_workers=0)
    val_loader = DataLoader(val_dataset, batch_size=BATCH_SIZE, shuffle=False,
                             collate_fn=collate_fn, num_workers=0)

    if torch.cuda.is_available():
        device = torch.device('cuda')
    else:
        try:
            import torch_directml
            device = torch_directml.device()
            print(f"[train] DirectML device: {device}")
        except ImportError:
            device = torch.device('cpu')
    print(f"[train] デバイス: {device}")
    print(f"[train] 学習サンプル: {len(train_dataset)}, 検証サンプル: {len(val_dataset)}")
    print(f"[train] 語彙サイズ: {train_dataset.meta['vocab_size']}")

    n_stats = train_dataset.meta.get('num_stats_features', 21)
    model = build_model(
        vocab_size=train_dataset.meta['vocab_size'],
        num_classes=len(train_dataset.meta['mode_names']),
        dropout=DROPOUT,
        max_seq_len=train_dataset.meta['max_seq_len'],
        num_stats_features=n_stats,
    )
    # Why: DirectML (AMD GPU) は model.to(device) の後に
    #      model = model.to(device) と再代入が必要な場合がある。
    model = model.to(device)

    total_params = sum(p.numel() for p in model.parameters())
    print(f"[train] モデルパラメータ数: {total_params:,}")
    print(f"[train] スタッツ特徴量: {train_dataset.meta.get('num_stats_features', 21)}次元")
    print(f"[train] 損失関数: TacticalUnlikelihoodLoss (教師+反面教師)")

    # Why: SGD は DirectML でフルGPU動作する。AdamW は lerp が非対応で CPU フォールバックが発生する。
    optimizer = optim.SGD(model.parameters(), lr=LEARNING_RATE * 10, momentum=0.9, weight_decay=WEIGHT_DECAY)
    total_steps = len(train_loader) * NUM_EPOCHS

    def lambda_lr(step: int):
        if step < WARMUP_STEPS:
            return step / max(1, WARMUP_STEPS)
        return max(0.0, 1.0 - (step - WARMUP_STEPS) / max(1, total_steps - WARMUP_STEPS))

    scheduler = optim.lr_scheduler.LambdaLR(optimizer, lambda_lr)

    best_val_loss = float('inf')
    patience_counter = 0
    best_model_path = os.path.join(MODEL_OUTPUT_DIR, 'tactical_llm_best.pt')

    # レジューム(再開)引数の処理
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--resume', action='store_true', help='Resume from best checkpoint')
    parser.add_argument('--start-epoch', type=int, default=1, help='Epoch to start from (e.g. 10)')
    args, _ = parser.parse_known_args()

    start_epoch = 1
    if args.resume and os.path.exists(best_model_path):
        print(f"[train] チェックポイント {best_model_path} から学習を再開します。")
        try:
            state_dict = torch.load(best_model_path, map_location=device)
            model.load_state_dict(state_dict)
            start_epoch = args.start_epoch
            # スケジューラのステップを前回の分まで進める
            initial_steps = len(train_loader) * (start_epoch - 1)
            for _ in range(initial_steps):
                scheduler.step()
            print(f"[train]  ✓ 前回の進捗を復元: start_epoch={start_epoch}, steps={initial_steps}")
        except Exception as e:
            print(f"[train] チェックポイントのロードに失敗しました (最初から開始します): {e}")

    criterion = TacticalUnlikelihoodLoss()

    print("[train] 学習開始...")
    for epoch in range(1, NUM_EPOCHS + 1):
        train_loss = train_epoch(model, train_loader, optimizer, scheduler, criterion, device)
        val_loss, val_acc = evaluate(model, val_loader, device)
        lr = optimizer.param_groups[0]['lr']

        print(f"[train] epoch {epoch:2d}/{NUM_EPOCHS} | "
              f"train_loss={train_loss:.4f} | val_loss={val_loss:.4f} | "
              f"val_acc={val_acc:.4f} | lr={lr:.2e}")

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            patience_counter = 0
            torch.save(model.state_dict(), best_model_path)
            print(f"[train]  ✓ モデル保存 (val_loss={val_loss:.4f})")
        else:
            patience_counter += 1
            if patience_counter >= EARLY_STOPPING_PATIENCE:
                print(f"[train] Early stopping (patience={EARLY_STOPPING_PATIENCE})")
                break

    # 最終モデルを保存
    final_path = os.path.join(MODEL_OUTPUT_DIR, 'tactical_llm_final.pt')
    torch.save(model.state_dict(), final_path)
    print(f"[train] 完了！最良モデル: {best_model_path} (val_loss={best_val_loss:.4f})")
    print(f"[train] 最終モデル: {final_path}")


if __name__ == '__main__':
    train()
