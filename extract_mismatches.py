import json, sys, glob, os
sys.path.insert(0, 'C:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー')
from game_state import GameState, ReachState, Meld
from evaluator import Evaluator
from strategy_manager import ShantenCalculator
from str_converter import tile_to_id, id_to_tile, is_honor

with open('config_parameters.json') as f:
    params = json.load(f)

SEAT_NAMES = ['東', '南', '西', '北']

CALL_NAMES = {0: 'チー', 1: 'ポン', 2: '大明槓', 3: '暗槓', 4: '加槓'}

def fmt_tile(t):
    m = {'1z':'東','2z':'南','3z':'西','4z':'北','5z':'白','6z':'發','7z':'中'}
    return m.get(t, t)

lines = []
def out(s=''):
    lines.append(s)

paths = sorted(glob.glob('C:/Users/Daikichi/Documents/code-workspace/雀魂ラッパー/data/record_*_trimmed.json'))

# Statistics counters
total_discard_decisions = 0
discard_matches = 0
total_meld_opportunities = 0
meld_matches = 0
meld_results = []  # (call_type_str, ai_decision, human_decision, turn, mismatch_detail)

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
                    d.get('doras', [d['dora']] if 'dora' in d else [])
                )
                # chang/ju for yaku detection
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

            # Discard agreement check
            if awaiting[seat]:
                hand = list(states[seat].my_hand)
                if len(hand) % 3 == 2:
                    is_riichi = states[seat].reach_states[seat].is_reach
                    if not is_riichi:
                        total_discard_decisions += 1
                        ev = Evaluator(states[seat], params)
                        best = ev.best_discard(hand)
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
                            mid = os.path.basename(path).split('_')[1].split('-')[0]
                            rivs = [' '.join(fmt_tile(t) for t in s_state.river[i]) if s_state.river[i] else 'なし' for i in range(4)]
                            doras_str = ' '.join(fmt_tile(t) for t in s_state.doras) if s_state.doras else 'なし'

                            human_turn = (s_state.tsumo_count - 1) // 4 + 1
                            out(f'===== 捨牌不一致 #{total_discard_decisions} =====')
                            is_dealer = '(親)' if s_state.my_seat == 0 else ''
                            out(f'{SEAT_NAMES[seat]}家{is_dealer} / {s_state.chang*4+s_state.ju+1}局 {s_state.ben}本場 / {human_turn}巡目({s_state.tsumo_count}ツモ) / 残り{s_state.left_tile_count}枚')
                            out(f'点数: {s_state.scores}')
                            out(f'ドラ: {doras_str}')
                            out(f'actual: {fmt_tile(tile)} (Rating: {actual_rating:.1f})  AI: {fmt_tile(best)}')
                            out(f'hand({len(hand)}枚): {hand}')
                            drawn = hand[-1] if len(hand) == 14 else '-'
                            out(f'ツモ: {drawn}')
                            seat_labels = ['自分' if i == seat else SEAT_NAMES[i] for i in range(4)]
                            for i in range(4):
                                r_info = rivs[i]
                                rc_info = ' リーチ' if s_state.reach_states[i].is_reach else ''
                                out(f'  {seat_labels[i]}: {r_info}{rc_info}')
                            out()

            awaiting[seat] = False
            for s in range(4):
                states[s].on_discard(seat, tile, isL, moq)
            reset_ippatsu()

        elif cls == 'RecordChiPengGang':
            call_type = d['type']
            call_seat = d['seat']
            tiles = d['tiles']
            froms = d.get('froms', [])
            tile_states = d.get('tileStates', [])

            # Meld agreement check (skip forced melds like akagari)
            if call_type in (0, 1, 2):
                total_meld_opportunities += 1
                ev = Evaluator(states[call_seat], params)
                ai_decision = ev.should_call_meld(call_type, tiles, froms[0] if froms else -1)
                human_decided = True

                if ai_decision == human_decided:
                    meld_matches += 1
                else:
                    hand = list(states[call_seat].my_hand)
                    s_state = states[call_seat]
                    rivs = [' '.join(fmt_tile(t) for t in s_state.river[i]) if s_state.river[i] else 'なし' for i in range(4)]
                    doras_str = ' '.join(fmt_tile(t) for t in s_state.doras) if s_state.doras else 'なし'

                    human_turn = (s_state.tsumo_count - 1) // 4 + 1
                    out(f'===== 副露不一致 #{total_meld_opportunities} =====')
                    is_dealer = '(親)' if s_state.my_seat == 0 else ''
                    out(f'{SEAT_NAMES[call_seat]}家{is_dealer} / {s_state.chang*4+s_state.ju+1}局 {s_state.ben}本場 / {human_turn}巡目({s_state.tsumo_count}ツモ) / 残り{s_state.left_tile_count}枚')
                    out(f'点数: {s_state.scores}')
                    out(f'ドラ: {doras_str}')
                    out(f'副露: {CALL_NAMES.get(call_type, str(call_type))} {" ".join(fmt_tile(t) for t in tiles)} (from {SEAT_NAMES[froms[0]] if froms else "?"})')
                    out(f'AI判断: {"する" if ai_decision else "しない"} / 実際: した')
                    out(f'hand({len(hand)}枚): {hand}')
                    seat_labels = ['自分' if i == call_seat else SEAT_NAMES[i] for i in range(4)]
                    for i in range(4):
                        r_info = rivs[i]
                        rc_info = ' リーチ' if s_state.reach_states[i].is_reach else ''
                        out(f'  {seat_labels[i]}: {r_info}{rc_info}')
                    out()

            # Always apply the meld to game state (it happened)
            for s in range(4):
                states[s].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
            awaiting[call_seat] = True
            reset_ippatsu()

        elif cls == 'RecordAnGangAddGang':
            call_type = d['type']
            call_seat = d['seat']
            tile = d['tiles']
            for s in range(4):
                states[s].on_an_gang_add_gang(call_type, call_seat, tile)

        elif cls in ('RecordHule', 'RecordNoTile'):
            awaiting = [False] * 4

