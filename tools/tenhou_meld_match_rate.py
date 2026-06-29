# -*- coding: utf-8 -*-
"""
@title ver.2 副露判断 vs 天鳳人間判断 一致率テスト
@description 天鳳ログから人間副露判断を正解データとして抽出、ver.2 meld_v2 との一致率を測定。
              雀魂牌譜では不足する人間判断データを補完する。

抽出パターン:
  1. RecordChiPengGang が出現 = 人間が鳴いた (正解: 鳴く)
  2. RecordAnGangAddGang が出現 = 人間がカンした (正解: カン)
  3. 人間がスルーした局面 (他家打牌時に手牌に 2 枚以上ある牌) (正解: 鳴かない)
     ※ この抽出は複雑なので、まず 1, 2 で recall テストから始める
"""
import sys
import os
import sqlite3
import time

sys.path.insert(0, '.')
from tools.tenhou_xml_to_actions import tenhou_blob_to_actions
from core.game_state import GameState, ReachState, Meld
from core.meld_v2 import should_call_meld
from core.shanten_v2 import ShantenCalculatorV2
from str_converter import hand_to_counts, tile_to_id
import json


DB = r'C:\Users\Daikichi\Documents\code-workspace\雀魂ラッパー_拡散AI\data\raw\tenhou_logs.db'


def replay_actions(actions: list, target_seat: int) -> GameState:
    """
    @title 牌譜を target_seat から見た GameState として再生
    """
    state = GameState()
    state.my_seat = target_seat
    state.reach_states = [ReachState() for _ in range(4)]
    state.scores = [25000, 25000, 25000, 25000]
    for action in actions:
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})
        try:
            if class_name == 'RecordNewRound':
                state.my_hand = []
                state.my_melds = []
                state.doras = list(data.get('doras', []))
                state.scores = list(data.get('scores', [25000]*4))
                state.left_tile_count = data.get('leftTileCount', 70)
                # target_seat の手牌をセット
                state.my_hand = list(data.get(f'tiles{target_seat}', []))
                state.chang = data.get('chang', 0)
                state.ju = data.get('ju', 0)
                state.tsumo_count = 0
            elif class_name == 'RecordDealTile':
                seat = data.get('seat')
                tile = data.get('tile')
                state.tsumo_count += 1
                if seat == target_seat and tile:
                    state.my_hand.append(tile)
            elif class_name == 'RecordDiscardTile':
                seat = data.get('seat')
                tile = data.get('tile')
                if seat == target_seat and tile and tile in state.my_hand:
                    state.my_hand.remove(tile)
                # 副露判定用の捨て牌を記録
                if not hasattr(state, '_last_discard'):
                    state._last_discard = None
                if seat != target_seat:
                    state._last_discard = (seat, tile)
                # リーチ判定
                is_liqi = data.get('isLiqi', False)
                if is_liqi and 0 <= seat < 4:
                    state.reach_states[seat].is_reach = True
            elif class_name == 'RecordChiPengGang':
                seat = data.get('seat')
                if seat == target_seat:
                    # 副露を反映
                    consumed = list(data.get('consumed', []))
                    target_tile = data.get('tile', '')
                    # consumed + target_tile を副露牌に
                    call_type = data.get('type', 1)
                    tiles = [target_tile] + consumed if target_tile else consumed
                    # 鳴いた牌を手牌から削除
                    for t in consumed:
                        if t in state.my_hand:
                            state.my_hand.remove(t)
                    # 副露を記録
                    froms = [data.get('fromSeat', 0)] + [target_seat] * len(consumed)
                    meld = Meld(type=call_type, tiles=tiles, froms=froms)
                    state.my_melds.append(meld)
            elif class_name == 'RecordAnGangAddGang':
                seat = data.get('seat')
                if seat == target_seat:
                    consumed = list(data.get('consumed', []))
                    for t in consumed:
                        if t in state.my_hand:
                            state.my_hand.remove(t)
        except Exception:
            pass
    return state


