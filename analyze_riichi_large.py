"""
Extended analysis: collect MANY more riichi events from a larger log set.
Target: 500+ riichi events for statistical significance.
"""
import json
import os
import sys
import sqlite3
import time
from collections import Counter

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile
from core.strategy_manager import ShantenCalculator
from core.hand_value import estimate_han_advanced
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

with open('tools/_log_ids_1000.txt') as f:
    ids = [line.strip() for line in f if line.strip()]

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
# Use ALL GA log IDs
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

print(f'ログ数: {len(rows)}')

riichi_events = []
start = time.time()
processed = 0

for log_id, blob in rows:
    processed += 1
    if processed % 50 == 0:
        elapsed = time.time() - start
        print(f'  処理中: {processed}/{len(rows)} ({elapsed:.0f}s経過, {len(riichi_events)}件リーチ検出)', flush=True)
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

            if isL and awaiting[seat]:
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    if sh <= 0:
                        try:
                            ev = Evaluator(states[seat], params)
                            riichi_ev, damaten_ev = ev._compare_riichi_vs_damaten()
                            han = estimate_han_advanced(
                                states[seat].my_hand, states[seat].my_melds, states[seat].doras,
                                is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
                                seat=states[seat].my_seat, chang=states[seat].chang, ju=states[seat].ju
                            )
                            han = max(han, 1)
                            wait_tiles = ev._wait_tiles_for_tenpai()
                            n_wait_types = len(wait_tiles)
                            dora_in_hand = sum(1 for h in hand for dd in states[seat].actual_doras if dd and id_to_tile(tile_to_id(dd)) == h)
                            visible = states[seat].all_visible_counts()
                            dora_ura = sum(visible[tile_to_id(dd)] for dd in states[seat].doras if dd)
                            my_score = states[seat].scores[states[seat].my_seat]
                            rank = sorted(states[seat].scores, reverse=True).index(my_score) + 1
                            turn = (states[seat].tsumo_count - 1) // 4 + 1
                            mode = ev.strategy.get_strategy_mode()
                            diff = damaten_ev - riichi_ev
                            left_tiles = states[seat].left_tile_count

                            riichi_events.append({
                                'log_id': log_id,
                                'seat': seat,
                                'kyoku': states[seat].chang * 4 + states[seat].ju + 1,
                                'turn': turn,
                                'riichi_ev': riichi_ev,
                                'damaten_ev': damaten_ev,
                                'diff': diff,
                                'han': han,
                                'n_wait_types': n_wait_types,
                                'dora_in_hand': dora_in_hand,
                                'dora_ura': dora_ura,
                                'left_tiles': left_tiles,
                                'my_score': my_score,
                                'rank': rank,
                                'mode': mode,
                                'is_dealer': seat == states[seat].dealer_seat,
                                'has_opp_reach': states[seat].is_any_opponent_reach(),
                            })
                        except Exception as e:
                            pass

            for s in range(4):
                if s == seat:
                    states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4: awaiting[seat] = False
            continue

        if cls == 'RecordChiPengGang':
            call_type = d.get('type')
            call_seat = d.get('seat')
            tiles = d.get('tiles', [])
            froms = d.get('froms', [])
            tile_states = d.get('tileStates', [])
            if 0 <= call_seat < 4:
                states[call_seat].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
                awaiting[call_seat] = True
            continue

        if cls in ('RecordHule', 'RecordNoTile'):
            for s in range(4):
                awaiting[s] = False
            continue

print(f'\n=== 人間のリーチ宣言総数: {len(riichi_events)}件 ===\n')

ai_riichi = [e for e in riichi_events if e['riichi_ev'] > e['damaten_ev']]
ai_damaten = [e for e in riichi_events if e['riichi_ev'] <= e['damaten_ev']]
print(f'AIがリーチ推奨: {len(ai_riichi)} ({len(ai_riichi)/len(riichi_events)*100:.1f}%)')
print(f'AIがダマテン推奨: {len(ai_damaten)} ({len(ai_damaten)/len(riichi_events)*100:.1f}%)')
print()

# Compare features
print('=== AIがダマテンと判断したケースの特徴 ===')
if ai_damaten:
    print(f'  平均手役: {sum(e["han"] for e in ai_damaten) / len(ai_damaten):.1f}翻')
    print(f'  平均待ち種類: {sum(e["n_wait_types"] for e in ai_damaten) / len(ai_damaten):.1f}')
    print(f'  平均持ち点: {sum(e["my_score"] for e in ai_damaten) / len(ai_damaten):.0f}')
    print(f'  平均順位: {sum(e["rank"] for e in ai_damaten) / len(ai_damaten):.2f}')
    print(f'  平均巡目: {sum(e["turn"] for e in ai_damaten) / len(ai_damaten):.1f}')
    print(f'  親: {sum(1 for e in ai_damaten if e["is_dealer"])}回')
    print(f'  対家リーチ有: {sum(1 for e in ai_damaten if e["has_opp_reach"])}回')
    print(f'  ドラ持ち: {sum(1 for e in ai_damaten if e["dora_in_hand"] > 0)}回')

