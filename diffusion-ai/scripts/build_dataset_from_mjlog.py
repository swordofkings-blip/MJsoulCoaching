#!/usr/bin/env python
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.game_state import GameState
from core.str_converter import tile_to_id
from diffusion_ai.feature_encoder import FeatureEncoder, LabelEncoder
from diffusion_ai.mjlog_parser import (
    DRAW_RE, DISCARD_RE, DRAW_MAP, DISCARD_MAP,
    tenhou_to_tile_str, decode_meld, build_meld_params,
    parse_final_scores, compute_ranks, build_rank_onehot,
)

OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'data' / 'processed'
MELD_OUTPUT_DIR = Path(__file__).resolve().parent.parent / 'data' / 'processed_meld'


def generate_meld_candidates(hand, tile, is_kamicha):
    """Generate possible meld candidates. Mirrors extract_mismatches.py."""
    from collections import Counter
    import itertools
    candidates = []
    tid = tile_to_id(tile)
    hand_counts = Counter(hand)
    hand_by_id = {}
    for h in hand:
        htid = tile_to_id(h)
        hand_by_id.setdefault(htid, [])
        if h not in hand_by_id[htid]:
            hand_by_id[htid].append(h)
    target_count = sum(hand_counts[h] for h in hand_by_id.get(tid, []))
    if target_count >= 2:
        for c in hand_by_id.get(tid, []):
            if hand_counts[c] >= 2:
                candidates.append((1, [tile, c, c]))
        if len(hand_by_id.get(tid, [])) >= 2:
            for c1, c2 in itertools.combinations(hand_by_id[tid], 2):
                candidates.append((1, [tile, c1, c2]))
    if target_count == 3:
        for c in hand_by_id.get(tid, []):
            if hand_counts[c] >= 3:
                candidates.append((2, [tile, c, c, c]))
    if is_kamicha and tid < 27:
        for off1, off2 in [(1, 2), (-1, 1), (-2, -1)]:
            id1, id2 = tid + off1, tid + off2
            if id1 // 9 == tid // 9 and id2 // 9 == tid // 9:
                if id1 in hand_by_id and id2 in hand_by_id:
                    for c1 in hand_by_id[id1]:
                        for c2 in hand_by_id[id2]:
                            candidates.append((0, [tile, c1, c2]))
    return candidates


def parse_init_seed(seed_str: str) -> tuple:
    return tuple(int(p) for p in seed_str.split(',')[:6])


class MjlogReplayer:
    def __init__(self):
        self.states = [GameState() for _ in range(4)]
        for s in range(4):
            self.states[s].my_seat = s
        self.awaited = [False] * 4
        self.chang = 0
        self.ju = 0
        self.ben = 0
        self.liqibang = 0

    def on_init(self, elem):
        seed = elem.get('seed', '0,0,0,0,0,0')
        ten_str = elem.get('ten', '250,250,250,250')
        scores = [int(x) * 100 for x in ten_str.split(',')]
        dora_id = parse_init_seed(seed)[5]
        dora_tile = tenhou_to_tile_str(dora_id)

        hands = {}
        for i in range(4):
            hai = elem.get(f'hai{i}', '')
            hands[i] = [tenhou_to_tile_str(int(x)) for x in hai.split(',') if x.strip()]

        tiles_list = [hands[i] for i in range(4)]

        for s in range(4):
            self.states[s].on_new_round(
                self.chang, self.ju, self.ben,
                self.liqibang, tiles_list[s],
                [scores[i] for i in range(4)],
                70 - sum(len(h) for h in tiles_list),
                [dora_tile]
            )
            self.states[s].chang = self.chang
            self.states[s].ju = self.ju
        self.awaited = [True] * 4

    def on_draw(self, who, tile_val):
        tile = tenhou_to_tile_str(tile_val)
        for s in range(4):
            if s == who:
                self.states[s].on_self_draw(tile)
            else:
                self.states[s].on_opponent_draw(who)
        self.awaited[who] = True
        return who, tile

    def on_discard(self, who, tile_val, is_riichi=False, moqie=False):
        tile = tenhou_to_tile_str(tile_val)
        for s in range(4):
            self.states[s].on_discard(who, tile, is_riichi, moqie)
        self.awaited[who] = False
        return who, tile

    def on_dora(self, tile_val):
        tile = tenhou_to_tile_str(tile_val)
        for s in range(4):
            self.states[s].on_new_dora(tile)

    def on_reach(self, who, step):
        if step == 2:
            for s in range(4):
                self.states[s].reach_states[who].is_reach = True

    def on_meld(self, who, m_val):
        result = build_meld_params(m_val, who)
        typ, seat = result[0], result[1]
        if typ == 3:  # ankan
            tile_str = result[2]
            for s in range(4):
                self.states[s].on_an_gang_add_gang(3, seat, tile_str)
        elif typ in (0, 1, 2):
            tiles, froms = result[2], result[3]
            for s in range(4):
                self.states[s].on_chi_peng_gang(typ, seat, tiles, froms, [0] * len(tiles))


