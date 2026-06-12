import json, sys, glob, os
from concurrent.futures import ProcessPoolExecutor, as_completed
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
from core.game_state import GameState
from core.evaluator import Evaluator
from core.str_converter import tile_to_id

SEAT_NAMES = ['東', '南', '西', '北']
CALL_NAMES = {0: 'チー', 1: 'ポン', 2: '大明槓', 3: '暗槓', 4: '加槓'}

def fmt_tile(t):
    m = {'1z':'東','2z':'南','3z':'西','4z':'北','5z':'白','6z':'發','7z':'中'}
    return m.get(t, t)


def process_file(path, params):
    """1ファイルを処理し (lines, total_discard, discard_match, total_meld, meld_match, fname) を返す"""
    lines = []
    def out(s=''):
        lines.append(s)

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

    fname = os.path.basename(path)
    mismatch_idx = 0
    total_discard = 0
    discard_match = 0
    total_meld = 0
    meld_match = 0

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
                        total_discard += 1
                        ev = Evaluator(states[seat], params)
                        best = ev.best_discard(hand)
                        is_exact = (best == tile)
                        is_matched = False
                        if is_exact:
                            is_matched = True
                        else:
                            scores = {t: ev.evaluate_tile(t) for t in dict.fromkeys(hand)}
                            best_score = scores.get(best, 0)
                            actual_score = scores.get(tile, min(scores.values()) if scores else 0)
                            range_val = max(best_score - min(scores.values()), params.get('MATCH_MIN_RANGE', 400.0))
                            diff = max(0.0, best_score - actual_score)
                            ratio = max(0.0, 1.0 - diff / range_val)
                            rating = 100.0 * (ratio ** 2)
                            is_matched = rating >= 90.0

                        if is_matched:
                            discard_match += 1
                        else:
                            mismatch_idx += 1
                            s_state = states[seat]
                            rivs = [', '.join(fmt_tile(t) for t in s_state.river[i]) if s_state.river[i] else 'なし' for i in range(4)]
                            doras_str = ', '.join(fmt_tile(t) for t in s_state.doras) if s_state.doras else 'なし'
                            human_turn = (s_state.tsumo_count - 1) // 4 + 1
                            is_dealer = '(親)' if s_state.my_seat == 0 else ''

                            out(f'===== 不一致 #{mismatch_idx} [{fname}] =====')
                            out(f'{SEAT_NAMES[seat]}家{is_dealer} / {s_state.chang*4+s_state.ju+1}局 {s_state.ben}本場 / {human_turn}巡目({s_state.tsumo_count}ツモ)')
                            out(f'手牌({len(hand)}枚): {",".join(hand)}')
                            out(f'actual: {fmt_tile(tile)} | AI推奨: {fmt_tile(best)}')
                            out(f'スコア上位: {", ".join(f"{fmt_tile(t)}({float(s):.0f})" for t,s in sorted(scores.items(), key=lambda x:-float(x[1]))[:5])}')
                            out(f'ドラ: {doras_str} | 点数: {s_state.scores}')
                            out(f'河:')
                            for i in range(4):
                                label = '自分' if i == seat else SEAT_NAMES[i]
                                rc = ' リーチ' if s_state.reach_states[i].is_reach else ''
                                out(f'  {label}: {rivs[i]}{rc}')
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

            if call_type in (0, 1, 2):
                total_meld += 1
                ev = Evaluator(states[call_seat], params)
                ai_decision = ev.should_call_meld(call_type, tiles, froms[0] if froms else -1)
                if ai_decision == True:
                    meld_match += 1
                else:
                    mismatch_idx += 1
                    hand = list(states[call_seat].my_hand)
                    s_state = states[call_seat]
                    rivs = [', '.join(fmt_tile(t) for t in s_state.river[i]) if s_state.river[i] else 'なし' for i in range(4)]
                    doras_str = ', '.join(fmt_tile(t) for t in s_state.doras) if s_state.doras else 'なし'
                    human_turn = (s_state.tsumo_count - 1) // 4 + 1
                    is_dealer = '(親)' if s_state.my_seat == 0 else ''

                    out(f'===== 不一致 #{mismatch_idx} [{fname}] =====')
                    out(f'{SEAT_NAMES[call_seat]}家{is_dealer} / {s_state.chang*4+s_state.ju+1}局 {s_state.ben}本場 / {human_turn}巡目({s_state.tsumo_count}ツモ)')
                    out(f'手牌({len(hand)}枚): {",".join(hand)}')
                    out(f'actual: 副露した ({CALL_NAMES.get(call_type)} {" ".join(fmt_tile(t) for t in tiles)} from {SEAT_NAMES[froms[0]] if froms else "?"})')
                    out(f'AI判断: するべきでない')
                    out(f'ドラ: {doras_str} | 点数: {s_state.scores}')
                    out(f'河:')
                    for i in range(4):
                        label = '自分' if i == call_seat else SEAT_NAMES[i]
                        rc = ' リーチ' if s_state.reach_states[i].is_reach else ''
                        out(f'  {label}: {rivs[i]}{rc}')
                    out()

            for s in range(4):
                states[s].on_chi_peng_gang(call_type, call_seat, tiles, froms, tile_states)
            awaiting[call_seat] = True
            reset_ippatsu()

        elif cls == 'RecordAnGangAddGang':
            for s in range(4):
                states[s].on_an_gang_add_gang(d['type'], d['seat'], d['tiles'])

        elif cls in ('RecordHule', 'RecordNoTile'):
            awaiting = [False] * 4

    return lines, total_discard, discard_match, total_meld, meld_match, fname


