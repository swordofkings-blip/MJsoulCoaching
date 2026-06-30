# -*- coding: utf-8 -*-
"""
@title ver.1 vs ver.2 対局テスト
@description 1 ver.2 + 3 ver.1 (1v3) または 2 ver.1 + 2 ver.2 (2v2) で半荘を回し、
              各チームの平均順位・スコア・PT を測定。
              既存の MahjongSimulator + AIPlayer を使用。
"""
from __future__ import annotations
import argparse
import io
import json
import os
import sys
import time
from typing import List

# Windows PowerShell での cp932 エンコードエラーを回避
if sys.platform == 'win32':
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.ai_player import AIPlayer
from core.evaluator import Evaluator
from core.evaluator_v2 import EvaluatorV2
from tools.mahjong_simulator import MahjongSimulator, GameResult, PlayerGameStats


PT_TABLE = {0: 95, 1: 45, 2: -5, 3: -125}
BASE_SCORE = 25000


def load_params(path: str) -> dict:
    if not path:
        return {}
    _base = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..')
    _paths = [path, os.path.join(_base, 'config', path), os.path.join(_base, path)]
    for _p in _paths:
        if os.path.exists(_p):
            with open(_p, 'r', encoding='utf-8-sig') as f:
                return json.load(f)
    return {}


def make_v1_ai(params: dict) -> AIPlayer:
    return AIPlayer("v1", Evaluator, params)


def make_v2_ai(params: dict) -> AIPlayer:
    p = dict(params) if params else {}
    # 副露の過剰抑制
    p.setdefault('MELD_THRESHOLD', 300.0)
    # 立直判定の微調整 (riichi_v2)
    p.setdefault('RIICHI_W_BASE_SCORE', -30.0)  # デフォルト -50 → -30 でやや積極的
    return AIPlayer("v2", EvaluatorV2, p)


def run_one_game(seed: int, v2_seat: int, params: dict, game_type: str = 'tonpu') -> dict:
    """v2_seat に ver.2 を配置、それ以外 ver.1"""
    players = []
    for seat in range(4):
        if seat == v2_seat:
            players.append(make_v2_ai(params))
        else:
            players.append(make_v1_ai(params))
    sim = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type)
    result = sim.run_game()

    st = result.player_stats
    return {
        'seed': seed,
        'v2_seat': v2_seat,
        'scores': list(result.final_scores),
        'player_stats': [{'wins': s.wins, 'tsumo': s.tsumo_wins, 'ron': s.ron_wins,
                          'deal': s.dealt_in, 'reach': s.reach_declarations,
                          'han': s.total_han, 'win_pts': s.total_win_points,
                          'nkyoku': s.num_kyoku, 'meld_kyoku': s.kyoku_with_meld,
                          'damaten_wins': s.damaten_wins, 'open_wins': s.open_wins,
                          'tenpai_ex': s.tenpai_exhaustive} for s in result.player_stats],
        'result': result,
    }


def run_v2_pair_game(seed: int, v2_seats: list, params: dict, game_type: str = 'tonpu') -> dict:
    """v2 2人 + v1 2人 (2v2 モード)"""
    players = []
    for seat in range(4):
        players.append(make_v2_ai(params) if seat in v2_seats else make_v1_ai(params))
    sim = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type)
    result = sim.run_game()
    return {
        'seed': seed,
        'scores': list(result.final_scores),
        'player_stats': [{'wins': s.wins, 'tsumo': s.tsumo_wins, 'ron': s.ron_wins,
                          'deal': s.dealt_in, 'reach': s.reach_declarations,
                          'han': s.total_han, 'win_pts': s.total_win_points,
                          'nkyoku': s.num_kyoku, 'meld_kyoku': s.kyoku_with_meld,
                          'damaten_wins': s.damaten_wins, 'open_wins': s.open_wins,
                          'tenpai_ex': s.tenpai_exhaustive, 'placement': result.placement_of(s.seat),
                          'score': result.final_scores[s.seat]} for s in result.player_stats],
    }


