# -*- coding: utf-8 -*-
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from core.game_state import GameState, Meld, ReachState
from core.str_converter import id_to_tile, tile_to_id, hand_to_counts, is_honor
from core.strategy_manager import ShantenCalculator

TILE_TYPES = 34
TILES_PER_TYPE = 4
WALL_SIZE = 136
DEAD_WALL_SIZE = 14
HAND_SIZE = 13

CALL_PON = 1
CALL_CHI = 0
CALL_KAN = 2


@dataclass
class KyokuResult:
    seed: int
    chang: int
    ju: int
    honba: int
    riichi_sticks: int
    winner_seat: Optional[int]
    is_tsumo: bool
    is_exhaustive: bool
    delta_scores: List[int]
    new_scores: List[int]
    tenpai_seats: List[int]
    han: int
    fu: int
    reach_seats: List[bool] = field(default_factory=lambda: [False] * 4)
    meld_counts: List[int] = field(default_factory=lambda: [0] * 4)
    open_meld_counts: List[int] = field(default_factory=lambda: [0] * 4)
    win_tile: Optional[str] = None
    win_score: int = 0
    tsumo_turn: int = 0
    yaku_list: List[str] = field(default_factory=list)
    dealer_seat: int = 0


@dataclass
class PlayerGameStats:
    seat: int = -1
    wins: int = 0
    tsumo_wins: int = 0
    ron_wins: int = 0
    dealt_in: int = 0
    reach_declarations: int = 0
    reach_wins: int = 0
    open_wins: int = 0
    damaten_wins: int = 0
    tenpai_exhaustive: int = 0
    busted: bool = False
    total_han: int = 0
    total_win_points: int = 0
    win_turns: List[int] = field(default_factory=list)
    yaku_counts: Dict[str, int] = field(default_factory=dict)
    placement: int = -1
    final_score: int = 0
    num_kyoku: int = 0
    kyoku_with_meld: int = 0
    max_renchan: int = 0
    # 役満統計
    yakuman_bonus_count: int = 0
    meld_seal_count: int = 0
    gap_relaxation_count: int = 0


@dataclass
class GameResult:
    seed: int
    game_type: str
    kyoku_results: List[KyokuResult] = field(default_factory=list)
    final_scores: List[int] = field(default_factory=lambda: [25000, 25000, 25000, 25000])
    final_placements: List[int] = field(default_factory=lambda: [0, 1, 2, 3])
    num_kyoku: int = 0
    player_stats: List[PlayerGameStats] = field(default_factory=lambda: [PlayerGameStats(seat=i) for i in range(4)])

    def placement_of(self, seat: int) -> int:
        for p, s in enumerate(self.final_placements):
            if s == seat:
                return p
        return 3


HONOR_MJAI = {'1z': 'E', '2z': 'S', '3z': 'W', '4z': 'N', '5z': 'P', '6z': 'F', '7z': 'C'}
REV_HONOR = {v: k for k, v in HONOR_MJAI.items()}

def to_mjai_tile(t):
    if t.startswith('0'):
        return t
    if t in HONOR_MJAI:
        return HONOR_MJAI[t]
    return t


