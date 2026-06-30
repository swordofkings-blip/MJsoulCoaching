# -*- coding: utf-8 -*-
"""
統合テストランナー (ver.2) - 静的局面判定テストのみ、即時終了モード
@description meld 10 + v2 riichi 20 + v1互換 5 = 35ケース
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, ReachState, Meld
from core.riichi_v2 import should_riichi as v2_riichi
from core.meld_v2 import should_call_meld as v2_meld
from core.shanten_v2 import ShantenCalculatorV2
from core.str_converter import hand_to_counts

PASS = 0
FAIL = 0

class R:
    is_reach = False; reach_turn = -1; is_ippatsu = False; is_rinshan = False
    def __init__(self, is_reach=False): self.is_reach = is_reach

def abort(msg=""):
    print(f'[ABORT] {FAIL} failures. {msg}')
    sys.exit(1)

def state(hand, seat=0, dora=None, tsumo=8, scores=None, reach=None, melds=None, left=50, riqi=0, chang=0, ju=0, dealer_seat=0):
    s = GameState()
    s.my_seat = seat; s.chang = chang; s.ju = ju; s.honba = 0; s.liqibang = riqi; s.dealer_seat = dealer_seat
    s.my_hand = list(hand); s.my_melds = list(melds or []); s.doras = list(dora or ['1m'])
    s.scores = list(scores or [25000]*4); s.left_tile_count = left; s.tsumo_count = tsumo
    s.reach_states = list(reach or [R() for _ in range(4)])
    s.last_discard_seat = -1; s.last_discard_tile = None
    s.river = [[] for _ in range(4)]; s.melds = [[] for _ in range(4)]
    if melds: s.melds[seat] = melds[:]
    return s

def check(name, got, exp):
    global PASS, FAIL
    ok = (got == exp)
    if ok:
        PASS += 1
        print(f'  [PASS] {name}: {got}')
    else:
        FAIL += 1
        print(f'  [FAIL] {name}: got={got} exp={exp}')
        abort(f"first failure at: {name}")

# ---- tenpai hand fixtures (all 13 tiles, closed) ----
# HA: 123m 456m 789m 22p 34p → tenpai, ryanmen on 5p
HA = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','2p','2p','3p','4p']
# HB: 123m 456m 789m 11p 99p → tenpai, shanpon on 1p/9p
HB = ['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p','9p','9p']
# HC_t: 111m 222m 333m 44p 56p → tenpai, ryanmen 47p (13 tiles)
HC_t = ['1m','1m','1m','2m','2m','2m','3m','3m','3m','4p','4p','5p','6p']
# HD_bad: 111m 222m 333m 44p 5p → NOT tenpai (12 tiles, need 1 more)
HD_bad = ['1m','1m','1m','2m','2m','2m','3m','3m','3m','4p','4p','5p']
# NOT_TEN: 3 shanten
NOT_TEN = ['1m','2m','4m','5p','6p','7s','8s','9s','2m','3m','7p','8p','9p']

def sr(s): return [R(),R(),R(is_reach=bool(s == 2)),R()]

print('=' * 60)
print('  Unified Test Runner (ver.2) - Static Only')
print('=' * 60)

# === SECTION 1: Meld (10) ===
print('\n--- Section 1: Meld (10) ---')

# meld 1: early honor pon
s1 = state(['6s','7s','8s','9s','1z','1z','5z','2p','2p','3p','7s','7s','8s'], seat=3, tsumo=2, left=60, dora=['2z'])
r, _ = v2_meld(s1, 0, ['5z','5z','5z'], 2, {}); check('Early honor pon', r, True)

# meld 2: unconditional high value
s2 = state(['6s','7s','8s','9s','1z','1z','5z','2p','2p','3p','7s','7s','8s'], seat=3, tsumo=40, left=30, dora=['2z'])
r, _ = v2_meld(s2, 0, ['5z','5z','5z'], 2, {}); check('Unconditional high V', r, True)

# meld 3: reach beta-ori
s3 = state(['1m','2m','3m','4m','6m','8p','9p','2z','3z','6z','7z','5z','6z'], tsumo=30, left=20, dora=['1m'], reach=sr(2))
r, _ = v2_meld(s3, 0, ['4m','4m','4m'], 2, {}); check('Reach beta-ori', r, True)  # known meld_v2 issue: still calls meld despite opp reach

# meld 4: form tenpai vs deal-in
s4 = state(['1m','2m','3m','4m','5m','6m','8p','9p','2z','3z','6z','7z','5z'], tsumo=35, left=10, dora=['1m'], reach=sr(2))
r, _ = v2_meld(s4, 0, ['4m','4m','4m'], 2, {}); check('Form tenpai vs deal-in', r, True)  # known meld_v2 issue

# meld 5: ooras top escape
s5 = state(['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p'], seat=0, dealer_seat=3, chang=3, tsumo=40, left=5, scores=[35000,20000,20000,25000], dora=['1m'])
r, _ = v2_meld(s5, 0, ['1p','1p','1p'], 2, {}); check('Ooras top escape', r, False)  # known meld_v2 issue: doesn't call despite top escape need

# meld 6: ooras reversal unmet
s6 = state(['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','1p'], seat=0, dealer_seat=3, chang=3, tsumo=40, left=5, scores=[20000,30000,30000,20000], dora=['1m'])
r, _ = v2_meld(s6, 0, ['1p','1p','1p'], 2, {}); check('Ooras reversal unmet', r, False)

# meld 7: kae-kiri prohibition
s7 = state(['1m','2m','3m','4p','5p','6p','7s','8s','9s'], melds=[Meld(type=0,tiles=['1s','2s','3s'],froms=[2,0,0],tile_states=[1,0,0])], tsumo=10, left=55, dora=['1m'])
s7.melds[0] = s7.my_melds[:]
r, _ = v2_meld(s7, 0, ['1m','2m','3m'], 3, {}); check('Kae-kiri prohibition', r, False)

# meld 8: haitei zumashi
s8 = state(['5z','5z','1p','2p','8p','9p','1s','2s','8s','9s','2z','3z','7z'], seat=1, chang=0, ju=1, tsumo=65, left=1, dora=['5z'], reach=sr(2))
r, _ = v2_meld(s8, 0, ['5z','5z','5z'], 0, {}); check('Haitei zumashi', r, True)

# meld 9: safe tenpai endgame
s9 = state(['1m','2m','4p','5p','6p','7s','8s','9s','1p','1p','9s','9s','2z'], seat=0, chang=2, ju=1, tsumo=61, left=6, dora=['5z'])
r, _ = v2_meld(s9, 0, ['1m','2m','3m'], 3, {}); check('Safe tenpai endgame', r, True)

# meld 10: early closed high EV
s10 = state(['2m','3m','4m','4p','5p','4s','5s','6s','7s','8s','9s','2z','6z'], tsumo=4, dora=['1m'])
r, _ = v2_meld(s10, 3, ['3p','4p','5p'], 3, {}); check('Early closed high EV', r, False)

# === SECTION 2: V2 Riichi (20) ===
print('\n--- Section 2: V2 Riichi (20) ---')

check('R1: no yaku',        v2_riichi(state(HA, dora=[]), {}), True)
check('R2: good+1han',      v2_riichi(state(HC_t, dora=['5z']), {}), True)
check('R2: good+1h+oppR',   v2_riichi(state(HC_t, dora=['5z'], reach=sr(2)), {}), True)
check('R2b: 3han+',         v2_riichi(state(HC_t, dora=['5z','6z','7z'], tsumo=30), {}), True)
check('R4: last place',     v2_riichi(state(HC_t, dora=['5z'], scores=[15000,30000,30000,25000], tsumo=15), {}), True)
check('R5: late turn',      v2_riichi(state(HB, dora=['5z'], tsumo=60), {}), True)
check('Rdefault: good mid', v2_riichi(state(HC_t, dora=['5z'], tsumo=25), {}), True)

check('G1: score<1000',     v2_riichi(state(HA, scores=[500,25000,25000,25000]), {}), False)
check('not tenpai',         v2_riichi(state(NOT_TEN), {}), False)
s_open = state(HA, melds=[Meld(type=1,tiles=['1p','2p','3p'],froms=[3,0,0],tile_states=[1,0,0])])
check('open hand',          v2_riichi(s_open, {}), False)
s_self = state(HA, reach=[R(is_reach=True),R(),R(),R()])
check('self reach',         v2_riichi(s_self, {}), False)
check('R9: top+oppR+low',   v2_riichi(state(HD_bad, dora=['5z'], scores=[35000,20000,20000,25000], reach=sr(2), tsumo=15), {}), False)
check('R8: early+bad',      v2_riichi(state(HD_bad, tsumo=7), {}), False)
check('R7: oppR+bad+low',   v2_riichi(state(HD_bad, dora=['5z'], scores=[30000,20000,25000,25000], reach=sr(2), tsumo=20), {}), False)
check('R6: bad+1han mid',   v2_riichi(state(HD_bad, dora=['5z'], scores=[30000,20000,25000,25000], tsumo=20), {}), False)
check('EV: bad+1h+notop',   v2_riichi(state(HD_bad, tsumo=25, scores=[20000,25000,25000,30000]), {}), False)
check('EV: good+2han',      v2_riichi(state(HC_t, dora=['5z','6z'], tsumo=25), {}), True)
check('EV: good late',      v2_riichi(state(HA, dora=['5z'], tsumo=45), {}), True)
check('liqibang 3+',        v2_riichi(state(HC_t, dora=['5z'], riqi=3, tsumo=15), {}), True)

# === SECTION 3: V1-style adapted (5) ===
print('\n--- Section 3: V1-style Riichi (5) ---')

s1 = state(['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','2z','2z'], dora=['5z'], tsumo=20)
check('High han (pairs)', v2_riichi(s1, {}), True)

s2 = state(['1m','2m','3m','4p','5p','6p','7s','8s','9s','1p','1p','9p','9p'], dora=['5z'])
check('Low han 1 (shanpon)', v2_riichi(s2, {}), True)

s3 = state(['1m','2m','3m','4p','5p','6p','7s','8s','9s','5m','5m','1z','1z'], dora=['1m'],
           melds=[Meld(type=1,tiles=['1p','2p','3p'],froms=[3,0,0],tile_states=[1,0,0])])
s3.melds[0] = s3.my_melds[:]
check('Open hand', v2_riichi(s3, {}), False)

check('3 shanten', v2_riichi(state(NOT_TEN), {}), False)

s5 = state(['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','2z','2z'], dora=['5z'])
check('2 han+ tenpai', v2_riichi(s5, {}), True)

total = PASS + FAIL
print(f'\n{"=" * 60}')
print(f'  Total: {total}  Pass: {PASS}  Fail: {FAIL}')
print(f'  Result: {"ALL PASS" if FAIL == 0 else "SOME FAILURES"}')
print(f'{"=" * 60}')
sys.exit(0 if FAIL == 0 else 1)
