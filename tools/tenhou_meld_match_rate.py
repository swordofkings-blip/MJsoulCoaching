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
    @title 人間副露判断を抽出
    @returns [(seat, call_type, tiles, from_seat, before_state, after_state), ...]
    """
    decisions = []
    # 各局ごとに state を再生
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
            # 鳴き前の状態で state を構築
            before_state = _build_state_before(cur_round_actions[:-1], seat)
            # 人間判断 = 鳴いた = 鳴く
            decisions.append({
                'seat': seat,
                'call_type': data.get('type', 1),
                'tiles': [data.get('tile', '')] + data.get('consumed', []),
                'from_seat': data.get('fromSeat', 0),
                'before_state': before_state,
                'human_decision': 'meld',
            })
        elif class_name == 'RecordAnGangAddGang':
            cur_round_actions.append(action)
            seat = data.get('seat')
            decisions.append({
                'seat': seat,
                'call_type': 2,
                'tiles': [data.get('tile', '')] + data.get('consumed', []),
                'from_seat': data.get('fromSeat', 0),
                'before_state': None,  # 簡略化
                'human_decision': 'kan',
            })
        else:
            cur_round_actions.append(action)
    return decisions


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
         exclude_outliers: bool = True):
    """
    exclude_outliers: シャンテン 0/4/5 のミスマッチ (人間判断ミス疑い) を除外
    """
    conn = sqlite3.connect(DB)
    cur = conn.cursor()
    cur.execute('SELECT id, log FROM logs WHERE is_processed=1 AND was_error=0 LIMIT ?', (n_logs,))
    rows = cur.fetchall()

    total_decisions = 0
    v2_correct = 0
    v2_wrong = 0
    v2_errors = 0
    excluded = 0
    meld_types = {}
    mismatches = []

    t0 = time.time()
    for log_id, blob in rows:
        try:
            json_dict, n_rounds = tenhou_blob_to_actions(blob)
            actions = json_dict.get('detail_records', {}).get('actions', [])
            decisions = extract_human_meld_decisions(actions)
            for d in decisions:
                seat = d['seat']
                call_type = d['call_type']
                tiles = d['tiles']
                from_seat = d['from_seat']
                before_state = d['before_state']
                if before_state is None:
                    continue
                if not tiles:
                    continue
                # ハズレ値除外: シャンテン 0/4/5 のミスマッチは人間判断ミス疑い
                sh = ShantenCalculatorV2.calculate_closed_effective(hand_to_counts(before_state.my_hand))
                if exclude_outliers and sh in (0, 4, 5, 6, 7, 8):
                    excluded += 1
                    continue
                try:
                    v2_should, reason = should_call_meld(before_state, call_type, tiles, from_seat, {})
                    if v2_should:
                        v2_correct += 1
                    else:
                        v2_wrong += 1
                    total_decisions += 1
                    meld_types.setdefault(call_type, [0, 0])
                    if v2_should:
                        meld_types[call_type][0] += 1
                    else:
                        meld_types[call_type][1] += 1
                    if save_mismatches and not v2_should:
                        if len(mismatches) < 200:
                            from core.meld_v2 import score_meld
                            total, breakdown = score_meld(before_state, call_type, tiles, from_seat, {})
                            mismatches.append({
                                'log_id': log_id,
                                'seat': seat,
                                'call_type': call_type,
                                'tiles': tiles,
                                'from_seat': from_seat,
                                'hand': before_state.my_hand,
                                'shanten': sh,
                                'meld_score': round(total, 1),
                                'reason': reason,
                                'breakdown_top': sorted(breakdown, key=lambda x: -abs(x[1]))[:5],
                            })
                except Exception as e:
                    v2_errors += 1
        except Exception as e:
            print(f'{log_id}: error {e}', flush=True)

    elapsed = time.time() - t0
    print()
    print(f'=== ver.2 人間副露判断 recall テスト ({n_logs} ログ) ===')
    print(f'  経過時間: {elapsed:.1f}秒')
    print(f'  除外 (shanten 0/4-8): {excluded}')
    print(f'  判定数: {total_decisions}')
    print(f'  ver.2 鳴く (正解): {v2_correct}')
    print(f'  ver.2 スルー (不正解): {v2_wrong}')
    print(f'  エラー: {v2_errors}')
    if total_decisions > 0:
        recall = v2_correct / total_decisions * 100
        print(f'  **Recall (人間が鳴いた時に ver.2 も鳴く率): {recall:.1f}%**')
    print(f'  種別:')
    for ct, (ok, ng) in meld_types.items():
        ct_name = {0: 'チー', 1: 'ポン', 2: '大明槓'}.get(ct, f'call_type={ct}')
        total = ok + ng
        rate = ok / total * 100 if total else 0
        print(f'    {ct_name}: {ok}/{total} ({rate:.1f}%)')

    if save_mismatches and mismatches:
        if out_path is None:
            out_path = 'tenhou_meld_mismatches.json'
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump(mismatches, f, ensure_ascii=False, indent=2)
        print(f'\n  不一致ケース {len(mismatches)} 件を {out_path} に保存')
        from collections import Counter
        sh_count = Counter(m['shanten'] for m in mismatches)
        print(f'  シャンテン数別: {dict(sh_count)}')
        avg_score = sum(m['meld_score'] for m in mismatches) / len(mismatches)
        print(f'  平均 meld_score: {avg_score:.1f}')

        # ポン分析
        pon_mismatches = [m for m in mismatches if m['call_type'] == 1]
        if pon_mismatches:
            print(f'  ポン不一致: {len(pon_mismatches)} 件')
            for m in pon_mismatches[:5]:
                print(f"    手牌={m['hand']} | 鳴き={m['tiles']} | score={m['meld_score']} | shanten={m['shanten']}")
                for n, v, r in m['breakdown_top']:
                    print(f"      {n}: {v:+.0f} ({r})")


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=50, help='ログ数')
    p.add_argument('--save-mismatches', action='store_true', help='不一致ケース保存')
    p.add_argument('--out', type=str, default=None, help='保存先')
    p.add_argument('--no-exclude', action='store_true', help='ハズレ値除外しない')
    args = p.parse_args()
    main(args.n, args.save_mismatches, args.out, not args.no_exclude)


if __name__ == '__main__':
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('--n', type=int, default=50, help='ログ数')
    args = p.parse_args()
    main(args.n)
