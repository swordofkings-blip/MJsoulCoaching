"""
@title 他家統計(player stats)の人間データ抽出
@description
    人間データから各 player の統計を抽出:
    - リーチ率
    - 放銃率
    - 和了率
    - 副露率
    - ダマテン率

    これを AI の player_stats に反映し、ベタオリ判断の精度向上に使う。
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')
from core.game_state import GameState
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

# Load 10k logs
print('Loading logs...')
with open('tools/_log_ids_10000.txt') as f:
    log_ids = [l.strip() for l in f if l.strip()]
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

# Track player stats
# 各 round での行動を記録
player_stats = defaultdict(lambda: {
    'reach_count': 0,    # リーチ宣言数
    'agari_count': 0,     # 和了数
    'deal_in_count': 0,   # 放銃数
    'meld_count': 0,      # 副露数
    'total_discards': 0,  # 打牌数 (放銃可能性)
})

# Track 放銃 = 振り込み
# 人間が「振り込まれた」 = ロンで失点
deal_in_log = []  # (log_id, round, attacker, victim)

processed = 0
for log_id, blob in all_log_blobs.items():
    processed += 1
    if processed % 1000 == 0:
        print(f'  処理: {processed}/{len(all_log_blobs)}', flush=True)
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

    for a in actions:
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

        if cls == 'RecordDiscardTile':
            seat = d.get('seat')
            tile = d.get('tile')
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if seat is None or seat < 0 or seat >= 4: continue
            player_stats[seat]['total_discards'] += 1
            if isL:
                player_stats[seat]['reach_count'] += 1
            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4:
                awaiting[seat] = False
                # Track last discard seat for ron detection
                for s in range(4):
                    states[s].last_discard_seat = seat
            continue

        if cls == 'RecordChiPengGang':
            call_seat = d.get('seat')
            if 0 <= call_seat < 4:
                player_stats[call_seat]['meld_count'] += 1
            call_type = d.get('type')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tile_states', [])
            if 0 <= call_seat < 4:
                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls == 'RecordHule':
            # 和了: hules配列にseatとzimo(ツモ/ロン)情報
            hules = d.get('hules', [])
            for h in hules:
                actor = h.get('seat')
                zimo = h.get('zimo', False)
                if actor is not None and 0 <= actor < 4:
                    player_stats[actor]['agari_count'] += 1
                # ロンの場合、放銃者を記録
                if not zimo:
                    dealer_seat = states[actor].last_discard_seat if hasattr(states[actor], 'last_discard_seat') else -1
                    if dealer_seat is not None and 0 <= dealer_seat < 4 and dealer_seat != actor:
                        player_stats[dealer_seat]['deal_in_count'] += 1
            # Round end
            for s in range(4):
                awaiting[s] = False
            continue

        if cls in ('RecordNoTile',):
            for s in range(4):
                awaiting[s] = False
            continue

# Save player_stats
player_stats_serializable = {k: dict(v) for k, v in player_stats.items()}
with open('player_stats.pkl', 'wb') as f:
    pickle.dump(player_stats_serializable, f)

print()
print('=== 各 player の統計 ===')
for seat, stats in sorted(player_stats.items()):
    total = stats['total_discards']
    reach = stats['reach_count']
    agari = stats['agari_count']
    deal_in = stats['deal_in_count']
    meld = stats['meld_count']
    if total == 0: continue
    print(f'\nSeat {seat}:')
    print(f'  打牌数: {total}')
    print(f'  リーチ数: {reach} ({reach/total*100:.1f}%)')
    print(f'  和了数: {agari} ({agari/total*100:.1f}%)')
    print(f'  放銃数: {deal_in} ({deal_in/total*100:.1f}%)')
    print(f'  副露数: {meld}')

# Aggregate
total_discards_all = sum(s['total_discards'] for s in player_stats.values())
total_reach_all = sum(s['reach_count'] for s in player_stats.values())
total_agari_all = sum(s['agari_count'] for s in player_stats.values())
total_deal_in_all = sum(s['deal_in_count'] for s in player_stats.values())
total_meld_all = sum(s['meld_count'] for s in player_stats.values())
print()
print('=== 全体統計 ===')
print(f'  打牌数: {total_discards_all}')
print(f'  リーチ数: {total_reach_all} ({total_reach_all/total_discards_all*100:.1f}%)')
print(f'  和了数: {total_agari_all} ({total_agari_all/total_discards_all*100:.1f}%)')
print(f'  放銃数: {total_deal_in_all} ({total_deal_in_all/total_discards_all*100:.1f}%)')
print(f'  副露数: {total_meld_all} ({total_meld_all/total_discards_all*100:.1f}%)')
print()

# 平均 player_stats
print('=== 平均 player_stats (per seat, 人間データ基準) ===')
print('人間データの平均:')
print('  call_rate:', total_meld_all / (total_discards_all / 4) / 4)  # 概算
print('  reach_rate:', total_reach_all / total_discards_all)
print('  agari_rate:', total_agari_all / total_discards_all)
print('  deal_in_rate:', total_deal_in_all / total_discards_all)
