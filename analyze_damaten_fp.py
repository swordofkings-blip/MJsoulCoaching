"""
Analyze damaten false positives (human damaten but AI says riichi)
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
    ids = [l.strip() for l in f if l.strip()][:100]  # 100件だけ

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
placeholders = ','.join(['?'] * len(ids))
cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', ids)
rows = cur.fetchall()
conn.close()

false_positive = []  # 人間ダマテンだがAIリーチ推奨
true_positive = []  # 人間ダマテンでAIもダマテン推奨
processed = 0

for log_id, blob in rows:
    processed += 1
    try:
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
    except:
        continue
    if n_rounds == 0:
        continue
    actions = json_dict.get('detail_records', {}).get('actions', [])
    if not actions:
        continue

    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    for a in actions:
        if a.get('type') != 1:
            continue
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
                if s != oya:
                    states[s].dealer_seat = oya
            awaiting = [True] * 4
            continue

        if cls == 'RecordDealTile':
            seat = d.get('seat')
            tile = d.get('tile')
            if seat is None or tile is None:
                continue
            for s in range(4):
                if s == seat:
                    states[s].on_self_draw(tile)
                else:
                    states[s].on_opponent_draw(seat)
            if 0 <= seat < 4:
                awaiting[seat] = True
            continue

        if cls == 'RecordDiscardTile':
            seat = d.get('seat')
            tile = d.get('tile')
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if seat is None or seat < 0 or seat >= 4:
                continue

            if not isL and awaiting[seat]:
                # 人間がダマテン
                hand = list(states[seat].my_hand)
                if hand and len(hand) % 3 == 2:
                    hand_counts = hand_to_counts(hand)
                    sh = ShantenCalculator.calculate_closed_effective(hand_counts)
                    if sh <= 0:
                        try:
                            ev = Evaluator(states[seat], params)
                            ai_should = ev.should_riichi()
                            han = max(estimate_han_advanced(
                                states[seat].my_hand, states[seat].my_melds, states[seat].doras,
                                is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
                                seat=states[seat].my_seat, chang=states[seat].chang, ju=states[seat].ju
                            ), 1)
                            rule = ev._rule_based_should_riichi()
                            wait_total = ev._wait_remaining_total()
                            info = {
                                'han': han, 'rule': rule, 'wait_total': wait_total,
                                'is_dealer': (seat == states[seat].dealer_seat),
                                'has_opp_reach': states[seat].is_any_opponent_reach(),
                                'turn': (states[seat].tsumo_count - 1) // 4 + 1,
                            }
                            if ai_should:
                                false_positive.append(info)
                            else:
                                true_positive.append(info)
                        except Exception as e:
                            pass

            for s in range(4):
                if s == seat:
                    states[s].on_discard(seat, tile, isL, moq)
            if 0 <= seat < 4:
                awaiting[seat] = False
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

print(f'人間ダマテン総数: {len(false_positive) + len(true_positive)}件')
print(f'  AIリーチ推奨 (mismatch): {len(false_positive)}件 ({len(false_positive)/(len(false_positive)+len(true_positive))*100:.1f}%)')
print(f'  AIダマテン推奨 (match): {len(true_positive)}件 ({len(true_positive)/(len(false_positive)+len(true_positive))*100:.1f}%)')
print()

# 偽陽性の分析
if false_positive:
    print('=== 偽陽性 (人間がダマテンしたのにAIがリーチ推奨) の特徴 ===')
    han_counter = Counter(c['han'] for c in false_positive)
    print('翻数:')
    for h in sorted(han_counter.keys()):
        print(f'  {h}翻: {han_counter[h]}件')

    print('ルール判定:')
    rule_counter = Counter(c['rule'] for c in false_positive)
    for r, n in rule_counter.most_common():
        print(f'  rule={r}: {n}件')

    print('巡目:')
    t_counter = Counter()
    for c in false_positive:
        if c['turn'] <= 5: t_counter['1-5'] += 1
        elif c['turn'] <= 8: t_counter['6-8'] += 1
        elif c['turn'] <= 11: t_counter['9-11'] += 1
        elif c['turn'] <= 14: t_counter['12-14'] += 1
        else: t_counter['15+'] += 1
    for k in ['1-5', '6-8', '9-11', '12-14', '15+']:
        if t_counter[k]: print(f'  {k}: {t_counter[k]}件')

    # 詳細
    print('=== 偽陽性ケースの代表例 (最初の20件) ===')
    for c in false_positive[:20]:
        print(f'  han={c["han"]} 待ち{c["wait_total"]}枚 親={c["is_dealer"]} opp_reach={c["has_opp_reach"]} 巡目{c["turn"]} rule={c["rule"]}')