# Report
out('=' * 50)
out('一致率レポート')
out('=' * 50)
out()

files_count = len(paths)
out(f'分析対象: {files_count} ファイル')
out()

discard_rate = (discard_matches / total_discard_decisions * 100) if total_discard_decisions else 0
out(f'【捨牌】')
out(f'  総判断回数: {total_discard_decisions}')
out(f'  一致回数: {discard_matches}')
out(f'  不一致回数: {total_discard_decisions - discard_matches}')
out(f'  一致率: {discard_rate:.1f}%')
out()

meld_rate = (meld_matches / total_meld_opportunities * 100) if total_meld_opportunities else 0
out(f'【副露】')
out(f'  総副露機会: {total_meld_opportunities}')
out(f'  AIも賛成(副露する): {meld_matches}')
out(f'  AIは拒否(副露しない): {total_meld_opportunities - meld_matches}')
out(f'  一致率: {meld_rate:.1f}%')
out()

total_decisions = total_discard_decisions + total_meld_opportunities
total_matches = discard_matches + meld_matches
overall_rate = (total_matches / total_decisions * 100) if total_decisions else 0
out(f'【総合】')
out(f'  総判断回数: {total_decisions} (捨牌{total_discard_decisions} + 副露{total_meld_opportunities})')
out(f'  一致回数: {total_matches}')
out(f'  総合一致率: {overall_rate:.1f}%')
out()

# Mismatch rate (AI says NOT to meld when human did = AI thinks human was wrong)
out('【考察】')
ai_says_no = total_meld_opportunities - meld_matches
out(f'  副露不一致のうち、AIが「するべきでない」と判断: {ai_says_no}回 ({ai_says_no/total_meld_opportunities*100:.1f}%)')
out(f'  → 現在の副露ルールはかなり抑制的（目標副露率30~40%に合わせて設計）')

with open('mismatches.txt', 'w', encoding='utf-8') as f:
    f.write('\n'.join(lines))
print(f'Saved {total_discard_decisions} discard + {total_meld_opportunities} meld decisions to mismatches.txt')
print(f'Discard agreement: {discard_rate:.1f}%  Meld agreement: {meld_rate:.1f}%')