def run_one_2v2_game(seed: int, v1_seats: list, v2_seats: list, params: dict,
                     game_type: str = 'tonpu') -> dict:
    """2v2: v1_seats に ver.1、v2_seats に ver.2 を配置"""
    assert sorted(v1_seats + v2_seats) == [0, 1, 2, 3], "v1_seats + v2_seats must cover 0-3"
    players = []
    for seat in range(4):
        if seat in v2_seats:
            players.append(make_v2_ai(params))
        else:
            players.append(make_v1_ai(params))
    sim = MahjongSimulator(wall_seed=seed, players=players, game_type=game_type)
    result = sim.run_game()

    v1_total_score = sum(result.final_scores[s] for s in v1_seats)
    v2_total_score = sum(result.final_scores[s] for s in v2_seats)
    v1_total_pt = sum(
        PT_TABLE.get(result.placement_of(s), 0) + (result.final_scores[s] - BASE_SCORE) // 1000
        for s in v1_seats
    )
    v2_total_pt = sum(
        PT_TABLE.get(result.placement_of(s), 0) + (result.final_scores[s] - BASE_SCORE) // 1000
        for s in v2_seats
    )
    v1_placements = sorted(result.placement_of(s) for s in v1_seats)
    v2_placements = sorted(result.placement_of(s) for s in v2_seats)
    v1_wins = sum(result.player_stats[s].wins for s in v1_seats)
    v2_wins = sum(result.player_stats[s].wins for s in v2_seats)
    v1_dealt_in = sum(result.player_stats[s].dealt_in for s in v1_seats)
    v2_dealt_in = sum(result.player_stats[s].dealt_in for s in v2_seats)
    v1_reach = sum(result.player_stats[s].reach_declarations for s in v1_seats)
    v2_reach = sum(result.player_stats[s].reach_declarations for s in v2_seats)
    v1_team_placement = sum(v1_placements)
    v2_team_placement = sum(v2_placements)
    if v1_team_placement < v2_team_placement:
        winner = 'v1'
    elif v2_team_placement < v1_team_placement:
        winner = 'v2'
    else:
        winner = 'draw' if v1_total_score == v2_total_score else ('v1' if v1_total_score > v2_total_score else 'v2')

    return {
        'seed': seed,
        'v1_seats': v1_seats,
        'v2_seats': v2_seats,
        'v1_total_score': v1_total_score,
        'v2_total_score': v2_total_score,
        'v1_total_pt': v1_total_pt,
        'v2_total_pt': v2_total_pt,
        'v1_placements': v1_placements,
        'v2_placements': v2_placements,
        'v1_wins': v1_wins,
        'v2_wins': v2_wins,
        'v1_dealt_in': v1_dealt_in,
        'v2_dealt_in': v2_dealt_in,
        'v1_reach': v1_reach,
        'v2_reach': v2_reach,
        'winner': winner,
        'score_diff': v2_total_score - v1_total_score,
        'final_scores': result.final_scores,
        # 詳細スタッツ (各席の PlayerGameStats をそのまま保持)
        'player_stats': result.player_stats,
    }


def merge_team_stats(player_stats_list, team_size: int = 1) -> dict:
    """複数席の PlayerGameStats を合算した dict を作る。
    牌譜屋のスタッツは「1 人あたり平均」なので、すべての局あたり事象カウンタを
    1 人あたりに正規化する (wins, dealt_in, open_wins 等)。
    sum_final_score と reach_income 等の絶対値も 1 人あたりに直す。
    team_size: チームの実人数 (1v3 なら 1、2v2 なら 2)。
                player_stats_list 長は 1 プレイヤーあたり = n_games ぶんあるので別引数が必要。
    """
    n_players = team_size if team_size > 0 else 1

    # 1 人あたりに正規化するキー
    per_player_keys = {
        'wins', 'tsumo_wins', 'dealt_in', 'damaten_win',
        'exhaustive_count', 'exhaustive_tenpai', 'kyoku_with_meld',
        'total_han', 'total_win_points', 'deal_in_score',
        'reach_declarations', 'reach_wins', 'reach_dealin',
        'reach_dealin_decl_tile', 'reach_exhaustive',
        'ippatsu_declared', 'ippatsu_wins', 'ura_dora_hits',
        'reach_income', 'reach_expense', 'reach_sticks_income',
        'reach_win_han_sum',
        'first_move_reach', 'chase_reach', 'chased_reach',
        'reach_furiten', 'reach_multi_wait', 'reach_good_shape',
        'open_wins', 'damaten_wins', 'tenpai_exhaustive',
        'open_tenpai_exhaustive', 'deal_in_when_open',
        'painful_dealer_steal', 'painful_dealer_steal_han4',
        'painful_dealer_steal_score',
        'sum_final_score', 'num_kyoku',
    }

    merged = {
        # リスト系
        'reach_turns': [], 'win_turns': [],
        # 対局単位
        'max_renchan': 0, 'placements': [],
    }
    for k in per_player_keys:
        merged[k] = 0

    for ps in player_stats_list:
        for key in merged:
            if key in ('reach_turns', 'win_turns'):
                merged[key].extend(getattr(ps, key, []))
            elif key == 'max_renchan':
                merged['max_renchan'] = max(merged['max_renchan'], ps.max_renchan)
            elif key == 'placements':
                merged['placements'].append(getattr(ps, 'placement', -1))
            elif key == 'sum_final_score':
                # ps.final_score → merged.sum_final_score に集計
                merged['sum_final_score'] += getattr(ps, 'final_score', 0) / n_players
            else:
                merged[key] += getattr(ps, key, 0) / n_players
    return merged