class MahjongSimulator:
    def __init__(self, wall_seed: int, players: List, game_type: str = 'hanchan', mjson_path: str = None, majsoul_path: str = None, player_names: List[str] = None):
        self.wall_seed = wall_seed
        self.players = [p.clone(i) for i, p in enumerate(players)]
        self.game_type = game_type
        if game_type == 'tonpu':
            self._rounds_per_game = 4
        else:
            self._rounds_per_game = 8
        self._mjson_path = mjson_path
        self._majsoul_path = majsoul_path
        self._player_names = player_names or [f'P{i}' for i in range(4)]
        self._mjson_log = []

    def run_game(self) -> GameResult:
        result = GameResult(seed=self.wall_seed, game_type=self.game_type)

        self._scores = [25000, 25000, 25000, 25000]
        self._riichi_sticks = 0
        self._honba = 0
        self._chang = 0
        self._ju = 0
        self._dealer_seat = 0
        self._kyoku_count = 0
        self._mjson_log = []
        self._ms_log = {'head': {'accounts': [{'seat': i, 'nickname': f'P{i}'} for i in range(4)]}, 'detail_records': {'actions': []}}

        self._mjson({'type': 'start_game', 'id': 0})

        while self._kyoku_count < 50:
            kr = self._run_kyoku()
            result.kyoku_results.append(kr)
            result.final_scores = list(kr.new_scores)
            self._kyoku_count += 1

            if self._should_game_end():
                break

            self._advance_kyoku(kr)

        result.num_kyoku = len(result.kyoku_results)
        result.final_placements = self._compute_placements()
        self._compute_player_stats(result)
        self._mjson_save()
        self._ms_save()
        return result

    def _mjson(self, msg):
        self._mjson_log.append(msg)

    def _mjson_save(self):
        if not self._mjson_path:
            return
        os.makedirs(os.path.dirname(self._mjson_path) or '.', exist_ok=True)
        with open(self._mjson_path, 'w', encoding='utf-8') as f:
            for msg in self._mjson_log:
                f.write(json.dumps(msg, ensure_ascii=False) + '\n')

    def _mjson_start_kyoku(self):
        bakaze = {0: 'E', 1: 'S', 2: 'W', 3: 'N'}.get(self._chang, 'E')
        msg = {
            'type': 'start_kyoku',
            'bakaze': bakaze,
            'kyoku': self._ju + 1,
            'honba': self._honba,
            'kyotaku': self._riichi_sticks,
            'oya': self._dealer_seat,
            'dora_marker': to_mjai_tile(self._dora_indicators[0]) if self._dora_indicators else '1m',
            'scores': list(self._scores),
        }
        self._mjson(msg)

    def _mjson_tsumo(self, seat, tile):
        self._mjson({'type': 'tsumo', 'actor': seat, 'pai': to_mjai_tile(tile)})

    def _mjson_dahai(self, seat, tile, moqie):
        self._mjson({'type': 'dahai', 'actor': seat, 'pai': to_mjai_tile(tile), 'tsumogiri': moqie})

    def _mjson_reach(self, seat):
        self._mjson({'type': 'reach', 'actor': seat})

    def _mjson_reach_accepted(self, seat):
        self._mjson({'type': 'reach_accepted', 'actor': seat})

    def _mjson_pon(self, seat, target, tile, consumed):
        self._mjson({
            'type': 'pon', 'actor': seat, 'target': target,
            'pai': to_mjai_tile(tile),
            'consumed': [to_mjai_tile(t) for t in consumed]
        })

    def _mjson_chi(self, seat, target, tile, consumed):
        self._mjson({
            'type': 'chi', 'actor': seat, 'target': target,
            'pai': to_mjai_tile(tile),
            'consumed': [to_mjai_tile(t) for t in consumed]
        })

    def _mjson_daiminkan(self, seat, target, tile):
        self._mjson({
            'type': 'daiminkan', 'actor': seat, 'target': target,
            'pai': to_mjai_tile(tile),
            'consumed': [to_mjai_tile(tile), to_mjai_tile(tile), to_mjai_tile(tile)]
        })

    def _mjson_ankan(self, seat, tile):
        self._mjson({
            'type': 'ankan', 'actor': seat,
            'consumed': [to_mjai_tile(tile), to_mjai_tile(tile), to_mjai_tile(tile), to_mjai_tile(tile)]
        })

    def _mjson_kakan(self, seat, tile):
        self._mjson({
            'type': 'kakan', 'actor': seat,
            'pai': to_mjai_tile(tile),
            'consumed': [to_mjai_tile(tile)]
        })

    def _mjson_dora(self):
        for di in self._dora_indicators:
            self._mjson({'type': 'dora', 'dora_marker': to_mjai_tile(di)})

    def _mjson_hora(self, winner, loser, tile, is_tsumo):
        msg = {
            'type': 'hora',
            'actor': winner,
        }
        if is_tsumo:
            msg['target'] = None
        else:
            msg['target'] = loser
        msg['pai'] = to_mjai_tile(tile)
        msg['scores'] = list(self._scores)
        self._mjson(msg)

    def _mjson_ryukyoku(self):
        self._mjson({
            'type': 'ryukyoku',
            'scores': list(self._scores),
        })

    def _ms_action(self, class_name, data):
        self._ms_log['detail_records']['actions'].append({
            'type': 1,
            'result': {'class_name': class_name, 'data': data}
        })

    def _ms_new_round(self):
        data = {
            'chang': self._chang, 'ju': self._ju,
            'ben': self._honba, 'liqibang': self._riichi_sticks,
            'scores': list(self._scores),
            'doras': [to_mjai_tile(d) for d in self._dora_indicators],
        }
        for s in range(4):
            data[f'tiles{s}'] = [to_mjai_tile(t) for t in self._hands[s]]
        self._ms_action('RecordNewRound', data)

    def _ms_add_dora(self):
        if self._dora_indicators:
            self._ms_action('RecordAddDora', {
                'dora': to_mjai_tile(self._dora_indicators[-1]),
            })

    def _ms_deal_tile(self, seat, tile):
        self._ms_action('RecordDealTile', {
            'seat': seat, 'tile': to_mjai_tile(tile),
            'leftTileCount': self._dead_wall_start - self._wall_pos,
            'operation': {'seat': seat, 'operationList': [{'type': 1}]},
        })

    def _ms_discard(self, seat, tile, is_liqi=False, moqie=False):
        self._ms_action('RecordDiscardTile', {
            'seat': seat, 'tile': to_mjai_tile(tile),
            'isLiqi': is_liqi, 'moqie': moqie, 'isWliqi': False,
        })

    def _ms_chi_peng_gang(self, seat, tiles, froms, meld_type):
        self._ms_action('RecordChiPengGang', {
            'seat': seat, 'type': meld_type,
            'tiles': [to_mjai_tile(t) for t in tiles],
            'froms': froms,
            'tileStates': [0] * len(tiles),
            'operation': {'seat': seat, 'operationList': [{'type': 1}]},
        })

    def _ms_an_gang_add_gang(self, seat, tile, gang_type):
        self._ms_action('RecordAnGangAddGang', {
            'seat': seat, 'tiles': to_mjai_tile(tile), 'type': gang_type,
        })

    def _ms_hule(self, seat, hules_data, old_scores, delta_scores):
        new_scores = [old_scores[i] + delta_scores[i] for i in range(4)]
        self._ms_action('RecordHule', {
            'seat': seat,
            'hules': hules_data,
            'scores': [{
                'scores': list(new_scores),
                'oldScores': list(old_scores),
                'deltaScores': list(delta_scores),
            }],
        })

    def _ms_no_tile(self, old_scores, delta_scores):
        new_scores = [old_scores[i] + delta_scores[i] for i in range(4)]
        players = []
        for s in range(4):
            is_tenpai = self._is_tenpai(s)
            entry = {'tingpai': is_tenpai}
            if is_tenpai:
                entry['hand'] = [to_mjai_tile(t) for t in self._hands[s]]
                entry['tings'] = []
            players.append(entry)
        self._ms_action('RecordNoTile', {
            'liujumanguan': False,
            'players': players,
            'scores': [{
                'scores': list(new_scores),
                'oldScores': list(old_scores),
                'deltaScores': list(delta_scores),
            }],
        })

    def _ms_save(self):
        path = self._majsoul_path or (self._mjson_path.replace('.mjson', '_ms.json') if self._mjson_path else None)
        if not path:
            return
        os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(self._ms_log, f, ensure_ascii=False, indent=2)

    def _compute_player_stats(self, result: GameResult):
        dealer_streak = [0] * 4
        max_dealer_streak = [0] * 4
        for kr in result.kyoku_results:
            for s in range(4):
                ps = result.player_stats[s]
                ps.num_kyoku += 1
                if kr.reach_seats[s]:
                    ps.reach_declarations += 1
                if kr.open_meld_counts[s] > 0:
                    ps.kyoku_with_meld += 1

                if kr.winner_seat == s:
                    ps.wins += 1
                    ps.tsumo_wins += 1 if kr.is_tsumo else 0
                    ps.ron_wins += 1 if not kr.is_tsumo else 0
                    ps.total_han += kr.han
                    ps.total_win_points += kr.win_score
                    ps.win_turns.append(kr.tsumo_turn)
                    if kr.reach_seats[s]:
                        ps.reach_wins += 1
                    if kr.open_meld_counts[s] > 0:
                        ps.open_wins += 1
                    elif not kr.reach_seats[s]:
                        ps.damaten_wins += 1
                    for y in kr.yaku_list:
                        ps.yaku_counts[y] = ps.yaku_counts.get(y, 0) + 1

                if kr.winner_seat is not None and not kr.is_tsumo and kr.winner_seat != s:
                    if kr.delta_scores[s] < 0:
                        ps.dealt_in += 1

                if kr.is_exhaustive and s in kr.tenpai_seats:
                    ps.tenpai_exhaustive += 1

            for s in range(4):
                if s == kr.dealer_seat:
                    if kr.winner_seat == s:
                        dealer_streak[s] += 1
                    elif kr.is_exhaustive and s in kr.tenpai_seats:
                        dealer_streak[s] += 1
                    else:
                        dealer_streak[s] = 0
                    max_dealer_streak[s] = max(max_dealer_streak[s], dealer_streak[s])

        for s in range(4):
            ps = result.player_stats[s]
            ps.final_score = result.final_scores[s]
            ps.placement = result.placement_of(s)
            ps.busted = result.final_scores[s] < 0
            ps.max_renchan = max_dealer_streak[s]

    def _init_wall(self, rng: random.Random) -> List[str]:
        tiles = []
        for tid in range(TILE_TYPES):
            for _ in range(TILES_PER_TYPE):
                tiles.append(id_to_tile(tid))
        tiles[4 * TILES_PER_TYPE + 0] = '0m'  # first 5m → 赤5m
        tiles[13 * TILES_PER_TYPE + 0] = '0p'  # first 5p → 赤5p
        tiles[22 * TILES_PER_TYPE + 0] = '0s'  # first 5s → 赤5s
        rng.shuffle(tiles)
        return tiles

    def _draw_live(self) -> Optional[str]:
        if self._wall_pos >= self._dead_wall_start:
            return None
        t = self._wall[self._wall_pos]
        self._wall_pos += 1
        return t

    def _draw_dead(self) -> Optional[str]:
        if self._dead_wall_pos < self._dead_wall_start:
            return None
        t = self._wall[self._dead_wall_pos]
        self._dead_wall_pos -= 1
        return t

    def _reveal_dora(self):
        idx = self._dead_wall_start + (len(self._dora_indicators) * 2)
        if idx < WALL_SIZE and len(self._dora_indicators) < 5:
            self._dora_indicators.append(self._wall[idx])

    def _deal_round(self):
        kyoku_rng = random.Random(self.wall_seed * 100 + self._kyoku_count)
        self._wall = self._init_wall(kyoku_rng)
        self._wall_pos = 0
        self._dead_wall_start = WALL_SIZE - DEAD_WALL_SIZE
        self._dead_wall_pos = WALL_SIZE - 1

        self._hands = [[], [], [], []]
        self._melds: List[List[Meld]] = [[], [], [], []]
        self._rivers: List[List[str]] = [[], [], [], []]
        self._river_moqie: List[List[bool]] = [[], [], [], []]
        self._reach_states: List[ReachState] = [ReachState() for _ in range(4)]
        self._reach_locked: List[bool] = [False] * 4
        self._tsumo_count = 0
        self._player_tsumo = [0, 0, 0, 0]
        self._last_discard = None
        self._last_discard_seat = -1
        self._current_player = self._dealer_seat
        self._skip_draw = False

        for _ in range(3):
            for s in range(4):
                for _ in range(4):
                    t = self._draw_live()
                    if t:
                        self._hands[s].append(t)
        for s in range(4):
            t = self._draw_live()
            if t:
                self._hands[s].append(t)

        self._dora_indicators = []
        self._reveal_dora()

        self._mjson_start_kyoku()

        t = self._draw_live()
        if t:
            self._hands[self._current_player].append(t)

        self._ms_new_round()

    def _run_kyoku(self) -> KyokuResult:
        self._deal_round()
        dealer_first_action = True

        while True:
            seat = self._current_player

            if self._reach_locked[seat]:
                drawn = self._draw_live()
                if drawn is None:
                    return self._ryuukyoku()
                self._hands[seat].append(drawn)
                self._tsumo_count += 1
                self._player_tsumo[seat] += 1

                if self._is_tenpai(seat):
                    st = self._build_state(seat)
                    if self.players[seat].should_tsumo(st):
                        return self._tsumo_win(seat, drawn)

                self._discard(seat, drawn, moqie=True)
                self._mjson_dahai(seat, drawn, True)
                self._ms_discard(seat, drawn, moqie=True)
                if self._wall_pos >= self._dead_wall_start:
                    return self._ryuukyoku()
                self._current_player = (seat + 1) % 4
                continue

            needs_draw = not (dealer_first_action and seat == self._dealer_seat)
            if self._skip_draw:
                needs_draw = False
                self._skip_draw = False
            if needs_draw:
                drawn = self._draw_live()
                if drawn is None:
                    return self._ryuukyoku()
                self._hands[seat].append(drawn)
                self._tsumo_count += 1
                self._player_tsumo[seat] += 1
                self._mjson_tsumo(seat, drawn)
                self._ms_deal_tile(seat, drawn)

                if self._is_tenpai(seat):
                    st = self._build_state(seat)
                    if self.players[seat].should_tsumo(st):
                        return self._tsumo_win(seat, drawn)

                ankan_candidate = self._find_ankan(seat)
                if ankan_candidate is not None:
                    st = self._build_state(seat)
                    if self.players[seat].should_kan(st):
                        self._do_ankan(seat, ankan_candidate)
                        self._mjson_ankan(seat, ankan_candidate)
                        self._ms_an_gang_add_gang(seat, ankan_candidate, 3)
                        self._mjson_dora()
                        self._ms_add_dora()
                        self._clear_ippatsu()
                        dealer_first_action = False
                        st = self._build_state(seat)
                        discard = self.players[seat].decide_discard(st)
                        if discard is None or discard not in self._hands[seat]:
                            discard = self._hands[seat][-1] if self._hands[seat] else None
                            if discard is None:
                                return self._ryuukyoku()
                        declare_riichi = self.players[seat].should_riichi(st)
                        self._discard(seat, discard, moqie=False)
                        self._mjson_dahai(seat, discard, False)
                        self._ms_discard(seat, discard, False, declare_riichi)
                        if declare_riichi and self._scores[seat] >= 1000:
                            self._scores[seat] -= 1000
                            self._riichi_sticks += 1
                            rs = self._reach_states[seat]
                            rs.is_reach = True
                            rs.reach_turn = self._tsumo_count
                            rs.is_ippatsu = True
                            self._reach_locked[seat] = True
                            self._mjson_reach(seat)
                        self._current_player = (seat + 1) % 4
                        continue

                # 加槓チェック
                if self._find_kakan(seat, drawn):
                    st = self._build_state(seat)
                    if self.players[seat].should_kan(st):
                        self._do_kakan(seat, drawn)
                        self._mjson_kakan(seat, drawn)
                        self._ms_an_gang_add_gang(seat, drawn, 2)
                        self._mjson_dora()
                        self._ms_add_dora()
                        self._clear_ippatsu()
                        dealer_first_action = False
                        # After kakan + rinshan, go directly to discard
                        st = self._build_state(seat)
                        discard = self.players[seat].decide_discard(st)
                        if discard is None or discard not in self._hands[seat]:
                            discard = self._hands[seat][-1] if self._hands[seat] else None
                            if discard is None:
                                return self._ryuukyoku()
                        declare_riichi = self.players[seat].should_riichi(st)
                        self._discard(seat, discard, moqie=False)
                        self._mjson_dahai(seat, discard, False)
                        self._ms_discard(seat, discard, False, declare_riichi)
                        if declare_riichi and self._scores[seat] >= 1000:
                            self._scores[seat] -= 1000
                            self._riichi_sticks += 1
                            rs = self._reach_states[seat]
                            rs.is_reach = True
                            rs.reach_turn = self._tsumo_count
                            rs.is_ippatsu = True
                            self._reach_locked[seat] = True
                            self._mjson_reach(seat)
                        self._current_player = (seat + 1) % 4
                        continue

            dealer_first_action = False

            st = self._build_state(seat)
            discard = self.players[seat].decide_discard(st)
            if discard is None or discard not in self._hands[seat]:
                discard = self._hands[seat][-1] if self._hands[seat] else None
                if discard is None:
                    return self._ryuukyoku()

            declare_riichi = self.players[seat].should_riichi(st)

            self._discard(seat, discard, moqie=False)
            self._mjson_dahai(seat, discard, False)
            self._ms_discard(seat, discard, False, declare_riichi)

            if declare_riichi and self._scores[seat] >= 1000:
                self._scores[seat] -= 1000
                self._riichi_sticks += 1
                rs = self._reach_states[seat]
                rs.is_reach = True
                rs.reach_turn = self._tsumo_count
                rs.is_ippatsu = True
                self._reach_locked[seat] = True
                self._mjson_reach(seat)

            call = self._resolve_call(seat, discard)
            if call is not None:
                if call['type'] == 'ron':
                    return self._ron_win(call['seat'], seat, discard)
                elif call['type'] == 'pon':
                    self._do_pon(call['seat'], seat, discard)
                    self._mjson_pon(call['seat'], seat, discard, [discard, discard])
                    self._ms_chi_peng_gang(call['seat'], [discard, discard, discard], [seat, call['seat'], call['seat']], 1)
                    self._clear_ippatsu()
                    self._skip_draw = True
                    self._current_player = call['seat']
                    continue
                elif call['type'] == 'chi':
                    self._do_chi(call['seat'], seat, discard, call['consumed'])
                    self._mjson_chi(call['seat'], seat, discard, call['consumed'])
                    full_tiles = [discard] + call['consumed']
                    self._ms_chi_peng_gang(call['seat'], full_tiles, [seat, call['seat'], call['seat']], 0)
                    self._clear_ippatsu()
                    self._skip_draw = True
                    self._current_player = call['seat']
                    continue
                elif call['type'] == 'kan':
                    cs = call['seat']
                    self._do_pon(cs, seat, discard)  # Use pon logic for 3 tiles
                    self._mjson_daiminkan(cs, seat, discard)
                    self._ms_chi_peng_gang(cs, [discard]*3, [seat, cs, cs], 2)
                    self._clear_ippatsu()
                    # Draw rinshan and reveal dora
                    dead = self._draw_dead()
                    if dead:
                        self._hands[cs].append(dead)
                    self._reveal_dora()
                    self._mjson_dora()
                    self._ms_add_dora()
                    self._skip_draw = True
                    self._current_player = cs
                    continue

            if self._wall_pos >= self._dead_wall_start:
                return self._ryuukyoku()
            self._current_player = (seat + 1) % 4

    def _clear_ippatsu(self):
        for rs in self._reach_states:
            rs.is_ippatsu = False

    def _is_tenpai(self, seat: int) -> bool:
        counts = hand_to_counts(self._hands[seat])
        mc = len(self._melds[seat])
        if mc == 0:
            return ShantenCalculator.calculate_closed_effective(counts) <= -1
        return ShantenCalculator.calculate_open(counts, mc) <= -1

    def _find_ankan(self, seat: int) -> Optional[str]:
        counts = hand_to_counts(self._hands[seat])
        for i in range(34):
            if counts[i] >= 4:
                for t in self._hands[seat]:
                    if tile_to_id(t) == i:
                        return t
        return None

    def _find_kakan(self, seat: int, drawn: str) -> bool:
        tid = tile_to_id(drawn)
        for m in self._melds[seat]:
            if m.type == 1 and len(m.tiles) >= 3:
                if tile_to_id(m.tiles[0]) == tid:
                    return True
        return False

    def _do_kakan(self, seat: int, tile: str):
        tid = tile_to_id(tile)
        for m in self._melds[seat]:
            if m.type == 1 and len(m.tiles) >= 3 and tile_to_id(m.tiles[0]) == tid:
                m.type = 2
                m.tiles = m.tiles + [tile]
                m.froms = m.froms + [seat]
                self._hands[seat].remove(tile)
                break
        dead = self._draw_dead()
        if dead:
            self._hands[seat].append(dead)
        self._reveal_dora()

    def _do_ankan(self, seat: int, tile: str):
        tid = tile_to_id(tile)
        for _ in range(4):
            for t in list(self._hands[seat]):
                if tile_to_id(t) == tid:
                    self._hands[seat].remove(t)
                    break
        self._melds[seat].append(
            Meld(type=3, tiles=[tile] * 4, froms=[seat] * 4, tile_states=[])
        )
        dead = self._draw_dead()
        if dead:
            self._hands[seat].append(dead)
        self._reveal_dora()

    def _discard(self, seat: int, tile: str, moqie: bool):
        if tile in self._hands[seat]:
            self._hands[seat].remove(tile)
        self._rivers[seat].append(tile)
        self._river_moqie[seat].append(moqie)
        self._last_discard = tile
        self._last_discard_seat = seat

    def _resolve_call(self, discarder: int, tile: str) -> Optional[dict]:
        tid = tile_to_id(tile)

        ron_candidates = []
        for s in range(4):
            if s == discarder:
                continue
            cnt = hand_to_counts(self._hands[s])
            cnt[tid] += 1
            mc = len(self._melds[s])
            # 多牌チェック: 手牌+副露の合計が14を超える場合は和了不可
            meld_tiles = sum(len(m.tiles) for m in self._melds[s])
            if sum(cnt) + meld_tiles > 14:
                continue
            if mc == 0:
                if ShantenCalculator.calculate_closed_effective(cnt) <= -1:
                    ron_candidates.append(s)
            else:
                if ShantenCalculator.calculate_open(cnt, mc) <= -1:
                    ron_candidates.append(s)

        for s in ron_candidates:
            st = self._build_state(s)
            if self.players[s].should_ron(st):
                return {'type': 'ron', 'seat': s}

        for s in range(4):
            if s == discarder or self._reach_locked[s]:
                continue
            if hand_to_counts(self._hands[s])[tid] >= 3:
                st = self._build_state(s)
                if self.players[s].should_call_meld(st, CALL_KAN, [tile, tile, tile], discarder):
                    return {'type': 'kan', 'seat': s}

        pon_seats = []
        for s in range(4):
            if s == discarder or self._reach_locked[s]:
                continue
            if hand_to_counts(self._hands[s])[tid] >= 2:
                pon_seats.append(s)
        if pon_seats:
            pon_seats.sort(key=lambda x: (x - discarder) % 4)
            for s in pon_seats:
                st = self._build_state(s)
                if self.players[s].should_call_meld(st, CALL_PON, [tile, tile, tile], discarder):
                    return {'type': 'pon', 'seat': s}

        chi_seat = (discarder + 1) % 4
        if not self._reach_locked[chi_seat] and not is_honor(tid):
            base = (tid // 9) * 9
            off = tid - base
            for first in (off - 2, off - 1):
                if 0 <= first <= 6 and first != off:
                    if first + 2 <= 8:
                        needed = [first, first + 1, first + 2]
                        if off in needed:
                            c = [n for n in needed if n != off]
                            ch = hand_to_counts(self._hands[chi_seat])
                            if ch[base + c[0]] >= 1 and ch[base + c[1]] >= 1:
                                consumed = [id_to_tile(base + c[0]), id_to_tile(base + c[1])]
                                full_tiles = [tile] + consumed
                                st = self._build_state(chi_seat)
                                if self.players[chi_seat].should_call_meld(st, CALL_CHI, full_tiles, discarder):
                                    return {
                                        'type': 'chi', 'seat': chi_seat, 'consumed': consumed
                                    }
        return None

    def _do_pon(self, seat: int, from_seat: int, tile: str):
        tid = tile_to_id(tile)
        removed = 0
        for t in list(self._hands[seat]):
            if tile_to_id(t) == tid and removed < 2:
                self._hands[seat].remove(t)
                removed += 1
        self._melds[seat].append(
            Meld(type=2, tiles=[tile] * 3, froms=[from_seat, seat, seat], tile_states=[])
        )

    def _do_chi(self, seat: int, from_seat: int, tile: str, consumed: List[str]):
        tid = tile_to_id(tile)
        base = (tid // 9) * 9
        offsets = sorted([tile_to_id(consumed[0]) - base, tile_to_id(consumed[1]) - base, tid - base])
        full = [id_to_tile(base + o) for o in offsets]
        froms = [from_seat] + [seat] * 2
        self._melds[seat].append(Meld(type=1, tiles=full, froms=froms, tile_states=[]))
        for c in consumed:
            if c in self._hands[seat]:
                self._hands[seat].remove(c)

    def _tsumo_win(self, seat: int, drawn: str) -> KyokuResult:
        from scoring import estimate_han, calculate_fu, calculate_score
        is_dealer = seat == self._dealer_seat
        open_melds = [m for m in self._melds[seat] if m.type in (1, 2)]
        is_open = len(open_melds) > 0
        hand = self._hands[seat]

        han, yaku_list = estimate_han(hand, self._melds[seat], self._dora_indicators,
                                      is_open=is_open, is_tsumo=True,
                                      has_reach=self._reach_states[seat].is_reach,
                                      is_ippatsu=self._reach_states[seat].is_ippatsu,
                                      seat=seat, chang=self._chang, ju=self._ju,
                                       win_tile=drawn, tsumo_turn=self._player_tsumo[seat])

        fu = calculate_fu(hand, self._melds[seat], drawn, is_tsumo=True,
                          is_open=is_open, is_dealer=is_dealer,
                          wait_type='tanki' if hand_to_counts(hand)[tile_to_id(drawn)] >= 2 else 'ryanmen')

        si = calculate_score(han, fu, is_dealer, is_tsumo=True,
                             honba=0, riichi_sticks=0)

        honba_pay = self._honba * 300
        riichi_pay = self._riichi_sticks * 1000

        delta = [0, 0, 0, 0]
        if is_dealer:
            each = si['from_each_non_dealer']
            for s in range(4):
                if s == seat:
                    delta[s] = each * 3 + honba_pay + riichi_pay
                else:
                    delta[s] = -(each + honba_pay // 3)
        else:
            from_dealer = si['from_dealer']
            from_non = si['from_each_non_dealer']
            for s in range(4):
                if s == seat:
                    delta[s] = from_dealer + from_non * 2 + honba_pay + riichi_pay
                elif s == 0:
                    delta[s] = -(from_dealer + honba_pay // 3)
                else:
                    delta[s] = -(from_non + honba_pay // 3)

        new_scores = [self._scores[s] + delta[s] for s in range(4)]
        old_scores = list(self._scores)
        self._scores = list(new_scores)

        self._ms_hule(seat, [{
            'seat': seat, 'zimo': True, 'liqi': self._reach_states[seat].is_reach,
        }], old_scores, delta)

        return KyokuResult(seed=self.wall_seed, chang=self._chang, ju=self._ju,
                           honba=self._honba, riichi_sticks=self._riichi_sticks,
                           winner_seat=seat, is_tsumo=True, is_exhaustive=False,
                           delta_scores=delta, new_scores=new_scores,
                           tenpai_seats=[seat], han=han, fu=fu,
                           reach_seats=[rs.is_reach for rs in self._reach_states],
                           meld_counts=[len(self._melds[s]) for s in range(4)],
                           open_meld_counts=[len([m for m in self._melds[s] if m.type in (1, 2)]) for s in range(4)],
                           win_tile=drawn, win_score=delta[seat],
                           tsumo_turn=self._player_tsumo[seat], yaku_list=yaku_list,
                           dealer_seat=self._dealer_seat)

    def _ron_win(self, seat: int, discarder: int, tile: str) -> KyokuResult:
        from scoring import estimate_han, calculate_fu, calculate_score
        is_dealer = seat == self._dealer_seat
        open_melds = [m for m in self._melds[seat] if m.type in (1, 2)]
        is_open = len(open_melds) > 0
        hand = list(self._hands[seat]) + [tile]

        han, yaku_list = estimate_han(hand, self._melds[seat], self._dora_indicators,
                                      is_open=is_open, is_tsumo=False,
                                      has_reach=self._reach_states[seat].is_reach,
                                      is_ippatsu=self._reach_states[seat].is_ippatsu,
                                      seat=seat, chang=self._chang, ju=self._ju,
                                      win_tile=tile, tsumo_turn=self._tsumo_count)

        from core.str_converter import hand_to_counts
        ron_wait = 'tanki' if hand_to_counts(list(self._hands[seat]) + [tile])[tile_to_id(tile)] >= 2 else 'ryanmen'
        fu = calculate_fu(hand, self._melds[seat], tile, is_tsumo=False,
                          is_open=is_open, is_dealer=is_dealer, wait_type=ron_wait)

        si = calculate_score(han, fu, is_dealer, is_tsumo=False,
                             honba=0, riichi_sticks=0)

        total_pay = si['total']
        honba_pay = self._honba * 300
        riichi_pay = self._riichi_sticks * 1000

        delta = [0, 0, 0, 0]
        delta[seat] = total_pay + honba_pay + riichi_pay
        delta[discarder] = -(total_pay + honba_pay)

        new_scores = [self._scores[s] + delta[s] for s in range(4)]
        old_scores = list(self._scores)
        self._scores = list(new_scores)

        self._ms_hule(seat, [{
            'seat': seat, 'zimo': False, 'liqi': self._reach_states[seat].is_reach,
        }], old_scores, delta)

        return KyokuResult(seed=self.wall_seed, chang=self._chang, ju=self._ju,
                           honba=self._honba, riichi_sticks=self._riichi_sticks,
                           winner_seat=seat, is_tsumo=False, is_exhaustive=False,
                           delta_scores=delta, new_scores=new_scores,
                           tenpai_seats=[seat], han=han, fu=fu,
                           reach_seats=[rs.is_reach for rs in self._reach_states],
                           meld_counts=[len(self._melds[s]) for s in range(4)],
                           open_meld_counts=[len([m for m in self._melds[s] if m.type in (1, 2)]) for s in range(4)],
                           win_tile=tile, win_score=delta[seat],
                           tsumo_turn=self._player_tsumo[seat], yaku_list=yaku_list,
                           dealer_seat=self._dealer_seat)

    def _ryuukyoku(self) -> KyokuResult:
        from scoring import calculate_tenpai_payments
        tenpai = [s for s in range(4) if self._is_tenpai(s)]
        teban = calculate_tenpai_payments(tenpai)
        old_scores = list(self._scores)
        new_scores = [self._scores[s] + teban[s] for s in range(4)]
        self._scores = list(new_scores)

        self._ms_no_tile(old_scores, teban)

        return KyokuResult(seed=self.wall_seed, chang=self._chang, ju=self._ju,
                           honba=self._honba, riichi_sticks=self._riichi_sticks,
                           winner_seat=None, is_tsumo=False, is_exhaustive=True,
                           delta_scores=teban, new_scores=new_scores,
                           tenpai_seats=tenpai, han=0, fu=0,
                           reach_seats=[rs.is_reach for rs in self._reach_states],
                           meld_counts=[len(self._melds[s]) for s in range(4)],
                           open_meld_counts=[len([m for m in self._melds[s] if m.type in (1, 2)]) for s in range(4)],
                           tsumo_turn=self._player_tsumo[self._dealer_seat],
                           dealer_seat=self._dealer_seat)

    def _build_state(self, seat: int, override_hand: List[str] = None) -> GameState:
        s = GameState()
        s.chang = self._chang
        s.ju = self._ju
        s.ben = self._honba
        s.liqibang = self._riichi_sticks
        s.my_seat = seat
        s.dealer_seat = self._dealer_seat
        s.my_hand = list(override_hand if override_hand is not None else self._hands[seat])
        s.my_melds = list(self._melds[seat])
        s.river = [list(r) for r in self._rivers]
        s.melds = [list(ms) for ms in self._melds]
        s.scores = list(self._scores)
        s.doras = list(self._dora_indicators)
        s.left_tile_count = self._dead_wall_start - self._wall_pos
        s.tsumo_count = self._player_tsumo[seat]
        s.reach_states = [ReachState(is_reach=rs.is_reach, reach_turn=rs.reach_turn,
                                      is_ippatsu=rs.is_ippatsu) for rs in self._reach_states]
        s.last_discard_seat = self._last_discard_seat
        s.last_discard_tile = self._last_discard
        s.river_moqie = [list(r) for r in self._river_moqie]
        return s

    def _should_game_end(self) -> bool:
        if self._kyoku_count < self._rounds_per_game:
            return False
        if max(self._scores) >= 30000:
            return True
        if self._kyoku_count >= self._rounds_per_game * 2 + 4:
            return True
        return False

    def _advance_kyoku(self, kr: KyokuResult):
        if kr.winner_seat is not None:
            if kr.winner_seat == self._dealer_seat:
                self._honba += 1
            else:
                self._honba = 0
            self._riichi_sticks = 0  # 和了時はリーチ棒を全て精算
        else:
            is_dealer_tenpai = self._dealer_seat in kr.tenpai_seats
            if is_dealer_tenpai:
                self._honba += 1
                return
            self._honba = 0
            # 流局時はリーチ棒を持ち越し（リセットしない）
        self._ju += 1
        if self._ju >= 4:
            self._ju = 0
            self._chang += 1
        self._dealer_seat = (self._dealer_seat + 1) % 4

    def _compute_placements(self) -> List[int]:
        indexed = [(self._scores[i], i) for i in range(4)]
        indexed.sort(key=lambda x: (-x[0], x[1]))
        return [s for _, s in indexed]
