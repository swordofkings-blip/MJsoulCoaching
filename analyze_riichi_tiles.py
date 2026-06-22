"""
Analyze the actual remaining tile count for each wait tile.
Humans likely look at "how many winning tiles are left in the wall"
NOT just "how many wait types".
"""
import json
import sys
import sqlite3
import pickle
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
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

riichi_events = []
processed = 0

for log_id, blob in rows:
    processed += 1
    if processed % 100 == 0:
        print(f'処理: {processed}/{len(rows)} ({len(riichi_events)}件)', flush=True)
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
                        except Exception as e:
                            import traceback
                            if processed < 5: traceback.print_exc()
                            continue
                        try:
                            pass

                            # Wait tiles analysis (returns tile IDs as int)
                            wait_tiles = ev._wait_tiles_for_tenpai()
                            visible = states[seat].all_visible_counts()
                            wait_remaining = []  # 待ち牌の残り枚数リスト
                            wait_remaining_total = 0  # 合計
                            wait_count_in_wall = 0  # 壁にある待ち牌の種類数
                            for w in wait_tiles:
                                if isinstance(w, int):
                                    tid = w
                                else:
                                    tid = tile_to_id(w)
                                if 0 <= tid < 34:
                                    remaining = max(0, 4 - visible[tid])
                                    wait_remaining.append(remaining)
                                    wait_remaining_total += remaining
                                    if remaining > 0:
                                        wait_count_in_wall += 1

                            n_wait_types = len(wait_tiles)
                            # 平均残り枚数
                            avg_wait_remaining = wait_remaining_total / n_wait_types if n_wait_types > 0 else 0

                            # ドラ候補(壁)
                            doras = states[seat].doras
                            dora_in_hand = sum(1 for h in hand for dd in doras if dd and id_to_tile(tile_to_id(dd)) == h)
                            ura_count = 0
                            for dd in doras:
                                if not dd: continue
                                tid = tile_to_id(dd)
                                if 0 <= tid < 34:
                                    ura_count += max(0, 4 - visible[tid])

                            # 役牌
                            hand_counter = Counter(hand)
                            bakaze = ['E', 'S', 'W', 'N'][states[seat].chang % 4]
                            jikaze = ['E', 'S', 'W', 'N'][seat]
                            jihai = ['h', 'g', 'r']
                            yakuhai_count = 0
                            if f'{bakaze}p' in hand_counter: yakuhai_count += hand_counter[f'{bakaze}p']
                            if f'{jikaze}p' in hand_counter: yakuhai_count += hand_counter[f'{jikaze}p']
                            for j in jihai:
                                if f'{j}h' in hand_counter: yakuhai_count += hand_counter[f'{j}h']

                            han = estimate_han_advanced(
                                states[seat].my_hand, states[seat].my_melds, states[seat].doras,
                                is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
                                seat=states[seat].my_seat, chang=states[seat].chang, ju=states[seat].ju
                            )
                            han = max(han, 1)
                            my_score = states[seat].scores[states[seat].my_seat]
                            rank = sorted(states[seat].scores, reverse=True).index(my_score) + 1
                            turn = (states[seat].tsumo_count - 1) // 4 + 1
                            mode = ev.strategy.get_strategy_mode()
                            is_dealer = (seat == states[seat].dealer_seat)
                            left_tiles = states[seat].left_tile_count

                            riichi_events.append({
                                'log_id': log_id, 'seat': seat,
                                'kyoku': states[seat].chang * 4 + states[seat].ju + 1,
                                'turn': turn, 'riichi_ev': riichi_ev, 'damaten_ev': damaten_ev,
                                'han': han, 'n_wait_types': n_wait_types,
                                'wait_remaining_total': wait_remaining_total,
                                'avg_wait_remaining': avg_wait_remaining,
                                'wait_count_in_wall': wait_count_in_wall,
                                'dora_in_hand': dora_in_hand, 'ura_count': ura_count,
                                'yakuhai_count': yakuhai_count,
                                'my_score': my_score, 'rank': rank,
                                'mode': mode, 'is_dealer': is_dealer,
                                'has_opp_reach': states[seat].is_any_opponent_reach(),
                                'left_tiles': left_tiles,
                                'ai_recommends_riichi': riichi_ev > damaten_ev,
                            })
                        except Exception as e:
                            import traceback
                            if processed < 5: traceback.print_exc()

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

with open('riichi_events_v3.pkl', 'wb') as f:
    pickle.dump(riichi_events, f)
print(f'\n人間リーチ宣言: {len(riichi_events)}件保存')

total = len(riichi_events)
ai_riichi = sum(1 for e in riichi_events if e['ai_recommends_riichi'])
print(f'AIリーチ推奨: {ai_riichi} ({ai_riichi/total*100:.1f}%)')
print()

# === 待ち牌の残り枚数別 ===
print('=== 待ち牌合計残り枚数別 ===')
total_bins = [(0, 2), (3, 4), (5, 6), (7, 8), (9, 12), (13, 99)]
for lo, hi in total_bins:
    subset = [e for e in riichi_events if lo <= e['wait_remaining_total'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
        print(f'  待ち{lo}-{hi}枚: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')

print()
print('=== 平均残り枚数 (平均=総和/種類数) 別 ===')
avg_bins = [(0, 1.0), (1.0, 1.5), (1.5, 2.0), (2.0, 2.5), (2.5, 4.0)]
for lo, hi in avg_bins:
    subset = [e for e in riichi_events if lo <= e['avg_wait_remaining'] < hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
        print(f'  平均{lo:.1f}-{hi:.1f}枚: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')

# 待ちが壁にある種類数
print()
print('=== 壁にある待ち種類数別 ===')
wcbins = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 99)]
for lo, hi in wcbins:
    subset = [e for e in riichi_events if lo <= e['wait_count_in_wall'] <= hi]
    if subset:
        riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
        print(f'  壁{lo}-{hi}種: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')

# 翻数 × 待ち合計枚数
print()
print('=== 翻数 × 待ち合計枚数 クロス集計 ===')
han_levels = [(1, 2), (3, 3), (4, 4), (5, 5), (6, 99)]
for han_lo, han_hi in han_levels:
    han_label = f'{han_lo}翻' if han_lo == han_hi else f'{han_lo}-{han_hi}翻'
    subset_han = [e for e in riichi_events if han_lo <= e['han'] <= han_hi]
    if not subset_han: continue
    print(f'【{han_label}】 人間リーチ: {len(subset_han)}件')
    for lo, hi in total_bins:
        subset = [e for e in subset_han if lo <= e['wait_remaining_total'] <= hi]
        if not subset: continue
        riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
        print(f'  待ち{lo}-{hi}枚: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')
    print()
