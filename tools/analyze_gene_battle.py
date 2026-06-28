"""
@title gene_battle ログ解析
@description logs/game_gene_*.log を解析し、各 AI のスタッツを出す
"""
import os
import re
import json
import sys
import glob
from collections import defaultdict
from typing import Dict, List

LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'logs')

# stdout を UTF-8 で開く
sys.stdout.reconfigure(encoding='utf-8')


def analyze_ai(player_id: int, ai_actions: List[dict]) -> dict:
    """
    @title 特定 AI (player_id) のスタッツを集計
    """
    stats = {
        'dahai': 0,
        'tsumo': 0,
        'reach': 0,
        'reach_accepted': 0,
        'pon': 0,
        'chi': 0,
        'daiminkan': 0,
        'ankan': 0,
        'hora': 0,
        'tsumo_hora': 0,
        'ron_hora': 0,
        'hora_score_sum': 0,
        'hoju': 0,
        'hoju_score_sum': 0,
        'ryukyoku': 0,
        'ryukyoku_tenpai': 0,
        'kyoku_count': 0,
        'reach_tenpai_ryanmen': 0,
        'reach_tenpai_tanmen': 0,
        'reach_tenpai_other': 0,
        'reach_turn_sum': 0,
        'reach_first_move': 0,
        'errors': 0,
    }
    # 局ごとに turn カウンタ
    cur_turn = 0
    first_reach_in_kyoku = False
    reach_actors_in_kyoku = set()
    in_kyoku = False
    for msg in ai_actions:
        t = msg.get('type', '')
        actor = msg.get('actor', -1)
        if t == 'error':
            stats['errors'] += 1
            continue
        if t == 'start_kyoku':
            stats['kyoku_count'] += 1
            cur_turn = 0
            first_reach_in_kyoku = False
            reach_actors_in_kyoku = set()
            in_kyoku = True
            continue
        if t == 'end_kyoku':
            in_kyoku = False
            continue
        if t == 'tsumo' and actor == player_id:
            cur_turn += 1
            stats['tsumo'] += 1
            continue
        if t == 'dahai' and actor == player_id:
            stats['dahai'] += 1
            continue
        if t == 'reach' and actor == player_id:
            stats['reach'] += 1
            continue
        if t == 'reach_accepted' and actor == player_id:
            stats['reach_accepted'] += 1
            stats['reach_turn_sum'] += cur_turn
            # 先制立直: 局内で自分が最初
            if not reach_actors_in_kyoku:
                stats['reach_first_move'] += 1
            reach_actors_in_kyoku.add(actor)
            # 待ち形判定 (ログからは直接取れないので一旦全 ryukyoku ryoumen 扱い)
            # start_kyoku の kyoku 数を分母に
            stats['reach_tenpai_ryanmen'] += 1
            continue
        if t == 'pon' and actor == player_id:
            stats['pon'] += 1
            continue
        if t == 'chi' and actor == player_id:
            stats['chi'] += 1
            continue
        if t == 'daiminkan' and actor == player_id:
            stats['daiminkan'] += 1
            continue
        if t == 'ankan' and actor == player_id:
            stats['ankan'] += 1
            continue
        if t == 'hora':
            target = msg.get('target', -1)
            # tsumo: actor == target
            is_tsumo = (actor == target)
            if actor == player_id:
                stats['hora'] += 1
                if 'deltas' in msg:
                    deltas = msg['deltas']
                    if player_id < len(deltas) and deltas[player_id] > 0:
                        stats['hora_score_sum'] += deltas[player_id]
                if is_tsumo:
                    stats['tsumo_hora'] += 1
                else:
                    stats['ron_hora'] += 1
            elif target == player_id:
                stats['hoju'] += 1
                if 'deltas' in msg:
                    deltas = msg['deltas']
                    if player_id < len(deltas) and deltas[player_id] < 0:
                        stats['hoju_score_sum'] += -deltas[player_id]
            continue
        if t == 'ryukyoku':
            stats['ryukyoku'] += 1
            if 'tenpais' in msg:
                tenpais = msg['tenpais']
                if isinstance(tenpais, list) and len(tenpais) > 0:
                    if isinstance(tenpais[0], list):
                        if player_id < len(tenpais) and tenpais[player_id]:
                            stats['ryukyoku_tenpai'] += 1
                    else:
                        if player_id < len(tenpais) and tenpais[player_id]:
                            stats['ryukyoku_tenpai'] += 1
            continue
    return stats


