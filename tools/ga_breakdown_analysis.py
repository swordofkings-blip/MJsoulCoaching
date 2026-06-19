# -*- coding: utf-8 -*-
"""
@title 詳細内訳分析: 巡目・シャンテン・他家状況・着順ごとの一致率
@description
    10 ログの天鳳牌譜について、捨牌判定の一致/不一致を
    各種条件 (巡目ブロック, シャンテン数, 他家リーチ, 着順, 局数) で
    分類集計する。

    また top-1 / top-2 / top-3 一致率 (人間の打牌が AI 上位 N 位に入るか)
    も測定する。
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict, Counter

THIS_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(THIS_DIR)
sys.path.insert(0, ROOT_DIR)
sys.path.insert(0, THIS_DIR)

from core.game_state import GameState
from core.evaluator import Evaluator
from core.strategy_manager import ShantenCalculator
from core.str_converter import tile_to_id
from tenhou_xml_to_actions import tenhou_blob_to_actions
from ga_fitness import _load_ids, _load_blobs


def analyze_logs(blobs: list, params: dict) -> dict:
    """
    全ログを逐次処理し、条件別の集計結果を返す。
    """
    # 集計用構造
    by_turn = {'序盤(1-6)': {'match': 0, 'total': 0},
               '中盤(7-12)': {'match': 0, 'total': 0},
               '終盤(13+)': {'match': 0, 'total': 0}}
    by_shanten = {'0以下(テンパイ)': {'match': 0, 'total': 0},
                  '1(一向聴)': {'match': 0, 'total': 0},
                  '2(二向聴)': {'match': 0, 'total': 0},
                  '3以上(三向聴+)': {'match': 0, 'total': 0}}
    by_opp_reach = {'平場(リーチ0)': {'match': 0, 'total': 0},
                    'リーチ1': {'match': 0, 'total': 0},
                    'リーチ2+': {'match': 0, 'total': 0}}
    by_rank = {'トップ(0)': {'match': 0, 'total': 0},
               '2位(1)': {'match': 0, 'total': 0},
               '3位(2)': {'match': 0, 'total': 0},
               'ラス(3)': {'match': 0, 'total': 0}}
    by_kyoku = {'東1-4(序盤)': {'match': 0, 'total': 0},
                '南1-4(終盤)': {'match': 0, 'total': 0}}
    by_moqie = {'ツモ切り': {'match': 0, 'total': 0},
                '手出し': {'match': 0, 'total': 0}}
    by_opp_open = {'平場(副露0)': {'match': 0, 'total': 0},
                   '副露1+': {'match': 0, 'total': 0}}

    top1_match = 0
    top2_match = 0
    top3_match = 0
    total_decisions = 0

    for bidx, (log_id, blob) in enumerate(blobs):
        json_dict, n_rounds = tenhou_blob_to_actions(blob)
        if n_rounds == 0:
            continue
        actions = json_dict.get('detail_records', {}).get('actions', [])
        states = [GameState() for _ in range(4)]
        for s in range(4):
            states[s].my_seat = s
        awaiting = [False] * 4

        def reset_ippatsu():
            for s in range(4):
                for rs in states[s].reach_states:
                    rs.is_ippatsu = False

        for idx, a in enumerate(actions):
            if a['type'] != 1:
                continue
            r = a['result']
            cls = r.get('class_name', '')
            d = r.get('data', {})

            if 'dora' in d:
                for s in range(4):
                    states[s].doras = [d['dora']]
            if 'doras' in d:
                for s in range(4):
                    states[s].doras = list(d['doras'])
            if 'liqibang' in d:
                for s in range(4):
                    states[s].liqibang = d['liqibang']

            if cls == 'RecordNewRound':
                for s in range(4):
                    k = f'tiles{s}'
                    states[s].on_new_round(
                        d.get('chang', 0), d.get('ju', 0), d.get('ben', 0),
                        d.get('liqibang', 0), d.get(k, []),
                        d.get('scores', [25000] * 4),
                        d.get('leftTileCount', 70),
                        d.get('doras', [d['dora']] if 'dora' in d else []),
                    )
                    states[s].chang = d.get('chang', 0)
                    states[s].ju = d.get('ju', 0)
                awaiting = [True] * 4

            elif cls == 'RecordDealTile':
                seat = d['seat']
                tile = d['tile']
                for s in range(4):
                    if s == seat:
                        states[s].on_self_draw(tile)
                    else:
                        states[s].on_opponent_draw(seat)
                awaiting[seat] = True

            elif cls == 'RecordDiscardTile':
                seat = d['seat']
                tile = d['tile']
                isL = d.get('isLiqi', False)
                moq = d.get('moqie', False)

                if awaiting[seat]:
                    hand = list(states[seat].my_hand)
                    if len(hand) % 3 == 2:
                        is_riichi_self = states[seat].reach_states[seat].is_reach
                        if not is_riichi_self:
                            total_decisions += 1
                            ev = Evaluator(states[seat], params)

                            # 全スコア取得 (score_all_tiles 相当)
                            raw_eval = Evaluator.evaluate_tile
                            # キャッシュで重複回避
                            from collections import OrderedDict
                            from tenhou_process_dict import _cached_evaluate_tile, _reset_eval_cache
                            _reset_eval_cache()
                            unique_tiles = list(dict.fromkeys(hand))
                            scored = [(self._cached_evaluate_tile if hasattr(ev, '_cached_evaluate_tile') else ev.evaluate_tile)(t) for t in unique_tiles]
                            # 最も簡単な方法: evaluate_tile を直接呼ぶ
                            scored = [(ev.evaluate_tile(t), t) for t in unique_tiles]
                            scored.sort(key=lambda x: (-x[0], x[1]))
                            rank = next((i+1 for i, (s, t) in enumerate(scored) if t == tile), None)

                            if rank == 1:
                                top1_match += 1
                            if rank is not None and rank <= 2:
                                top2_match += 1
                            if rank is not None and rank <= 3:
                                top3_match += 1

                            is_matched = (rank == 1)

                            # --- 条件別集計 ---
                            state = states[seat]
                            turn = (state.tsumo_count - 1) // 4 + 1
                            scores = state.scores
                            rank_self = state.my_score_rank()
                            opp_reach = sum(1 for i in range(4) if i != seat and state.reach_states[i].is_reach)
                            opp_open = sum(1 for i in range(4) if i != seat and sum(1 for m in state.melds[i] if m.is_open) > 0)
                            hand_counts = state.my_hand_counts()
                            open_meld_count = sum(1 for m in state.my_melds if m.is_open)
                            if open_meld_count == 0:
                                shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
                            else:
                                shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
                            kyoku_chang = state.chang

                            # 巡目ブロック
                            if turn <= 6:
                                key = '序盤(1-6)'
                            elif turn <= 12:
                                key = '中盤(7-12)'
                            else:
                                key = '終盤(13+)'
                            by_turn[key]['total'] += 1
                            if is_matched:
                                by_turn[key]['match'] += 1

                            # シャンテンブロック
                            if shanten <= 0:
                                key = '0以下(テンパイ)'
                            elif shanten == 1:
                                key = '1(一向聴)'
                            elif shanten == 2:
                                key = '2(二向聴)'
                            else:
                                key = '3以上(三向聴+)'
                            by_shanten[key]['total'] += 1
                            if is_matched:
                                by_shanten[key]['match'] += 1

                            # 他家リーチ
                            if opp_reach == 0:
                                key = '平場(リーチ0)'
                            elif opp_reach == 1:
                                key = 'リーチ1'
                            else:
                                key = 'リーチ2+'
                            by_opp_reach[key]['total'] += 1
                            if is_matched:
                                by_opp_reach[key]['match'] += 1

                            # 副露数
                            if opp_open == 0:
                                key = '平場(副露0)'
                            else:
                                key = '副露1+'
                            by_opp_open[key]['total'] += 1
                            if is_matched:
                                by_opp_open[key]['match'] += 1

                            # 着順
                            key = {0: 'トップ(0)', 1: '2位(1)', 2: '3位(2)', 3: 'ラス(3)'}.get(rank_self, '?')
                            by_rank[key]['total'] += 1
                            if is_matched:
                                by_rank[key]['match'] += 1

                            # 局
                            if kyoku_chang == 0:
                                key = '東1-4(序盤)'
                            else:
                                key = '南1-4(終盤)'
                            by_kyoku[key]['total'] += 1
                            if is_matched:
                                by_kyoku[key]['match'] += 1

                            # ツモ切り/手出し
                            key = 'ツモ切り' if moq else '手出し'
                            by_moqie[key]['total'] += 1
                            if is_matched:
                                by_moqie[key]['match'] += 1

                awaiting[seat] = False
                for s in range(4):
                    states[s].on_discard(seat, tile, isL, moq)
                reset_ippatsu()

            elif cls == 'RecordChiPengGang':
                for s in range(4):
                    states[s].on_chi_peng_gang(
                        d['type'], d['seat'], d['tiles'],
                        d.get('froms', []), d.get('tileStates', []),
                    )
                awaiting[d['seat']] = True
                reset_ippatsu()

            elif cls == 'RecordAnGangAddGang':
                for s in range(4):
                    states[s].on_an_gang_add_gang(d['type'], d['seat'], d['tiles'])

            elif cls in ('RecordHule', 'RecordNoTile'):
                awaiting = [False] * 4

    # 結果整形
    result = {}
    for name, data in [('by_turn', by_turn), ('by_shanten', by_shanten),
                       ('by_opp_reach', by_opp_reach), ('by_rank', by_rank),
                       ('by_kyoku', by_kyoku), ('by_moqie', by_moqie),
                       ('by_opp_open', by_opp_open)]:
        rows_list = []
        for k, v in data.items():
            rows_list.append({
                'category': k,
                'match': v['match'],
                'total': v['total'],
                'rate': round(v['match'] / v['total'] * 100, 2) if v['total'] else 0.0,
            })
        result[name] = rows_list

    result['top_accuracy'] = {
        'top1_count': top1_match,
        'top2_count': top2_match,
        'top3_count': top3_match,
        'total': total_decisions,
        'top1_rate': round(top1_match / total_decisions * 100, 2) if total_decisions else 0.0,
        'top2_rate': round(top2_match / total_decisions * 100, 2) if total_decisions else 0.0,
        'top3_rate': round(top3_match / total_decisions * 100, 2) if total_decisions else 0.0,
    }
    return result


def main():
    with open('config/config_parameters.json', encoding='utf-8') as f:
        params = json.load(f)

    ids = _load_ids('tools/_log_ids_ga.txt')
    rows = _load_blobs('diffusion-ai/data/raw/tenhou_logs.db', ids)
    blobs = [(r[0], r[1]) for r in rows]
    print(f'[setup] {len(blobs)} logs', flush=True)

    t0 = time.time()
    result = analyze_logs(blobs, params)
    elapsed = time.time() - t0

    print(f'\n=== 詳細内訳分析 (time={elapsed:.1f}s) ===\n', flush=True)

    sections = [
        ('① 巡目別一致率', 'by_turn'),
        ('② シャンテン数別一致率', 'by_shanten'),
        ('③ 他家リーチ数別一致率', 'by_opp_reach'),
        ('④ 他家副露数別一致率', 'by_opp_open'),
        ('⑤ 着順別一致率', 'by_rank'),
        ('⑥ 東南戦局別一致率', 'by_kyoku'),
        ('⑦ ツモ切り/手出し別一致率', 'by_moqie'),
    ]

    for title, key in sections:
        print(f'--- {title} ---')
        for row in result[key]:
            pct = row['rate']
            print(f'  {row["category"]:<20s}: {row["match"]:>4d}/{row["total"]:<4d} = {pct:.1f}%')
        print()

    print(f'--- top-N 一致率 ---')
    ta = result['top_accuracy']
    print(f'  top-1: {ta["top1_count"]}/{ta["total"]} = {ta["top1_rate"]:.1f}%')
    print(f'  top-2: {ta["top2_count"]}/{ta["total"]} = {ta["top2_rate"]:.1f}%')
    print(f'  top-3: {ta["top3_count"]}/{ta["total"]} = {ta["top3_rate"]:.1f}%')

    # JSON保存
    with open('breakdown_analysis.json', 'w', encoding='utf-8') as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print(f'\nsaved: breakdown_analysis.json', flush=True)


if __name__ == '__main__':
    main()