def extract_decisions(xml_path: Path, encoder: FeatureEncoder):
    with open(xml_path, 'r', encoding='utf-8') as f:
        content = f.read()
    root = ET.fromstring(content)
    if root.tag != 'mjloggm':
        return []

    # Compute rank labels for all 4 players
    final_scores = parse_final_scores(root)
    rank_labels = compute_ranks(final_scores)

    samples = []
    player = MjlogReplayer()
    in_round = False

    for elem in root:
        tag = elem.tag

        if tag == 'INIT':
            player.on_init(elem)
            in_round = True

        elif tag in ('AGARI', 'RYUUKYOKU'):
            in_round = False
            # Reset liqibang if agari (simplified)
            if tag == 'AGARI':
                player.liqibang = 0

        elif tag == 'REACH' and in_round:
            who = int(elem.get('who', '0'))
            step = int(elem.get('step', '1'))
            player.on_reach(who, step)

        elif tag == 'DORA' and in_round:
            player.on_dora(int(elem.get('hai', '0')))

        elif tag == 'N' and in_round:
            who = int(elem.get('who', '0'))
            m_val = int(elem.get('m', '0'))
            player.on_meld(who, m_val)

        else:
            dm = DRAW_RE.match(tag)
            if dm and in_round:
                who = DRAW_MAP[dm.group(1)]
                tile_val = int(dm.group(2))
                who, tile = player.on_draw(who, tile_val)
                st = player.states[who]
                if not st.reach_states[who].is_reach:
                    rank_cond = build_rank_onehot(rank_labels[who])
                    samples.append((encoder.encode(st), None, tile, who, rank_cond))
                continue

            dcm = DISCARD_RE.match(tag)
            if dcm and in_round:
                who = DISCARD_MAP[dcm.group(1)]
                tile_val = int(dcm.group(2))
                tile = tenhou_to_tile_str(tile_val)

                # Check if next action is a meld by someone
                next_is_meld_seat = None
                elem_iter = list(root)
                elem_idx = elem_iter.index(elem)
                if elem_idx + 1 < len(elem_iter):
                    nxt = elem_iter[elem_idx + 1]
                    if nxt.tag == 'N':
                        next_is_meld_seat = int(nxt.get('who', '0'))

                for opp in range(4):
                    if opp == who:
                        continue
                    if player.states[opp].reach_states[opp].is_reach:
                        continue
                    is_kamicha = ((opp - 1) % 4 == who)
                    opp_hand = list(player.states[opp].my_hand)
                    cands = generate_meld_candidates(opp_hand, tile, is_kamicha)
                    if cands:
                        feat = encoder.encode(player.states[opp])
                        did_meld = (next_is_meld_seat == opp)
                        label = np.array([1.0 if did_meld else 0.0], dtype=np.float32)
                        rank_cond = build_rank_onehot(rank_labels[opp])
                        samples.append((feat, label, 'meld_skip', opp, rank_cond))

                who, _ = player.on_discard(who, tile_val)

                st = player.states[who]
                hand_at_discard = list(st.my_hand)
                hand_at_discard.append(tile)

                for i in range(len(samples) - 1, -1, -1):
                    f, lbl, info, seat, rc = samples[i]
                    if seat == who and lbl is None:
                        lbl = LabelEncoder.discard_label(hand_at_discard, tile)
                        samples[i] = (f, lbl, tile, seat, rc)
                        break
                continue

    return [(f, lbl, t, s, rc) for f, lbl, t, s, rc in samples if lbl is not None]


def process_directory(xml_dir: str):
    encoder = FeatureEncoder()
    features, labels, conditions, metadata = [], [], [], []
    meld_features, meld_labels, meld_conditions, meld_metadata = [], [], [], []
    xml_path = Path(xml_dir)
    files = sorted(xml_path.glob('*.xml')) + sorted(xml_path.glob('*.mjlog'))

    if not files:
        print(f"No XML files found in {xml_dir}")
        return

    print(f"Processing {len(files)} files...")
    total = 0

    for f in files:
        try:
            samples = extract_decisions(f, encoder)
            for feat, label, info, seat, rank_cond in samples:
                cond = np.array(rank_cond, dtype=np.float32)
                if info in ('meld_skip', 'meld'):
                    meld_features.append(feat)
                    meld_labels.append(label)
                    meld_conditions.append(cond)
                    meld_metadata.append({'file': f.name, 'info': info, 'seat': int(seat)})
                else:
                    features.append(feat)
                    labels.append(label)
                    conditions.append(cond)
                    metadata.append({'file': f.name, 'tile': info, 'seat': int(seat)})
            total += len(samples)
        except Exception as e:
            print(f"  Error: {f.name}: {e}")

    if not features:
        print("No decisions extracted")
        return

    if features:
        features_arr = np.stack(features, axis=0)
        labels_arr = np.stack(labels, axis=0)
        conds_arr = np.stack(conditions, axis=0)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        np.save(os.path.join(OUTPUT_DIR, 'features.npy'), features_arr)
        np.save(os.path.join(OUTPUT_DIR, 'labels.npy'), labels_arr)
        np.save(os.path.join(OUTPUT_DIR, 'conditions.npy'), conds_arr)
        with open(os.path.join(OUTPUT_DIR, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(metadata, f, ensure_ascii=False)
        print(f"Discard: {len(features)} -> {OUTPUT_DIR} ({features_arr.shape})")

    if meld_features:
        mf = np.stack(meld_features, axis=0)
        ml = np.stack(meld_labels, axis=0)
        mc = np.stack(meld_conditions, axis=0)
        md = OUTPUT_DIR / 'meld'
        md.mkdir(parents=True, exist_ok=True)
        np.save(os.path.join(md, 'features.npy'), mf)
        np.save(os.path.join(md, 'labels.npy'), ml)
        np.save(os.path.join(md, 'conditions.npy'), mc)
        with open(os.path.join(md, 'metadata.json'), 'w', encoding='utf-8') as f:
            json.dump(meld_metadata, f, ensure_ascii=False)
        print(f"Meld: {len(meld_features)} -> {md} ({mf.shape})")

    print(f"Total: {total} decisions")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--xml-dir', type=str,
                        default=str(Path(__file__).resolve().parent.parent / 'data' / 'raw' / 'tenhou_xml'))
    args = parser.parse_args()
    process_directory(args.xml_dir)
