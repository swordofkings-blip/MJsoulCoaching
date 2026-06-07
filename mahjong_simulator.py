# -*- coding: utf-8 -*-
from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from game_state import GameState, Meld, ReachState
from str_converter import id_to_tile, tile_to_id, hand_to_counts, is_honor
from strategy_manager import ShantenCalculator

TILE_TYPES = 34
TILES_PER_TYPE = 4
WALL_SIZE = 136
DEAD_WALL_SIZE = 14
HAND_SIZE = 13


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


@dataclass
class GameResult:
    seed: int
    game_type: str
    kyoku_results: List[KyokuResult] = field(default_factory=list)
    final_scores: List[int] = field(default_factory=lambda: [25000, 25000, 25000, 25000])
    final_placements: List[int] = field(default_factory=lambda: [0, 1, 2, 3])
    num_kyoku: int = 0

    def placement_of(self, seat: int) -> int:
        for p, s in enumerate(self.final_placements):
            if s == seat:
                return p
        return 3


class MahjongSimulator:
    def __init__(self, wall_seed: int, players: List, game_type: str = 'hanchan'):
        self.wall_seed = wall_seed
        self.players = [p.clone(i) for i, p in enumerate(players)]
        self.game_type = game_type
        if game_type == 'tonpu':
            self._rounds_per_game = 4
        else:
            self._rounds_per_game = 8

    def run_game(self) -> GameResult:
        result = GameResult(seed=self.wall_seed, game_type=self.game_type)

        self._scores = [25000, 25000, 25000, 25000]
        self._riichi_sticks = 0
        self._honba = 0
        self._chang = 0
        self._ju = 0
        self._dealer_seat = 0
        self._kyoku_count = 0

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
        return result

    def _init_wall(self, rng: random.Random) -> List[str]:
        tiles = []
        for tid in range(TILE_TYPES):
            for _ in range(TILES_PER_TYPE):
                tiles.append(id_to_tile(tid))
        tiles[4] = '0m'
        tiles[4 + 34] = '0m'
        tiles[4 + 68] = '0p'
        tiles[4 + 102] = '0p'
        rng.shuffle(tiles)
        return tiles

    def _draw_live(self) -> Optional[str]:
        if self._wall_pos >= self._dead_wall_start:
            return None
        t = self._wall[self._wall_pos]
        self._wall_pos += 1
        return t

    def _draw_dead(self) -> Optional[str]:
        if self._wall_pos >= WALL_SIZE:
            return None
        t = self._wall[self._wall_pos]
        self._wall_pos += 1
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

        self._hands = [[], [], [], []]
        self._melds: List[List[Meld]] = [[], [], [], []]
        self._rivers: List[List[str]] = [[], [], [], []]
        self._river_moqie: List[List[bool]] = [[], [], [], []]
        self._reach_states: List[ReachState] = [ReachState() for _ in range(4)]
        self._reach_locked: List[bool] = [False] * 4
        self._tsumo_count = 0
        self._last_discard = None
        self._last_discard_seat = -1
        self._current_player = self._dealer_seat

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

        t = self._draw_live()
        if t:
            self._hands[self._current_player].append(t)

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

                if self._is_tenpai(seat):
                    st = self._build_state(seat)
                    if self.players[seat].should_tsumo(st):
                        return self._tsumo_win(seat, drawn)

                self._discard(seat, drawn, moqie=True)
                self._clear_ippatsu()
                if self._wall_pos >= self._dead_wall_start:
                    return self._ryuukyoku()
                self._current_player = (seat + 1) % 4
                continue

            needs_draw = not (dealer_first_action and seat == self._dealer_seat)
            if needs_draw:
                drawn = self._draw_live()
                if drawn is None:
                    return self._ryuukyoku()
                self._hands[seat].append(drawn)
                self._tsumo_count += 1

                if self._is_tenpai(seat):
                    st = self._build_state(seat)
                    if self.players[seat].should_tsumo(st):
                        return self._tsumo_win(seat, drawn)

                ankan_candidate = self._find_ankan(seat)
                if ankan_candidate is not None:
                    st = self._build_state(seat)
                    if self.players[seat].should_kan(st):
                        self._do_ankan(seat, ankan_candidate)
                        self._clear_ippatsu()
                        dealer_first_action = False
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

            if declare_riichi and self._scores[seat] >= 1000:
                self._scores[seat] -= 1000
                self._riichi_sticks += 1
                rs = self._reach_states[seat]
                rs.is_reach = True
                rs.reach_turn = self._tsumo_count
                rs.is_ippatsu = True
                self._reach_locked[seat] = True

            call = self._resolve_call(seat, discard)
            self._clear_ippatsu()
            if call is not None:
                if call['type'] == 'ron':
                    return self._ron_win(call['seat'], seat, discard)
                elif call['type'] == 'pon':
                    self._do_pon(call['seat'], seat, discard)
                    self._current_player = call['seat']
                    continue
                elif call['type'] == 'chi':
                    self._do_chi(call['seat'], seat, discard, call['consumed'])
                    self._current_player = call['seat']
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
                if self.players[s].should_call_meld(st, 5, [tile, tile, tile], discarder):
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
                if self.players[s].should_call_meld(st, 2, [tile, tile, tile], discarder):
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
                                if self.players[chi_seat].should_call_meld(st, 1, full_tiles, discarder):
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
        is_dealer = (seat % 4) == 0
        open_melds = [m for m in self._melds[seat] if m.type in (1, 2)]
        is_open = len(open_melds) > 0
        hand = self._hands[seat]

        han = estimate_han(hand, self._melds[seat], self._dora_indicators,
                           is_open=is_open, is_tsumo=True,
                           has_reach=self._reach_states[seat].is_reach,
                           is_ippatsu=self._reach_states[seat].is_ippatsu)

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
        self._scores = list(new_scores)

        return KyokuResult(seed=self.wall_seed, chang=self._chang, ju=self._ju,
                           honba=self._honba, riichi_sticks=self._riichi_sticks,
                           winner_seat=seat, is_tsumo=True, is_exhaustive=False,
                           delta_scores=delta, new_scores=new_scores,
                           tenpai_seats=[seat], han=han, fu=fu)

    def _ron_win(self, seat: int, discarder: int, tile: str) -> KyokuResult:
        from scoring import estimate_han, calculate_fu, calculate_score
        is_dealer = (seat % 4) == 0
        open_melds = [m for m in self._melds[seat] if m.type in (1, 2)]
        is_open = len(open_melds) > 0
        hand = list(self._hands[seat]) + [tile]

        han = estimate_han(hand, self._melds[seat], self._dora_indicators,
                           is_open=is_open, is_tsumo=False,
                           has_reach=self._reach_states[seat].is_reach,
                           is_ippatsu=self._reach_states[seat].is_ippatsu)

        fu = calculate_fu(hand, self._melds[seat], tile, is_tsumo=False,
                          is_open=is_open, is_dealer=is_dealer, wait_type='ron')

        si = calculate_score(han, fu, is_dealer, is_tsumo=False,
                             honba=0, riichi_sticks=0)

        total_pay = si['total']
        honba_pay = self._honba * 300
        riichi_pay = self._riichi_sticks * 1000

        delta = [0, 0, 0, 0]
        delta[seat] = total_pay + honba_pay + riichi_pay
        delta[discarder] = -(total_pay + honba_pay)

        new_scores = [self._scores[s] + delta[s] for s in range(4)]
        self._scores = list(new_scores)

        return KyokuResult(seed=self.wall_seed, chang=self._chang, ju=self._ju,
                           honba=self._honba, riichi_sticks=self._riichi_sticks,
                           winner_seat=seat, is_tsumo=False, is_exhaustive=False,
                           delta_scores=delta, new_scores=new_scores,
                           tenpai_seats=[seat], han=han, fu=fu)

    def _ryuukyoku(self) -> KyokuResult:
        from scoring import calculate_tenpai_payments
        tenpai = [s for s in range(4) if self._is_tenpai(s)]
        teban = calculate_tenpai_payments(tenpai)
        new_scores = [self._scores[s] + teban[s] for s in range(4)]
        self._scores = list(new_scores)

        return KyokuResult(seed=self.wall_seed, chang=self._chang, ju=self._ju,
                           honba=self._honba, riichi_sticks=self._riichi_sticks,
                           winner_seat=None, is_tsumo=False, is_exhaustive=True,
                           delta_scores=teban, new_scores=new_scores,
                           tenpai_seats=tenpai, han=0, fu=0)

    def _build_state(self, seat: int, override_hand: List[str] = None) -> GameState:
        s = GameState()
        s.chang = self._chang
        s.ju = self._ju
        s.ben = self._honba
        s.liqibang = self._riichi_sticks
        s.my_seat = seat
        s.my_hand = list(override_hand if override_hand is not None else self._hands[seat])
        s.my_melds = list(self._melds[seat])
        s.river = [list(r) for r in self._rivers]
        s.melds = [list(ms) for ms in self._melds]
        s.scores = list(self._scores)
        s.doras = list(self._dora_indicators)
        s.left_tile_count = self._dead_wall_start - self._wall_pos
        s.tsumo_count = self._tsumo_count
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
                return
            self._riichi_sticks = 0
            self._honba = 0
        else:
            is_dealer_tenpai = self._dealer_seat in kr.tenpai_seats
            if is_dealer_tenpai:
                self._honba += 1
                return
            self._riichi_sticks = 0
            self._honba = 0
        self._ju += 1
        if self._ju >= 4:
            self._ju = 0
            self._chang += 1
        self._dealer_seat = (self._dealer_seat + 1) % 4

    def _compute_placements(self) -> List[int]:
        indexed = [(self._scores[i], i) for i in range(4)]
        indexed.sort(key=lambda x: (-x[0], x[1]))
        return [s for _, s in indexed]
