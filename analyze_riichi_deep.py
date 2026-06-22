"""
Deep dive: when AI says NO to riichi but human does it, what's the difference?
We need to replay each tenhou log and at each riichi declaration, compute the AI's
should_riichi value AND the damaten value to see why AI is being too conservative.
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

# Categorize riichi decisions
riichi_events = []  # (log_id, seat, kyoku, riichi_ev, damaten_ev, mode, is_dealer, has_opp_reach, turn, tenpai_score)

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
    dealer_seat = 0
    chang = 0
    ju = 0
    kyoku_first = 0

    for a in actions:
        if a.get('type') != 1: continue
        r = a.get('result', {})
        cls = r.get('class_name', '')
        d = r.get('data', {})

        if cls == 'RecordNewRound':
            chang = d.get('chang', 0)
            ju = d.get('ju', 0)
            kyoku = chang * 4 + ju + 1
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

            # Check if human declared riichi
            if isL and awaiting[seat]:
                # This is a riichi declaration by human
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    if sh <= 0:
                        # Human declared riichi. Compute AI's evaluation.
                        try:
                            ev = Evaluator(states[seat], params)
                            riichi_ev, damaten_ev = ev._compare_riichi_vs_damaten()
                            has_opp_reach = states[seat].is_any_opponent_reach()
                            is_dealer = (seat == states[seat].dealer_seat)
                            mode = ev.strategy.get_strategy_mode()
                            turn = (states[seat].tsumo_count - 1) // 4 + 1
                            riichi_events.append({
                                'log_id': log_id,
                                'seat': seat,
                                'kyoku': kyoku,
                                'turn': turn,
                                'riichi_ev': riichi_ev,
                                'damaten_ev': damaten_ev,
                                'mode': mode,
                                'has_opp_reach': has_opp_reach,
                                'is_dealer': is_dealer,
                            })
                        except Exception as e:
                            pass

            # Process discard
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
ai_riichi_count = sum(1 for e in riichi_events if e['riichi_ev'] > e['damaten_ev'])
ai_damaten_count = total - ai_riichi_count
print(f'人間のリーチ宣言総数: {total}')
print(f'AIがリーチ推奨: {ai_riichi_count} ({ai_riichi_count/total*100:.1f}%)')
print(f'AIがダマテン推奨: {ai_damaten_count} ({ai_damaten_count/total*100:.1f}%)')
print()

# Categorize by game state
print('=== モード別のAI判断 ===')
mode_ai = Counter()
for e in riichi_events:
    mode_ai[e['mode']] += 1
for m, c in mode_ai.most_common():
    riichi_count = sum(1 for e in riichi_events if e['mode'] == m and e['riichi_ev'] > e['damaten_ev'])
    print(f'  {m}: {c}回 (AIリーチ推奨: {riichi_count}, ダマテン: {c-riichi_count})')

print()
print('=== 対家リーチ有の場面 ===')
opp_reach = [e for e in riichi_events if e['has_opp_reach']]
print(f'  総数: {len(opp_reach)}')
opp_reach_riichi = sum(1 for e in opp_reach if e['riichi_ev'] > e['damaten_ev'])
print(f'  AIリーチ推奨: {opp_reach_riichi} / ダマテン: {len(opp_reach) - opp_reach_riichi}')

print()
print('=== 親 vs 子 ===')
for dealer_flag in [True, False]:
    subset = [e for e in riichi_events if e['is_dealer'] == dealer_flag]
    if subset:
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  {"親" if dealer_flag else "子"}: {len(subset)}回, AIリーチ推奨: {riichi_count}')

print()
print('=== サンプル: AIダマテン推奨ケース (リーチEV vs ダマテンEV) ===')
# Show top 10 cases where AI said damaten
damaten_cases = [e for e in riichi_events if e['riichi_ev'] <= e['damaten_ev']]
damaten_cases.sort(key=lambda e: e['damaten_ev'] - e['riichi_ev'], reverse=True)
for e in damaten_cases[:10]:
    diff = e['damaten_ev'] - e['riichi_ev']
    print(f'  局{e["kyoku"]} {e["turn"]}巡 親={e["is_dealer"]} opp_reach={e["has_opp_reach"]} モード={e["mode"]} '
          f'riichi_ev={e["riichi_ev"]:+.2f} damaten_ev={e["damaten_ev"]:+.2f} diff={diff:+.2f}')

# Show riichi recommendations
print()
print('=== サンプル: AIリーチ推奨ケース ===')
riichi_cases = [e for e in riichi_events if e['riichi_ev'] > e['damaten_ev']]
riichi_cases.sort(key=lambda e: e['riichi_ev'] - e['damaten_ev'], reverse=True)
for e in riichi_cases[:5]:
    diff = e['riichi_ev'] - e['damaten_ev']
    print(f'  局{e["kyoku"]} {e["turn"]}巡 親={e["is_dealer"]} opp_reach={e["has_opp_reach"]} モード={e["mode"]} '
          f'riichi_ev={e["riichi_ev"]:+.2f} damaten_ev={e["damaten_ev"]:+.2f} diff={diff:+.2f}')