def safe_div(num, den):
    return num / den if den else 0


def _row(label, v1_val, v2_val, fmt='{:>8.2f}', unit=''):
    v1_s = fmt.format(v1_val) if isinstance(v1_val, (int, float)) else v1_val
    v2_s = fmt.format(v2_val) if isinstance(v2_val, (int, float)) else v2_val
    print(f"  {label:<18} ver.1={v1_s}{unit}  ver.2={v2_s}{unit}")


def print_majsoul_metrics(v1_stats: dict, v2_stats: dict,
                          v1_total_kyoku: int, v2_total_kyoku: int,
                          n_kyoku_v1: int, n_kyoku_v2: int,
                          n_games: int):
    """
    @title 雀魂牌譜屋 (amae-koromo) 準拠のスタッツ表示 (2v2 チーム別)
    @param v1_stats ver.1 チームの合算スタッツ
    @param v2_stats ver.2 チームの合算スタッツ
    @param v1_total_kyoku ver.1 チーム全員の総プレイ局数の合計 (分母用)
    @param v2_total_kyoku ver.2 チーム全員の総プレイ局数の合計 (分母用)
    @param n_kyoku_v1 ver.1 1人あたりの平均局数 (表示用)
    @param n_kyoku_v2 ver.2 1人あたりの平均局数 (表示用)
    @param n_games 対局ゲーム数
    """
    # 牌譜屋では大半のスタッツが "個人平均" なので分母は「個人あたりの局数」
    p_kyoku_v1 = max(n_kyoku_v1, 1)
    p_kyoku_v2 = max(n_kyoku_v2, 1)

    print()
    print("=" * 72)
    print("  雀魂牌譜屋 (amae-koromo) 準拠スタッツ (1 人あたり平均)")
    print("=" * 72)

    # -------- 基本タブ --------
    print()
    print("【基本】")
    _row("総計局数", n_kyoku_v1, n_kyoku_v2, fmt='{:>4}')
    # 平均順位: 全プレイヤーの placement 平均 (牌譜屋は 1-4 表示)
    avg_pl_v1 = safe_div(sum(v1_stats['placements']), len(v1_stats['placements'])) if v1_stats['placements'] else 0
    avg_pl_v2 = safe_div(sum(v2_stats['placements']), len(v2_stats['placements'])) if v2_stats['placements'] else 0
    _row("平均順位", avg_pl_v1 + 1, avg_pl_v2 + 1, fmt='{:>5.2f}')
    _row("和了率", safe_div(v1_stats['wins'], p_kyoku_v1) * 100,
         safe_div(v2_stats['wins'], p_kyoku_v2) * 100, fmt='{:>6.2f}', unit='%')
    _row("放銃率", safe_div(v1_stats['dealt_in'], p_kyoku_v1) * 100,
         safe_div(v2_stats['dealt_in'], p_kyoku_v2) * 100, fmt='{:>6.2f}', unit='%')
    # 自摸率 = 自摸局数 / 和牌局数
    _row("自摸率", safe_div(v1_stats['tsumo_wins'], v1_stats['wins']) * 100,
         safe_div(v2_stats['tsumo_wins'], v2_stats['wins']) * 100, fmt='{:>6.2f}', unit='%')
    # 默聴率 (ダマ率) = 門前黙聴和了 / 和牌局数
    _row("黙聴率(ダマ)", safe_div(v1_stats['damaten_win'], v1_stats['wins']) * 100,
         safe_div(v2_stats['damaten_win'], v2_stats['wins']) * 100, fmt='{:>6.2f}', unit='%')
    _row("流局率", safe_div(v1_stats['exhaustive_count'], p_kyoku_v1) * 100,
         safe_div(v2_stats['exhaustive_count'], p_kyoku_v2) * 100, fmt='{:>6.2f}', unit='%')
    # 流聴率 = 流局聴牌 / 流局数
    _row("流聴率", safe_div(v1_stats['exhaustive_tenpai'], v1_stats['exhaustive_count']) * 100,
         safe_div(v2_stats['exhaustive_tenpai'], v2_stats['exhaustive_count']) * 100, fmt='{:>6.2f}', unit='%')
    _row("副露率", safe_div(v1_stats['kyoku_with_meld'], p_kyoku_v1) * 100,
         safe_div(v2_stats['kyoku_with_meld'], p_kyoku_v2) * 100, fmt='{:>6.2f}', unit='%')
    _row("立直率", safe_div(v1_stats['reach_declarations'], p_kyoku_v1) * 100,
         safe_div(v2_stats['reach_declarations'], p_kyoku_v2) * 100, fmt='{:>6.2f}', unit='%')
    # 和了巡数 (個人平均) = sum(win_turns) / num wins
    _row("和了巡数", safe_div(sum(v1_stats['win_turns']), max(v1_stats['wins'], 1)),
         safe_div(sum(v2_stats['win_turns']), max(v2_stats['wins'], 1)), fmt='{:>5.2f}')
    # 平均打点
    _row("平均打点", safe_div(v1_stats['total_win_points'], max(v1_stats['wins'], 1)),
         safe_div(v2_stats['total_win_points'], max(v2_stats['wins'], 1)), fmt='{:>7.0f}')
    # 平均銃点
    _row("平均銃点", safe_div(v1_stats['deal_in_score'], max(v1_stats['dealt_in'], 1)),
         safe_div(v2_stats['deal_in_score'], max(v2_stats['dealt_in'], 1)), fmt='{:>7.0f}')

    # -------- 立直タブ --------
    print()
    print("【立直】")
    _row("立直率", safe_div(v1_stats['reach_declarations'], p_kyoku_v1) * 100,
         safe_div(v2_stats['reach_declarations'], p_kyoku_v2) * 100, fmt='{:>6.2f}', unit='%')
    # 立直後和了率 (立直和了率) = 立直和了局数 / 立直局数
    _row("立直和了", safe_div(v1_stats['reach_wins'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['reach_wins'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    # 立直後放銃率 (立直放銃A) = 立直放銃局数(含立直瞬間) / 立直局数
    _row("立直放銃A", safe_div(v1_stats['reach_dealin'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['reach_dealin'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    # 立直後非瞬間放銃率 (立直放銃B) = 立直放銃 - 宣言牌放銃 / 立直局数
    v1_b = v1_stats['reach_dealin'] - v1_stats['reach_dealin_decl_tile']
    v2_b = v2_stats['reach_dealin'] - v2_stats['reach_dealin_decl_tile']
    _row("立直放銃B", safe_div(v1_b, v1_stats['reach_declarations']) * 100,
         safe_div(v2_b, v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    # 立直収支 = 立直総収支(含供託) / 立直局数
    _row("立直収支", safe_div(v1_stats['reach_income'] - v1_stats['reach_expense'], v1_stats['reach_declarations']),
         safe_div(v2_stats['reach_income'] - v2_stats['reach_expense'], v2_stats['reach_declarations']),
         fmt='{:>+7.1f}')
    # 立直収入 = 立直和了収入(含供託) / 立直和了局数
    _row("立直収入", safe_div(v1_stats['reach_income'], v1_stats['reach_wins']),
         safe_div(v2_stats['reach_income'], v2_stats['reach_wins']), fmt='{:>7.0f}')
    # 立直支出 = 立直放銃支出(含立直棒) / 立直放銃局数
    _row("立直支出", safe_div(v1_stats['reach_expense'], v1_stats['reach_dealin']),
         safe_div(v2_stats['reach_expense'], v2_stats['reach_dealin']), fmt='{:>7.0f}')
    _row("先制率", safe_div(v1_stats['first_move_reach'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['first_move_reach'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    _row("追立率", safe_div(v1_stats['chase_reach'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['chase_reach'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    _row("被追率", safe_div(v1_stats['chased_reach'], v1_stats['first_move_reach']) * 100,
         safe_div(v2_stats['chased_reach'], v2_stats['first_move_reach']) * 100, fmt='{:>6.2f}', unit='%')
    _row("立直巡目", safe_div(sum(v1_stats['reach_turns']), max(len(v1_stats['reach_turns']), 1)),
         safe_div(sum(v2_stats['reach_turns']), max(len(v2_stats['reach_turns']), 1)), fmt='{:>6.2f}')
    # 立直流局
    _row("立直流局", safe_div(v1_stats['reach_exhaustive'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['reach_exhaustive'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    # 一発率 = 一発局数 / 立直和了局数
    _row("一発率", safe_div(v1_stats['ippatsu_wins'], v1_stats['reach_wins']) * 100,
         safe_div(v2_stats['ippatsu_wins'], v2_stats['reach_wins']) * 100, fmt='{:>6.2f}', unit='%')
    # 振聴率
    _row("振聴率", safe_div(v1_stats['reach_furiten'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['reach_furiten'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    # 立直多面
    _row("立直多面", safe_div(v1_stats['reach_multi_wait'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['reach_multi_wait'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')
    # 立直良形
    _row("立直良形", safe_div(v1_stats['reach_good_shape'], v1_stats['reach_declarations']) * 100,
         safe_div(v2_stats['reach_good_shape'], v2_stats['reach_declarations']) * 100, fmt='{:>6.2f}', unit='%')

    # -------- ほかタブ --------
    print()
    print("【ほか】")
    _row("最大連荘", v1_stats['max_renchan'], v2_stats['max_renchan'], fmt='{:>3}')
    # 裏ドラ率 = 中裏ドラ局数 / 立直和了局数
    _row("裏ドラ率", safe_div(v1_stats['ura_dora_hits'], v1_stats['reach_wins']) * 100,
         safe_div(v2_stats['ura_dora_hits'], v2_stats['reach_wins']) * 100, fmt='{:>6.2f}', unit='%')
    # 被親かぶり率 (満貫以上のおやかぶり) = 親かぶり(満貫+) / 被自摸回数
    # 仕様簡略化: 親かぶり(満貫+) / 和了局数
    _row("被親かぶり率", safe_div(v1_stats['painful_dealer_steal_han4'], v1_stats['wins']) * 100,
         safe_div(v2_stats['painful_dealer_steal_han4'], v2_stats['wins']) * 100, fmt='{:>6.2f}', unit='%')
    _row("平均被親かぶり点", safe_div(v1_stats['painful_dealer_steal_score'], v1_stats['painful_dealer_steal_han4']),
         safe_div(v2_stats['painful_dealer_steal_score'], v2_stats['painful_dealer_steal_han4']),
         fmt='{:>7.0f}')
    # 放銃時立直率 = 放銃時立直回数 / 放銃回数
    _row("放銃時立直率", safe_div(v1_stats['reach_dealin'], v1_stats['dealt_in']) * 100,
         safe_div(v2_stats['reach_dealin'], v2_stats['dealt_in']) * 100, fmt='{:>6.2f}', unit='%')
    # 放銃時副露率 = 放銃時副露回数 / 放銃回数
    _row("放銃時副露率", safe_div(v1_stats['deal_in_when_open'], v1_stats['dealt_in']) * 100,
         safe_div(v2_stats['deal_in_when_open'], v2_stats['dealt_in']) * 100, fmt='{:>6.2f}', unit='%')
    # 副露後放銃率 = 放銃時副露 / 副露数
    _row("副露後放銃率", safe_div(v1_stats['deal_in_when_open'], v1_stats['kyoku_with_meld']) * 100,
         safe_div(v2_stats['deal_in_when_open'], v2_stats['kyoku_with_meld']) * 100, fmt='{:>6.2f}', unit='%')
    # 副露後和了率 = 副露後和了 / 副露数
    _row("副露後和了率", safe_div(v1_stats['open_wins'], v1_stats['kyoku_with_meld']) * 100,
         safe_div(v2_stats['open_wins'], v2_stats['kyoku_with_meld']) * 100, fmt='{:>6.2f}', unit='%')
    # 副露後流局率 = 副露後流局 / 副露数
    _row("副露後流局率", safe_div(v1_stats['open_tenpai_exhaustive'], v1_stats['kyoku_with_meld']) * 100,
         safe_div(v2_stats['open_tenpai_exhaustive'], v2_stats['kyoku_with_meld']) * 100, fmt='{:>6.2f}', unit='%')
    # 打点効率 = 和了率 * 平均打点
    v1_win_rate = safe_div(v1_stats['wins'], p_kyoku_v1)
    v2_win_rate = safe_div(v2_stats['wins'], p_kyoku_v2)
    v1_avg_win = safe_div(v1_stats['total_win_points'], max(v1_stats['wins'], 1))
    v2_avg_win = safe_div(v2_stats['total_win_points'], max(v2_stats['wins'], 1))
    _row("打点効率", v1_win_rate * v1_avg_win, v2_win_rate * v2_avg_win, fmt='{:>7.0f}')
    # 銃点損失 = 放銃率 * 平均銃点
    v1_deal_rate = safe_div(v1_stats['dealt_in'], p_kyoku_v1)
    v2_deal_rate = safe_div(v2_stats['dealt_in'], p_kyoku_v2)
    v1_avg_deal = safe_div(v1_stats['deal_in_score'], max(v1_stats['dealt_in'], 1))
    v2_avg_deal = safe_div(v2_stats['deal_in_score'], max(v2_stats['dealt_in'], 1))
    _row("銃点損失", v1_deal_rate * v1_avg_deal, v2_deal_rate * v2_avg_deal, fmt='{:>7.0f}')
    #調整打点効率 = 打点効率 - 銃点損失
    _row("調整打点効率", v1_win_rate * v1_avg_win - v1_deal_rate * v1_avg_deal,
         v2_win_rate * v2_avg_win - v2_deal_rate * v2_avg_deal, fmt='{:>+7.0f}')
    # 局収支 = (場平均素点 - 場起始素点) * 記録場数 / 総計局数
    # sum_final_score は既に per-person 正規化済み (1 人あたりの最終点合計)
    # 場平均素点 (per-game, per-person) = sum_final_score / n_games
    # 局収支 = (場平均素点 - 25000) * n_games / n_kyoku_per_person
    #       = (sum_final_score - 25000 * n_games) / n_kyoku_per_person
    if n_kyoku_v1 > 0:
        round_pl_v1 = (v1_stats['sum_final_score'] - 25000 * n_games) / n_kyoku_v1
    else:
        round_pl_v1 = 0
    if n_kyoku_v2 > 0:
        round_pl_v2 = (v2_stats['sum_final_score'] - 25000 * n_games) / n_kyoku_v2
    else:
        round_pl_v2 = 0
    _row("局収支", round_pl_v1, round_pl_v2, fmt='{:>+7.1f}')
    print("=" * 72)


def main(seeds: int, v2_seats: str, params_path: str, game_type: str,
         mode: str, v1_seats: str):
    params = load_params(params_path)

    print(f"=== ver.1 vs ver.2 対局テスト (mode={mode}) ===")
    print(f"  seeds: {seeds}")
    print(f"  ゲーム形式: {game_type}")
    print(f"  パラメータ: {params_path or '(default)'}")
    print()

    if mode == '1v3':
        seat_list = [int(s) for s in v2_seats.split(',')]
        if any(s < 0 or s > 3 for s in seat_list):
            raise ValueError(f"v2_seats must be 0-3, got {v2_seats}")
        print(f"  v2 配置 (1v3): {seat_list}")
        print()
        run_1v3(seeds, seat_list, params, game_type)
    elif mode == '2v2':
        v1 = sorted(int(s) for s in v1_seats.split(','))
        v2 = sorted(int(s) for s in v2_seats.split(','))
        if sorted(v1 + v2) != [0, 1, 2, 3]:
            raise ValueError(f"v1_seats({v1}) + v2_seats({v2}) must cover 0-3 uniquely, got {sorted(v1+v2)}")
        print(f"  v1 配置 (2v2): {v1}")
        print(f"  v2 配置 (2v2): {v2}")
        print()
        run_2v2(seeds, v1, v2, params, game_type)
    else:
        raise ValueError(f"mode must be '1v3' or '2v2', got {mode}")


def run_1v3(seeds: int, seat_list: list, params: dict, game_type: str):
    all_results = []
    t0 = time.time()
    for i in range(seeds):
        for v2_seat in seat_list:
            try:
                r = run_one_game(seed=i, v2_seat=v2_seat, params=params, game_type=game_type)
                all_results.append(r)
                if len(all_results) % 5 == 0:
                    elapsed = time.time() - t0
                    print(f"  ... {len(all_results)} 局完了 ({elapsed:.1f}秒)")
            except Exception as e:
                print(f"  ! seed={i} seat={v2_seat} エラー: {e}")
                import traceback
                traceback.print_exc()

    if not all_results:
        print("結果なし")
        return

    n = len(all_results)
    # run_one_game は新形式 (scores + player_stats) を返す
    v2_stats = [r['player_stats'][r['v2_seat']] for r in all_results]
    placements = [r['result'].placement_of(r['v2_seat']) for r in all_results]
    avg_placement = sum(placements) / n
    avg_score = sum(r['scores'][r['v2_seat']] for r in all_results) / n
    avg_pt = sum(PT_TABLE.get(placements[i], 0) + (r['scores'][r['v2_seat']] - BASE_SCORE) // 1000 for i, r in enumerate(all_results)) / n

    total_wins = sum(s['wins'] for s in v2_stats)
    total_tsumo = sum(s['tsumo'] for s in v2_stats)
    total_ron = sum(s['ron'] for s in v2_stats)
    total_dealt_in = sum(s['deal'] for s in v2_stats)
    total_reach = sum(s['reach'] for s in v2_stats)
    total_han = sum(s['han'] for s in v2_stats)
    total_num_kyoku = sum(s['nkyoku'] for s in v2_stats)
    den = max(total_num_kyoku, 1)

    win_rate = total_wins / den * 100
    deal_in_rate = total_dealt_in / den * 100
    reach_rate = total_reach / den * 100
    avg_han = total_han / max(total_wins, 1)

    print()
    print("=== 結果サマリ (1v3) ===")
    print(f"  対局数: {n}")
    print(f"  総局数: {total_num_kyoku}")
    print(f"  ver.2 平均順位: {avg_placement:.2f} (1.0 が最高、3.0 が最低)")
    print(f"  ver.2 平均スコア: {avg_score:.0f} (25000 がベース)")
    print(f"  ver.2 平均 PT: {avg_pt:+.1f}")
    print(f"  和了率: {win_rate:.1f}% (玉座の間基準: 20-21%)")
    print(f"  放銃率: {deal_in_rate:.1f}% (玉座の間基準: 12-14%)")
    print(f"  立直率: {reach_rate:.1f}% (玉座の間基準: 18-19%)")
    print(f"  ツモ和了: {total_tsumo}, ロン和了: {total_ron}")
    print(f"  平均翻数 (和了時): {avg_han:.1f}")
    print()
    print(f"  経過時間: {time.time() - t0:.1f}秒")
    print(f"  ゲームあたり: {(time.time() - t0)/n:.2f}秒")


def run_2v2(seeds: int, v1_seats: list, v2_seats: list, params: dict, game_type: str):
    all_results = []
    t0 = time.time()
    for i in range(seeds):
        try:
            r = run_one_2v2_game(seed=i, v1_seats=v1_seats, v2_seats=v2_seats,
                                  params=params, game_type=game_type)
            all_results.append(r)
            if len(all_results) % 5 == 0:
                elapsed = time.time() - t0
                print(f"  ... {len(all_results)} 局完了 ({elapsed:.1f}秒)")
        except Exception as e:
            print(f"  ! seed={i} エラー: {e}")
            import traceback
            traceback.print_exc()

    if not all_results:
        print("結果なし")
        return

    n = len(all_results)
    avg_v1_score = sum(r['v1_total_score'] for r in all_results) / n
    avg_v2_score = sum(r['v2_total_score'] for r in all_results) / n
    avg_v1_pt = sum(r['v1_total_pt'] for r in all_results) / n
    avg_v2_pt = sum(r['v2_total_pt'] for r in all_results) / n
    total_v1_wins = sum(r['v1_wins'] for r in all_results)
    total_v2_wins = sum(r['v2_wins'] for r in all_results)
    total_v1_dealt_in = sum(r['v1_dealt_in'] for r in all_results)
    total_v2_dealt_in = sum(r['v2_dealt_in'] for r in all_results)
    total_v1_reach = sum(r['v1_reach'] for r in all_results)
    total_v2_reach = sum(r['v2_reach'] for r in all_results)
    v1_wins_count = sum(1 for r in all_results if r['winner'] == 'v1')
    v2_wins_count = sum(1 for r in all_results if r['winner'] == 'v2')
    draw_count = sum(1 for r in all_results if r['winner'] == 'draw')
    players_per_team = len(v1_seats)

    # 雀魂牌譜屋スタイルの詳細スタッツ
    v1_ps = [r['player_stats'][s] for r in all_results for s in v1_seats]
    v2_ps = [r['player_stats'][s] for r in all_results for s in v2_seats]
    v1_stats = merge_team_stats(v1_ps)
    v2_stats = merge_team_stats(v2_ps)
    # Why: チームの総プレイ局数を算出し、それを個人平均のスタッツ割合を求める際の分母とします。
    v1_total_kyoku = max(v1_stats['num_kyoku'], 1)
    v2_total_kyoku = max(v2_stats['num_kyoku'], 1)

    win_rate = total_v1_wins / v1_total_kyoku * 100
    v2_win_rate = total_v2_wins / v2_total_kyoku * 100
    deal_in_rate = total_v1_dealt_in / v1_total_kyoku * 100
    v2_deal_in_rate = total_v2_dealt_in / v2_total_kyoku * 100
    reach_rate = total_v1_reach / v1_total_kyoku * 100
    v2_reach_rate = total_v2_reach / v2_total_kyoku * 100

    print()
    print("=== 結果サマリ (2v2) ===")
    print(f"  対局数: {n}")
    print(f"  v1 配置: {v1_seats}  /  v2 配置: {v2_seats}")
    print()
    print(f"  【チーム勝率】")
    print(f"    ver.1 チーム勝ち: {v1_wins_count} ({v1_wins_count/n*100:.1f}%)")
    print(f"    ver.2 チーム勝ち: {v2_wins_count} ({v2_wins_count/n*100:.1f}%)")
    if draw_count:
        print(f"    引き分け: {draw_count} ({draw_count/n*100:.1f}%)")
    print()
    print(f"  【スコア】")
    # 牌譜屋準拠: 1 プレイヤーあたりの平均スコア (ベース 25000)
    per_player_v1 = avg_v1_score / len(v1_seats)
    per_player_v2 = avg_v2_score / len(v2_seats)
    print(f"    ver.1 1人平均スコア: {per_player_v1:.0f} (25000 がベース)")
    print(f"    ver.2 1人平均スコア: {per_player_v2:.0f}")
    print(f"    差分 (v2 - v1): {per_player_v2 - per_player_v1:+.0f}")
    print()
    print(f"  【PT】")
    print(f"    ver.1 チーム平均 PT: {avg_v1_pt:+.1f}")
    print(f"    ver.2 チーム平均 PT: {avg_v2_pt:+.1f}")
    print(f"    差分 (v2 - v1): {avg_v2_pt - avg_v1_pt:+.1f}")
    print()
    print(f"  【個人指標 (1 人あたり平均)】")
    print(f"    ver.1 和了率: {win_rate:.1f}%  /  ver.2 和了率: {v2_win_rate:.1f}%  (差 {v2_win_rate - win_rate:+.1f}pt)")
    print(f"    ver.1 放銃率: {deal_in_rate:.1f}%  /  ver.2 放銃率: {v2_deal_in_rate:.1f}%  (差 {v2_deal_in_rate - deal_in_rate:+.1f}pt)")
    print(f"    ver.1 立直率: {reach_rate:.1f}%  /  ver.2 立直率: {v2_reach_rate:.1f}%  (差 {v2_reach_rate - reach_rate:+.1f}pt)")

    # 雀魂牌譜屋スタイルの詳細スタッツ
    v1_ps = [r['player_stats'][s] for r in all_results for s in v1_seats]
    v2_ps = [r['player_stats'][s] for r in all_results for s in v2_seats]
    v1_stats = merge_team_stats(v1_ps, team_size=len(v1_seats))
    v2_stats = merge_team_stats(v2_ps, team_size=len(v2_seats))
    # 1 人あたり実プレイ局数 (既に per-person 正規化済み)
    n_kyoku_v1 = v1_stats['num_kyoku']
    n_kyoku_v2 = v2_stats['num_kyoku']
    print_majsoul_metrics(v1_stats, v2_stats, v1_stats['num_kyoku'], v2_stats['num_kyoku'], n_kyoku_v1, n_kyoku_v2, n)

    elapsed = time.time() - t0
    print()
    print(f"  経過時間: {elapsed:.1f}秒")
    print(f"  ゲームあたり: {elapsed/n:.2f}秒")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--mode", type=str, default="1v3", choices=["1v3", "2v2"],
                   help="対局形式 (1v3: ver.2 を 1 席配置, 2v2: 2 席ずつ配置)")
    p.add_argument("--seeds", type=int, default=20, help="シード数 (各席配置に展開)")
    p.add_argument("--v2-seats", type=str, default=None,
                   help="ver.2 を配置する席 (カンマ区切り, 未指定なら mode 別既定値を使用)")
    p.add_argument("--v1-seats", type=str, default="0,1",
                   help="ver.1 を配置する席 (2v2 のみ使用, カンマ区切り, 既定 0,1)")
    p.add_argument("--params", type=str, default="config/config_parameters.json")
    p.add_argument("--game-type", type=str, default="tonpu", choices=["tonpu", "hanchan"])
    args = p.parse_args()
    v2_seats_arg = args.v2_seats if args.v2_seats is not None else ("0,1,2,3" if args.mode == "1v3" else "2,3")
    main(args.seeds, v2_seats_arg, args.params, args.game_type, args.mode, args.v1_seats)
