# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from str_converter import (
    HONOR_IDS,
    TERMINAL_IDS,
    hand_to_counts,
    is_honor,
    is_red_five,
    tile_to_id,
    id_to_tile,
)


TOTAL_TILE_TYPES = 34
TILES_PER_TYPE = 4


@dataclass
class Meld:
    type: int
    tiles: List[str]
    froms: List[int]
    tile_states: List[int] = field(default_factory=list)

    @property
    def tiles_id_counts(self) -> List[int]:
        from str_converter import hand_to_counts
        return hand_to_counts(self.tiles)

    @property
    def is_open(self) -> bool:
        return self.type in (0, 1, 2)


@dataclass
class ReachState:
    is_reach: bool = False
    reach_turn: int = -1
    is_ippatsu: bool = False
    is_rinshan: bool = False


class GameState:
    def __init__(self):
        self.reset()

    def reset(self):
        self.chang: int = 0
        self.ju: int = 0
        self.ben: int = 0
        self.liqibang: int = 0
        self.my_seat: int = 0
        self.my_hand: List[str] = []
        self.my_melds: List[Meld] = []
        self.last_self_drawn: Optional[str] = None
        self.river: List[List[str]] = [[], [], [], []]
        self.melds: List[List[Meld]] = [[], [], [], []]
        self.scores: List[int] = [25000, 25000, 25000, 25000]
        self.doras: List[str] = []
        self.left_tile_count: int = 70
        self.tsumo_count: int = 0
        self.reach_states: List[ReachState] = [ReachState() for _ in range(4)]
        self.last_discard_seat: int = -1
        self.last_discard_tile: Optional[str] = None
        self.tenhou_chiihou_locked: bool = False
        self.river_moqie: List[List[bool]] = [[], [], [], []]
        self.player_stats: Dict[str, Dict[str, float]] = {}
        self.wall_seed: int = 0
        self.kyoku_count: int = 0
        self.all_hands: List[List[str]] = [[], [], [], []]
        self.initial_hands: List[List[str]] = [[], [], [], []]
        self.player_tsumo: List[int] = [0, 0, 0, 0]
        self.wall: List[str] = []
        self.wall_pos: int = 0
        self.global_tsumo_count: int = 0

    def on_new_round(self, chang, ju, ben, liqibang, tiles, scores, left_tile_count, doras):
        self.chang = chang
        self.ju = ju
        self.ben = ben
        self.liqibang = liqibang
        self.my_hand = list(tiles)
        self.scores = list(scores)
        self.left_tile_count = left_tile_count
        self.doras = list(doras)
        self.my_melds = []
        self.river = [[], [], [], []]
        self.melds = [[], [], [], []]
        self.tsumo_count = 0
        self.reach_states = [ReachState() for _ in range(4)]
        self.last_discard_seat = -1
        self.last_discard_tile = None
        self.last_self_drawn = None
        self.tenhou_chiihou_locked = False
        self.river_moqie = [[], [], [], []]

    def on_self_draw(self, tile: str):
        self.my_hand.append(tile)
        self.last_self_drawn = tile
        self.left_tile_count = max(0, self.left_tile_count - 1)
        self.tsumo_count += 1

    def on_opponent_draw(self, seat: int):
        self.left_tile_count = max(0, self.left_tile_count - 1)
        self.tsumo_count += 1
        _ = seat

    def on_discard(self, seat: int, tile: str, isLiqi: bool, moqie: bool):
        self.river[seat].append(tile)
        self.river_moqie[seat].append(bool(moqie))
        self.last_discard_seat = seat
        self.last_discard_tile = tile
        if seat == self.my_seat:
            if tile in self.my_hand:
                self.my_hand.remove(tile)
            self.last_self_drawn = None
        if isLiqi:
            self.reach_states[seat].is_reach = True
            self.reach_states[seat].reach_turn = self.tsumo_count
            self.reach_states[seat].is_ippatsu = True

    def on_chi_peng_gang(self, type_: int, seat: int, tiles: List[str], froms: List[int], tile_states: List[int]):
        meld = Meld(type=type_, tiles=list(tiles), froms=list(froms), tile_states=list(tile_states))
        self.melds[seat].append(meld)
        if seat == self.my_seat:
            self.my_melds.append(meld)
            # 他家から出た牌を除き、自分が手牌から差し出した牌(fromsがmy_seatのもの)のみを削除
            for t, f in zip(tiles, froms):
                if f == self.my_seat:
                    target_id = tile_to_id(t)
                    # 赤5と通常5の表記揺れによる削除漏れを防ぐため、34種IDの一致で手牌から削除
                    for h_tile in list(self.my_hand):
                        if tile_to_id(h_tile) == target_id:
                            self.my_hand.remove(h_tile)
                            break
        if type_ == 2:
            self.doras_advance_if_needed()

    def on_an_gang_add_gang(self, type_: int, seat: int, tiles: str):
        if type_ == 3:
            meld_tiles = [tiles, tiles, tiles, tiles]
            meld = Meld(type=3, tiles=meld_tiles, froms=[seat] * 4)
            self.melds[seat].append(meld)
            if seat == self.my_seat:
                self.my_melds.append(meld)
                target_id = tile_to_id(tiles)
                # 暗槓する4枚を手牌から削除。赤5と通常5の両方が混在する場合を考慮しID一致で削除
                for _ in range(4):
                    for h_tile in list(self.my_hand):
                        if tile_to_id(h_tile) == target_id:
                            self.my_hand.remove(h_tile)
                            break
        elif type_ == 2:
            target_meld = None
            for m in self.melds[seat]:
                if tiles in m.tiles and m.type == 1:
                    target_meld = m
                    break
            if target_meld is None and seat == self.my_seat:
                for m in self.my_melds:
                    if tiles in m.tiles and m.type == 1:
                        target_meld = m
                        break
            if target_meld is not None:
                target_meld.tiles.append(tiles)
                # 加槓時に自分の手牌から加えた1枚を削除 (ID一致で赤5も安全に削除)
                if seat == self.my_seat:
                    target_id = tile_to_id(tiles)
                    for h_tile in list(self.my_hand):
                        if tile_to_id(h_tile) == target_id:
                            self.my_hand.remove(h_tile)
                            break
        self.doras_advance_if_needed()

    def on_new_dora(self, dora: str):
        self.doras.append(dora)

    def doras_advance_if_needed(self):
        pass

    def my_hand_counts(self) -> List[int]:
        return hand_to_counts(self.my_hand)

    def all_visible_counts(self) -> List[int]:
        from str_converter import hand_to_counts
        visible = [0] * TOTAL_TILE_TYPES
        for t in self.my_hand:
            visible[tile_to_id(t)] += 1
        for seat_river in self.river:
            for t in seat_river:
                visible[tile_to_id(t)] += 1
        for seat_melds in self.melds:
            for m in seat_melds:
                for t in m.tiles:
                    visible[tile_to_id(t)] += 1
        for dora in self.doras:
            visible[tile_to_id(dora)] += 1
        return visible

    @property
    def actual_doras(self) -> List[str]:
        """
        @title 実際のドラ牌のリスト取得
        @description ドラ表示牌(self.doras)に対応する、実際のドラ牌の文字列リストを返します。
        @returns {List[str]} 実際のドラ牌リスト
        """
        from str_converter import dora_indicator_to_dora
        return [dora_indicator_to_dora(d) for d in self.doras]

    def remaining_counts(self) -> List[int]:
        return [max(0, TILES_PER_TYPE - c) for c in self.all_visible_counts()]

    def is_any_opponent_reach(self) -> bool:
        for i, rs in enumerate(self.reach_states):
            if i == self.my_seat:
                continue
            if rs.is_reach:
                return True
        return False

    def opponent_reach_turns(self) -> List[int]:
        return [rs.reach_turn for i, rs in enumerate(self.reach_states) if i != self.my_seat and rs.is_reach]

    def my_hand_size_including_melds(self) -> int:
        return len(self.my_hand) + sum(len(m.tiles) for m in self.my_melds)

    def is_oya(self) -> bool:
        return self.my_seat == (getattr(self, 'dealer_seat', 0))

    def my_score_rank(self) -> int:
        ordered = sorted([(s, i) for i, s in enumerate(self.scores)], reverse=True)
        for rank, (s, i) in enumerate(ordered):
            if i == self.my_seat:
                return rank
        return -1

    def is_first_turn_wind_limit_possible(self) -> Tuple[bool, Optional[str]]:
        for seat_melds in self.melds:
            if seat_melds:
                return False, None
        active_seats = []
        for seat in range(4):
            if len(self.river[seat]) == 1:
                active_seats.append(seat)
            elif len(self.river[seat]) != 0:
                return False, None
        if len(active_seats) != 3:
            return False, None
        wind_tile = None
        for seat in active_seats:
            river_tile = self.river[seat][0]
            tid = tile_to_id(river_tile)
            if not (27 <= tid <= 30):
                return False, None
            if wind_tile is None:
                wind_tile = river_tile
            elif river_tile != wind_tile:
                return False, None
        if wind_tile not in self.my_hand:
            return False, None
        return True, wind_tile

    def is_last_round(self) -> bool:
        return self.ju == 3 or (self.ju == 2 and self.is_oya())

    def summary(self) -> Dict:
        return {
            'chang': self.chang,
            'ju': self.ju,
            'my_seat': self.my_seat,
            'hand': list(self.my_hand),
            'melds': [m.tiles for m in self.my_melds],
            'river': [list(r) for r in self.river],
            'river_moqie': [list(r) for r in self.river_moqie],
            'scores': list(self.scores),
            'doras': list(self.doras),
            'tsumo_count': self.tsumo_count,
            'reach_states': [rs.is_reach for rs in self.reach_states],
        }