print()
print('=== AIがリーチ推奨したケースの特徴 ===')
if ai_riichi:
    print(f'  平均手役: {sum(e["han"] for e in ai_riichi) / len(ai_riichi):.1f}翻')
    print(f'  平均待ち種類: {sum(e["n_wait_types"] for e in ai_riichi) / len(ai_riichi):.1f}')
    print(f'  平均持ち点: {sum(e["my_score"] for e in ai_riichi) / len(ai_riichi):.0f}')
    print(f'  平均順位: {sum(e["rank"] for e in ai_riichi) / len(ai_riichi):.2f}')
    print(f'  平均巡目: {sum(e["turn"] for e in ai_riichi) / len(ai_riichi):.1f}')
    print(f'  親: {sum(1 for e in ai_riichi if e["is_dealer"])}回')
    print(f'  対家リーチ有: {sum(1 for e in ai_riichi if e["has_opp_reach"])}回')
    print(f'  ドラ持ち: {sum(1 for e in ai_riichi if e["dora_in_hand"] > 0)}回')

# Han distribution
print()
print('=== 翻数別: 人間リーチ宣言 vs AI判断一致率 ===')
han_labels = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 99)]
for lo, hi in han_labels:
    subset = [e for e in riichi_events if lo <= e['han'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        label = f'{lo}翻' if lo == hi else f'{lo}翻+'
        print(f'  {label}: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Turn distribution
print()
print('=== 巡目別: 人間リーチ宣言 vs AI判断一致率 ===')
turn_bins = [(1, 5), (6, 8), (9, 11), (12, 14), (15, 18)]
for lo, hi in turn_bins:
    subset = [e for e in riichi_events if lo <= e['turn'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  巡目{lo}-{hi}: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Rank distribution
print()
print('=== 順位別: 人間リーチ宣言 vs AI判断一致率 ===')
for r in [1, 2, 3, 4]:
    subset = [e for e in riichi_events if e['rank'] == r]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  {r}位: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Score
print()
print('=== 持ち点別: 人間リーチ宣言 vs AI判断一致率 ===')
score_bins = [(0, 15000), (15000, 25000), (25000, 35000), (35000, 50000), (50000, 100000)]
for lo, hi in score_bins:
    subset = [e for e in riichi_events if lo <= e['my_score'] < hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  {lo}-{hi}: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Dora
print()
print('=== ドラ持ち/壁残り別 ===')
dora_bins = [(0, 0), (1, 1), (2, 2), (3, 99)]
for lo, hi in dora_bins:
    subset = [e for e in riichi_events if lo <= e['dora_in_hand'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        label = f'ドラ{lo}枚' if lo == hi else f'ドラ{lo}枚以上'
        print(f'  {label}: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Wait count
print()
print('=== 待ち種類数別 ===')
wait_bins = [(1, 1), (2, 2), (3, 3), (4, 5), (6, 99)]
for lo, hi in wait_bins:
    subset = [e for e in riichi_events if lo <= e['n_wait_types'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        label = f'待ち{lo}種' if lo == hi else f'待ち{lo}種以上'
        print(f'  {label}: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Wall remaining
print()
print('=== 壁残り別 ===')
wall_bins = [(0, 10), (11, 20), (21, 30), (31, 40), (41, 70)]
for lo, hi in wall_bins:
    subset = [e for e in riichi_events if lo <= e['left_tiles'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  壁{lo}-{hi}: 人間リーチ{len(subset)}回 → AIリーチ推奨{riichi_count} ({riichi_count/len(subset)*100:.1f}%)')

# Detailed: low-han scenarios
print()
print('=== 重要ケース: 高手役(5翻+)で人間がリーチしたのにAIがダマテン ===')
high_han = [e for e in ai_damaten if e['han'] >= 5]
print(f'  該当: {len(high_han)}/{len(ai_damaten)} (ダマテン内の{len(high_han)/len(ai_damaten)*100:.1f}%)')
if high_han:
    print(f'  平均持ち点: {sum(e["my_score"] for e in high_han)/len(high_han):.0f}')
    print(f'  平均巡目: {sum(e["turn"] for e in high_han)/len(high_han):.1f}')
    print(f'  平均順位: {sum(e["rank"] for e in high_han)/len(high_han):.2f}')
    print(f'  ドラ持ち: {sum(1 for e in high_han if e["dora_in_hand"] > 0)}回')
    print(f'  親: {sum(1 for e in high_han if e["is_dealer"])}回')

# Save for later
import pickle
with open('riichi_events_large.pkl', 'wb') as f:
    pickle.dump(riichi_events, f)
print(f'\n{len(riichi_events)}件保存: riichi_events_large.pkl')
