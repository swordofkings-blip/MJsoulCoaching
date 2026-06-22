"""
@title ベタオリミスマッチ分析(1万戦規模)
@description
    各局面で人間が何を選んだか(押す/オリる/中立)を分析。
    人間は他家リーチに対してどう行動したかを集計する。

    状況:
    - 対家リーチ中、自分の手番
    - 自分の手牌状態(シャンテン数、待ち、手役、ドラ)
    - 自分の手牌の安牌数
    - 自分の点数、巡目

    判定:
    - 人間が「押した」: 自分から他家リーチ牌にロンできそうな牌を切らない、
                        もしくは他家に振り込まない/好形を目指す打牌
    - 人間が「オリた」: 安全牌を確実に通す打牌
"""
import json
import sys
import sqlite3
import os
import time
import pickle
from collections import Counter, defaultdict
from typing import List, Tuple

sys.path.insert(0, '.')
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id, hand_to_counts, id_to_tile
from core.strategy_manager import ShantenCalculator
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions

with open('config/config_parameters.json', encoding='utf-8') as f:
    params = json.load(f)

# Load 10k log IDs
id_file = 'tools/_log_ids_10000.txt'
with open(id_file) as f:
    ids = [line.strip() for line in f if line.strip()]
print(f'対象ログ数: {len(ids)}')

db_path = 'diffusion-ai/data/raw/tenhou_logs.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()
BATCH = 2000
all_data = []  # (log_id, seat, kyoku, turn, shanten, my_hand, scores, has_reach, discard, classification)
processed = 0
skipped = 0
t_start = time.time()

for batch_start in range(0, len(ids), BATCH):
    batch_ids = ids[batch_start:batch_start+BATCH]
    placeholders = ','.join(['?'] * len(batch_ids))
    cur.execute(f'SELECT id, log FROM logs WHERE id IN ({placeholders})', batch_ids)
    rows = cur.fetchall()

    for log_id, blob in rows:
        processed += 1
        if processed % 500 == 0:
            elapsed = time.time() - t_start
            print(f'処理: {processed}/{len(ids)} ({elapsed:.0f}s, {len(all_data)}件, {skipped}skip)', flush=True)
        try:
            json_dict, n_rounds = tenhou_blob_to_actions(blob)
        except:
            skipped += 1
            continue
        if n_rounds == 0:
            skipped += 1
            continue
        actions = json_dict.get('detail_records', {}).get('actions', [])
        if not actions: continue

        states = [GameState() for _ in range(4)]
        for s in range(4):
            states[s].my_seat = s
        awaiting = [False] * 4
        # Track riichi states per seat
        any_reach_declarer = [-1] * 4  # seat -> seat of who declared riichi against them, -1 if none

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
                any_reach_declarer = [-1] * 4
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

                # Check BEFORE this discard: was there an opponent reach?
                # At this point, reach states from previous discards are reflected.
                reachers = [s for s in range(4) if states[s].reach_states[s].is_reach and s != seat]
                if reachers and not isL and awaiting[seat]:
                    # 自分手番、他家リーチ中、人間がオリた/押した
                    hand = list(states[seat].my_hand)
                    # 14(closed) or 11(3 melds) or 8(4 melds) - these are valid hand sizes for discarding
                    if hand and len(hand) in (8, 11, 14):
                        try:
                            hand_counts = hand_to_counts(hand)
                            shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
                            my_score = states[seat].scores[seat]
                            my_rank = sorted(states[seat].scores, reverse=True).index(my_score) + 1
                            turn = (states[seat].tsumo_count - 1) // 4 + 1
                            reach_turns = [states[s].reach_states[s].reach_turn for s in reachers]
                            reach_turn = reach_turns[0] if reach_turns else 0
                            kyoku = states[seat].chang * 4 + states[seat].ju + 1
                            t_us = tile

                            from core.evaluator import DefenseEvaluator
                            d_eval = DefenseEvaluator(states[seat], params=params)
                            defense_score = d_eval.defense_score_for_tile(t_us) if hasattr(d_eval, 'defense_score_for_tile') else 0

                            all_data.append({
                                'log_id': log_id,
                                'seat': seat,
                                'kyoku': kyoku,
                                'turn': turn,
                                'reach_turn': reach_turn,
                                'reach_seat': reachers[0],
                                'shanten': shanten,
                                'hand_size': len(hand),
                                'discard_tile': t_us,
                                'defense_score': defense_score,
                                'my_score': my_score,
                                'my_rank': my_rank,
                                'scores': list(states[seat].scores),
                                'doras': list(states[seat].doras),
                                'is_dealer': (seat == states[seat].dealer_seat),
                                'ben': states[seat].ben,
                                'reach_n': len(reachers),
                            })
                        except Exception as e:
                            pass

                if isL and awaiting[seat]:
                    any_reach_declarer[seat] = seat

                for s in range(4):
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

    # Save batch
    with open('betadata_full.pkl', 'wb') as f:
        pickle.dump(all_data, f)

conn.close()
print(f'\n=== 完了 ===')
print(f'総局面数: {len(all_data)}件')
print(f'処理時間: {time.time() - t_start:.0f}秒')

# サンプル表示
if all_data:
    print('\n=== サンプル 5件 ===')
    for d in all_data[:5]:
        print(f'  {d["log_id"][-8:]} seat={d["seat"]} 局{d["kyoku"]} 巡目{d["turn"]} シャンテン{d["shanten"]} '
              f'切った牌={d["discard_tile"]} 安全度={d["defense_score"]} 自分={d["my_score"]}({d["my_rank"]}位)')
