# -*- coding: utf-8 -*-
"""
ミスマッチ抽出スクリプト
- 玉座の間の牌譜（data/record_*_trimmed.json）を解析
- AIの推奨手と人間の実際の手が一致しなかった局面を抽出
- 外部AIに悪手判定を依頼するためのJSONを出力
"""
import json, sys, glob, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id

with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'config_parameters.json')) as f:
    params = json.load(f)

SEAT_NAMES = ['東', '南', '西', '北']

paths = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'record_*_trimmed.json')))

all_mismatches = []
total_discard_decisions = 0
discard_matches = 0

for path in paths:
    with open(path, encoding='utf-8') as f:
        data = json.load(f)
    actions = data.get('detail_records', {}).get('actions', [])
    states = [GameState() for _ in range(4)]
    for s in range(4):
        states[s].my_seat = s
    awaiting = [False] * 4

    def reset_ippatsu():
        for s in range(4):
            for rs in states[s].reach_states:
                rs.is_ippatsu = False

    for a in actions:
        if a['type'] != 1:
            continue
        r = a['result']
        cls = r['class_name']
        d = r['data']

        if 'dora' in d:
            for s in range(4): states[s].doras = [d['dora']]
        if 'doras' in d:
            for s in range(4): states[s].doras = list(d['doras'])
        if 'liqibang' in d:
            for s in range(4): states[s].liqibang = d['liqibang']

        if cls == 'RecordNewRound':
            for s in range(4):
                k = f'tiles{s}'
                states[s].on_new_round(
                    d.get('chang', 0), d.get('ju', 0), d.get('ben', 0),
                    d.get('liqibang', 0), d.get(k, []),
                    d.get('scores', [25000] * 4),
                    d.get('leftTileCount', 70),
                    d.get('doras', [d['dora']] if 'dora' in d else [])
                )
                states[s].chang = d.get('chang', 0)
                states[s].ju = d.get('ju', 0)
            awaiting = [True] * 4

        elif cls == 'RecordDealTile':
            seat = d['seat']
            tile = d['tile']
            for s in range(4):
                if s == seat: states[s].on_self_draw(tile)
                else: states[s].on_opponent_draw(seat)
            awaiting[seat] = True

        elif cls == 'RecordDiscardTile':
            seat = d['seat']
            tile = d['tile']
            isL = d.get('isLiqi', False)
            moq = d.get('moqie', False)

            if awaiting[seat]:
                hand = list(states[seat].my_hand)
                if len(hand) % 3 == 2:
                    is_riichi = states[seat].reach_states[seat].is_reach
                    if not is_riichi:
                        total_discard_decisions += 1
                        ev = Evaluator(states[seat], params)
                        best = ev.best_discard(hand)
                        if best is None:
                            is_match = True  # skip: no recommendation
                        else:
                            is_exact = (best == tile)
                            is_match = False
                            actual_rating = 100.0
                            if is_exact:
                                is_match = True
                            else:
                                scores = {t: ev.evaluate_tile(t) for t in dict.fromkeys(hand)}
                                best_score = scores.get(best, 0)
                                actual_score = scores.get(tile, min(scores.values()) if scores else 0)

                                range_val = max(best_score - min(scores.values()), params.get('MATCH_MIN_RANGE', 400.0))
                                diff = max(0.0, best_score - actual_score)
                                ratio = max(0.0, 1.0 - diff / range_val)
                                actual_rating = 100.0 * (ratio ** 2)

                                rating_threshold = params.get('MATCH_RATING_THRESHOLD', 90.0)
                                is_match = actual_rating >= rating_threshold

                        if is_match:
                            discard_matches += 1
                        else:
                            s_state = states[seat]
                            atk = ev.attack
                            best_shanten = atk.shanten_after_discard(best)
                            actual_shanten = atk.shanten_after_discard(tile)

                            # Top 3 recommendations for context
                            scored = sorted(scores.items(), key=lambda x: -x[1])
                            top3 = [(t, round(s, 1)) for t, s in scored[:3]]

                            # AI's score breakdown for each tile
                            tile_details = {}
                            for t in [tile, best]:
                                tile_details[t] = {
                                    'score_atk': round(atk.attack_score_for_tile(t), 1),
                                    'score_def': round(ev.defense.defense_score_for_tile(t), 1),
                                    'shanten': atk.shanten_after_discard(t),
                                    'ukeire': atk.ukeire_for_discard(t),
                                }

                            # Game context
                            rivs = [
                                [t for t in s_state.river[i]]
                                for i in range(4)
                            ]
                            reach_states = [
                                s_state.reach_states[i].is_reach
                                for i in range(4)
                            ]

                            all_mismatches.append({
                                'file': os.path.basename(path),
                                'seat': seat,
                                'tsumo': s_state.tsumo_count,
                                'chang': s_state.chang,
                                'ju': s_state.ju,
                                'ben': s_state.ben,
                                'scores': s_state.scores,
                                'doras': s_state.doras,
                                'left_tiles': s_state.left_tile_count,
                                'hand': hand,
                                'river': rivs,
                                'reach': reach_states,
                                'actual': tile,
                                'best': best,
                                'rating': round(actual_rating, 1),
                                'best_actual_gap': round(best_score - actual_score, 1),
                                'top3': top3,
                                'tile_details': tile_details,
                            })

            awaiting[seat] = False
            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)
            reset_ippatsu()

        elif cls == 'RecordChiPengGang':
            for s in range(4):
                states[s].on_chi_peng_gang(
                    d['type'], d['seat'], d['tiles'],
                    d.get('froms', []), d.get('tileStates', [])
                )
            awaiting[d['seat']] = True
            reset_ippatsu()

        elif cls == 'RecordAnGangAddGang':
            for s in range(4):
                states[s].on_an_gang_add_gang(d['type'], d['seat'], d['tiles'])

        elif cls in ('RecordHule', 'RecordNoTile'):
            awaiting = [False] * 4

# Output
rate = (discard_matches / total_discard_decisions * 100) if total_discard_decisions else 0
output = {
    'summary': {
        'files': len(paths),
        'total_decisions': total_discard_decisions,
        'matches': discard_matches,
        'mismatches': len(all_mismatches),
        'match_rate_pct': round(rate, 1),
    },
    'mismatches': all_mismatches,
}

outpath = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'mismatches.json')
with open(outpath, 'w', encoding='utf-8') as f:
    json.dump(output, f, ensure_ascii=False, indent=2)

print(f'Analyzed: {len(paths)} files, {total_discard_decisions} decisions')
print(f'Match rate: {rate:.1f}% ({discard_matches}/{total_discard_decisions})')
print(f'Mismatches exported: {len(all_mismatches)} to {outpath}')
print(f'* Use mismatches.json with a stronger AI to identify actual bad moves')
