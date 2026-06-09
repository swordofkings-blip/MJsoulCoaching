# -*- coding: utf-8 -*-
"""
役満v2 総合テスト
- 副露封印
- 牌貢献度判定
- 門前限定チェック
- 点差緩和
- 優先度選択
- 複合役満時
"""
import json, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'core'))
from game_state import GameState, Meld
from evaluator import Evaluator
from yakuman_evaluator import YakumanEvaluator
from strategy_manager import StrategyManager

P = lambda: json.load(open('config/config_parameters.json', encoding='utf-8'))
TOTAL = 0; PASS = 0; FAIL = 0

def make(hand, scores=None, tsumo=5, melds=None):
    s = GameState()
    s.my_seat = 0
    s.my_hand = list(hand)
    s.scores = scores or [25000]*4
    s.tsumo_count = tsumo
    s.doras = ['1m']
    s.left_tile_count = 70 - tsumo * 4
    if melds:
        s.my_melds = melds
        s.melds[0] = melds
    return s

def check(label, condition, detail=''):
    global TOTAL, PASS, FAIL
    TOTAL += 1
    if condition:
        PASS += 1
        print(f"  [OK] {label}")
    else:
        FAIL += 1
        print(f"  [NG] {label} {detail}")

def test_meld_seal():
    print(f"\n{'='*60}\n  [副露封印テスト]\n{'='*60}")

    # 1. 国士無双1向聴 → 封印ON
    s = make(['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m'])
    sm = StrategyManager(s, params={})
    check("国士無双1向聴 封印ON", not sm.is_meld_open_allowed())

    # 2. 国士無双テンパイ → 封印ON
    s = make(['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','7z','7z'])
    sm = StrategyManager(s, params={})
    check("国士無双テンパイ 封印ON", not sm.is_meld_open_allowed())

    # 3. 四暗刻テンパイ → 封印ON
    s = make(['1m','1m','1m','9p','9p','9p','1s','1s','1s','1z','1z','7z','7z','7z'])
    sm = StrategyManager(s, params={})
    check("四暗刻テンパイ 封印ON", not sm.is_meld_open_allowed())

    # 4. 九蓮宝燈テンパイ → 封印ON
    s = make(['1m','1m','1m','2m','3m','4m','5m','6m','7m','8m','9m','9m','9m','5m'])
    sm = StrategyManager(s, params={})
    check("九蓮宝燈テンパイ 封印ON", not sm.is_meld_open_allowed())

    # 5. 大三元1向聴（副露可）→ 封印OFF
    s = make(['5z','5z','5z','6z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p'])
    sm = StrategyManager(s, params={})
    check("大三元1向聴 封印OFF", sm.is_meld_open_allowed())

    # 6. 字一色テンパイ（副露可）→ 封印OFF
    s = make(['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','6z'])
    sm = StrategyManager(s, params={})
    check("字一色テンパイ 封印OFF", sm.is_meld_open_allowed())

    # 7. 清老頭テンパイ（副露可）→ 封印OFF
    s = make(['1m','1m','1m','9m','9m','9m','1p','1p','1p','9p','9p','9s','9s','9s'])
    sm = StrategyManager(s, params={})
    check("清老頭テンパイ 封印OFF", sm.is_meld_open_allowed())

    # 8. 大四喜テンパイ（副露可）→ 封印OFF
    s = make(['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','4z','5z','5z'])
    sm = StrategyManager(s, params={})
    check("大四喜テンパイ 封印OFF", sm.is_meld_open_allowed())

    # 9. 通常手一向聴 → 封印OFF
    s = make(['1m','2m','3m','4m','5m','6m','7m','8m','9m','1p','2p','3p','4p','4p'])
    sm = StrategyManager(s, params={})
    check("通常手 封印OFF", sm.is_meld_open_allowed())

    # 10. 既に副露済みで門前限定役満が無効 → 封印OFF
    meld = Meld(type=0, tiles=['2p','2p','2p'], froms=[1], tile_states=[0,0,0])
    s = make(['1m','1m','1m','9p','9p','9p','1s','1s','1s','1z','1z','7z','7z','7z'], melds=[meld])
    sm = StrategyManager(s, params={})
    check("副露済み 封印OFF（四暗刻は既に無効）", sm.is_meld_open_allowed())


def test_closed_only():
    print(f"\n{'='*60}\n  [門前限定テスト]\n{'='*60}")

    # 副露ありで四暗刻は無効
    meld = Meld(type=0, tiles=['2p','2p','2p'], froms=[1], tile_states=[0,0,0])
    s = make(['1m','1m','1m','9p','9p','9p','1s','1s','1s','1z','1z','7z','7z','7z'], melds=[meld])
    ye = YakumanEvaluator(s)
    r = ye.evaluate_all()
    check("副露時 四暗刻無効", not r['suuankou'].is_possible)
    check("副露時 国士無双無効", not r['kokushi'].is_possible)
    check("副露時 九蓮宝燈無効", not r['chuuren'].is_possible)

    # 門前で四暗刻は有効
    s2 = make(['1m','1m','1m','9p','9p','9p','1s','1s','1s','1z','1z','7z','7z','7z'])
    ye2 = YakumanEvaluator(s2)
    r2 = ye2.evaluate_all()
    check("門前 四暗刻有効", r2['suuankou'].is_possible)

    # 副露ありで大三元は有効
    s3 = make(['5z','5z','5z','6z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p'], melds=[meld])
    ye3 = YakumanEvaluator(s3)
    r3 = ye3.evaluate_all()
    check("副露時 大三元有効（副露可）", r3['daisangen'].is_possible)


