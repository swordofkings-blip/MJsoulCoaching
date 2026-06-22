"""
@title 鳴き判断の人間データ分析
@description
    人間データから:
    1. 人間がポン/チー/カンをした場面の分析
    2. 鳴いた後の手牌構成
    3. 鳴かなかった場面
    4. 鳴き判断の人間特徴

    人間は:
    - 染め手進行中 → 鳴いて手を進める
    - 役牌 → ポンする
    - 1シャンテンで安い手 → チーしない
    - 終盤でオリ判断 → 鳴かない
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')
from core.game_state import GameState
from core.str_converter import tile_to_id, hand_to_counts, is_honor
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load 10k logs
print('Loading logs...')
with open('tools/_log_ids_10000.txt') as f:
    log_ids = [l.strip() for l in f if l.strip()][:2000]
db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
BATCH = 2000
all_log_blobs = {}
for batch_start in range(0, len(log_ids), BATCH):
    batch_ids = log_ids[batch_start:batch_start+BATCH]
    placeholders = ','.join(['?'] * len(batch_ids))
    cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', batch_ids)
    rows = cur.fetchall()
    for lid, blob in rows:
        all_log_blobs[lid] = blob
db.close()
print(f'  {len(all_log_blobs)} logs loaded')

# Track 鳴き events
melds_calls = []  # (log_id, seat, type, tiles, hand_at_call, shanten_at_call, scores, reach_n)
melds_passes = []  # 鳴き可能だったのに鳴かなかった

processed = 0
for log_id, blob in all_log_blobs.items():
    processed += 1
    if processed % 200 == 0:
        print(f'  処理: {processed}/{len(all_log_blobs)} ({len(melds_calls)}鳴き)', flush=True)
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except:
        continue
    if n_rounds == 0: continue
    actions = json_dict.get('detail_records', {}).get('actions', [])
    if not actions: continue

    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    for i, a in enumerate(actions):
        if a.get('type') != 1: continue
        r = a.get('result', {})
        cls = r.get('class_name', '')
        d = r.get('data', {})

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(
                    d.get('chang', 0), d.get('ju', 0), d.get('ben', 0), d.get('liqibang', 0),
                    d.get(k, []), d.get('scores', [25000] * 4), d.get('leftTileCount', 70),
                    d.get('doras', [])
                )
                states[s].chang = d.get('chang', 0)
                states[s].ju = d.get('ju', 0)
            oya = d.get('oya', 0)
            states[oya].dealer_seat = oya
            for s in range(4):
                if s != oya: states[s].dealer_seat = oya
            awaiting = [True] * 4
            continue

        if cls == 'RecordDealTile':
            seat = d.get('seat')
            tile = d.get('tile')
            if seat is None or tile is None: continue
            for s in range(4):
                if s == seat:
                    states[s].on_self_draw(tile)
                else:
                    states[s].on_opponent_draw(seat)
            if 0 <= seat < 4: awaiting[seat] = True
            continue

        if cls == 'RecordChiPengGang':
            call_type = d.get('type')
            call_seat = d.get('seat')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tile_states', [])

            if 0 <= call_seat < 4:
                # 鳴き前(今)の状態を記録
                # 人間: 鳴いた = YES
                hand_before = list(states[call_seat].my_hand)
                melds_before = list(states[call_seat].my_melds)
                if hand_before and len(hand_before) % 3 == 2:
                    hand_counts = hand_to_counts(hand_before)
                    open_meld_count = sum(1 for m in melds_before if m.is_open)
                    if open_meld_count == 0:
                        sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    else:
                        sh = ShantenCalculator.calculate_open(hand_counts, open_meld_count)

                    call_type_name = ['chi', 'pon', 'daiminkan', 'ankan', 'kakan'][call_type]
                    turn = (states[call_seat].tsumo_count - 1) // 4 + 1
                    reach_n = sum(1 for s in range(4) if s != call_seat and states[s].reach_states[s].is_reach)
                    melds_calls.append({
                        'log_id': log_id,
                        'seat': call_seat,
                        'call_type': call_type_name,
                        'tiles': tiles,
                        'shanten': sh,
                        'open_meld_count': open_meld_count,
                        'turn': turn,
                        'reach_n': reach_n,
                        'my_score': states[call_seat].scores[call_seat],
                        'my_rank': sorted(states[call_seat].scores, reverse=True).index(states[call_seat].scores[call_seat]) + 1,
                        'is_dealer': (call_seat == states[call_seat].dealer_seat),
                    })

                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls in ('RecordHule', 'RecordNoTile'):
            for s in range(4):
                awaiting[s] = False
            continue

# Save
with open('meld_data.pkl', 'wb') as f:
    pickle.dump(melds_calls, f)

print(f'\n=== 鳴き総数: {len(melds_calls)}件 ===')
print()

# 鳴き種類
type_counter = Counter(m['call_type'] for m in melds_calls)
print('=== 鳴き種類 ===')
for t, n in type_counter.most_common():
    print(f'  {t}: {n}件')

# 鳴きのシャンテン分布
print()
print('=== 鳴き時のシャンテン ===')
sh_counter = Counter(m['shanten'] for m in melds_calls)
for sh in sorted(sh_counter.keys()):
    print(f'  {sh}シャンテン: {sh_counter[sh]}件')

# 鳴きとリーチの関係
print()
print('=== 鳴き時の対家リーチ数 ===')
reach_counter = Counter(m['reach_n'] for m in melds_calls)
for rn in sorted(reach_counter.keys()):
    print(f'  reach={rn}: {reach_counter[rn]}件')

# ポンの特徴
pon_cases = [m for m in melds_calls if m['call_type'] == 'pon']
chi_cases = [m for m in melds_calls if m['call_type'] == 'chi']
daiminkan_cases = [m for m in melds_calls if m['call_type'] == 'daiminkan']
print()
print(f'ポン総数: {len(pon_cases)}件')
print(f'チー総数: {len(chi_cases)}件')
print(f'大明槓総数: {len(daiminkan_cases)}件')

# ポンした時の手牌の鳴かれた牌
print()
print('=== ポンの牌トップ20 ===')
tile_counter = Counter()
for m in pon_cases:
    for t in m['tiles']:
        tile_counter[t] += 1
for t, n in tile_counter.most_common(20):
    print(f'  {t}: {n}件')

# チーの巡目
print()
print('=== チーの巡目 ===')
turn_counter = Counter(m['turn'] for m in chi_cases)
for t in sorted(turn_counter.keys())[:15]:
    print(f'  巡目{t}: {turn_counter[t]}件')
