"""
Deep dive into WHY humans riichi when AI says damaten.
Look at:
1. Hand value (役/han) - high value hands benefit from riichi
2. Dora - more dora = more ura potential
3. Wait quality - already in AI but verify
4. Wall remaining - more tiles = more ura likely
5. Score position - behind = more riichi
"""
import json
import os
import sys
import sqlite3
from collections import Counter

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.hand_value import estimate_han_advanced

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

with open('tools/_log_ids_ga.txt') as f:
    ids = [line.strip() for line in f if line.strip()]

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

# Collect riichi events with hand details
riichi_events = []

for log_id, blob in rows:
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
                            # Compute hand value
                            han = estimate_han_advanced(
                                states[seat].my_hand, states[seat].my_melds, states[seat].doras,
                                is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
                                seat=states[seat].my_seat, chang=states[seat].chang, ju=states[seat].ju
                            )
                            han = max(han, 1)
                            # Wait tiles
                            wait_tiles = ev._wait_tiles_for_tenpai()
                            n_wait_types = len(wait_tiles)
                            # Dora count
                            visible = states[seat].all_visible_counts()
                            dora_in_hand = sum(1 for h in hand for d in states[seat].actual_doras if d and id_to_tile(tile_to_id(d)) == h)
                            # DORA tiles in wall: how many ura are still in the wall
                            from core.str_converter import tile_to_id
                            dora_ura = sum(visible[tile_to_id(d)] for d in states[seat].doras if d)
                            # Wall remaining
                            wall = sum(visible[:34])
                            # Score
                            my_score = states[seat].scores[states[seat].my_seat]
                            rank = sorted(states[seat].scores, reverse=True).index(my_score) + 1
                            turn = (states[seat].tsumo_count - 1) // 4 + 1
                            mode = ev.strategy.get_strategy_mode()

                            riichi_events.append({
                                'log_id': log_id,
                                'seat': seat,
                                'kyoku': states[seat].chang * 4 + states[seat].ju + 1,
                                'turn': turn,
                                'riichi_ev': riichi_ev,
                                'damaten_ev': damaten_ev,
                                'han': han,
                                'n_wait_types': n_wait_types,
                                'dora_in_hand': dora_in_hand,
                                'wall_remaining': 70 - wall + len(states[seat].my_hand),  # approx
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

# Analysis
total = len(riichi_events)
ai_riichi = [e for e in riichi_events if e['riichi_ev'] > e['damaten_ev']]
ai_damaten = [e for e in riichi_events if e['riichi_ev'] <= e['damaten_ev']]

print(f'人間リーチ宣言: {total}回')
print(f'AIリーチ推奨: {len(ai_riichi)}回')
print(f'AIダマテン推奨: {len(ai_damaten)}回')
print()

# Compare features
print('=== AIがダマテンと判断した77ケースの特徴 ===')
if ai_damaten:
    avg_han_d = sum(e['han'] for e in ai_damaten) / len(ai_damaten)
    avg_wait_d = sum(e['n_wait_types'] for e in ai_damaten) / len(ai_damaten)
    avg_score_d = sum(e['my_score'] for e in ai_damaten) / len(ai_damaten)
    avg_rank_d = sum(e['rank'] for e in ai_damaten) / len(ai_damaten)
    avg_turn_d = sum(e['turn'] for e in ai_damaten) / len(ai_damaten)
    dealer_count = sum(1 for e in ai_damaten if e['is_dealer'])
    print(f'  平均手役: {avg_han_d:.1f}翻')
    print(f'  平均待ち種類: {avg_wait_d:.1f}')
    print(f'  平均持ち点: {avg_score_d:.0f}')
    print(f'  平均順位: {avg_rank_d:.2f}')
    print(f'  平均巡目: {avg_turn_d:.1f}')
    print(f'  親: {dealer_count}回')

print()
print('=== AIがリーチ推奨した16ケースの特徴 ===')
if ai_riichi:
    avg_han_r = sum(e['han'] for e in ai_riichi) / len(ai_riichi)
    avg_wait_r = sum(e['n_wait_types'] for e in ai_riichi) / len(ai_riichi)
    avg_score_r = sum(e['my_score'] for e in ai_riichi) / len(ai_riichi)
    avg_rank_r = sum(e['rank'] for e in ai_riichi) / len(ai_riichi)
    avg_turn_r = sum(e['turn'] for e in ai_riichi) / len(ai_riichi)
    dealer_count = sum(1 for e in ai_riichi if e['is_dealer'])
    print(f'  平均手役: {avg_han_r:.1f}翻')
    print(f'  平均待ち種類: {avg_wait_r:.1f}')
    print(f'  平均持ち点: {avg_score_r:.0f}')
    print(f'  平均順位: {avg_rank_r:.2f}')
    print(f'  平均巡目: {avg_turn_r:.1f}')
    print(f'  親: {dealer_count}回')

# Han distribution comparison
print()
print('=== 翻数分布 (AI判断別) ===')
han_bins = [1, 2, 3, 4, 5, 100]
han_labels = ['1翻', '2翻', '3翻', '4翻', '5翻+']
for label, lo, hi in zip(han_labels, [1, 2, 3, 4, 5], [1, 2, 3, 4, 99]):
    damaten_count = sum(1 for e in ai_damaten if lo <= e['han'] <= hi)
    riichi_count = sum(1 for e in ai_riichi if lo <= e['han'] <= hi)
    print(f'  {label}: ダマテン{ai_damaten and "AI"}[{damaten_count}回] / リーチ[{riichi_count}回]')

# Turn distribution
print()
print('=== 巡目分布 (AI判断別) ===')
turn_bins = [(1, 5), (6, 10), (11, 14), (15, 18)]
for lo, hi in turn_bins:
    damaten_count = sum(1 for e in ai_damaten if lo <= e['turn'] <= hi)
    riichi_count = sum(1 for e in ai_riichi if lo <= e['turn'] <= hi)
    print(f'  巡目{lo}-{hi}: ダマテン{damaten_count}回 / リーチ{riichi_count}回')

# Score analysis
print()
print('=== 持ち点分布 (AI判断別) ===')
score_bins = [(0, 15000), (15000, 25000), (25000, 35000), (35000, 99999)]
for lo, hi in score_bins:
    damaten_count = sum(1 for e in ai_damaten if lo <= e['my_score'] < hi)
    riichi_count = sum(1 for e in ai_riichi if lo <= e['my_score'] < hi)
    print(f'  {lo}-{hi}: ダマテン{damaten_count}回 / リーチ{riichi_count}回')

# Where is damaten excessive?
print()
print('=== ダマテン推奨ケースのうち、本来リーチすべきケース ===')
# These are cases where AI says damaten but it's CLEARLY wrong (e.g., late game, no threats, decent hand)
suspicious = []
for e in ai_damaten:
    if e['turn'] >= 12 and not e['has_opp_reach'] and e['han'] >= 3:
        suspicious.append(e)

print(f'  巡目12+で対家リーチなしで3翻以上: {len(suspicious)}/{len(ai_damaten)}')

# Score rank analysis
print()
print('=== 順位分布 (AI判断別) ===')
for r in [1, 2, 3, 4]:
    d = sum(1 for e in ai_damaten if e['rank'] == r)
    ri = sum(1 for e in ai_riichi if e['rank'] == r)
    print(f'  {r}位: ダマテン{d}回 / リーチ{ri}回')
