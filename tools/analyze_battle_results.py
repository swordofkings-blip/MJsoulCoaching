import json
import os
import glob
from collections import defaultdict

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')

def has_qm(tehais):
    for hand in tehais:
        if isinstance(hand, list):
            for tile in hand:
                if tile == '?':
                    return True
    return False

def is_short_hora(data):
    return (data.get('type') == 'hora' and 'fan' not in data
            and 'hora_points' not in data and 'uradora_markers' not in data)

def analyze():
    import re
    pattern = re.compile(r'game_(\d+)\.mjson$')
    mjson_files = sorted(
        (f for f in glob.glob(os.path.join(LOG_DIR, 'game_*.mjson')) if pattern.search(f)),
        key=lambda x: int(pattern.search(x).group(1))
    )

    stats = defaultdict(lambda: {
        'kyoku': 0, 'wins': 0, 'ron_wins': 0, 'tsumo_wins': 0,
        'deal_in': 0, 'call_kyoku': 0,
    })
    player_names = set()

    for fpath in mjson_files:
        with open(fpath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        names, seat_map = [], {}

        for line in lines:
            try:
                data = json.loads(line.strip())
            except:
                continue
            if data.get('type') == 'start_game':
                names = data.get('names', [])
                seat_map = {s: n for s, n in enumerate(names)}
                player_names.update(names)
                break

        in_kyoku = False
        seen_hora = set()
        callers_this_kyoku = set()

        for line in lines:
            try:
                data = json.loads(line.strip())
            except:
                continue

            tp = data.get('type', '')

            if tp == 'start_kyoku':
                tehais = data.get('tehais', [])
                if not tehais or not isinstance(tehais, list) or len(tehais) < 4:
                    continue
                if has_qm(tehais):
                    continue
                in_kyoku = True
                seen_hora = set()
                callers_this_kyoku = set()
                for s in seat_map:
                    stats[seat_map[s]]['kyoku'] += 1

            if not in_kyoku:
                continue

            if tp == 'pon':
                if data.get('consumed') and data.get('actor') is not None:
                    actor = data['actor']
                    if actor in seat_map:
                        callers_this_kyoku.add(actor)

            if tp == 'daiminkan':
                if data.get('actor') is not None:
                    actor = data['actor']
                    if actor in seat_map:
                        callers_this_kyoku.add(actor)

            if is_short_hora(data):
                actor = data.get('actor')
                target = data.get('target')
                hkey = (actor, target)
                if hkey in seen_hora:
                    continue
                seen_hora.add(hkey)
                winner = seat_map.get(actor, f'P{actor}')
                is_tsumo = (actor == target)
                stats[winner]['wins'] += 1
                if is_tsumo:
                    stats[winner]['tsumo_wins'] += 1
                else:
                    stats[winner]['ron_wins'] += 1
                    loser = seat_map.get(target, f'P{target}')
                    stats[loser]['deal_in'] += 1
                in_kyoku = False

            if tp == 'ryukyoku':
                in_kyoku = False

        # Register callers for this game
        for s in callers_this_kyoku:
            stats[seat_map[s]]['call_kyoku'] += 1

    total_kyoku = sum(stats[n]['kyoku'] for n in player_names) // max(len(player_names), 1)
    print(f"Analyzed {len(mjson_files)} games, ~{total_kyoku} kyoku total")
    print()

    order = ['Akochan'] + sorted([n for n in player_names if n.startswith('OurAI')])
    for name in order:
        if name not in stats:
            continue
        s = stats[name]
        ky = s['kyoku']
        print(f"=== {name} ({ky} kyoku) ===")
        print(f"  Wins:      {s['wins']:3d}  ({s['wins']/max(ky,1)*100:.1f}%)")
        if s['wins']:
            print(f"    Ron:     {s['ron_wins']:3d} / Tsumo: {s['tsumo_wins']:3d}")
        print(f"  Deal-ins:  {s['deal_in']:3d}  ({s['deal_in']/max(ky,1)*100:.1f}%)")
        print(f"  Call kyoku:{s['call_kyoku']:3d}  ({s['call_kyoku']/max(ky,1)*100:.1f}%)")
        print()

    ako = stats.get('Akochan', {})
    our_names = [n for n in player_names if n.startswith('OurAI')]
    aggr = {k: sum(stats[n].get(k, 0) for n in our_names) for k in ['kyoku', 'wins', 'ron_wins', 'tsumo_wins', 'deal_in', 'call_kyoku']}
    ky_total = max(aggr['kyoku'] // 3, 1)

    print("=== Summary (per agent per kyoku) ===")
    print(f"              OurAI(avg)  Akochan")
    print(f"  Win rate    {aggr['wins']/ky_total/3*100:6.1f}%     {ako.get('wins',0)/max(ako.get('kyoku',1),1)*100:5.1f}%")
    print(f"  Deal-in rate{aggr['deal_in']/ky_total/3*100:6.1f}%     {ako.get('deal_in',0)/max(ako.get('kyoku',1),1)*100:5.1f}%")
    print(f"  Call rate   {aggr['call_kyoku']/ky_total/3*100:6.1f}%     {ako.get('call_kyoku',0)/max(ako.get('kyoku',1),1)*100:5.1f}%")
    print(f"  Ron/Tsumo   {aggr['ron_wins']}/{aggr['tsumo_wins']:3d}              {ako.get('ron_wins',0)}/{ako.get('tsumo_wins',0)}")
    print()
    total_wins = ako.get('wins',0) + aggr['wins']
    print(f"  Total wins: {total_wins} / {total_kyoku} kyoku ({total_wins/max(total_kyoku,1)*100:.1f}%)")

if __name__ == '__main__':
    analyze()