def extract_human_meld_decisions(actions: list) -> list:
    """
    @title 人間副露判断を抽出 (positive + negative)
    @returns [(seat, call_type, tiles, from_seat, before_state, human_decision), ...]
        human_decision: 'meld' (鳴いた) or 'pass' (スルー可能だったのにしなかった)
    """
    decisions = []
    cur_round_actions = []
    for action in actions:
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})
        if class_name == 'RecordNewRound':
            cur_round_actions = [action]
        elif class_name == 'RecordChiPengGang':
            cur_round_actions.append(action)
            seat = data.get('seat')
            before_state = _build_state_before(cur_round_actions[:-1], seat)
            decisions.append({
                'seat': seat,
                'call_type': data.get('type', 1),
                'tiles': [data.get('tile', '')] + data.get('consumed', []),
                'from_seat': data.get('fromSeat', 0),
                'before_state': before_state,
                'human_decision': 'meld',
                'log_idx': len(cur_round_actions) - 1,
            })
        elif class_name == 'RecordAnGangAddGang':
            cur_round_actions.append(action)
            seat = data.get('seat')
            decisions.append({
                'seat': seat,
                'call_type': 2,
                'tiles': [data.get('tile', '')] + data.get('consumed', []),
                'from_seat': data.get('fromSeat', 0),
                'before_state': None,
                'human_decision': 'kan',
                'log_idx': len(cur_round_actions) - 1,
            })
        else:
            cur_round_actions.append(action)
    return decisions


def extract_possible_melds(actions: list) -> list:
    """
    @title 人間がスルーした「鳴き可能」局面を抽出
    @description 他家打牌時に人間の手牌に 2 枚以上ある牌 → 鳴き可能だったのにスルー
    @returns [(seat, call_type, tiles, from_seat, before_state, human_decision='pass'), ...]
    """
    from collections import defaultdict
    decisions = []
    cur_round_actions = []
    cur_states = {}  # seat -> state 構築用
    for action in actions:
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})
        if class_name == 'RecordNewRound':
            cur_round_actions = [action]
            # 各 seat の初期状態
            cur_states = {s: {'hand': list(data.get(f'tiles{s}', [])),
                              'melds': [], 'reach': False, 'riichi_turn': -1}
                          for s in range(4)}
        elif class_name == 'RecordDealTile':
            cur_round_actions.append(action)
            seat = data.get('seat')
            tile = data.get('tile')
            if seat is not None and tile and seat in cur_states:
                cur_states[seat]['hand'].append(tile)
        elif class_name == 'RecordDiscardTile':
            cur_round_actions.append(action)
            discarder = data.get('seat')
            discard_tile = data.get('tile')
            if discarder is None or not discard_tile or discarder not in cur_states:
                continue
            # この打牌に対して、各他家 (discarder 以外) が 鳴き可能 かチェック
            for seat in range(4):
                if seat == discarder:
                    continue
                if seat not in cur_states:
                    continue
                st = cur_states[seat]
                hand = st['hand']
                # チー可能: 捨て牌の隣接牌が手牌に 2 枚以上
                if discarder == (seat + 1) % 4:  # 上家からチー可能 (discarder は seat の下家)
                    # チー: discard_tile - 1, discard_tile, discard_tile + 1 パターン
                    if discard_tile in ('1m', '1p', '1s', '9m', '9p', '9s', '1z', '2z', '3z', '4z', '5z', '6z', '7z'):
                        pass  # 端牌はチー不可
                    else:
                        # discard_tile id
                        try:
                            dt_id = tile_to_id(discard_tile)
                            if dt_id < 27:  # 数牌のみ
                                n = dt_id % 9
                                suit = dt_id // 9
                                base = suit * 9
                                # discard_tile - 2, -1, 0
                                if n >= 2:
                                    needed = base + n - 2
                                    count = sum(1 for t in hand if tile_to_id(t) == needed)
                                    if count >= 1:
                                        # チー可能 (123 形)
                                        tiles = [tile_id_to_str(base + n - 2), tile_id_to_str(base + n - 1), discard_tile]
                                        if all(t in hand for t in [tiles[0], tiles[1]]):
                                            before_state = _build_full_state(seat, cur_states[seat], data, cur_states)
                                            if before_state is not None:
                                                decisions.append({
                                                    'seat': seat,
                                                    'call_type': 0,
                                                    'tiles': tiles,
                                                    'from_seat': discarder,
                                                    'before_state': before_state,
                                                    'human_decision': 'pass',
                                                    'discard_tile': discard_tile,
                                                    'reason': 'chi_possible',
                                                })
                                if n >= 1 and n <= 7:
                                    needed = base + n
                                    needed2 = base + n + 1
                                    count = sum(1 for t in hand if tile_to_id(t) == needed)
                                    count2 = sum(1 for t in hand if tile_to_id(t) == needed2)
                                    if count >= 1 and count2 >= 1:
                                        tiles = [discard_tile, tile_id_to_str(needed), tile_id_to_str(needed2)]
                                        if all(t in hand for t in [tiles[1], tiles[2]]):
                                            before_state = _build_full_state(seat, cur_states[seat], data, cur_states)
                                            if before_state is not None:
                                                decisions.append({
                                                    'seat': seat,
                                                    'call_type': 0,
                                                    'tiles': tiles,
                                                    'from_seat': discarder,
                                                    'before_state': before_state,
                                                    'human_decision': 'pass',
                                                    'discard_tile': discard_tile,
                                                    'reason': 'chi_possible',
                                                })
                                if n <= 6:
                                    needed = base + n + 1
                                    needed2 = base + n + 2
                                    count = sum(1 for t in hand if tile_to_id(t) == needed)
                                    count2 = sum(1 for t in hand if tile_to_id(t) == needed2)
                                    if count >= 1 and count2 >= 1:
                                        tiles = [tile_id_to_str(needed), tile_id_to_str(needed2), discard_tile]
                                        if all(t in hand for t in [tiles[0], tiles[1]]):
                                            before_state = _build_full_state(seat, cur_states[seat], data, cur_states)
                                            if before_state is not None:
                                                decisions.append({
                                                    'seat': seat,
                                                    'call_type': 0,
                                                    'tiles': tiles,
                                                    'from_seat': discarder,
                                                    'before_state': before_state,
                                                    'human_decision': 'pass',
                                                    'discard_tile': discard_tile,
                                                    'reason': 'chi_possible',
                                                })
                        except Exception:
                            pass
                # ポン可能: 手牌に捨て牌と同一牌が 2 枚以上
                try:
                    dt_id = tile_to_id(discard_tile)
                except Exception:
                    continue
                count_in_hand = sum(1 for t in hand if tile_to_id(t) == dt_id)
                if count_in_hand >= 2:
                    tiles = [discard_tile] * 3
                    before_state = _build_full_state(seat, cur_states[seat], data, cur_states)
                    if before_state is not None:
                        decisions.append({
                            'seat': seat,
                            'call_type': 1,
                            'tiles': tiles,
                            'from_seat': discarder,
                            'before_state': before_state,
                            'human_decision': 'pass',
                            'discard_tile': discard_tile,
                            'reason': 'pon_possible',
                        })
            # 人間の手牌更新
            if discard_tile in cur_states[discarder]['hand']:
                cur_states[discarder]['hand'].remove(discard_tile)
        elif class_name == 'RecordChiPengGang':
            cur_round_actions.append(action)
            seat = data.get('seat')
            if seat in cur_states:
                consumed = list(data.get('consumed', []))
                for t in consumed:
                    if t in cur_states[seat]['hand']:
                        cur_states[seat]['hand'].remove(t)
        elif class_name == 'RecordAnGangAddGang':
            cur_round_actions.append(action)
            seat = data.get('seat')
            if seat in cur_states:
                consumed = list(data.get('consumed', []))
                for t in consumed:
                    if t in cur_states[seat]['hand']:
                        cur_states[seat]['hand'].remove(t)
        else:
            cur_round_actions.append(action)
    return decisions