def test_tile_contribution():
    print(f"\n{'='*60}\n  [牌貢献度テスト]\n{'='*60}")

    params = P()
    params['yakuman_strategy']['YAKUMAN_TILE_CONTRIBUTION_ENABLED'] = True
    params['yakuman_strategy']['YAKUMAN_MIN_SHANTEN'] = 2

    # 国士無双1向聴：老頭・字牌貢献、中張牌貢献しない
    s = make(['1m','9m','1p','9p','1s','9s','1z','2z','3z','4z','5z','6z','2m','2m'], scores=[15000,35000,25000,25000])
    ev = Evaluator(s, params=params)
    for t in ['1m','9m','1z','2z','7z']:
        ev.evaluate_tile(t)
    check("国士: 1mにボーナス", any('役満' in d for d in ev.details.get('1m', [])), str(ev.details.get('1m',[])))
    check("国士: 2mにボーナスなし", not any('役満' in d for d in ev.details.get('2m', [])), str(ev.details.get('2m',[])))

    # 大三元2向聴：YakumanEvaluatorの進行度確認（evaluate_tileはシャンテン後退で早期returnするため）
    s2 = make(['5z','5z','5z','6z','6z','7z','7z','1m','2m','3m','4p','5p','6p','9s'])
    ye2 = YakumanEvaluator(s2)
    r2 = ye2.evaluate_all()
    check("大三元2向聴: 進行度=0.33", round(r2['daisangen'].progress, 2) == 0.33)
    check("大三元2向聴: shanten=2", r2['daisangen'].shanten == 2)
    check("大三元2向聴: possible", r2['daisangen'].is_possible)

    # 字一色テンパイ：字牌貢献
    s3 = make(['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','6z'])
    ev3 = Evaluator(s3, params=params)
    for t in ['1z','6z']:
        ev3.evaluate_tile(t)
    check("字一色: 6zにボーナス", any('役満' in d for d in ev3.details.get('6z', [])))


def test_priority_selection():
    print(f"\n{'='*60}\n  [優先度選択テスト]\n{'='*60}")

    params = P()
    # 四暗刻テンパイ + 大三元2向聴 → 進行度が高い四暗刻選ばれる
    s = make(['1m','1m','1m','9p','9p','9p','1s','1s','1s','1z','1z','7z','7z','7z'])
    ev = Evaluator(s, params=params)
    ev.evaluate_tile('7z')  # 7zは両方に貢献
    check("四暗刻テンパイ+大三元2向聴: 四暗刻選択",
          any('suuankou' in d for d in ev.details.get('7z', [])),
          str(ev.details.get('7z',[])))

    # 字一色テンパイ + 小四喜テンパイ → 進行度が高い字一色選ばれる
    s2 = make(['1z','1z','1z','2z','2z','2z','3z','3z','3z','4z','4z','5z','5z','6z'])
    ev2 = Evaluator(s2, params=params)
    ev2.evaluate_tile('6z')
    check("字一色+小四喜 両テンパイ: 字一色選択（progress=1.0）",
          any('tsuuiisou' in d for d in ev2.details.get('6z', [])),
          str(ev2.details.get('6z',[])))


def test_score_gap():
    print(f"\n{'='*60}\n  [点差緩和テスト]\n{'='*60}")

    params = P()
    hand_3shanten = ['1m','9m','1p','9p','1s','9s','1z','2z','5z','6z','2m','3m','4m','5m']

    # 点差0（mangan_line内）→ ボーナスなし
    s = make(hand_3shanten, scores=[25000]*4)
    ev = Evaluator(s, params=params)
    for t in ['1p']:
        ev.evaluate_tile(t)
    check("点差0: ボーナスなし", not any('役満' in d for d in ev.details.get('1p', [])))

    # 点差大（mangan_line×2超）→ ボーナスあり
    s2 = make(hand_3shanten, scores=[5000, 45000, 25000, 25000])
    ev2 = Evaluator(s2, params=params)
    for t in ['1p']:
        ev2.evaluate_tile(t)
    check("点差40000: ボーナスあり", any('役満' in d for d in ev2.details.get('1p', [])))


def test_impossible_yakuman():
    print(f"\n{'='*60}\n  [成立不可能テスト]\n{'='*60}")

    # 清老頭：中張牌を含む → 進行度低い
    s = make(['1m','1m','9m','9m','1p','1p','9p','1s','1s','9s','5m','5p','5s','2m'])
    ye = YakumanEvaluator(s)
    r = ye.evaluate_all()
    check("清老頭 中張牌混在: shanten=6", r['chinroutou'].shanten == 6)


def test_bot_integration():
    print(f"\n{'='*60}\n  [Bot統合テスト]\n{'='*60}")
    try:
        from evaluator import Evaluator as E
        ev = E(make(['1m'], scores=[25000]*4), params=P())
        check("Evaluator.should_call_meld 確認", hasattr(ev, 'should_call_meld'))
    except Exception as e:
        check("Evaluator.should_call_meld 確認", False, str(e))


def run():
    test_meld_seal()
    test_closed_only()
    test_tile_contribution()
    test_priority_selection()
    test_score_gap()
    test_impossible_yakuman()
    test_bot_integration()

    print(f"\n{'='*60}")
    print(f"  結果: {PASS}/{TOTAL} passed, {FAIL} failed")
    print(f"{'='*60}")
    return FAIL == 0

if __name__ == '__main__':
    run()