if __name__ == '__main__':
    with open(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'config', 'config_parameters.json')) as f:
        params = json.load(f)

    paths = sorted(glob.glob(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'record_*_trimmed.json')))
    total_files = len(paths)

    all_lines = []
    total_discard = 0
    discard_match = 0
    total_meld = 0
    meld_match = 0

    n_workers = min(os.cpu_count() or 4, total_files)
    with ProcessPoolExecutor(max_workers=n_workers) as executor:
        futures = {executor.submit(process_file, path, params): i for i, path in enumerate(paths)}
        file_results = {}
        completed = 0
        for future in as_completed(futures):
            idx = futures[future]
            lines, td, dm, tm, mm, fname = future.result()
            file_results[idx] = lines
            total_discard += td
            discard_match += dm
            total_meld += tm
            meld_match += mm
            completed += 1
            pct_d = f'{discard_match/total_discard*100:.1f}%' if total_discard else 'N/A'
            pct_m = f'{meld_match/total_meld*100:.1f}%' if total_meld else 'N/A'
            sys.stdout.write(f'\r({completed}/{total_files}) {fname} ... 捨牌: {discard_match}/{total_discard} ({pct_d}) | 副露: {meld_match}/{total_meld} ({pct_m})')
            sys.stdout.flush()

    # ファイル順にlinesを結合
    for idx in range(total_files):
        all_lines.extend(file_results[idx])

    sys.stdout.write('\n')
    summary = []
    def out(s=''):
        summary.append(s)
    out('=' * 40)
    out('集計')
    out('=' * 40)
    out(f'ファイル数: {total_files}')
    out(f'捨牌: 合計{total_discard} 一致{discard_match} 不一致{total_discard-discard_match} ({discard_match/total_discard*100:.1f}%)')
    out(f'副露: 合計{total_meld} 一致{meld_match} 不一致{total_meld-meld_match} ({meld_match/total_meld*100:.1f}%)')
    out(f'総合: {discard_match+meld_match}/{total_discard+total_meld} = {(discard_match+meld_match)/(total_discard+total_meld)*100:.1f}%')

    all_lines.extend(summary)

    with open('mismatches.txt', 'w', encoding='utf-8') as f:
        f.write('\n'.join(all_lines))
    print(f'Output: {total_discard + total_meld} decisions, {total_discard+total_meld-discard_match-meld_match} mismatches')
    print(f'Discard: {discard_match}/{total_discard} = {discard_match/total_discard*100:.1f}%')
    print(f'Meld:    {meld_match}/{total_meld} = {meld_match/total_meld*100:.1f}%')