def _build_full_state(seat: int, st: dict, current_data: dict, all_states: dict) -> GameState:
    """@title スルー判定用の state を構築"""
    try:
        state = GameState()
        state.my_seat = seat
        state.my_hand = list(st['hand'])
        state.my_melds = []
        for m in st.get('melds', []):
            from core.game_state import Meld
            state.my_melds.append(Meld(
                type=(2 if m.get('type') == 'minggang' else 1),
                tiles=list(m.get('tiles', [])),
                froms=list(m.get('froms', [])),
            ))
        state.chang = current_data.get('chang', 0)
        state.ju = current_data.get('ju', 0)
        state.ben = current_data.get('ben', 0)
        state.liqibang = current_data.get('liqibang', 0)
        state.doras = list(current_data.get('doras', []))
        state.tsumo_count = current_data.get('tsumo_count', 0)
        state.left_tile_count = current_data.get('leftTileCount', 70)
        state.dealer_seat = current_data.get('oya', 0)
        state.scores = list(current_data.get('scores', [25000]*4))
        state.reach_states = [ReachState() for _ in range(4)]
        for s in range(4):
            if all_states.get(s, {}).get('reach'):
                state.reach_states[s].is_reach = True
        return state
    except Exception:
        return None


def tile_id_to_str(tile_id: int) -> str:
    """@title tile_id (0-33) を '1m' 形式に変換"""
    tile_id = int(tile_id)
    suit = tile_id // 9
    rank = tile_id % 9 + 1
    return f'{rank}{["m","p","s","z"][suit]}'


