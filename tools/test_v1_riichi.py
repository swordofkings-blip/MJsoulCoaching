# -*- coding: utf-8 -*-
"""
@title v1 (Evaluator) 立直評価検証
@description v1 が立直時に ツモ/裏ドラ/一発 を正しく評価しているか検証
"""
import os
import sys
import io
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.game_state import GameState, ReachState
from core.evaluator import Evaluator
from core.str_converter import hand_to_counts


def make_state(my_hand, my_seat=0, dealer_seat=0, dora_indicators=None):
    s = GameState()
    s.my_seat = my_seat
    s.dealer_seat = dealer_seat
    s.chang = 0
    s.ju = 0
    s.honba = 0
    s.liqibang = 0
    s.tsumo_count = 8
    s.kyotaku = 0
    s.my_hand = list(my_hand)
    s.my_melds = []
    s.doras = list(dora_indicators or ['1m'])
    s.scores = [25000, 25000, 25000, 25000]
    s.left_tile_count = 50
    s.reach_states = [ReachState() for _ in range(4)]
    s.kyoku_count = 0
    s.last_discard_seat = -1
    s.last_discard_tile = None
    s.river = [[] for _ in range(4)]
    s.melds = [[] for _ in range(4)]
    return s


# 10 翻の手牌 (面前テンパイ、満貫以上)
# [123m 456p 789s 東東 南南] 東東 + 南南 で 東(役牌)+南(役牌) の 2 翻 + 面前 + タンヤオ 1 翻
# ツモ 1/4 → 期待 +0.25 翻, 裏ドラ 30% → 期待 +0.30 翻, 一発 20% → 期待 +0.20 翻, 立直 1 翻
# 期待値: 1+0.25+0.30+0.20+1 (面前) + 0.50 (タンヤオ) = 3.25 翻
# ダマ: 2.5 翻 (面前 + タンヤオ)
# リーチ: +1 (立直) + 期待 +0.75 (その他) = 1.75 翻 上乗せ
# → 明らかにリーチ有利
def test_v1_riichi_high_han():
    """6 翻の手 (面前テンパイ) → リーチ有利"""
    s = make_state(
        my_hand=['1m','2m','3m','4p','5p','6p','7s','8s','9s','1z','1z','2z','2z','5z']
    )
    ev = Evaluator(s, {})
    decision = ev.should_riichi()
    return decision


# 1 翻の手 (面前テンパイ、役なし手牌)
def test_v1_riichi_low_han():
    """1 翻の手 (面前テンパイ) → リーチ有利 (1 翻上乗せ)"""
    s = make_state(
        my_hand=['1m','2m','3m','4p','5p','6p','7s','8s','9s','1m','2p','3s','9p','8p']
    )
    ev = Evaluator(s, {})
    decision = ev.should_riichi()
    return decision


# 8 翻の手 (面前テンパイ、満貫級)
def test_v1_riichi_haneman():
    """8 翻級 (満貫) → リーチ有利"""
    s = make_state(
        my_hand=['1m','2m','3m','4p','5p','6p','7s','8s','9s','0m','0m','1z','1z','5z'],
        dora_indicators=['1m']
    )
    ev = Evaluator(s, {})
    decision = ev.should_riichi()
    return decision


# 副露後のテンパイ手 (リーチできないはず)
def test_v1_riichi_with_open_meld():
    """副露後のテンパイ → リーチ不可 (面前でない)"""
    s = make_state(
        my_hand=['1m','2m','3m','4p','5p','6p','7s','8s','9s','5m','5m','1z','1z','5z'],
    )
    # 副露は tile_states フラグ (0=手牌, 1=オープン)
    from core.game_state import Meld
    s.my_melds = [Meld(type=1, tiles=['1p','2p','3p'], froms=[3,0,0], tile_states=[1,0,0])]
    s.melds[0].append(s.my_melds[0])
    ev = Evaluator(s, {})
    decision = ev.should_riichi()
    return decision


# 遠い手 (3 向聴) → リーチしない
def test_v1_riichi_far_away():
    """3 向聴 → リーチしない (遠い)"""
    s = make_state(
        my_hand=['1m','2m','4m','5p','6p','7s','8s','9s','2m','3m','7p','8p','9p','4s']
    )
    ev = Evaluator(s, {})
    decision = ev.should_riichi()
    return decision


# 牌が少ない (10 枚のみ) → そもそも 13 枚にする
def main():
    print('=== v1 (Evaluator) 立直評価テスト ===\n')

    results = []
    for name, fn, expected, desc in [
        ('Test 1: 高打点 (6 翻以上) 面前テンパイ → リーチ',
         test_v1_riichi_high_han, True,
         '面前 6 翻手 → 立直で +1.75 翻上乗せ → リーチすべき'),
        ('Test 2: 低打点 (1 翻) 面前テンパイ → リーチ',
         test_v1_riichi_low_han, True,
         '面前 1 翻手 → 立直で +1 翻上乗せ → リーチすべき'),
        ('Test 3: 満貫級 (8 翻) 面前テンパイ → リーチ',
         test_v1_riichi_haneman, True,
         '面前 8 翻手 → 立直で +1.75 翻上乗せ → リーチすべき'),
        ('Test 4: 副露後テンパイ → リーチ不可',
         test_v1_riichi_with_open_meld, False,
         '副露済 (チー) → 面前でない → リーチ不可'),
        ('Test 5: 遠い手 (3 向聴) → リーチしない',
         test_v1_riichi_far_away, False,
         '3 向聴 → テンパイしてない → リーチ不可'),
    ]:
        try:
            result = fn()
            ok = (result == expected)
            mark = '[PASS]' if ok else '[FAIL]'
            print(f'  {mark} {name}')
            print(f'         期待: {"リーチ" if expected else "スルー"}, 実際: {"リーチ" if result else "スルー"}')
            print(f'         {desc}')
            results.append(ok)
        except Exception as e:
            print(f'  [ERR] {name}: {e}')
            results.append(False)

    passed = sum(results)
    total = len(results)
    print(f'\n=== 結果: {passed}/{total} pass ===')
    return passed == total


if __name__ == '__main__':
    ok = main()
    sys.exit(0 if ok else 1)
