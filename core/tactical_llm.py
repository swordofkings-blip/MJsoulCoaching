# -*- coding: utf-8 -*-
"""
@title 戦術モード予測 Transformer
@description プレイヤーのペルソナ（スタッツ）と局面情報から適切な戦術モードを
             予測するための極小 Transformer モデル定義。

入力トークン形式:
  [Persona: ...] [Stats: ...] [Score: ...] [Shanten: ...] -> [手牌...]

出力:
  - 戦術モード (Mode.ATTACK / DEFEND / FOLD / BALANCED 等の分類)
  - または各モードへの確率ベクトル

Why: 従来の if-else ルールによるモード判定 (core/strategy_v2.py) は
     明示的で解釈性が高いが、プレイヤーの癖や打ち筋を反映できない。
     本モデルにより、牌譜データから学習したパーソナライズドな戦術選択が可能になる。
"""
from __future__ import annotations
import math
from typing import Optional

import torch
import torch.nn as nn
import torch.nn.functional as F


# デフォルトのハイパーパラメータ（ハードコード値のドキュメント化）
# d_model: 埋め込み次元。64 は極小 Transformer として十分な表現力を持つ。
# nhead: マルチヘッドアテンションのヘッド数。d_model を割り切る必要がある。
# num_layers: Transformer エンコーダの積層数。2 層で局所・大域の両方を捉える。
# dropout: 過学習防止用ドロップアウト率。0.1 は小規模データセット向け。
# max_seq_len: 最大トークン系列長。入力フォーマットの最大長を想定。
DEFAULT_D_MODEL = 64
DEFAULT_NHEAD = 4
DEFAULT_NUM_LAYERS = 2
DEFAULT_DROPOUT = 0.1
# Why: トークナイズ後の最大系列長は約189。余裕を持って256に設定。
DEFAULT_MAX_SEQ_LEN = 256
DEFAULT_NUM_CLASSES = 8  # Mode 列挙子の数
# num_stats_features: 牌譜屋準拠の21項目のプレイヤースタッツベクトル
DEFAULT_NUM_STATS = 21