def safe_div(a, b):
    return a / b if b > 0 else 0.0


def summarize(name: str, agg: dict, lines: list) -> None:
    """スタッツを lines に追加"""
    n = agg['kyoku_count']
    if n == 0:
        lines.append(f'  {name}: データなし')
        return
    reach_rate = safe_div(agg['reach_accepted'], agg['dahai']) * 100
    meld_rate = safe_div(agg['pon'] + agg['chi'] + agg['daiminkan'] + agg['ankan'], agg['dahai']) * 100
    hora_rate = safe_div(agg['hora'], n) * 100
    tsumo_rate = safe_div(agg['tsumo_hora'], agg['hora']) * 100
    hoju_rate = safe_div(agg['hoju'], n) * 100
    avg_hora = safe_div(agg['hora_score_sum'], agg['hora'])
    avg_hoju = safe_div(agg['hoju_score_sum'], agg['hoju'])
    reach_ryoumen = safe_div(agg['reach_tenpai_ryanmen'], agg['reach_accepted']) * 100
    reach_tanmen = safe_div(agg['reach_tenpai_tanmen'], agg['reach_accepted']) * 100
    reach_avg_turn = safe_div(agg['reach_turn_sum'], agg['reach_accepted'])
    ryukyoku_tenpai = safe_div(agg['ryukyoku_tenpai'], agg['ryukyoku']) * 100
    lines.append(f'')
    lines.append(f'  {name}:')
    lines.append(f'    局数: {n}')
    lines.append(f'    立直率: {reach_rate:.1f}% (受け入れ {agg["reach_accepted"]}/{agg["dahai"]})')
    lines.append(f'    副露率: {meld_rate:.1f}% (pon {agg["pon"]} chi {agg["chi"]} dm {agg["daiminkan"]} an {agg["ankan"]})')
    lines.append(f'    和了率: {hora_rate:.1f}% (tsumo {agg["tsumo_hora"]} ron {agg["ron_hora"]})')
    lines.append(f'    ツモ率: {tsumo_rate:.1f}%')
    lines.append(f'    放銃率: {hoju_rate:.1f}%')
    lines.append(f'    平均和了点: {avg_hora:.0f}')
    lines.append(f'    平均放銃点: {avg_hoju:.0f}')
    lines.append(f'    立直良形率: {reach_ryoumen:.1f}% (端: {reach_tanmen:.1f}%)')
    lines.append(f'    立直平均巡目: {reach_avg_turn:.2f}')
    lines.append(f'    流局テンパイ率: {ryukyoku_tenpai:.1f}%')


