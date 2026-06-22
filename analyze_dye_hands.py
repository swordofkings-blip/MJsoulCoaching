"""
@title 染め手/特殊手の人間データ分析
@description
    人間データから:
    1. 染め手進行中の手牌の傾向
    2. 人間は何巡目から染め手を目指すか
    3. 染め手完成後のオリ判断
    4. 高打点(跳満/倍満)狙いの手牌構成
"""
import pickle
import json
import sys
from collections import Counter, defaultdict
from statistics import mean

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile, is_honor
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
import sqlite3

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load logs
print('Loading logs...')
with open('tools/_log_ids_10000.txt') as f:
    log_ids = [l.strip() for l in f if l.strip()][:1000]
db = sqlite3.connect('diffusion-ai/data/raw/tenhou_logs.db')
cur = db.cursor()
placeholders = ','.join(['?'] * len(log_ids))
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', log_ids)
rows = cur.fetchall()
db.close()
log_blobs = {lid: blob for lid, blob in rows}
print(f'  {len(log_blobs)} logs loaded')

# Extract hand states where染め手進行中
dye_hands = []  # (log_id, seat, kyoku, turn, hand, melds, shanten, doras, scores)
honor_hands = []  # (similar for honor-heavy hands)
n_flush_initiated = 0

processed = 0
for log_id, blob in log_blobs.items():
    processed += 1
    if processed % 100 == 0:
        print(f'  処理: {processed}/{len(log_blobs)} ({len(dye_hands)}染め手候補)', flush=True)
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

            if awaiting[seat] and not isL:
                hand = list(states[seat].my_hand)
                melds = list(states[seat].my_melds)
                if hand and len(hand) % 3 == 2:
                    try:
                        hand_counts = hand_to_counts(hand)
                        open_meld_count = sum(1 for m in melds if m.is_open)
                        if open_meld_count == 0:
                            shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
                        else:
                            shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)

                        # 染め手チェック: 数牌のうち1種が7枚以上
                        suits_count = [sum(hand_counts[i:i+9]) for i in (0, 9, 18)]
                        max_suit = max(suits_count)
                        max_suit_idx = suits_count.index(max_suit)
                        # 混一色: 字牌+1種の数牌が9枚以上
                        honor_count = sum(hand_counts[27:34])
                        is_flush_attempt = (max_suit >= 7)

                        if is_flush_attempt:
                            turn = (states[seat].tsumo_count - 1) // 4 + 1
                            kyoku = states[seat].chang * 4 + states[seat].ju + 1
                            dye_hands.append({
                                'log_id': log_id,
                                'seat': seat,
                                'kyoku': kyoku,
                                'turn': turn,
                                'shanten': shanten,
                                'max_suit': max_suit,
                                'max_suit_idx': max_suit_idx,
                                'honor_count': honor_count,
                                'hand_size': len(hand),
                                'is_dealer': (seat == states[seat].dealer_seat),
                                'my_score': states[seat].scores[seat],
                                'reach_n': sum(1 for s in range(4) if s != seat and states[s].reach_states[s].is_reach),
                                'discard_tile': tile,
                            })
                    except Exception:
                        pass

            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4: awaiting[seat] = False
            continue

        if cls == 'RecordChiPengGang':
            call_type = d.get('type')
            call_seat = d.get('seat')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tile_states', [])
            if 0 <= call_seat < 4:
                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls in ('RecordHule', 'RecordNoTile'):
            for s in range(4):
                awaiting[s] = False
            continue

# Save
with open('dye_hands.pkl', 'wb') as f:
    pickle.dump(dye_hands, f)

print(f'\n=== 染め手進行中の手牌: {len(dye_hands)}件 ===')

# 分析
print('\n=== 染め手の巡目分布 ===')
turn_counter = Counter()
for d in dye_hands:
    turn_counter[d['turn']] += 1
for t in sorted(turn_counter.keys())[:20]:
    print(f'  巡目{t}: {turn_counter[t]}件')

print('\n=== 染め手のシャンテン分布 ===')
sh_counter = Counter(d['shanten'] for d in dye_hands)
for sh in sorted(sh_counter.keys()):
    print(f'  {sh}シャンテン: {sh_counter[sh]}件')

print('\n=== 染め手のスート分布 ===')
suit_counter = Counter()
for d in dye_hands:
    suit_name = ['萬子', '筒子', '索子'][d['max_suit_idx']]
    suit_counter[suit_name] += 1
for s, n in suit_counter.most_common():
    print(f'  {s}: {n}件')

print('\n=== 染め手の巡目×シャンテン ===')
turn_bins = [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]
shanten_bins = [0, 1, 2, 3, 4, 5]
print(f'  {"":12}', end='')
for lo, hi in turn_bins:
    print(f' 巡{lo}-{hi}', end='')
print()
for sh in shanten_bins:
    if sh == 5:
        subset = [d for d in dye_hands if d['shanten'] >= 5]
        label = '5+'
    else:
        subset = [d for d in dye_hands if d['shanten'] == sh]
        label = f'{sh}'
    print(f'  {label:12} ({len(subset):5})', end='')
    for lo, hi in turn_bins:
        s = [d for d in subset if lo <= d['turn'] <= hi]
        print(f' {len(s):5}', end='')
    print()

# 染め手の人間挙動
print('\n=== 染め手進行中の人間判断 ===')
# 人間は字牌を切る = 押す, 中張を切る = オリる
push_count = 0
fold_count = 0
for d in dye_hands:
    tile = d['discard_tile']
    if is_honor(tile_to_id(tile)):
        push_count += 1
    else:
        fold_count += 1
print(f'  字牌切り (押す): {push_count}件 ({push_count/len(dye_hands)*100:.1f}%)')
print(f'  中張/端牌切り (オリる/中間): {fold_count}件 ({fold_count/len(dye_hands)*100:.1f}%)')

# 染め手の押し/オリ率 by shanten
print('\n=== 染め手のシャンテン×人間判断 ===')
for sh in [0, 1, 2, 3, 4, 5]:
    if sh == 5:
        subset = [d for d in dye_hands if d['shanten'] >= 5]
    else:
        subset = [d for d in dye_hands if d['shanten'] == sh]
    if not subset: continue
    push_n = sum(1 for d in subset if is_honor(tile_to_id(d['discard_tile'])))
    fold_n = len(subset) - push_n
    print(f'  {sh}シャンテン: {len(subset)}件, 字牌切り{push_n}({push_n/len(subset)*100:.1f}%)')

# 染め手の reach_n
print('\n=== 染め手の対家リーチ数 ===')
reach_counter = Counter(d['reach_n'] for d in dye_hands)
for rn, n in sorted(reach_counter.items()):
    print(f'  reach={rn}: {n}件')

# 染め手の最高スート枚数
print('\n=== 染め手の主力色枚数 ===')
suit_count_counter = Counter(d['max_suit'] for d in dye_hands)
for c in sorted(suit_count_counter.keys()):
    print(f'  {c}枚: {suit_count_counter[c]}件')
