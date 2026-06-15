#!/usr/bin/env python
from __future__ import annotations
import json
import os
import sys
import numpy as np
from tqdm import tqdm

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.game_state import GameState
from diffusion_ai.feature_encoder import FeatureEncoder, LabelEncoder

DATA_DIR = os.path.join(os.path.dirname(__file__), '..', '..', 'data')
OUTPUT_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'processed')
os.makedirs(OUTPUT_DIR, exist_ok=True)


def iter_record_discard_decisions(record_path: str, encoder: FeatureEncoder):
    with open(record_path, encoding='utf-8') as f:
        data = json.load(f)
    actions = data.get('detail_records', {}).get('actions', [])

    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s

    awaiting = [False] * 4
    last_action_per_seat = -1

    for idx, a in enumerate(actions):
        if a['type'] != 1:
            continue
        r = a['result']
        cls = r['class_name']
        d = r['data']

        if 'dora' in d:
            for s in range(4):
                states[s].doras = [d['dora']]
        if 'doras' in d:
            for s in range(4):
                states[s].doras = list(d['doras'])
        if 'liqibang' in d:
            for s in range(4):
                states[s].liqibang = d['liqibang']

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(
                    d.get('chang', 0), d.get('ju', 0), d.get('ben', 0),
                    d.get('liqibang', 0), d.get(k, []),
                    d.get('scores', [25000] * 4),
                    d.get('leftTileCount', 70),
                    d.get('doras', [d['dora']] if 'dora' in d else [])
                )
                states[s].chang = d.get('chang', 0)
                states[s].ju = d.get('ju', 0)
            awaiting = [True] * 4

        elif cls == 'RecordDealTile':
            seat = d['seat']
            tile = d['tile']
            for s in range(4):
                if s == seat:
                    states[s].on_self_draw(tile)
                else:
                    states[s].on_opponent_draw(seat)
            awaiting[seat] = True

        elif cls == 'RecordDiscardTile':
            seat = d['seat']
            tile = d['tile']
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if awaiting[seat]:
                hand = list(states[seat].my_hand)
                if len(hand) % 3 == 2:
                    is_riichi_already = states[seat].reach_states[seat].is_reach
                    if not is_riichi_already:
                        feat = encoder.encode(states[seat])
                        label = LabelEncoder.discard_label(hand, tile)
                        yield feat, label, tile, seat

            awaiting[seat] = False
            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)

        elif cls == 'RecordChiPengGang':
            call_type = d['type']
            call_seat = d['seat']
            tiles = d['tiles']
            froms = d.get('froms', [])
            tile_states = d.get('tileStates', [])
            for s in range(4):
                states[s].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)

        elif cls == 'RecordAnGangAddGang':
            call_type = d['type']
            call_seat = d['seat']
            tiles = d.get('tiles', '')
            for s in range(4):
                states[s].on_an_gang_add_gang(call_type, call_seat, tiles)

        elif cls == 'RecordNewDora':
            dora_tile = d['dora']
            for s in range(4):
                states[s].on_new_dora(dora_tile)

    return


def build_dataset():
    encoder = FeatureEncoder()
    all_features = []
    all_labels = []
    all_metadata = []

    record_files = sorted([
        os.path.join(DATA_DIR, f)
        for f in os.listdir(DATA_DIR)
        if f.endswith('.json') and not f.endswith('_trimmed.json')
    ])

    print(f"Found {len(record_files)} record files")
    total_decisions = 0

    for rpath in record_files:
        fname = os.path.basename(rpath)
        decisions = 0
        for feat, label, tile, seat in iter_record_discard_decisions(rpath, encoder):
            all_features.append(feat)
            all_labels.append(label)
            all_metadata.append({'file': fname, 'tile': tile, 'seat': seat})
            decisions += 1
        total_decisions += decisions
        print(f"  {fname}: {decisions} discard decisions")

    print(f"\nTotal: {total_decisions} decisions")

    if total_decisions == 0:
        print("No decisions extracted. Check record format.")
        return

    features_arr = np.stack(all_features, axis=0)
    labels_arr = np.stack(all_labels, axis=0)

    np.save(os.path.join(OUTPUT_DIR, 'features.npy'), features_arr)
    np.save(os.path.join(OUTPUT_DIR, 'labels.npy'), labels_arr)

    with open(os.path.join(OUTPUT_DIR, 'metadata.json'), 'w', encoding='utf-8') as f:
        json.dump(all_metadata, f, ensure_ascii=False)

    print(f"Saved: {OUTPUT_DIR}")
    print(f"  features.npy: {features_arr.shape} ({features_arr.nbytes / 1024:.0f} KB)")
    print(f"  labels.npy: {labels_arr.shape}")
    print(f"  metadata.json: {len(all_metadata)} entries")
    print(f"  Feature dimension: {encoder.feature_dim}")


if __name__ == '__main__':
    build_dataset()
