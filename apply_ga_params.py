"""
Apply best GA parameters to config_parameters.json
"""
import json

# Best params from GA
best_params = {
    "DAMATEN_FLEX_BONUS": 8,
    "DAMATEN_TSUMO_RATE": 0.1,
    "DAMATEN_WAIT_IMP_BONUS": 0.12,
    "DAMATEN_YAKU_IMP_BONUS": 0.0,
    "RIICHI_DEFENSE_COST": 0.36,
    "RIICHI_DORA_DOUBLE_THRESH": 2,
    "RIICHI_DORA_LOW_THRESH": 2,
    "RIICHI_DORA_MID_THRESH": 1,
    "RIICHI_FOLD_RATE": 0.659,
    "RIICHI_HAN_HIGH_THRESH": 4,
    "RIICHI_HAN_MID_THRESH": 3,
    "RIICHI_LAST_TURN": 9,
    "RIICHI_LAST_WAIT_LOW": 3,
    "RIICHI_LATE_PENALTY": 0.848,
    "RIICHI_LATE_TURN_DAMATEN": 10,
    "RIICHI_LATE_WAIT_MAX": 5,
    "RIICHI_MODE_AGGRO": 0.031,
    "RIICHI_OPP_REACH_PENALTY": 0.515,
    "RIICHI_STICK_COST": 0.704,
    "RIICHI_TSUMO_RATE": 0.241,
    "RIICHI_TURN_MAX_LOW": 8,
    "RIICHI_TURN_MAX_MID": 10,
    "RIICHI_TURN_MIN_LOW": 1,
    "RIICHI_TURN_MIN_MID": 1,
    "RIICHI_URA_MULT": 1.408,
    "RIICHI_URA_THRESH": 1,
    "RIICHI_VERY_LATE_TURN": 12,
    "RIICHI_VERY_LATE_WAIT_MAX": 7,
    "RIICHI_WAIT_GOOD_LOW": 7,
    "RIICHI_WAIT_GOOD_THRESH": 9,
    "RIICHI_WAIT_KANCHAN": 0.274,
    "RIICHI_WAIT_MIN_MID": 5,
    "RIICHI_WAIT_PENCHAN": 0.381,
    "RIICHI_WAIT_RYANMEN": 0.593,
    "RIICHI_WAIT_SHANPON": 0.216,
    "RIICHI_WAIT_TANKI": 0.072,
    "RIICHI_WAIT_VERY_LOW": 9,
    "RIICHI_YAKUHAI_LOW_THRESH": 3,
    "RIICHI_YAKUHAI_MID_THRESH": 3,
}

with open('config/config_parameters.json', encoding='utf-8') as f:
    cfg = json.load(f)

# Backup
with open('config/config_parameters.json.bak', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

# Apply
for k, v in best_params.items():
    cfg[k] = v

with open('config/config_parameters.json', 'w', encoding='utf-8') as f:
    json.dump(cfg, f, ensure_ascii=False, indent=2)

print(f'Applied {len(best_params)} parameters to config_parameters.json')
print('Backup saved to config_parameters.json.bak')
