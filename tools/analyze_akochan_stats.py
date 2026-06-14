import json
import os
import glob

LOG_DIR = os.path.join(os.path.dirname(__file__), '..', 'logs')

def has_question_marks(tehais):
    for hand in tehais:
        if isinstance(hand, list):
            for tile in hand:
                if tile == '?':
                    return True
    return False

def analyze():
    import re
    pattern = re.compile(r'game_(\d+)\.mjson$')
    mjson_files = sorted(
        (f for f in glob.glob(os.path.join(LOG_DIR, 'game_*.mjson')) if pattern.search(f)),
        key=lambda x: int(pattern.search(x).group(1))
    )

    total_kyoku = 0
    win_count = 0
    deal_in_count = 0
    call_kyoku = 0
    riichi_kyoku = 0
    riichi_wins = 0
    damaten_wins = 0
    valid_games = 0

    for fpath in mjson_files:
        with open(fpath, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        akochan_seat = -1
        for line in lines:
            try:
                data = json.loads(line.strip())
            except:
                continue
            if data.get('type') == 'start_game':
                names = data.get('names', [])
                if 'Akochan' in names:
                    akochan_seat = names.index('Akochan')
                break

        if akochan_seat < 0:
            continue

        valid_games += 1
        in_kyoku = False
        akochan_called_this_kyoku = False
        akochan_riichi_this_kyoku = False

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
                if has_question_marks(tehais):
                    continue
                # Full start_kyoku (all hands visible)
                in_kyoku = True
                total_kyoku += 1
                akochan_called_this_kyoku = False
                akochan_riichi_this_kyoku = False

            if not in_kyoku:
                continue

            if tp in ('pon', 'chi', 'daiminkan'):
                if data.get('actor') == akochan_seat:
                    akochan_called_this_kyoku = True

            if tp == 'reach':
                if data.get('actor') == akochan_seat:
                    akochan_riichi_this_kyoku = True

            if tp == 'hora':
                winner = data.get('actor')
                loser = data.get('fromWho')
                if winner == akochan_seat:
                    win_count += 1
                    if akochan_riichi_this_kyoku:
                        riichi_wins += 1
                    else:
                        damaten_wins += 1
                if loser == akochan_seat:
                    deal_in_count += 1
                in_kyoku = False
                if akochan_called_this_kyoku:
                    call_kyoku += 1
                if akochan_riichi_this_kyoku:
                    riichi_kyoku += 1

            if tp == 'ryukyoku':
                in_kyoku = False
                if akochan_called_this_kyoku:
                    call_kyoku += 1
                if akochan_riichi_this_kyoku:
                    riichi_kyoku += 1

    win_rate = win_count / total_kyoku if total_kyoku else 0
    deal_in_rate = deal_in_count / total_kyoku if total_kyoku else 0
    call_rate = call_kyoku / total_kyoku if total_kyoku else 0
    riichi_rate = riichi_kyoku / total_kyoku if total_kyoku else 0
    damaten_rate = damaten_wins / win_count if win_count else 0

    print(f"Valid games: {valid_games}")
    print(f"Total kyoku: {total_kyoku}")
    print()
    print(f"Wins:        {win_count:4d}  (win_rate={win_rate:.3f})")
    print(f"  Riichi:    {riichi_wins:4d}")
    print(f"  Damaten:   {damaten_wins:4d}  (damaten_rate={damaten_rate:.3f})")
    print(f"Deal-ins:    {deal_in_count:4d}  (deal_in_rate={deal_in_rate:.3f})")
    print(f"Call kyoku:  {call_kyoku:4d}  (call_rate={call_rate:.3f})")
    print(f"Riichi kyoku:{riichi_kyoku:4d}  (riichi_rate={riichi_rate:.3f})")
    print()
    print("For config_parameters.json:")
    print(f'  "OPPONENT_DEFAULT_CALL_RATE": {call_rate:.3f},')
    print(f'  "OPPONENT_DEFAULT_WIN_RATE": {win_rate:.3f},')
    print(f'  "OPPONENT_DEFAULT_DAMATEN_RATE": {damaten_rate:.3f},')
    print(f'  "OPPONENT_DEFAULT_DEAL_IN_RATE": {deal_in_rate:.3f},')
    print(f'  "OPPONENT_DEFAULT_RIICHI_RATE": {riichi_rate:.3f}')

if __name__ == '__main__':
    analyze()
