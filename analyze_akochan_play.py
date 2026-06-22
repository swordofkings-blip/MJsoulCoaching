import json
with open('logs/game_0.mjson') as f:
    lines = f.readlines()
print(f'Total events: {len(lines)}')
n_akochan_dahai = 0
n_akochan_reach = 0
for i, line in enumerate(lines):
    try:
        d = json.loads(line)
        if d.get('type') == 'dahai' and d.get('actor') == 3:
            n_akochan_dahai += 1
        if d.get('type') == 'reach' and d.get('actor') == 3:
            n_akochan_reach += 1
    except:
        pass
print(f'Akochan dahai: {n_akochan_dahai}')
print(f'Akochan reach: {n_akochan_reach}')

# Compare OurAI dahai count
n_ourai_dahai = 0
n_ourai_reach = 0
for i, line in enumerate(lines):
    try:
        d = json.loads(line)
        if d.get('type') == 'dahai' and d.get('actor') in (0, 1, 2):
            n_ourai_dahai += 1
        if d.get('type') == 'reach' and d.get('actor') in (0, 1, 2):
            n_ourai_reach += 1
    except:
        pass
print(f'OurAI dahai: {n_ourai_dahai}')
print(f'OurAI reach: {n_ourai_reach}')