def _build_state_before(actions: list, target_seat: int) -> GameState:
    """@title 鳴き直前の state を構築"""
    state = GameState()
    state.my_seat = target_seat
    state.reach_states = [ReachState() for _ in range(4)]
    state.scores = [25000, 25000, 25000, 25000]
    for action in actions:
        result = action.get('result', {})
        class_name = result.get('class_name', '')
        data = result.get('data', {})
        try:
            if class_name == 'RecordNewRound':
                state.my_hand = list(data.get(f'tiles{target_seat}', []))
                state.doras = list(data.get('doras', []))
                state.scores = list(data.get('scores', [25000]*4))
                state.left_tile_count = data.get('leftTileCount', 70)
                state.chang = data.get('chang', 0)
                state.ju = data.get('ju', 0)
                state.tsumo_count = 0
            elif class_name == 'RecordDealTile':
                seat = data.get('seat')
                tile = data.get('tile')
                state.tsumo_count += 1
                if seat == target_seat and tile:
                    state.my_hand.append(tile)
            elif class_name == 'RecordDiscardTile':
                seat = data.get('seat')
                tile = data.get('tile')
                if seat == target_seat and tile and tile in state.my_hand:
                    state.my_hand.remove(tile)
                is_liqi = data.get('isLiqi', False)
                if is_liqi and 0 <= seat < 4:
                    state.reach_states[seat].is_reach = True
        except Exception:
            pass
    return state