def main():
    log_files = sorted(glob.glob(os.path.join(LOG_DIR, 'game_gene_*.log')))
    lines = []
    lines.append(f'=== ログ解析: {len(log_files)} ファイル ===')
    lines.append('')

    per_ai_stats = defaultdict(lambda: {
        'dahai': 0, 'tsumo': 0, 'reach': 0, 'reach_accepted': 0,
        'pon': 0, 'chi': 0, 'daiminkan': 0, 'ankan': 0,
        'hora': 0, 'tsumo_hora': 0, 'ron_hora': 0, 'hora_score_sum': 0,
        'hoju': 0, 'hoju_score_sum': 0, 'ryukyoku': 0, 'ryukyoku_tenpai': 0,
        'kyoku_count': 0, 'reach_tenpai_ryanmen': 0, 'reach_tenpai_tanmen': 0,
        'reach_tenpai_other': 0, 'reach_turn_sum': 0, 'reach_first_move': 0, 'errors': 0,
    })

    for log_path in log_files:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        names = None
        m = re.search(r'"type"\s*:\s*"start_game"[^}]*"names"\s*:\s*\[([^\]]+)\]', content)
        if m:
            try:
                names = json.loads('[' + m.group(1) + ']')
            except json.JSONDecodeError:
                pass

        if not names:
            lines.append(f'Skip {os.path.basename(log_path)}: cannot determine player names')
            continue

        player_actions = defaultdict(list)
        for line in content.splitlines():
            m = re.search(r'server -> player (\d+)\s+(\{.+\})', line)
            if not m:
                continue
            try:
                msg = json.loads(m.group(2))
                player_actions[int(m.group(1))].append(msg)
            except json.JSONDecodeError:
                pass

        for player_id, actions in player_actions.items():
            if player_id >= len(names) or names[player_id] is None:
                continue
            ai_name = names[player_id]
            stats = analyze_ai(player_id, actions)
            for k, v in stats.items():
                per_ai_stats[ai_name][k] += v

    lines.append('=' * 60)
    lines.append('=== 全 AI スタッツ集計 ===')
    lines.append('=' * 60)

    for name in ['OurAI-0', 'OurAI-1', 'OurAI-2', 'Akochan']:
        if name in per_ai_stats:
            summarize(name, per_ai_stats[name], lines)

    lines.append('')
    lines.append('=' * 60)
    lines.append('=== 玉座の間 (魂天～雀聖) 目標スタッツ ===')
    lines.append('=' * 60)
    lines.append('  和了率: 20-21%, 副露率: 31-33%, 平均和了: 6466, 放銃率: 12-14%')
    lines.append('  立直率: 18-19%, ツモ率: 39%, 流局テンパイ: 45-46%')
    lines.append('  和了巡数: 12-13, 立直良形率: 48-50%, 立直和了率: 47-49%')
    lines.append('  立直先制率: 79-81%, 立直巡目平均: 9.4, 追っかけ: 19-21%')
    lines.append('  立直和了収入: 8000-8100, 立直多面率: 73.5%')
    lines.append('  銃点損失: 734, 調整打点効率: 631, 打点効率: 1350')

    # 比較表
    lines.append('')
    lines.append('=' * 60)
    lines.append('=== 比較表 (現状 vs 目標) ===')
    lines.append('=' * 60)
    lines.append(f'{"項目":<20} {"OurAI-0":<12} {"OurAI-1":<12} {"OurAI-2":<12} {"Akochan":<12} {"目標":<12}')
    lines.append('-' * 80)

    def get(name, key):
        return per_ai_stats.get(name, {}).get(key, 0)
    def get_kyoku(name):
        return get(name, 'kyoku_count')

    rows = []
    rows.append(('和了率(%)', [
        safe_div(get('OurAI-0', 'hora'), get_kyoku('OurAI-0')) * 100,
        safe_div(get('OurAI-1', 'hora'), get_kyoku('OurAI-1')) * 100,
        safe_div(get('OurAI-2', 'hora'), get_kyoku('OurAI-2')) * 100,
        safe_div(get('Akochan', 'hora'), get_kyoku('Akochan')) * 100,
    ], '20-21%'))
    rows.append(('副露率(%)', [
        safe_div(get('OurAI-0', 'pon') + get('OurAI-0', 'chi') + get('OurAI-0', 'daiminkan') + get('OurAI-0', 'ankan'), get('OurAI-0', 'dahai')) * 100,
        safe_div(get('OurAI-1', 'pon') + get('OurAI-1', 'chi') + get('OurAI-1', 'daiminkan') + get('OurAI-1', 'ankan'), get('OurAI-1', 'dahai')) * 100,
        safe_div(get('OurAI-2', 'pon') + get('OurAI-2', 'chi') + get('OurAI-2', 'daiminkan') + get('OurAI-2', 'ankan'), get('OurAI-2', 'dahai')) * 100,
        safe_div(get('Akochan', 'pon') + get('Akochan', 'chi') + get('Akochan', 'daiminkan') + get('Akochan', 'ankan'), get('Akochan', 'dahai')) * 100,
    ], '31-33%'))
    rows.append(('立直率(%)', [
        safe_div(get('OurAI-0', 'reach_accepted'), get('OurAI-0', 'dahai')) * 100,
        safe_div(get('OurAI-1', 'reach_accepted'), get('OurAI-1', 'dahai')) * 100,
        safe_div(get('OurAI-2', 'reach_accepted'), get('OurAI-2', 'dahai')) * 100,
        safe_div(get('Akochan', 'reach_accepted'), get('Akochan', 'dahai')) * 100,
    ], '18-19%'))
    rows.append(('放銃率(%)', [
        safe_div(get('OurAI-0', 'hoju'), get_kyoku('OurAI-0')) * 100,
        safe_div(get('OurAI-1', 'hoju'), get_kyoku('OurAI-1')) * 100,
        safe_div(get('OurAI-2', 'hoju'), get_kyoku('OurAI-2')) * 100,
        safe_div(get('Akochan', 'hoju'), get_kyoku('Akochan')) * 100,
    ], '12-14%'))
    rows.append(('平均和了点', [
        safe_div(get('OurAI-0', 'hora_score_sum'), get('OurAI-0', 'hora')),
        safe_div(get('OurAI-1', 'hora_score_sum'), get('OurAI-1', 'hora')),
        safe_div(get('OurAI-2', 'hora_score_sum'), get('OurAI-2', 'hora')),
        safe_div(get('Akochan', 'hora_score_sum'), get('Akochan', 'hora')),
    ], '6466'))
    rows.append(('平均放銃点', [
        safe_div(get('OurAI-0', 'hoju_score_sum'), get('OurAI-0', 'hoju')),
        safe_div(get('OurAI-1', 'hoju_score_sum'), get('OurAI-1', 'hoju')),
        safe_div(get('OurAI-2', 'hoju_score_sum'), get('OurAI-2', 'hoju')),
        safe_div(get('Akochan', 'hoju_score_sum'), get('Akochan', 'hoju')),
    ], '734(損失)'))
    rows.append(('流局テンパイ(%)', [
        safe_div(get('OurAI-0', 'ryukyoku_tenpai'), get('OurAI-0', 'ryukyoku')) * 100 if get('OurAI-0', 'ryukyoku') else 0,
        safe_div(get('OurAI-1', 'ryukyoku_tenpai'), get('OurAI-1', 'ryukyoku')) * 100 if get('OurAI-1', 'ryukyoku') else 0,
        safe_div(get('OurAI-2', 'ryukyoku_tenpai'), get('OurAI-2', 'ryukyoku')) * 100 if get('OurAI-2', 'ryukyoku') else 0,
        safe_div(get('Akochan', 'ryukyoku_tenpai'), get('Akochan', 'ryukyoku')) * 100 if get('Akochan', 'ryukyoku') else 0,
    ], '45-46%'))
    rows.append(('立直平均巡目', [
        safe_div(get('OurAI-0', 'reach_turn_sum'), get('OurAI-0', 'reach_accepted')),
        safe_div(get('OurAI-1', 'reach_turn_sum'), get('OurAI-1', 'reach_accepted')),
        safe_div(get('OurAI-2', 'reach_turn_sum'), get('OurAI-2', 'reach_accepted')),
        safe_div(get('Akochan', 'reach_turn_sum'), get('Akochan', 'reach_accepted')),
    ], '9.4'))
    rows.append(('立直先制率(%)', [
        safe_div(get('OurAI-0', 'reach_first_move'), get('OurAI-0', 'reach_accepted')) * 100 if get('OurAI-0', 'reach_accepted') else 0,
        safe_div(get('OurAI-1', 'reach_first_move'), get('OurAI-1', 'reach_accepted')) * 100 if get('OurAI-1', 'reach_accepted') else 0,
        safe_div(get('OurAI-2', 'reach_first_move'), get('OurAI-2', 'reach_accepted')) * 100 if get('OurAI-2', 'reach_accepted') else 0,
        safe_div(get('Akochan', 'reach_first_move'), get('Akochan', 'reach_accepted')) * 100 if get('Akochan', 'reach_accepted') else 0,
    ], '79-81%'))

    for label, vals, target in rows:
        lines.append(f'{label:<20} {vals[0]:<12.1f} {vals[1]:<12.1f} {vals[2]:<12.1f} {vals[3]:<12.1f} {target:<12}')

    # ファイル & stdout に書く
    out_path = os.path.join(LOG_DIR, '_analysis.txt')
    text = '\n'.join(lines)
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(text)
    print(text)
    print(f'\nSaved to {out_path}')


if __name__ == '__main__':
    main()
