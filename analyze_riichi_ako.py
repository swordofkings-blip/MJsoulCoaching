import json, os
from collections import Counter, defaultdict

# Parse mjson and compare Our AI's choices vs Akochan's choices
our_discard = []
akochan_discard = []

# In the mjson, each Our AI and Akochan has their own daihai events
# Our AI names: 'OurAI-0', 'OurAI-1', 'OurAI-2'
# Akochan name: 'Akochan'

# Track per-game our_vs_ako mismatches
mismatches = []
total_turns = 0
game_count = 0

# For riichi-related analysis
our_dahai_in_riichi = []
ako_dahai_in_riichi = []

current_riichi = [False, False, False, False]  # 0,1,2 = OurAI; 3 = Akochan

for path in sorted(os.listdir('logs')):
    if not path.startswith('game_') or not path.endswith('.mjson'): continue
    full = os.path.join('logs', path)
    if os.path.getsize(full) < 1000: continue

    current_riichi = [False, False, False, False]
    dahai_by_actor = [[], [], [], []]
    game_count += 1

    with open(full, 'r', encoding='utf-8') as f:
        for line in f:
            try: ev = json.loads(line.strip())
            except: continue
            t = ev.get('type')
            actor = ev.get('actor')
            if actor is None: continue

            if t == 'reach':
                current_riichi[actor] = True
            elif t == 'reach_accepted':
                current_riichi[actor] = True
            elif t == 'reach_canceled':
                current_riichi[actor] = False
            elif t == 'end_kyoku':
                current_riichi = [False, False, False, False]
            elif t == 'dahai':
                if actor in [0, 1, 2, 3]:
                    name = 'OurAI' if actor in [0, 1, 2] else 'Akochan'
                    is_riichi = current_riichi[actor]
                    tile = ev.get('pai', '?')
                    tsumogiri = ev.get('tsumogiri', True)
                    dahai_by_actor[actor].append((tile, is_riichi, tsumogiri))

    # For each turn, compare
    # Find max length
    max_len = max(len(d) for d in dahai_by_actor)
    for i in range(max_len):
        # Get our AI's discards (any of 0, 1, 2) and Akochan's (3)
        # Actually we should look at each of OurAI's choices vs Akochan
        for our_actor in [0, 1, 2]:
            if i < len(dahai_by_actor[our_actor]) and i < len(dahai_by_actor[3]):
                our_tile, our_riichi, our_tsumogiri = dahai_by_actor[our_actor][i]
                ako_tile, ako_riichi, ako_tsumogiri = dahai_by_actor[3][i]
                total_turns += 1
                if our_tile != ako_tile:
                    mismatches.append({
                        'game': path,
                        'our_actor': our_actor,
                        'turn_idx': i,
                        'our_tile': our_tile,
                        'ako_tile': ako_tile,
                        'our_riichi': our_riichi,
                        'ako_riichi': ako_riichi,
                    })

print(f'ゲーム数: {game_count}')
print(f'総ターン数: {total_turns}')
print(f'ミスマッチ数: {len(mismatches)} (一致率: {(total_turns-len(mismatches))/total_turns*100:.1f}%)')
print()

# === Riichi-specific analysis ===
riichi_mismatches = [m for m in mismatches if m['our_riichi'] or m['ako_riichi']]
print(f'リーチ状況ミスマッチ: {len(riichi_mismatches)}/{len(mismatches)}')
print()

# === Categorize by our/ako riichi state ===
print('=== ミスマッチの分類 ===')
both_riichi = sum(1 for m in mismatches if m['our_riichi'] and m['ako_riichi'])
our_riichi_only = sum(1 for m in mismatches if m['our_riichi'] and not m['ako_riichi'])
ako_riichi_only = sum(1 for m in mismatches if m['ako_riichi'] and not m['our_riichi'])
no_riichi = sum(1 for m in mismatches if not m['our_riichi'] and not m['ako_riichi'])
print(f'  両者リーチ: {both_riichi}')
print(f'  OurAIのみリーチ: {our_riichi_only}')
print(f'  Akochanのみリーチ: {ako_riichi_only}')
print(f'  両者非リーチ: {no_riichi}')
print()

# === Tsumogiri analysis ===
tsumogiri_mismatches = [m for m in mismatches if m.get('our_tsumogiri', True) or m.get('ako_tsumogiri', True)]
print(f'ツモ切り関連ミスマッチ: {len(tsumogiri_mismatches)}')