class PositionalEncoding(nn.Module):
    """
    @title 位置エンコーディング
    @description Transformer に入力系列の位置情報を付与する。
                 固定正弦波 (Sinusoidal) を使用し、学習可能パラメータは持たない。
    Why: 学習可能な位置埋め込みと違い、未学習の系列長に対しても
         一貫した位置情報を提供できる。小規模データセットでは過学習リスクも低い。
    @param {int} d_model - 埋め込み次元
    @param {float} dropout - ドロップアウト率
    @param {int} max_len - 最大系列長
    """

    def __init__(self, d_model: int = DEFAULT_D_MODEL, dropout: float = DEFAULT_DROPOUT, max_len: int = DEFAULT_MAX_SEQ_LEN):
        super().__init__()
        self.dropout = nn.Dropout(p=dropout)
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0).transpose(0, 1)
        self.register_buffer('pe', pe)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        @param {Tensor} x - 形状 (seq_len, batch_size, d_model)
        @returns {Tensor} 位置情報を加算したテンソル
        """
        x = x + self.pe[:x.size(0), :]
        return self.dropout(x)


class TacticalTransformer(nn.Module):
    """
    @title 戦術モード予測 Transformer
    @description プレイヤーペルソナ + 局面情報から戦術モードを予測する極小 Transformer。
    @param {int} vocab_size - トークン語彙サイズ
    @param {int} d_model - 埋め込み次元
    @param {int} nhead - アテンションヘッド数
    @param {int} num_layers - エンコーダ層数
    @param {float} dropout - ドロップアウト率
    @param {int} max_seq_len - 最大系列長
    @param {int} num_classes - 出力クラス数（戦術モード数）
    @param {int} num_stats_features - スタッツ特徴量の数（stats_embed を使わず直接結合する場合）
    """

    def __init__(
        self,
        vocab_size: int,
        d_model: int = DEFAULT_D_MODEL,
        nhead: int = DEFAULT_NHEAD,
        num_layers: int = DEFAULT_NUM_LAYERS,
        dropout: float = DEFAULT_DROPOUT,
        max_seq_len: int = DEFAULT_MAX_SEQ_LEN,
        num_classes: int = DEFAULT_NUM_CLASSES,
        num_stats_features: int = DEFAULT_NUM_STATS,
    ):
        super().__init__()
        self.d_model = d_model
        self.token_embedding = nn.Embedding(vocab_size, d_model, padding_idx=0)
        # Why: padding_idx=0 にすることで、パディングトークンの勾配が常にゼロになり、
        # 不要な計算を削減できる。
        self.pos_encoder = PositionalEncoding(d_model, dropout, max_seq_len)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=d_model * 4,
            dropout=dropout,
            batch_first=False,
        )
        self.transformer_encoder = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        # 統計特徴量を埋め込みに射影する層
        self.stats_proj = nn.Linear(num_stats_features, d_model)
        self.layer_norm = nn.LayerNorm(d_model)
        self.classifier = nn.Linear(d_model, num_classes)

        self._init_weights()

    def _init_weights(self):
        """Xavier 一様分布で重み初期化"""
        for p in self.parameters():
            if p.dim() > 1:
                nn.init.xavier_uniform_(p)

    def forward(
        self,
        input_ids: torch.Tensor,
        stats_features: Optional[torch.Tensor] = None,
        attention_mask: Optional[torch.Tensor] = None,
    ) -> torch.Tensor:
        """
        @title 順伝搬
        @param {Tensor} input_ids - トークンID列 (seq_len, batch_size)
        @param {Tensor|None} stats_features - プレイヤースタッツ特徴量 (batch_size, num_stats_features)
        @param {Tensor|None} attention_mask - アテンションマスク (batch_size, seq_len)
        @returns {Tensor} 各モードのスコア (batch_size, num_classes)
        """
        # トークン埋め込み + 位置エンコーディング
        x = self.token_embedding(input_ids) * math.sqrt(self.d_model)
        # Why: sqrt(d_model) のスケーリングは "Attention Is All You Need" 論文に従い、
        # 埋め込みの分散を適正範囲に保つ。
        x = self.pos_encoder(x)
        # Transformer エンコーダ
        src_key_padding_mask = ~attention_mask.bool() if attention_mask is not None else None
        x = self.transformer_encoder(x, src_key_padding_mask=src_key_padding_mask)
        # 系列全体の集約: 最終層の全トークンの平均を取る
        if attention_mask is not None:
            # マスクを考慮した平均プーリング
            # mask: (batch_size, seq_len) -> (seq_len, batch_size, 1)
            mask = attention_mask.t().float().unsqueeze(-1)
            x = (x * mask).sum(dim=0) / mask.sum(dim=0).clamp(min=1)
        else:
            x = x.mean(dim=0)
        # 統計特徴量があれば結合
        if stats_features is not None:
            stats_emb = self.stats_proj(stats_features)
            x = x + stats_emb
        x = self.layer_norm(x)
        return self.classifier(x)

    def predict_mode(self, input_ids: torch.Tensor, stats_features: Optional[torch.Tensor] = None) -> int:
        """
        @title モード予測 (推論用)
        @param {Tensor} input_ids - トークンID列 (seq_len, 1)
        @param {Tensor|None} stats_features - プレイヤースタッツ (1, num_stats_features)
        @returns {int} 予測モードのクラスID
        """
        self.eval()
        with torch.no_grad():
            logits = self.forward(input_ids, stats_features)
            return logits.argmax(dim=-1).item()


def build_model(vocab_size: int, **kwargs) -> TacticalTransformer:
    """
    @title モデル構築ファクトリ
    @description デフォルト設定で TacticalTransformer を構築する。
    @param {int} vocab_size - 語彙サイズ
    @param {dict} kwargs - オーバーライドする引数
    @returns {TacticalTransformer} 構築されたモデル
    """
    return TacticalTransformer(vocab_size=vocab_size, **kwargs)
