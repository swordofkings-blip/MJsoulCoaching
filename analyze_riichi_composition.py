"""
Detailed analysis of WHY humans riichi at each han level.
Look at hand composition: dora, yakuhai, sanshoku/ittsuu potential.
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

# Hand composition analysis
riichi_events = []
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
                            riichi_ev, damaten_ev = ev._compare_riichi_vs_damaten()

                            # Hand composition
                            hand_counter = Counter(hand)
                            doras = states[seat].doras
                            dora_in_hand = sum(hand_counter.get(d, 0) for d in doras if d)

                            # 役牌判定 (場風・自風・三元)
                            bakaze = ['E', 'S', 'W', 'N'][states[seat].chang % 4]
                            jikaze = ['E', 'S', 'W', 'N'][seat]
                            jihai = ['h', 'g', 'r']  # 白発中
                            yakuhai_count = 0
                            if f'{bakaze}p' in hand_counter: yakuhai_count += hand_counter[f'{bakaze}p']
                            if f'{jikaze}p' in hand_counter: yakuhai_count += hand_counter[f'{jikaze}p']
                            for j in jihai:
                                if f'{j}h' in hand_counter: yakuhai_count += hand_counter[f'{j}h']

                            # ドラ候補 (裏ドラ含め、ドラ表示牌の次の牌)
                            # ドラは表示牌の次の牌(筒/索/萬の1-9のみ、字牌は固定対応)
                            visible = states[seat].all_visible_counts()
                            from core.str_converter import tile_to_id
                            ura_count = 0
                            for dd in doras:
                                if not dd: continue
                                tid = tile_to_id(dd)
                                if 0 <= tid < 34:
                                    ura_count += max(0, 4 - visible[tid])

                            # 待ち牌 (実際の上がり牌)
                            wait_tiles = ev._wait_tiles_for_tenpai()
                            n_wait_types = len(wait_tiles)
                            wait_safety = 0
                            for w in wait_tiles:
                                tid = tile_to_id(w) if w in [id_to_tile(i) for i in range(34)] else -1
                                if tid >= 0 and visible[tid] < 4:
                                    wait_safety += 1

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
                                'dora_in_hand': dora_in_hand, 'ura_count': ura_count,
                                'yakuhai_count': yakuhai_count,
                                'wait_tiles': wait_tiles, 'wait_safety': wait_safety,
                                'my_score': my_score, 'rank': rank,
                                'mode': mode, 'is_dealer': is_dealer,
                                'has_opp_reach': states[seat].is_any_opponent_reach(),
                                'left_tiles': left_tiles,
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

# Save
with open('riichi_events_v2.pkl', 'wb') as f:
    pickle.dump(riichi_events, f)
print(f'人間リーチ宣言: {len(riichi_events)}件保存')

# Analysis
total = len(riichi_events)
ai_riichi = [e for e in riichi_events if e['riichi_ev'] > e['damaten_ev']]
ai_damaten = [e for e in riichi_events if e['riichi_ev'] <= e['damaten_ev']]
print(f'AIリーチ推奨: {len(ai_riichi)} ({len(ai_riichi)/total*100:.1f}%)')
print(f'AIダマテン推奨: {len(ai_damaten)} ({len(ai_damaten)/total*100:.1f}%)')
print()

# Detailed analysis by han level: composition breakdown
print('=== 翻数×ドラ持ち/役牌数のクロス集計 ===')
print('各セル: 人間リーチ件数 (AIリーチ推奨率%)')
print()
han_levels = [(1, 1), (2, 2), (3, 3), (4, 4), (5, 5), (6, 6), (7, 99)]
dora_levels = [(0, 0), (1, 1), (2, 2), (3, 99)]
for han_lo, han_hi in han_levels:
    han_label = f'{han_lo}翻' if han_lo == han_hi else f'{han_lo}-{han_hi}翻'
    subset_han = [e for e in riichi_events if han_lo <= e['han'] <= han_hi]
    if not subset_han: continue
    print(f'【{han_label}】 人間リーチ: {len(subset_han)}件')
    for dora_lo, dora_hi in dora_levels:
        dora_label = f'ドラ{dora_lo}枚' if dora_lo == dora_hi else f'ドラ{dora_lo}+枚'
        subset = [e for e in subset_han if dora_lo <= e['dora_in_hand'] <= dora_hi]
        if not subset: continue
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  {dora_label}: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')
    print()

# Han level × yakuhai
print('=== 翻数×役牌数のクロス集計 ===')
for han_lo, han_hi in han_levels:
    han_label = f'{han_lo}翻' if han_lo == han_hi else f'{han_lo}-{han_hi}翻'
    subset_han = [e for e in riichi_events if han_lo <= e['han'] <= han_hi]
    if not subset_han: continue
    print(f'【{han_label}】 人間リーチ: {len(subset_han)}件')
    for yaku_lo, yaku_hi in [(0, 0), (1, 1), (2, 2), (3, 99)]:
        yaku_label = f'役牌{yaku_lo}枚' if yaku_lo == yaku_hi else f'役牌{yaku_lo}+枚'
        subset = [e for e in subset_han if yaku_lo <= e['yakuhai_count'] <= yaku_hi]
        if not subset: continue
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  {yaku_label}: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')
    print()

# Han × ura_count
print('=== 翻数×ドラ候補(壁)数のクロス集計 ===')
for han_lo, han_hi in han_levels:
    han_label = f'{han_lo}翻' if han_lo == han_hi else f'{han_lo}-{han_hi}翻'
    subset_han = [e for e in riichi_events if han_lo <= e['han'] <= han_hi]
    if not subset_han: continue
    print(f'【{han_label}】 人間リーチ: {len(subset_han)}件')
    for ura_lo, ura_hi in [(0, 0), (1, 1), (2, 2), (3, 3), (4, 99)]:
        ura_label = f'ドラ候補{ura_lo}枚' if ura_lo == ura_hi else f'ドラ候補{ura_lo}+枚'
        subset = [e for e in subset_han if ura_lo <= e['ura_count'] <= ura_hi]
        if not subset: continue
        riichi_count = sum(1 for e in subset if e['riichi_ev'] > e['damaten_ev'])
        print(f'  {ura_label}: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')
    print()

# What if the 段UP criterion drives this?
# 4翻→跳満, 5翻→跳満, 6翻→倍満, 7翻→倍満, 8翻→三倍満
# "段UP閾値までの距離" で判断する
print('=== 次の段UPまでの距離 (高いほどリーチ価値低) ===')
# 4翻→1, 5翻→1, 6翻→1, 7翻→1, 8翻→1  (裏ドラ1枚で次段)
# 3翻→2 (リーチ+ドラ2枚で満貫)
def upgrade_distance(han):
    """リーチ+ドラ何枚で次の段UPするか"""
    if han <= 3: return 3 - han + 1  # 3翻以下: (4-han+1)枚ドラ必要
    if han == 4: return 2  # 4翻(満貫)→跳満: ドラ2枚
    if han == 5: return 2  # 5翻(満貫)→跳満: ドラ2枚
    if han == 6: return 2  # 6翻(跳満)→倍満: ドラ2枚
    if han == 7: return 2  # 7翻(跳満)→倍満: ドラ2枚
    if han == 8: return 2  # 8翻(倍満)→三倍満: ドラ2枚
    if han == 9: return 2  # 9翻(倍満)→三倍満: ドラ2枚
    if han == 10: return 2  # 10翻(三倍満)→数え役満: ドラ2枚
    if han == 11: return 2  # 11翻(三倍満)→数え役満: ドラ2枚
    if han == 12: return 2  # 12翻(三倍満)→数え役満: ドラ2枚
    if han >= 13: return 99  # 役満: ドラ関係なし
    return 2

for e in riichi_events:
    e['upgrade_dist'] = upgrade_distance(e['han'])
    e['ai_recommends_riichi'] = e['riichi_ev'] > e['damaten_ev']

print('人間リーチの段UP距離分布:')
dist_counter = Counter(e['upgrade_dist'] for e in riichi_events)
for d in sorted(dist_counter.keys()):
    subset = [e for e in riichi_events if e['upgrade_dist'] == d]
    riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
    print(f'  段UP距離{d}: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')

# 4翻 vs 5翻 (両方「満貫」だが、人間は5翻でもリーチしている)
print()
print('=== 満貫同士の比較: 4翻 vs 5翻 ===')
for han in [4, 5]:
    subset = [e for e in riichi_events if e['han'] == han]
    if subset:
        riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
        print(f'  {han}翻: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')

# 跳満同士: 6翻 vs 7翻
print()
print('=== 跳満同士の比較: 6翻 vs 7翻 ===')
for han in [6, 7]:
    subset = [e for e in riichi_events if e['han'] == han]
    if subset:
        riichi_count = sum(1 for e in subset if e['ai_recommends_riichi'])
        print(f'  {han}翻: {len(subset)}件 (AI推奨 {riichi_count/len(subset)*100:.1f}%)')