def main(n_logs: int = 50, save_mismatches: bool = False, out_path: str = None,
         exclude_outliers: bool = True, include_pass: bool = True):
    """
    exclude_outliers: シャンテン 0/4-8 のミスマッチ (人間判断ミス疑い) を除外
    include_pass: 人間スルー判断もテスト (specificity)
    """
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT id, log FROM logs WHERE is_processed=1 AND was_error=0 LIMIT ?', (n_logs,))
    rows = cur.fetchall()

    # Positive (人間 = 鳴いた)
    n_pos_total = 0
    n_pos_correct = 0
    n_pos_wrong = 0
    n_pos_excluded = 0
    meld_types = {}
    pos_mismatches = []

    # Negative (人間 = スルー した possible meld)
    n_neg_total = 0
    n_neg_correct = 0
    n_neg_wrong = 0
    n_neg_excluded = 0
    neg_mismatches = []

    t0 = time.time()
    for log_id, blob in rows:
        try:
            json_dict, n_rounds = tenhou_blob_to_actions(blob)
            actions = json_dict.get('detail_records', {}).get('actions', [])
            pos_decisions = extract_human_meld_decisions(actions)
            for d in pos_decisions:
                seat = d['seat']
                call_type = d['call_type']
                tiles = d['tiles']
                from_seat = d['from_seat']
                before_state = d['before_state']
                if before_state is None or not tiles:
                    continue
                sh = ShantenCalculatorV2.calculate_closed_effective(hand_to_counts(before_state.my_hand))
                if exclude_outliers and sh in (0, 4, 5, 6, 7, 8):
                    n_pos_excluded += 1
                    continue
                try:
                    v2_should, reason = should_call_meld(before_state, call_type, tiles, from_seat, {})
                    if v2_should:
                        n_pos_correct += 1
                    else:
                        n_pos_wrong += 1
                    n_pos_total += 1
                    meld_types.setdefault(call_type, [0, 0])
                    if v2_should:
                        meld_types[call_type][0] += 1
                    else:
                        meld_types[call_type][1] += 1
                    if save_mismatches and not v2_should:
                        if len(pos_mismatches) < 200:
                            from core.meld_v2 import score_meld
                            total, breakdown = score_meld(before_state, call_type, tiles, from_seat, {})
                            pos_mismatches.append({
                                'log_id': log_id, 'seat': seat, 'call_type': call_type,
                                'tiles': tiles, 'from_seat': from_seat,
                                'hand': before_state.my_hand, 'shanten': sh,
                                'meld_score': round(total, 1), 'reason': reason,
                                'breakdown_top': sorted(breakdown, key=lambda x: -abs(x[1]))[:5],
                            })
                except Exception as e:
                    pass

            # Negative (スルー)
            if include_pass:
                neg_decisions = extract_possible_melds(actions)
                for d in neg_decisions:
                    seat = d['seat']
                    call_type = d['call_type']
                    tiles = d['tiles']
                    from_seat = d['from_seat']
                    before_state = d['before_state']
                    if before_state is None or not tiles:
                        continue
                    sh = ShantenCalculatorV2.calculate_closed_effective(hand_to_counts(before_state.my_hand))
                    if exclude_outliers and sh in (0, 4, 5, 6, 7, 8):
                        n_neg_excluded += 1
                        continue
                    try:
                        v2_should, reason = should_call_meld(before_state, call_type, tiles, from_seat, {})
                        # 人間 = スルー → ver.2 も スルー が正解
                        if not v2_should:
                            n_neg_correct += 1
                        else:
                            n_neg_wrong += 1
                        n_neg_total += 1
                        if save_mismatches and v2_should:
                            if len(neg_mismatches) < 200:
                                from core.meld_v2 import score_meld
                                total, breakdown = score_meld(before_state, call_type, tiles, from_seat, {})
                                neg_mismatches.append({
                                    'log_id': log_id, 'seat': seat, 'call_type': call_type,
                                    'tiles': tiles, 'from_seat': from_seat,
                                    'hand': before_state.my_hand, 'shanten': sh,
                                    'meld_score': round(total, 1), 'reason': reason,
                                    'discard_tile': d.get('discard_tile', ''),
                                    'breakdown_top': sorted(breakdown, key=lambda x: -abs(x[1]))[:5],
                                })
                    except Exception as e:
                        pass
        except Exception as e:
            print(f'{log_id}: error {e}', flush=True)

    elapsed = time.time() - t0
    print()
    print(f'=== ver.2 人間副露判断テスト ({n_logs} ログ) ===')
    print(f'  経過時間: {elapsed:.1f}秒')
    print()
    print(f'--- Positive (人間 = 鳴く, Recall) ---')
    print(f'  除外 (shanten 0/4-8): {n_pos_excluded}')
    print(f'  判定数: {n_pos_total}')
    print(f'  ver.2 鳴く (正解): {n_pos_correct}')
    print(f'  ver.2 スルー (不正解): {n_pos_wrong}')
    if n_pos_total > 0:
        recall = n_pos_correct / n_pos_total * 100
        print(f'  **Recall: {recall:.1f}%**')
    print(f'  種別:')
    for ct, (ok, ng) in meld_types.items():
        ct_name = {0: 'チー', 1: 'ポン', 2: '大明槓'}.get(ct, f'call_type={ct}')
        total = ok + ng
        rate = ok / total * 100 if total else 0
        print(f'    {ct_name}: {ok}/{total} ({rate:.1f}%)')

    if include_pass:
        print()
        print(f'--- Negative (人間 = スルー, Specificity) ---')
        print(f'  除外 (shanten 0/4-8): {n_neg_excluded}')
        print(f'  判定数: {n_neg_total}')
        print(f'  ver.2 スルー (正解): {n_neg_correct}')
        print(f'  ver.2 鳴く (不正解): {n_neg_wrong}')
        if n_neg_total > 0:
            specificity = n_neg_correct / n_neg_total * 100
            print(f'  **Specificity: {specificity:.1f}%**')

    # 総合
    if n_pos_total + n_neg_total > 0:
        total = n_pos_correct + n_neg_correct
        overall = total / (n_pos_total + n_neg_total) * 100
        print()
        print(f'--- 総合 (正答率) ---')
        print(f'  {n_pos_correct + n_neg_correct} / {n_pos_total + n_neg_total} = {overall:.1f}%')

    # 不一致保存
    if save_mismatches:
        if pos_mismatches or neg_mismatches:
            result = {
                'positive_mismatches': pos_mismatches,
                'negative_mismatches': neg_mismatches,
            }
            if out_path is None:
                out_path = 'tenhou_meld_mismatches.json'
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump(result, f, ensure_ascii=False, indent=2)
            print(f'\n  不一致ケース保存: positive={len(pos_mismatches)}, negative={len(neg_mismatches)} -> {out_path}')


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=50, help='ログ数')
    p.add_argument('--save-mismatches', action='store_true', help='不一致ケース保存')
    p.add_argument('--out', type=str, default=None, help='保存先')
    p.add_argument('--no-exclude', action='store_true', help='ハズレ値除外しない')
    p.add_argument('--no-pass', action='store_true', help='スルー判断テストしない')
    args = p.parse_args()
    main(args.n, args.save_mismatches, args.out, not args.no_exclude, not args.no_pass)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=50, help='ログ数')
    args = p.parse_args()
    main(args.n)
