# -*- coding: utf-8 -*-
"""
@title 副露判断テストハーネス (10 ケース)
@description ユーザ指定の 10 個のテストケースで should_call_meld の判断を検証
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

from core.game_state import GameState, ReachState, Meld
from core.meld_v2 import should_call_meld
from core.str_converter import tile_to_id


def make_state(hand, my_seat=0, dealer_seat=0, chang=0, ju=0,
               dora_indicators=None, honba=0, riqibang=0,
               scores=None, reach_states=None, tsumo_count=0,
               my_melds=None, last_discards=None,
               kyoku_idx=0, left_tile_count=50):
    """テスト用の GameState を作る"""
    s = GameState()
    s.my_seat = my_seat
    s.dealer_seat = dealer_seat
    s.chang = chang
    s.ju = ju
    s.honba = honba
    s.liqibang = riqibang
    s.tsumo_count = tsumo_count
    s.kyotaku = 0
    s.my_hand = list(hand)
    s.my_melds = list(my_melds or [])
    s.doras = list(dora_indicators or ['1m'])
    s.scores = scores or [25000] * 4
    s.left_tile_count = left_tile_count
    s.reach_states = [ReachState() for _ in range(4)]
    if reach_states:
        for seat, reach in reach_states.items():
            if reach:
                s.reach_states[seat].is_reach = True
                        # 3 巡目: 東 1 局 0 巡
    s.kyoku_count = kyoku_idx
    if last_discards is None:
        s.last_discard_seat = -1
        s.last_discard_tile = None
    else:
        s.last_discard_seat, s.last_discard_tile = last_discards
    s.river = [[] for _ in range(4)]
    s.melds = [[] for _ in range(4)]
    if my_melds:
        for m in my_melds:
            s.melds[my_seat].append(m)
    return s


def test_case_1():
    """【攻撃】最序盤の役牌1鳴き (スピード優先)"""
    # 東 1 局 / 0 巡 / ドラ 1 萬 / 南家 (seat 1) / 東家 (seat 0) が發を捨てた
    s = make_state(
        hand=['3m','4m','5m','5p','6p','7s','8s','1z','1z','2z','4z'],
        my_seat=1, dealer_seat=0, chang=0, ju=0,
        dora_indicators=['1m'],
        tsumo_count=4,  # 2 巡目 (4 自摸)
        reach_states={},
    )
    return s, 1, ['1z','1z','4z'], 0  # ポンする牌 (發發北)


def test_case_2():
    """【攻撃】打点確定時の無条件進行"""
    s = make_state(
        hand=['3m','0m','5m','6p','7p','4s','0s','8m','8m','1z','1z','2z'],
        my_seat=2, dealer_seat=0, chang=0, ju=1,
        dora_indicators=['0m','0p','0s'],
        tsumo_count=8,  # 6 巡目
        reach_states={},
    )
    return s, 1, ['1z','1z','2z'], 2  # 南家 (seat 2) が東を捨てた


def test_case_3():
    """【守備】リーチに対する完全ベタオリ"""
    # 国士無双 1 向聴 (13 種 + 1 雀頭) → ポン 東 (役牌ではない) は無意味
    # 14 枚の手牌 (ツモ後) で 鳴く判断
    s = make_state(
        hand=['1m','1z','1z','9m','9m','1p','9p','1s','9s','2z','3z','4z','6z','7z'],
        my_seat=3, dealer_seat=0, chang=2, ju=0,  # 南 1 局
        dora_indicators=['5z'],
        tsumo_count=12,  # 9 巡目
        reach_states={0: True},  # 東家 (seat 0) リーチ
        scores=[38000, 24000, 21000, 17000],
    )
    return s, 1, ['1z'], 1  # 南家 (seat 1) が東を捨てた


def test_case_4():
    """【守備】形式テンパイと放銃リスクの天秤"""
    s = make_state(
        hand=['2m','3m','4m','5p','6p','7p','3s','4s','9m','9m','2z','2z','4z'],
        my_seat=0, dealer_seat=0, chang=0, ju=2,  # 東 3 局
        dora_indicators=['5z'],
        tsumo_count=20,  # 15 巡目
        reach_states={2: True},  # 西家 (seat 2) リーチ
    )
    return s, 3, ['2s'], 3  # 上家 (seat 3) が 2 索を捨てた


def test_case_5():
    """【状況判断】オーラスのトップ逃げ切り"""
    s = make_state(
        hand=['2m','3m','4m','5p','6p','7s','8s','9s','1m','1m','5z','5z','4z'],
        my_seat=0, dealer_seat=0, chang=3, ju=3,  # 南 4 局
        dora_indicators=['5z'],
        tsumo_count=10,  # 8 巡目
        reach_states={},
        scores=[35000, 32000, 24000, 19000],  # 1 位 +3000 差
    )
    return s, 2, ['5z','5z','4z'], 2  # 西家 (seat 2) 中を捨てた


def test_case_6():
    """【状況判断】オーラスの逆転条件未達"""
    s = make_state(
        hand=['2m','3m','4m','4p','5p','6p','7s','8s','1m','1m','1z','1z','4z'],
        my_seat=0, dealer_seat=0, chang=3, ju=3,  # 南 4 局
        dora_indicators=['1m'],
        tsumo_count=14,  # 10 巡目
        reach_states={},
        scores=[18000, 25000, 22000, 15000],  # 4 位 +7000 差
    )
    return s, 3, ['1z','1z','4z'], 3  # 南家 (seat 3) 發を捨てた


def test_case_7():
    """【ルール】食い替えの禁止"""
    s = make_state(
        hand=['2m','3m','4m','5p','6p','7p','7s','8s','9s','1p','1p','1s','2s'],
        my_seat=0, dealer_seat=0, chang=0, ju=0,
        dora_indicators=['5z'],
        tsumo_count=4,  # 3 巡目
        reach_states={},
    )
    # チー [2m 3m 4m] + 1m → 切るのは 4m (食い替え) → 実行不可
    return s, 3, ['1m','2m','3m'], 3  # 上家 (seat 3) 1 萬を捨てた


def test_case_8():
    """【特殊戦術】ハイテイずらし"""
    s = make_state(
        hand=['5z','5z','1p','2p','8p','9p','1s','2s','8s','9s','2z','3z','7z'],
        my_seat=1, dealer_seat=0, chang=0, ju=1,  # 東 2 局
        dora_indicators=['5z'],
        tsumo_count=65,  # 17 巡目 (海底直前)
        left_tile_count=1,  # 海底牌の直前 (残り 1 枚)
        reach_states={2: True},  # 西家 (seat 2) リーチ中
    )
    # ポン [5z 5z 5z] → 安全牌 (南西北) を切る
    return s, 0, ['5z','5z','5z'], 0  # 東家 (seat 0) 白を捨てた


def test_case_9():
    """【点数確保】終盤の安全な形式テンパイ"""
    s = make_state(
        hand=['1m','2m','4p','5p','6p','7s','8s','9s','1p','1p','9s','9s','2z'],
        my_seat=0, dealer_seat=0, chang=2, ju=1,  # 南 2 局
        dora_indicators=['5z'],
        tsumo_count=61,  # 16 巡目
        left_tile_count=6,  # 終盤 (残り 6 枚)
        reach_states={},
    )
    # チー [123m] + 3m → 西 (安全) を切る
    return s, 0, ['1m','2m','3m'], 3  # 上家 (seat 3) 3 萬を捨てた (chi=0)


def test_case_10():
    """【戦略】序盤の面前高期待値の維持"""
    s = make_state(
        hand=['2m','3m','4m','4p','5p','4s','5s','6s','7s','8s','9s','2z','6z'],
        my_seat=0, dealer_seat=0, chang=0, ju=0,
        dora_indicators=['1m'],
        tsumo_count=4,  # 3 巡目
        reach_states={},
    )
    # チー [345p] + 3p → 手牌良形だがピンフ潰し
    return s, 3, ['3p','4p','5p'], 3  # 上家 (seat 3) 3 索を捨てた


def run_all_tests():
    test_funcs = [
        ('Test 1 [攻撃] 最序盤の役牌1鳴き', test_case_1, True),   # ポン期待
        ('Test 2 [攻撃] 打点確定時の無条件進行', test_case_2, True),  # ポン期待
        ('Test 3 [守備] リーチ完全ベタオリ', test_case_3, False),  # スルー期待
        ('Test 4 [守備] 形式テンパイ vs 放銃', test_case_4, False),  # スルー期待
        ('Test 5 [状況] オーラストップ逃げ切り', test_case_5, True),  # ポン期待
        ('Test 6 [状況] オーラス逆転条件未達', test_case_6, False),  # スルー期待
        ('Test 7 [ルール] 食い替え禁止', test_case_7, False),  # スルー期待
        ('Test 8 [特殊] ハイテイずらし', test_case_8, True),  # ポン期待
        ('Test 9 [点数] 終盤の安全形式テンパイ', test_case_9, True),  # チー期待
        ('Test 10 [戦略] 序盤の面前高期待値', test_case_10, False),  # スルー期待
    ]

    passed = 0
    total = len(test_funcs)
    results = []
    for name, fn, expected_pon in test_funcs:
        s, call_type, tiles, from_seat = fn()
        try:
            decision, reason = should_call_meld(s, call_type, tiles, from_seat, {})
        except Exception as e:
            decision = False
            reason = f'EXCEPTION: {e}'
        # 鳴くべきかどうか
        should_meld = decision
        ok = (should_meld == expected_pon)
        results.append((name, ok, expected_pon, should_meld, reason))
        if ok:
            passed += 1
    print(f'\n=== 結果: {passed}/{total} pass ===\n', flush=True)
    for name, ok, expected, actual, reason in results:
        mark = '[PASS]' if ok else '[FAIL]'
        expect_str = '鳴く' if expected else 'スルー'
        actual_str = '鳴く' if actual else 'スルー'
        print(f'  {mark} {name}')
        print(f'         期待: {expect_str}, 実際: {actual_str}')
        print(f'         理由: {reason[:100]}')
    return passed, total


if __name__ == '__main__':
    p, t = run_all_tests()
    sys.exit(0 if p == t else 1)
