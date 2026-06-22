"""
Analyze the 64 false cases (human riichi but rule said False)
and see if we can refine the rules.
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
    ids = [l.strip() for l in f if l.strip()]

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({",".join(["?"] * len(ids))})', ids)
rows = cur.fetchall()
conn.close()

missed_cases = []  # ルールがFalse だが人間がリーチ
processed = 0

for log_id, blob in rows:
    processed += 1
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
                            rule_result = ev._rule_based_should_riichi()
                            if rule_result == False:  # Missed case
                                han = estimate_han_advanced(
                                    states[seat].my_hand, states[seat].my_melds, states[seat].doras,
                                    is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
                                    seat=states[seat].my_seat, chang=states[seat].chang, ju=states[seat].ju
                                )
                                han = max(han, 1)
                                wait_total = ev._wait_remaining_total()
                                dora = ev._count_dora_in_hand()
                                yakuhai = ev._count_yakuhai_in_hand()
                                ura = ev._count_ura_candidates_in_wall()
                                turn = (states[seat].tsumo_count - 1) // 4 + 1
                                is_dealer = (seat == states[seat].dealer_seat)
                                my_score = states[seat].scores[states[seat].my_seat]
                                rank = sorted(states[seat].scores, reverse=True).index(my_score) + 1
                                wait_tiles = ev._wait_tiles_for_tenpai()
                                n_wait_types = len(wait_tiles)

                                missed_cases.append({
                                    'log_id': log_id, 'seat': seat,
                                    'han': han, 'wait_total': wait_total,
                                    'dora': dora, 'yakuhai': yakuhai, 'ura': ura,
                                    'turn': turn, 'is_dealer': is_dealer, 'rank': rank,
                                    'n_wait_types': n_wait_types, 'my_score': my_score,
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

print(f'ルールがFalse判定した{missed_cases and "human" or "no"}リーチケース: {len(missed_cases)}件')
print()

# 分析
if missed_cases:
    han_counter = Counter(c['han'] for c in missed_cases)
    print('=== 翻数分布 ===')
    for h in sorted(han_counter.keys()):
        print(f'  {h}翻: {han_counter[h]}件')

    # 待ち枚数
    wt_counter = Counter()
    for c in missed_cases:
        if c['wait_total'] <= 4: wt_counter['0-4'] += 1
        elif c['wait_total'] <= 6: wt_counter['5-6'] += 1
        elif c['wait_total'] <= 8: wt_counter['7-8'] += 1
        elif c['wait_total'] <= 12: wt_counter['9-12'] += 1
        else: wt_counter['13+'] += 1
    print('=== 待ち枚数分布 ===')
    for k in ['0-4', '5-6', '7-8', '9-12', '13+']:
        if wt_counter[k]: print(f'  {k}枚: {wt_counter[k]}件')

    # ドラ持ち
    print('=== ドラ持ち ===')
    d0 = sum(1 for c in missed_cases if c['dora'] == 0)
    d1 = sum(1 for c in missed_cases if c['dora'] >= 1)
    print(f'  ドラ0枚: {d0}件 / ドラ1+枚: {d1}件')

    # 役牌
    print('=== 役牌数 ===')
    y0 = sum(1 for c in missed_cases if c['yakuhai'] == 0)
    y1 = sum(1 for c in missed_cases if c['yakuhai'] >= 1)
    print(f'  役牌0枚: {y0}件 / 役牌1+枚: {y1}件')

    # 巡目
    print('=== 巡目 ===')
    t_counter = Counter()
    for c in missed_cases:
        if c['turn'] <= 5: t_counter['1-5'] += 1
        elif c['turn'] <= 8: t_counter['6-8'] += 1
        elif c['turn'] <= 11: t_counter['9-11'] += 1
        elif c['turn'] <= 14: t_counter['12-14'] += 1
        else: t_counter['15+'] += 1
    for k in ['1-5', '6-8', '9-11', '12-14', '15+']:
        if t_counter[k]: print(f'  巡目{k}: {t_counter[k]}件')

    # 順位
    print('=== 順位 ===')
    r_counter = Counter(c['rank'] for c in missed_cases)
    for r in [1, 2, 3, 4]:
        print(f'  {r}位: {r_counter[r]}件')

    # Show first 10 cases
    print()
    print('=== サンプル (最初の20件) ===')
    for c in missed_cases[:20]:
        print(f'  log={c["log_id"][-8:]} seat={c["seat"]} han={c["han"]} 待ち{c["wait_total"]}枚 ドラ{c["dora"]} 役牌{c["yakuhai"]} 巡目{c["turn"]} 親={c["is_dealer"]} {c["rank"]}位 待ち種類{c["n_wait_types"]}')
