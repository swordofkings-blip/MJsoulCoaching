# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import List, Optional, Tuple

from game_state import GameState
from str_converter import (
    HONOR_IDS,
    TERMINAL_IDS,
    hand_to_counts,
    id_to_tile,
    is_honor,
    is_red_five,
    is_terminal,
    tile_to_id,
    suji_safe_tiles,
)
from strategy_manager import ShantenCalculator, StrategyManager
from hand_value import SANGEN


SCORE_GENBUTSU = 1000
SCORE_SUJI = 500
SCORE_WALL_SUJI = 800
SCORE_KABE_EDGE = 750
SCORE_NO_CHANCE = 700
SCORE_ONE_CHANCE = 200
SCORE_HONOR = 300
SCORE_MUSUJI_BASE = 0
SCORE_MUSUJI_PER_REACH = -200
SCORE_ATAMAKAKE_BONUS = 200
MATAGI_PENALTY = 100


# 形テン（形式テンパイ）ボーナス: 終盤に和了形に一歩でも近づける打牌を評価する
# 巡目別加算値。18巡目以降はボーナス倍率を上げ、流局間際の押し返しを強調する設計。
KEITEN_BONUS_15_17 = 1500
KEITEN_BONUS_18 = 3000


class MeldSealTracker:
    """配牌時点の役進行度と初期向聴数から「副露封印モード」を判定"""

    _CLOSED_YAKU = {'pinfu', 'chiitoitsu', 'ryanpeikou', 'sanshoku', 'ittsuu'}
    _OPEN_YAKU = {'yakuhai', 'toitoi', 'honitsu', 'chinitsu', 'tanyao'}

    def __init__(self):
        self._sealed: bool | None = None

    def evaluate(self, hand, melds, seat, chang, ju) -> bool:
        # トイトイ移行条件（対子4以上 + 役牌/ドラ対子）を最優先で動的チェック
        # キャッシュより先に判定し、条件成立時は常に封印解除
        counts = hand_to_counts(hand)
        n_pairs = sum(1 for c in counts if c >= 2)
        if n_pairs >= 4:
            has_valuable_pair = False
            for tid in range(34):
                if counts[tid] >= 2:
                    if tid in SANGEN:
                        has_valuable_pair = True
                        break
                    seat_wind = 27 + ((seat - ju) % 4)
                    round_wind = 27 + (chang % 4)
                    if tid == seat_wind or tid == round_wind:
                        has_valuable_pair = True
                        break
            if not has_valuable_pair and counts[31] >= 2:
                has_valuable_pair = True
            if not has_valuable_pair and counts[32] >= 2:
                has_valuable_pair = True
            if not has_valuable_pair and counts[33] >= 2:
                has_valuable_pair = True
            if has_valuable_pair:
                self._sealed = False
                return False
        if self._sealed is not None:
            return self._sealed
        # 初期向聴が4以上 = 手が極端に悪い → 門前維持（来るべき手を待つ）
        from strategy_manager import ShantenCalculator
        initial_shanten = ShantenCalculator.calculate_closed(counts)
        if initial_shanten >= 4:
            self._sealed = True
            return True
        try:
            from yaku_detector import analyze_all
            yi = analyze_all(hand, melds, seat=seat, chang=chang, ju=ju)
            closed_w = sum(y.progress * y.closed_han for n, y in yi.items() if n in self._CLOSED_YAKU)
            open_w = sum(y.progress * y.closed_han for n, y in yi.items() if n in self._OPEN_YAKU)
            self._sealed = closed_w >= open_w and closed_w > 0
        except Exception:
            self._sealed = False
        return self._sealed


class DefenseEvaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        self.evaluator = None

    def _player_stats_for_seat(self, seat: int) -> dict:
        if not self.state.player_stats:
            return {}
        key = str(seat)
        return self.state.player_stats.get(key, {})

    def record_detail(self, tile: str, msg: str):
        if self.evaluator:
            self.evaluator.record_detail(tile, msg)

    def genbutsu_tiles(self) -> List[int]:
        genbutsu = set()
        for i in range(4):
            for t in self.state.river[i]:
                genbutsu.add(tile_to_id(t))
            for m in self.state.melds[i]:
                for t in m.tiles:
                    genbutsu.add(tile_to_id(t))
        if self.state.last_discard_seat >= 0 and self.state.last_discard_seat == self.state.my_seat:
            for i in range(4):
                if i == self.state.my_seat:
                    continue
                for rs_i, rs in enumerate(self.state.reach_states):
                    pass
        return list(genbutsu)

    def same_turn_furiten_tiles(self) -> List[int]:
        return []

    def is_suji_tile(self, my_seat: int, opponent_seat: int, tile_id: int) -> bool:
        return False

    def is_genbutsu(self, tile_id: int) -> bool:
        for i in range(4):
            for t in self.state.river[i]:
                if tile_to_id(t) == tile_id:
                    return True
        return False

    def is_suji_for_opponent(self, tile_id: int, opponent_seat: int) -> bool:
        if is_honor(tile_id):
            return False
        for t in self.state.river[opponent_seat]:
            try:
                if tile_to_id(t) == tile_id:
                    return True
            except Exception:
                continue
        return False

    def is_atamakake(self, tile_id: int) -> bool:
        return False

    def _consecutive_tsumogiri_count(self, seat: int) -> int:
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        count = 0
        for m in reversed(moqie):
            if m:
                count += 1
            else:
                break
        return count

    def _tsumogiri_rate_for_seat(self, seat: int, lookback: int = 5) -> float:
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        if not moqie:
            return 0.5
        recent = moqie[-lookback:]
        if not recent:
            return 0.5
        return sum(recent) / len(recent)

    def _broke_tsumogiri_streak(self, seat: int) -> bool:
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        if len(moqie) < 3:
            return False
        last = moqie[-1]
        if last:
            return False
        streak = 0
        for m in reversed(moqie[:-1]):
            if m:
                streak += 1
            else:
                break
        return streak >= 2

    def _damaten_tenpai_score(self, seat: int) -> float:
        moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
        pstats = self.state.player_stats.get(str(seat), {})
        damaten_rate = pstats.get("damaten_rate", self.params.get('OPPONENT_DEFAULT_DAMATEN_RATE', 0.15))
        from core.bayesian_tenpai import estimate_tenpai_prob
        bayesian_base = estimate_tenpai_prob(moqie, damaten_rate)
        consec = self._consecutive_tsumogiri_count(seat)
        boost = 0.0
        if consec >= 3:
            boost += 0.25
        elif consec >= 2:
            boost += 0.1
        if self._broke_tsumogiri_streak(seat):
            boost += 0.2
        if moqie and not moqie[-1]:
            from str_converter import is_honor, tile_to_id
            river = self.state.river[seat]
            if len(river) > 0:
                try:
                    if is_honor(tile_to_id(river[-1])):
                        boost += 0.15
                except:
                    pass
        return min(1.0, bayesian_base + boost)

    def _active_reach_seats(self) -> List[int]:
        """
        @title 立直者の seat リスト
        @description 現在リーチ宣言している他家（自分以外）の seat インデックス一覧を返す。
        @returns {List[int]} リーチ中他家の seat 番号リスト
        """
        return [i for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach]

    def _common_genbutsu_ids(self, reach_seats: List[int]) -> set:
        """
        @title 共通現物の算出
        @description 立直している他家全員の河に共通して現れている牌IDの集合（共通現物）を返す。
        @param {List[int]} reach_seats - 立直者の seat リスト
        @returns {set} 共通現物牌IDの集合
        """
        if not reach_seats:
            return set()
        common = None
        for seat in reach_seats:
            ids = set()
            for t in self.state.river[seat]:
                try:
                    ids.add(tile_to_id(t))
                except Exception:
                    continue
            for m in self.state.melds[seat]:
                for t in m.tiles:
                    try:
                        ids.add(tile_to_id(t))
                    except Exception:
                        continue
            common = ids if common is None else common & ids
            if not common:
                return set()
        return common or set()

    def _reach_suji_ids(self, reach_seats: List[int]) -> set:
        """
        @title リーチ者河からのスジ集合
        @description いずれかの立直者の河にある牌の現物スジ（suji_safe_tiles で導出される安全牌）の集合を返す。
        @param {List[int]} reach_seats - 立直者の seat リスト
        @returns {set} スジ牌IDの集合
        """
        result = set()
        for seat in reach_seats:
            for t in self.state.river[seat]:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid):
                    continue
                for s in suji_safe_tiles(tid):
                    result.add(s)
        return result

    def _visible_counts(self) -> List[int]:
        return self.state.all_visible_counts()

    def _wall_tile_ids(self) -> set:
        visible = self._visible_counts()
        return {i for i in range(27) if visible[i] >= 4}

    def _wall_suji_ids(self) -> set:
        walls = self._wall_tile_ids()
        result = set()
        for tid in walls:
            for s in suji_safe_tiles(tid):
                result.add(s)
        return result

    def _no_chance_ids(self) -> set:
        visible = self._visible_counts()
        return {i for i in range(34) if visible[i] >= 4}

    def _one_chance_ids(self) -> set:
        visible = self._visible_counts()
        return {i for i in range(34) if visible[i] == 3}

    def _matagi_danger_ids(self, reach_seats: List[int]) -> set:
        result = set()
        for seat in reach_seats:
            for t in self.state.river[seat]:
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid):
                    continue
                base = (tid // 9) * 9
                off = tid - base
                for delta in (-1, 1):
                    adj = off + delta
                    if 0 <= adj <= 8:
                        result.add(base + adj)
        return result

    def _kabe_edge_safe_ids(self) -> set:
        visible = self._visible_counts()
        result = set()
        for tid in range(27):
            if visible[tid] >= 4:
                off = tid % 9
                base = (tid // 9) * 9
                if off == 1:
                    result.add(base)
                elif off == 7:
                    result.add(base + 8)
        return result

    def _genbutsu_ids_for_seat(self, seat: int) -> set:
        """
        @title プレイヤーごとの現物牌IDリスト
        @description 指定された他家の現物（フリテン対象牌）のID集合を返す。
        @param {int} seat - 他家のseatインデックス
        @returns {set} 現物牌IDの集合
        """
        # なぜセットを用いるか：重複を排除し、他家現物判定のルックアップ（in 演算）を O(1) で高速化するためです。
        genbutsu = set()
        
        # 1. 河の現物
        for t in self.state.river[seat]:
            try:
                genbutsu.add(tile_to_id(t))
            except Exception:
                continue
                
        # 2. 副露（メルド）を構成する牌
        for m in self.state.melds[seat]:
            for t in m.tiles:
                try:
                    genbutsu.add(tile_to_id(t))
                except Exception:
                    continue
                    
        # 3. リーチ後通過牌（このプレイヤーがリーチ者の場合）
        # なぜこれを行うか：リーチ後に誰かが切って通った牌はフリテンにより安全となるため、現物として扱います。
        if self.state.reach_states[seat].is_reach:
            post_count = 0
            for m in reversed(self.state.river_moqie[seat]):
                if m:
                    post_count += 1
                else:
                    break
            if post_count > 0:
                for rseat in range(4):
                    if rseat == seat:
                        continue
                    river = self.state.river[rseat]
                    start = max(0, len(river) - post_count)
                    for i in range(start, len(river)):
                        try:
                            genbutsu.add(tile_to_id(river[i]))
                        except Exception:
                            continue
        return genbutsu

    def _tile_remaining_weights(self, opponent_seat: int) -> List[float]:
        """
        @title 待ちパターンの残余重み計算
        @description 指定された立直者に対し、全34種の牌が当たり牌となり得る待ちの形の残り重み合計を返す。
        @param {int} opponent_seat - 立直者のseatインデックス
        @returns {List[float]} 34種の牌ごとの残余重みリスト
        """
        # なぜ visible_counts と genbutsu を事前に取得するか：ループ内での再計算を防ぎ、カベとスジの論理判定を高速に行うためです。
        visible = self._visible_counts()
        genbutsu = self._genbutsu_ids_for_seat(opponent_seat)
        weights = [0.0] * 34

        for tile_id in range(34):
            # なぜ現物を 0.0 にするか：フリテンによりどの待ちパターンでも放銃し得ないことが確定しているからです。
            if tile_id in genbutsu:
                weights[tile_id] = 0.0
                continue

            is_h = is_honor(tile_id)
            
            # なぜこのようにするか：字牌は順子を作れないため、単騎(1.0)と双碰(2.0)のみを考慮します。
            # これらの重み（1.0, 2.0）は電脳麻将の最良パラメータ定義に従っています。
            if is_h:
                w_tanki = 1.0 if visible[tile_id] < 4 else 0.0
                w_shanpon = 2.0 if visible[tile_id] < 3 else 0.0
                weights[tile_id] = w_tanki + w_shanpon
                continue

            # 数牌のベースとオフセットの計算 (0=萬子, 9=筒子, 18=索子)
            base = (tile_id // 9) * 9
            offset = tile_id % 9

            # 数牌の単騎・双碰の重み（電脳麻将の定義に準拠）
            w_tanki = 1.0 if visible[tile_id] < 4 else 0.0
            w_shanpon = 2.0 if visible[tile_id] < 3 else 0.0

            w_kanchan = 0.0
            w_penchan = 0.0
            w_ryanmen = 0.0

            # --- 1・9牌の待ち (offset == 0 or 8) ---
            if offset == 0 or offset == 8:
                # なぜ辺張に 3.0 を与えるか：電脳麻将の待ち形別出現頻度の近似値に従うためです。
                # 1待ちなら2,3が必要、9待ちなら7,8が必要。
                req_tiles = (base + 1, base + 2) if offset == 0 else (base + 6, base + 7)
                if visible[req_tiles[0]] < 4 and visible[req_tiles[1]] < 4:
                    w_penchan = 3.0
                    
                # なぜ両面に 10.0 を与えるか：電脳麻将の標準両面重みに従うためです。
                # 1待ちなら2-3持ち(1-4待ち)、相方は4。9待ちなら7-8持ち(6-9待ち)、相方は6。
                partner = base + 3 if offset == 0 else base + 5
                if (visible[req_tiles[0]] < 4 and 
                    visible[req_tiles[1]] < 4 and 
                    partner not in genbutsu):
                    w_ryanmen = 10.0

            # --- 2・8牌の待ち (offset == 1 or 7) ---
            elif offset == 1 or offset == 7:
                # なぜ嵌張に 3.0 を与えるか：電脳麻将の統計的重みに従うためです。
                # 2待ちなら1,3が必要、8待ちなら7,9が必要。
                req_tiles = (base + 0, base + 2) if offset == 1 else (base + 6, base + 8)
                if visible[req_tiles[0]] < 4 and visible[req_tiles[1]] < 4:
                    w_kanchan = 3.0
                    
                # 2待ちなら3-4持ち(2-5待ち)、相方は5。8待ちなら5-6持ち(5-8待ち)、相方は5。
                req_ryan = (base + 2, base + 3) if offset == 1 else (base + 4, base + 5)
                partner = base + 4
                if (visible[req_ryan[0]] < 4 and 
                    visible[req_ryan[1]] < 4 and 
                    partner not in genbutsu):
                    w_ryanmen = 10.0

            # --- 3・7牌の待ち (offset == 2 or 6) ---
            elif offset == 2 or offset == 6:
                # 3待ちなら2,4が必要、7待ちなら6,8が必要。
                req_kan = (base + 1, base + 3) if offset == 2 else (base + 5, base + 7)
                if visible[req_kan[0]] < 4 and visible[req_kan[1]] < 4:
                    w_kanchan = 3.0
                    
                # 3待ちなら1-2持ち(3待ち)、7待ちなら8-9持ち(7待ち)。
                req_pen = (base + 0, base + 1) if offset == 2 else (base + 7, base + 8)
                if visible[req_pen[0]] < 4 and visible[req_pen[1]] < 4:
                    w_penchan = 3.0
                    
                # 3待ちなら4-5持ち(3-6待ち)、相方は6。7待ちなら5-6持ち(4-7待ち)、相方は4。
                req_ryan = (base + 3, base + 4) if offset == 2 else (base + 4, base + 5)
                partner = base + 5 if offset == 2 else base + 3
                if (visible[req_ryan[0]] < 4 and 
                    visible[req_ryan[1]] < 4 and 
                    partner not in genbutsu):
                    w_ryanmen = 10.0

            # --- 4・5・6牌の待ち (offset in (3, 4, 5)) ---
            else:
                # 嵌張待ち: X-1, X+1が必要。
                req_tiles = (tile_id - 1, tile_id + 1)
                if visible[req_tiles[0]] < 4 and visible[req_tiles[1]] < 4:
                    w_kanchan = 3.0
                    
                # なぜ 4,5,6 の両面は 20.0 (最大) か：上方向と下方向の2つの両面が存在し得るためです (10.0 × 2)。
                # 両面1 (下方向): 相方は X-3
                req_ryan1 = (tile_id - 2, tile_id - 1)
                partner1 = tile_id - 3
                w_ryan1 = 0.0
                if (visible[req_ryan1[0]] < 4 and 
                    visible[req_ryan1[1]] < 4 and 
                    partner1 not in genbutsu):
                    w_ryan1 = 10.0

                # 両面2 (上方向): 相方は X+3
                req_ryan2 = (tile_id + 1, tile_id + 2)
                partner2 = tile_id + 3
                w_ryan2 = 0.0
                if (visible[req_ryan2[0]] < 4 and 
                    visible[req_ryan2[1]] < 4 and 
                    partner2 not in genbutsu):
                    w_ryan2 = 10.0

                w_ryanmen = w_ryan1 + w_ryan2

            weights[tile_id] = w_tanki + w_shanpon + w_kanchan + w_penchan + w_ryanmen

        return weights

    def _calculate_denno_danger_for_seat(self, opponent_seat: int, tile_id: int) -> float:
        """
        @title リーチ者単体に対する電脳麻将危険度の算出
        @description 待ちの形ごとの残余重みから、該当牌の相対危険度(0.0〜1.0)を算出する。
        @param {int} opponent_seat - 立直者のseatインデックス
        @param {int} tile_id - 評価する牌のID
        @returns {float} 牌の相対危険度 (0.0〜1.0)
        """
        weights = self._tile_remaining_weights(opponent_seat)
        total_w = sum(weights)
        # なぜ 0.0 を返すか：すべての牌の待ち重みが0（あり得ない状況だが極限）の際にゼロ除算を防ぐためです。
        if total_w == 0.0:
            return 0.0
        return weights[tile_id] / total_w

    def defense_score_for_tile(self, tile: str) -> int:
        """
        @title 牌の総合防衛スコアの評価
        @description リーチ者がいる場合は電脳麻将危険度ベースで評価し、いない場合は既存のルールベースで安全度を評価する。
        @param {str} tile - 評価対象の牌記号（'1m', '5z'など）
        @returns {int} 防衛スコア（安全なほど高い点数、最大1000）
        """
        tile_id = tile_to_id(tile)
        reach_seats = self._active_reach_seats()
        n_reach = len(reach_seats)
        use_p1 = self.params.get('USE_PHASE1_DEFENSE', True)

        # リーチ者がいなくても基本的な安全度を評価
        if not reach_seats:
            # 字牌の見え枚数で安全判定
            if is_honor(tile_id):
                visible = self.state.all_visible_counts()
                my_counts = self.state.my_hand_counts()
                total_count = visible[tile_id]
                public_count = total_count - my_counts[tile_id]
                # なぜこのようにするか：自分が3枚や4枚持っている場合も残数は1枚以下になり、他家はトイツを作れずシャボ待ちが否定されるため安全だからです。
                # また、河に2枚見えている場合も他家はトイツを持てないのでシャボが否定されます。
                if total_count >= 3 or public_count >= 2:
                    score = self.params.get('SCORE_HONOR', SCORE_HONOR)
                    self.record_detail(tile, f"字牌安牌判定 (全体{total_count}/公開{public_count}) (+{score})")
                    return score
                return 0
            # 現物（誰かの河にある牌）は基本安全
            for s in range(4):
                if s == self.state.my_seat:
                    continue
                for t in self.state.river[s]:
                    if tile_to_id(t) == tile_id:
                        score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU) // 2
                        self.record_detail(tile, f"現物安全 (+{score})")
                        return score

            # 非リーチ他家脅威による危険ペナルティ（巡目ではなく脅威度で判定）
            if self.evaluator and self.evaluator.strategy:
                max_threat = self.evaluator.strategy.compute_opponent_threat()
                if max_threat >= 0.10:
                    threat_penalty = int(-400 * max_threat)
                    meld_score_adjust = threat_penalty
                    self.record_detail(tile, f"非リーチ他家脅威による危険ペナルティ ({threat_penalty})")
                else:
                    meld_score_adjust = 0
            else:
                meld_score_adjust = 0

            # --- 人読み: 他家鳴き時の打点/危険度見積もり補正 ---
            for s in range(4):
                if s == self.state.my_seat:
                    continue
                open_melds = [m for m in self.state.melds[s] if m.is_open]
                if not open_melds:
                    continue
                pstats = self._player_stats_for_seat(s)
                call_rate = pstats.get("call_rate", self.params.get('OPPONENT_DEFAULT_CALL_RATE', 0.33))
                win_rate = pstats.get("win_rate", self.params.get('OPPONENT_DEFAULT_WIN_RATE', 0.22))
                if call_rate > 0.40 and win_rate > 0.22:
                    # 高副露+高和了 = 安手早仕掛け 危険度0.75倍（守備点を上げる）
                    meld_score_adjust += 5
                    self.record_detail(tile, f"人読み: S{s}安手早仕掛け傾向のためリスク軽減 (+5)")
                elif call_rate <= 0.25:
                    # 低副露 = 勝負手 危険度1.5倍（守備点を下げる）
                    meld_score_adjust -= 30
                    self.record_detail(tile, f"人読み: S{s}低副露勝負手のためリスク増大 (-30)")

            # --- ダマテン警戒: 牌単体の危険度をデンノー軽量版で評価 ---
            for s in range(4):
                if s == self.state.my_seat:
                    continue
                if self.state.reach_states[s].is_reach:
                    continue
                pstats = self._player_stats_for_seat(s)
                damaten_rate = pstats.get("damaten_rate", self.params.get('OPPONENT_DEFAULT_DAMATEN_RATE', 0.15))
                tenpai_score = self._damaten_tenpai_score(s)
                combined = damaten_rate * tenpai_score
                if combined < 0.05:
                    continue
                # この対局者にとっての現物なら安全
                if tile_id in self._genbutsu_ids_for_seat(s):
                    continue
                # カベ・ノーチャンスで安全
                if tile_id in self._no_chance_ids() and not is_honor(tile_id):
                    continue
                # スジ安全
                is_musuji = True
                river = self.state.river[s]
                for rt in river:
                    try:
                        rtid = tile_to_id(rt)
                    except:
                        continue
                    if is_honor(rtid):
                        continue
                    for st in suji_safe_tiles(rtid):
                        if st == tile_id:
                            is_musuji = False
                            break
                    if not is_musuji:
                        break
                danger_mult = 1.0
                if is_musuji:
                    danger_mult = 1.3
                base_penalty = self.params.get('DAMATEN_BASE_PENALTY', 200)
                penalty = int(base_penalty * combined * danger_mult)
                meld_score_adjust -= penalty
                self.record_detail(tile, f"ダマ{s}危険度(dr:{damaten_rate:.2f}*ts:{tenpai_score:.2f}={combined:.2f}) penalty={penalty}")
            matagi = self._matagi_penalty_for_tile(tile_id)
            if matagi > 0:
                meld_score_adjust -= matagi
                self.record_detail(tile, f"またぎスジ危険 (-{matagi})")
            impact = self._early_discard_safety_impact(tile_id)
            if impact > 0:
                meld_score_adjust += impact
                self.record_detail(tile, f"序盤の利安全 (+{impact})")
            elif impact < 0:
                meld_score_adjust += impact
                self.record_detail(tile, f"中盤手出し危険 ({impact})")
            return meld_score_adjust

        # ============================================================
        # リーチ者がいる場合（電脳麻将危険度評価モデルの適用）
        # ============================================================
        
        # 1. 共通現物の早期リターン判定
        common_genbutsu = self._common_genbutsu_ids(reach_seats)
        if tile_id in common_genbutsu:
            score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
            self.record_detail(tile, f"他家共通現物 (+{score})")
            return score

        # 2. 個別現物（単独リーチ時）の早期リターン判定
        if n_reach == 1:
            for seat in reach_seats:
                if tile_id in self._genbutsu_ids_for_seat(seat):
                    score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
                    self.record_detail(tile, f"リーチ者個別現物 (S{seat}) (+{score})")
                    return score

        # 3. リーチ後通過牌（他家立直時）の早期リターン判定
        # なぜ行うか：複数リーチ時でも、立直後に誰かが切って通った牌はフリテンにより完全にロンされないためです。
        for seat in reach_seats:
            post_count = 0
            for m in reversed(self.state.river_moqie[seat]):
                if m:
                    post_count += 1
                else:
                    break
            if post_count <= 0:
                continue
            for rseat in range(4):
                if rseat == seat:
                    continue
                river = self.state.river[rseat]
                start = max(0, len(river) - post_count)
                for i in range(start, len(river)):
                    try:
                        if tile_to_id(river[i]) == tile_id:
                            score = self.params.get('SCORE_GENBUTSU', SCORE_GENBUTSU)
                            self.record_detail(tile, f"リーチ後通過牌 (S{rseat}→S{seat}) (+{score})")
                            return score
                    except Exception:
                        continue

        # 4. 電脳麻将危険度モデルに基づく安全度の計算
        # なぜ max から sum に変更するか：複数他家がリーチしている場合、片方に現物でも他方に無筋であれば放銃リスクがあるため、
        # 全員への危険度を足し合わせた累積放銃リスク（放銃期待値の近似）として評価すべきだからです。
        danger = sum(self._calculate_denno_danger_for_seat(seat, tile_id) for seat in reach_seats)
        
        # なぜこのようにマッピングするか：危険度を適切にスケール倍して減算することで、無筋(0付近)とスジ(700付近)のメリハリをつけるためです。
        # 15000 は GAで調整されたデンノー危険度スケールの既定値です。
        base_score = int(SCORE_GENBUTSU - danger * self.params.get('DENNO_DANGER_SCALE', 15000))
        self.record_detail(tile, f"電脳麻将モデル累積危険度 D={danger:.4f} (ベース安全度: {base_score})")

        # 5. 既存の統計外の戦術的ノイズ（ペナルティ）を重ね合わせる
        score = base_score

        if use_p1:
            # またぎスジ危険ペナルティ
            matagi = self._matagi_penalty_for_tile(tile_id)
            if matagi > 0:
                score -= matagi
                self.record_detail(tile, f"またぎスジ危険 (-{matagi})")
                
            # リーチ宣言牌の前後隣接ペナルティ
            riichi_neighbor_ids = self._get_riichi_neighbor_ids(reach_seats)
            if tile_id in riichi_neighbor_ids:
                penalty = self.params.get('RIICHI_NEIGHBOR_PENALTY', 200)
                score -= penalty
                self.record_detail(tile, f"リーチ宣言牌隣接危険 (-{penalty})")
                
            # 裏スジ危険ペナルティ
            ura_suji = self._ura_suji_penalty_for_tile(tile_id)
            if ura_suji > 0:
                score -= ura_suji
                self.record_detail(tile, f"裏スジ危険 (-{ura_suji})")
                
            # 序盤・中盤の手出しによる安全度補正
            impact = self._early_discard_safety_impact(tile_id)
            if impact > 0:
                score += impact
                self.record_detail(tile, f"序盤の利安全 (+{impact})")
            elif impact < 0:
                score += impact
                self.record_detail(tile, f"中盤手出し危険 ({impact})")

        return score


    def _get_riichi_neighbor_ids(self, reach_seats: List[int]) -> set:
        result = set()
        for seat in reach_seats:
            river = self.state.river[seat]
            moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
            if len(river) < 2:
                continue
            post_riichi = 0
            for m in reversed(moqie):
                if m:
                    post_riichi += 1
                else:
                    break
            riichi_idx = len(river) - post_riichi - 1
            if riichi_idx < 0 or riichi_idx >= len(river):
                continue
            for idx in [riichi_idx, riichi_idx - 1]:
                if idx < 0:
                    continue
                tid = tile_to_id(river[idx])
                if tid >= 27:
                    continue
                off = tid % 9
                base = (tid // 9) * 9
                if off > 0:
                    result.add(base + off - 1)
                if off < 8:
                    result.add(base + off + 1)
        return result

    def _ura_suji_tiles(self, tile_id: int) -> List[int]:
        if is_honor(tile_id):
            return []
        base = (tile_id // 9) * 9
        off = tile_id - base
        result = []
        if off < 4:
            if off + 1 <= 8:
                result.append(base + off + 1)
            if off + 4 <= 8:
                result.append(base + off + 4)
        elif off > 4:
            if off - 4 >= 0:
                result.append(base + off - 4)
            if off - 1 >= 0:
                result.append(base + off - 1)
        else:
            result.append(base + 0)
            result.append(base + 3)
            result.append(base + 5)
            result.append(base + 8)
        return result

    def _ura_suji_penalty_for_tile(self, tile_id: int) -> int:
        params = self.params or {}
        penalty = params.get('URASUJI_PENALTY', 100)
        lookback = params.get('URASUJI_LOOKBACK_TURNS', 2)
        decay = params.get('URASUJI_LOOKBACK_DECAY', 0.7)
        total = 0
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            if not self.state.reach_states[seat].is_reach:
                continue
            river = self.state.river[seat]
            moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
            if not river:
                continue
            genbutsu_ids = set()
            for t in river:
                try:
                    genbutsu_ids.add(tile_to_id(t))
                except Exception:
                    continue
            for m in self.state.melds[seat]:
                for t in m.tiles:
                    try:
                        genbutsu_ids.add(tile_to_id(t))
                    except Exception:
                        continue
            if tile_id in genbutsu_ids:
                continue
            post_riichi = 0
            for m in reversed(moqie):
                if m:
                    post_riichi += 1
                else:
                    break
            riichi_idx = len(river) - post_riichi - 1
            if riichi_idx < 0:
                continue
            dist = 0
            for idx in range(riichi_idx - 1, -1, -1):
                if dist >= lookback:
                    break
                if not moqie[idx]:
                    turn = idx // 4 + 1
                    try:
                        tid = tile_to_id(river[idx])
                    except Exception:
                        dist += 1
                        continue
                    if is_honor(tid) or tid >= 27:
                        dist += 1
                        continue
                    off = tid % 9
                    if off < 2 or off > 6:
                        dist += 1
                        continue
                    if turn < 3 or turn > 9:
                        dist += 1
                        continue
                    if tile_id in self._ura_suji_tiles(tid):
                        p = penalty if dist == 0 else int(penalty * (decay ** dist))
                        total += p
                    dist += 1
        return total

    def _matagi_suji_tiles(self, tile_id: int) -> List[int]:
        if is_honor(tile_id) or tile_id >= 27:
            return []
        base = (tile_id // 9) * 9
        off = tile_id - base
        if off < 2 or off > 6:
            return []
        result = []
        for delta in (-2, -1, 1, 2):
            adj = off + delta
            if 0 <= adj <= 8:
                result.append(base + adj)
        return result

    def _matagi_penalty_for_tile(self, tile_id: int) -> int:
        params = self.params or {}
        m_penalty = params.get('MATAGI_PENALTY', 100)
        m_lookback = params.get('MATAGI_LOOKBACK_TURNS', 2)
        m_decay = params.get('MATAGI_LOOKBACK_DECAY', 0.7)
        total = 0
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            river = self.state.river[seat]
            moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
            if not river:
                continue
            genbutsu_ids = set()
            for t in river:
                try:
                    genbutsu_ids.add(tile_to_id(t))
                except Exception:
                    continue
            for m in self.state.melds[seat]:
                for t in m.tiles:
                    try:
                        genbutsu_ids.add(tile_to_id(t))
                    except Exception:
                        continue
            if tile_id in genbutsu_ids:
                continue
            is_reach = self.state.reach_states[seat].is_reach
            sources = []
            if is_reach:
                post_riichi = 0
                for m in reversed(moqie):
                    if m:
                        post_riichi += 1
                    else:
                        break
                riichi_idx = len(river) - post_riichi - 1
                if riichi_idx < 0:
                    continue
                sources.append((riichi_idx, 0))
                dist = 1
                for idx in range(riichi_idx - 1, -1, -1):
                    if dist > m_lookback:
                        break
                    if not moqie[idx]:
                        sources.append((idx, dist))
                        dist += 1
            else:
                local_turn = (self.state.tsumo_count - 1) // 4 + 1
                max_threat = 0.0
                if self.evaluator and self.evaluator.strategy:
                    max_threat = self.evaluator.strategy.compute_opponent_threat()
                if max_threat < 0.15 or local_turn < 10:
                    continue
                for idx in range(len(river) - 1, -1, -1):
                    if not moqie[idx]:
                        sources.append((idx, 0))
                        break
            for idx, dist in sources:
                turn = idx // 4 + 1
                if turn < 4:
                    continue
                try:
                    tid = tile_to_id(river[idx])
                except Exception:
                    continue
                if is_honor(tid) or tid >= 27:
                    continue
                off = tid % 9
                if off < 2 or off > 6:
                    continue
                if tile_id in self._matagi_suji_tiles(tid):
                    p = m_penalty if dist == 0 else int(m_penalty * (m_decay ** dist))
                    total += p
        return total

    def _early_discard_safe_tiles(self, tile_id: int) -> List[int]:
        if is_honor(tile_id) or tile_id >= 27:
            return []
        base = (tile_id // 9) * 9
        off = tile_id - base
        if off < 2 or off > 6:
            result = []
            for delta in (-1, 1):
                adj = off + delta
                if 0 <= adj <= 8:
                    result.append(base + adj)
            return result
        return self._matagi_suji_tiles(tile_id)

    def _early_discard_safety_impact(self, tile_id: int) -> int:
        # Why: 序盤の捨牌による安全度評価（序盤の利安全・中盤手出し危険）は、他家脅威度がHighとなる3つの戦略モード
        # （「危険度勝負」「回し打ち」「完全撤退」）のときのみ適用し、それ以外の押し・様子見モードでは手効率評価を歪めないようにします。
        if not self.evaluator or not self.evaluator.strategy:
            return 0
        mode = self.evaluator.strategy.get_strategy_mode()
        if mode not in ("危険度勝負", "回し打ち", "完全撤退"):
            return 0

        params = self.params or {}
        bonus_early = params.get('EARLY_DISCARD_SAFETY_BONUS', 300)
        bonus_mid = params.get('EARLY_DISCARD_SAFETY_BONUS_MID', 150)
        penalty_mid = params.get('EARLY_MID_HAND_DRAWN_PENALTY', 100)
        result = 0
        safety_applied = False
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            river = self.state.river[seat]
            moqie = self.state.river_moqie[seat] if seat < len(self.state.river_moqie) else []
            if not river:
                continue
            genbutsu = set()
            for t in river:
                try:
                    genbutsu.add(tile_to_id(t))
                except Exception:
                    continue
            for m in self.state.melds[seat]:
                for t in m.tiles:
                    try:
                        genbutsu.add(tile_to_id(t))
                    except Exception:
                        continue
            if tile_id in genbutsu:
                continue
            for idx, t in enumerate(river):
                if idx >= len(moqie):
                    break
                try:
                    tid = tile_to_id(t)
                except Exception:
                    continue
                if is_honor(tid) or tid >= 27:
                    continue
                if tile_id not in self._early_discard_safe_tiles(tid):
                    continue
                turn = idx // 4 + 1
                if turn <= 3:
                    if not safety_applied:
                        result += bonus_early
                        safety_applied = True
                elif turn <= 6:
                    is_hand = not moqie[idx]
                    if not is_hand:
                        if not safety_applied:
                            result += bonus_mid
                            safety_applied = True
                    else:
                        is_reach = self.state.reach_states[seat].is_reach
                        is_high_threat = False
                        if not is_reach and self.evaluator and self.evaluator.strategy:
                            lt = (self.state.tsumo_count - 1) // 4 + 1
                            mt = self.evaluator.strategy.compute_opponent_threat()
                            is_high_threat = mt >= 0.15 and lt >= 10
                        if not is_reach and not is_high_threat:
                            result -= penalty_mid
        return result

    def _collect_suji_from_river(self, seat: int) -> List[int]:
        result = set()
        for t in self.state.river[seat]:
            try:
                tid = tile_to_id(t)
            except Exception:
                continue
            if is_honor(tid):
                continue
            for s in suji_safe_tiles(tid):
                result.add(s)
        return list(result)


class AttackEvaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        self.evaluator = None

    def record_detail(self, tile: str, msg: str):
        if self.evaluator:
            self.evaluator.record_detail(tile, msg)

    def ukeire_for_discard(self, discard_tile: str) -> Tuple[int, int]:
        """
        @title 有効牌の計算
        @description 指定された牌を捨てた後の手牌に対して、シャンテン数を下げる有効牌の総枚数と種類数を計算する。
        @param discard_tile 捨てる牌の文字列 (例: "5m")
        @returns Tuple[int, int] (有効牌の総山残り枚数, 有効牌の種類数)
        """
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)

        # 切った後のシャンテン数を計算
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)

        visible = self.state.all_visible_counts()
        ukeire_total = 0
        unique_ukeire = 0

        for tile_id in range(34):
            if new_counts[tile_id] >= 4:
                continue

            # 1枚仮に加える
            temp_counts = list(new_counts)
            temp_counts[tile_id] += 1

            # 加えた後のシャンテン数を計算
            if open_meld_count == 0:
                next_shanten = ShantenCalculator.calculate_closed_effective(temp_counts)
            else:
                next_shanten = ShantenCalculator.calculate_open(temp_counts, open_meld_count)

            # シャンテン数が下がっていれば有効牌
            if next_shanten < current_shanten:
                # 山に残っている枚数を算出 (見えている枚数を4枚から引く)
                remaining = 4 - visible[tile_id]
                if remaining > 0:
                    ukeire_total += remaining
                    unique_ukeire += 1

        return ukeire_total, unique_ukeire

    def shanten_after_discard(self, discard_tile: str) -> int:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            return ShantenCalculator.calculate_open(new_counts, open_meld_count)

    def _standard_shanten_after(self, discard_tile: str) -> int:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(new_counts)
        return ShantenCalculator.calculate_open(new_counts, open_meld_count)

    def _best_standard_shanten(self) -> int:
        hand_counts = list(self.state.my_hand_counts())
        best = 8
        seen = set()
        for t in self.state.my_hand:
            tid = tile_to_id(t)
            if tid in seen or hand_counts[tid] <= 0:
                continue
            seen.add(tid)
            tmp = list(hand_counts)
            tmp[tid] -= 1
            open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
            if open_meld_count == 0:
                s = ShantenCalculator.calculate_closed_effective(tmp)
            else:
                s = ShantenCalculator.calculate_open(tmp, open_meld_count)
            if s < best:
                best = s
        return best

    def best_shanten_after_single_discard(self) -> int:
        """
        @title 最良シャンテン数の算出
        @description 14枚手牌から1枚を捨てた場合に達成可能な最小（最良）のシャンテン数を返す。手牌の牌種類数だけ評価し、最良値を採用する。
        @returns int 全候補打牌のうち最小のシャンテン数
        """
        hand_counts = list(self.state.my_hand_counts())
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        best = 8
        seen = set()
        for t in self.state.my_hand:
            tid = tile_to_id(t)
            if tid in seen or hand_counts[tid] <= 0:
                continue
            seen.add(tid)
            tmp = list(hand_counts)
            tmp[tid] -= 1
            if open_meld_count == 0:
                s = ShantenCalculator.calculate_closed_effective(tmp)
            else:
                s = ShantenCalculator.calculate_open(tmp, open_meld_count)
            if s < best:
                best = s
        return best

    def attack_score_for_tile(self, tile: str) -> int:
        mode = self.evaluator.strategy.get_strategy_mode() if (self.evaluator and self.evaluator.strategy) else None
        ukeire_total, _ = self.ukeire_for_discard(tile)
        shanten = self.shanten_after_discard(tile)
        SHANTEN_BACKTRACK_PENALTY = -self.params.get('PENALTY_SHANTEN_BACKWARD', 1000)
        std_shanten = self._standard_shanten_after(tile)
        # Why: シャンテン後退時に即時 return すると、ドラ切りや形状破壊などの他ペナルティがスキップされ、
        # 役なしテンパイ維持（超低スコア）よりも後退打牌が高評価される逆転バグを防ぐため、フラグ保持して最後に減算する
        is_backtrack = std_shanten > self._best_standard_shanten()

        USE_P2 = self.params.get('USE_PHASE2_ATTACK', True)
        if USE_P2:
            quality = self._ukeire_quality_mult(tile)
            effective_ukeire = int(ukeire_total * quality)
            score = effective_ukeire * self.params.get('UKEIRE_MULTIPLIER', 10)
            self.record_detail(tile, f"有効牌枚数・質評価 (+{score})")
            shanten_penalty = max(0, shanten) * self.params.get('SHANTEN_MULTIPLIER', 500)
            score -= shanten_penalty
            if shanten_penalty > 0:
                self.record_detail(tile, f"シャンテン数ペナルティ (-{shanten_penalty})")
            score += self._hand_value_bonus(tile)
            
            # --- 1〜2向聴DFS期待値 ---
            current_min_shanten = self.best_shanten_after_single_discard()
            if current_min_shanten <= 1:
                dfs_val = self._run_1shanten_dfs(tile)
                dfs_bonus = int(dfs_val * 8.0)
                if dfs_bonus > 0:
                    score += dfs_bonus
                    self.record_detail(tile, f"DFS期待値(向聴{current_min_shanten})ボーナス (+{dfs_bonus})")
        else:
            score = ukeire_total * 10 - shanten * 500
            self.record_detail(tile, f"手効率基本評価 (+{score})")
        if shanten <= 0:
            furiten_pen = self._compute_furiten_penalty(tile)
            if furiten_pen > 0:
                score -= furiten_pen
                self.record_detail(tile, f"フリテンペナルティ (-{furiten_pen})")
            if shanten <= 3:
                hand_counts = self.state.my_hand_counts()
                discard_id = tile_to_id(tile)
                after_counts = list(hand_counts)
                after_counts[discard_id] = max(0, after_counts[discard_id] - 1)
                open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
                blocks_before = ShantenCalculator.calculate_blocks(hand_counts, open_meld_count)
                # Why: 「全力攻撃」「押し気味」「積極駒組み」「危険度勝負」の攻撃系4モードのときは、
                # ブロックの受入れを広く受けるために6ブロックを維持することを許容し、ペナルティを課さないようにします。
                if blocks_before >= 6 and mode not in ("全力攻撃", "押し気味", "積極駒組み", "危険度勝負"):
                    is_isolated = (hand_counts[discard_id] == 1 and not is_honor(discard_id))
                    if is_isolated:
                        base = (discard_id // 9) * 9
                        off = discard_id - base
                        has_l = off > 0 and hand_counts[base + off - 1] > 0
                        has_r = off < 8 and hand_counts[base + off + 1] > 0
                        is_isolated = not has_l and not has_r
                    if not is_isolated:
                        blocks_after = ShantenCalculator.calculate_blocks(after_counts, open_meld_count)
                        if blocks_after >= 6:
                            penalty = self.params.get('PENALTY_6BLOCK_MAINTAIN', 80)
                            score -= penalty
                            self.record_detail(tile, f"6ブロック維持ペナルティ (-{penalty})")
            # テンパイかつ副露時の役なしチェック
            if open_meld_count > 0:
                has_yaku = False
                counts_after = list(hand_counts)
                counts_after[discard_id] = max(0, counts_after[discard_id] - 1)
                for tid in range(34):
                    if counts_after[tid] >= 4:
                        continue
                    temp = list(counts_after)
                    temp[tid] += 1
                    ns = ShantenCalculator._suit_shanten(temp, open_meld_count)
                    if ns < 0:
                        temp_hand = []
                        for i in range(34):
                            temp_hand.extend([id_to_tile(i)] * temp[i])
                        # Check tanyao (all 2-8, no terminals/honors)
                        all_tanyao = all(
                            not is_terminal(tile_to_id(t)) and not is_honor(tile_to_id(t))
                            for t in temp_hand
                        )
                        if all_tanyao:
                            # Also check melds for terminals/honors
                            for m in self.state.my_melds:
                                for mt in m.tiles:
                                    if is_terminal(tile_to_id(mt)) or is_honor(tile_to_id(mt)):
                                        all_tanyao = False
                                        break
                                if not all_tanyao:
                                    break
                        if all_tanyao:
                            has_yaku = True
                            break
                        # Check yakuhai in melds (dragon, seat wind, round wind)
                        yakuhai_ids = {31, 32, 33}
                        sw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.my_seat)
                        rw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.chang % 4)
                        if sw: yakuhai_ids.add(sw)
                        if rw: yakuhai_ids.add(rw)
                        for m in self.state.my_melds:
                            if getattr(m, 'is_open', True) and len(getattr(m, 'tiles', [])) >= 3:
                                mt = m.tiles[0]
                                mtid = tile_to_id(mt)
                                yakuhai_ids = {31, 32, 33}
                                sw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.my_seat)
                                rw = {0: 27, 1: 28, 2: 29, 3: 30}.get(self.state.chang % 4)
                                if sw: yakuhai_ids.add(sw)
                                if rw: yakuhai_ids.add(rw)
                                if mtid in yakuhai_ids:
                                    has_yaku = True  # yakuhai
                                    break
                if not has_yaku:
                    penalty = self.params.get('OPEN_TENPAI_NO_YAKU_PENALTY', 1500)
                    score -= penalty
                    self.record_detail(tile, f"役なしテンパイペナルティ (-{penalty})")

        # 通常手（面子手）の形状破壊ペナルティ: 七対子優先で全体シャンテンが変わらなくても
        # 通常手としてのシャンテンが後退する場合はペナルティ（即時returnはせず減算のみ）
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        best_std_shanten = 8
        for t in self.state.my_hand:
            tid = tile_to_id(t)
            tmp = list(hand_counts)
            tmp[tid] -= 1
            s = ShantenCalculator.calculate_standard(tmp)
            if s < best_std_shanten:
                best_std_shanten = s
        std_after = ShantenCalculator.calculate_standard(new_counts)
        if std_after > best_std_shanten:
            chiitoi_mode = self._is_chiitoi_toitoi_mode(hand_counts)
            if chiitoi_mode != 'none':
                self.record_detail(tile, f"七対子/トイトイ移行モード: 形状破壊ペナルティ免除")
            else:
                shape_pen = self.params.get('PENALTY_STANDARD_SHANTEN_BACKWARD', 350)
                score -= shape_pen
                self.record_detail(tile, f"通常手シャンテン後退（形状破壊）ペナルティ (-{shape_pen})")

        furiten_reserve, fr_reason = self._furiten_reserve_penalty(tile)
        if furiten_reserve > 0:
            score -= furiten_reserve
            self.record_detail(tile, fr_reason)
        if shanten >= self.params.get('BETAORI_PREP_SHANTEN', 4):
            score += self._betaori_prep_bonus(tile, shanten)

        # Why: シャンテン後退した打牌に対して、他のマイナス要素（ドラ切りなど）を正しく加味した上でペナルティを課すため、ここで減算する
        if is_backtrack:
            score += SHANTEN_BACKTRACK_PENALTY
            self.record_detail(tile, f"シャンテン後退ペナルティ ({SHANTEN_BACKTRACK_PENALTY})")

        # リャンメン維持・発展ボーナス: 切り出し後の手牌に残るリャンメン形状1つにつき加点
        after_counts = list(self.state.my_hand_counts())
        discard_id = tile_to_id(tile)
        after_counts[discard_id] = max(0, after_counts[discard_id] - 1)
        dora_ids = set(tile_to_id(d) for d in self.state.actual_doras)
        dora_ryanmen_bonus = 0
        for base in [0, 9, 18]:
            for i in range(7):
                if after_counts[base + i] >= 1 and after_counts[base + i + 1] >= 1:
                    wait_l = base + i - 1 if i > 0 else -1
                    wait_r = base + i + 2 if i < 7 else -1
                    if wait_l in dora_ids or wait_r in dora_ids:
                        dora_ryanmen_bonus += 1
        if dora_ryanmen_bonus > 0:
            dora_bonus = dora_ryanmen_bonus * self.params.get('DORA_RYANMEN_BONUS', 15)
            score += dora_bonus
            self.record_detail(tile, f"ドラ受けリャンメン維持ボーナス (+{dora_bonus})")

        # ブロック競合ペナルティ: 切り出し後、リャンメンとカンチャンが同じ待ち牌を奪い合う場合は減点
        ryanmen_waits = set()
        kanchan_waits = set()
        for base in [0, 9, 18]:
            for i in range(7):
                if after_counts[base + i] >= 1 and after_counts[base + i + 1] >= 1:
                    wait_l = base + i - 1 if i > 0 else -1
                    wait_r = base + i + 2 if i < 7 else -1
                    if wait_l >= 0: ryanmen_waits.add(wait_l)
                    if wait_r >= 0: ryanmen_waits.add(wait_r)
            for i in range(9):
                if after_counts[base + i] >= 1 and i + 2 < 9 and after_counts[base + i + 2] >= 1 and after_counts[base + i + 1] == 0:
                    wait = base + i + 1
                    kanchan_waits.add(wait)
        overlapping = ryanmen_waits & kanchan_waits
        if overlapping:
            base_pen = self.params.get('BLOCK_COMPETITION_PENALTY', 10)
            comp_pen = 0
            for w in overlapping:
                mult = 2 if w in dora_ids else 1
                comp_pen += base_pen * mult
            score -= comp_pen
            self.record_detail(tile, f"ブロック競合ペナルティ (-{comp_pen})")

        return score

    def _betaori_prep_bonus(self, tile: str, shanten: int) -> int:
        # Why: 「全力攻撃」「押し気味」「積極駒組み」「危険度勝負」の攻撃系4モードのときは、手牌のスリム化（安牌抱え）を避けて手効率（最大受入れ）を追うため、ベタオリ準備ボーナスを適用しません。
        if self.evaluator and self.evaluator.strategy:
            mode = self.evaluator.strategy.get_strategy_mode()
            if mode in ("全力攻撃", "押し気味", "積極駒組み", "危険度勝負"):
                return 0

        turn = (self.state.tsumo_count - 1) // 4 + 1
        if not (5 <= turn <= 10):
            return 0
        if shanten < 3:
            return 0
        n_reach = sum(1 for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach)
        if n_reach > 0:
            return 0

        tid = tile_to_id(tile)
        counts = self.state.my_hand_counts()
        bonus = 0

        if is_honor(tid):
            visible = self.state.all_visible_counts()
            if visible[tid] < 4:
                return 0

        remaining = counts[tid]
        if remaining == 1 and not is_honor(tid):
            base = (tid // 9) * 9
            off = tid - base
            has_l = off > 0 and counts[base + off - 1] > 0
            has_r = off < 8 and counts[base + off + 1] > 0
            if not has_l and not has_r:
                suit_counts = [sum(counts[0:9]), sum(counts[9:18]), sum(counts[18:27])]
                my_idx = tid // 9 if tid < 27 else -1
                if my_idx >= 0:
                    my_suit = suit_counts[my_idx]
                    max_suit = max(suit_counts) if suit_counts else 0
                    if my_suit <= max_suit - 3:
                        bonus += self.params.get('BETAORI_SLIM_BONUS', 40)

        if remaining >= 2 and not is_honor(tid):
            base = (tid // 9) * 9
            off = tid - base
            has_adj = (off > 0 and counts[base + off - 1] > 0) or (off < 8 and counts[base + off + 1] > 0)
            if has_adj:
                return 0

        return bonus

    def _ukeire_quality_mult(self, tile: str) -> float:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        is_tenpai = current_shanten <= 0
        total = 0
        total_weighted = 0
        visible = self.state.all_visible_counts()
        for tid in range(34):
            if new_counts[tid] >= 4:
                continue
            test = list(new_counts)
            test[tid] += 1
            if open_meld_count == 0:
                current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
            else:
                current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
            is_tenpai = current_shanten <= 0
            total = 0
            total_weighted = 0
            visible = self.state.all_visible_counts()
            for tid in range(34):
                if new_counts[tid] >= 4:
                    continue
                test = list(new_counts)
                test[tid] += 1
                if open_meld_count == 0:
                    ns = ShantenCalculator.calculate_closed_effective(test)
                else:
                    ns = ShantenCalculator.calculate_open(test, open_meld_count)
                if ns >= current_shanten:
                    continue
                remaining = 4 - visible[tid]
                if remaining <= 0:
                    continue
                total += remaining
                
                # なぜこのようにウエイトをつけるか：受入れ牌の良形（両面など）と愚形（カンチャン/ペンチャン/単騎）で
                # その後のアガリやすさ・打点上昇期待度が異なるため、受入れ枚数に品質の重み付けを行います。
                # 1.0, 0.7, 0.5, 0.4, 0.2 は受入れ牌の品質および接続度合に応じた重み係数（パラメータ）です。
                if is_honor(tid):
                    weight = self.params.get('UKEIRE_QUAL_TANKI', 0.5)
                elif is_tenpai:
                    base = (tid // 9) * 9
                    off = tid - base
                    has_l = off > 0 and new_counts[base + off - 1] >= 1
                    has_r = off < 8 and new_counts[base + off + 1] >= 1
                    has_l2 = off >= 2 and new_counts[base + off - 2] >= 1
                    has_r2 = off <= 6 and new_counts[base + off + 2] >= 1
                    if has_l and has_r:
                        weight = self.params.get('UKEIRE_QUAL_RYANMEN', 1.0)
                    elif has_l2 and has_l:
                        weight = self.params.get('UKEIRE_QUAL_KANCHAN', 0.7)
                    elif has_r and has_r2:
                        weight = self.params.get('UKEIRE_QUAL_KANCHAN', 0.7)
                    elif off == 0 and has_r and has_r2:
                        weight = self.params.get('UKEIRE_QUAL_PENCHAN', 0.5)
                    elif off == 8 and has_l and has_l2:
                        weight = self.params.get('UKEIRE_QUAL_PENCHAN', 0.5)
                    else:
                        weight = self.params.get('UKEIRE_QUAL_TANKI', 0.5)
                else:
                    connect = 0
                    off = tid % 9
                    base = (tid // 9) * 9
                    if off > 0 and new_counts[base + off - 1] > 0:
                        connect += 1
                    if off < 8 and new_counts[base + off + 1] > 0:
                        connect += 1
                    if new_counts[tid] >= 2:
                        connect += 1
                    base_w = self.params.get('UKEIRE_QUAL_CONNECT_BASE', 0.4)
                    per = self.params.get('UKEIRE_QUAL_CONNECT_PER', 0.2)
                    weight = min(1.0, base_w + connect * per)
                    if connect == 1 and tid < 27:
                        if (off > 0 and new_counts[base + off - 1] > 0 and off >= 2):
                            weight = max(weight, 0.8)
                        elif (off < 8 and new_counts[base + off + 1] > 0 and off <= 6):
                            weight = max(weight, 0.8)
                total_weighted += remaining * weight
            if total == 0:
                return 0.0
            return total_weighted / total

    def _ukeire_quality_breakdown(self, tile: str) -> dict:
        """
        @title 受入れ牌品質内訳計算
        @description 指定された牌を切った後の受入れ牌を「良形」と「愚形」に分類して合計枚数を返します。
        @param {str} tile - 捨てる牌の文字列
        @returns {dict} 良形・愚形・総受入れ枚数の辞書
        """
        # なぜこのようにするか：打牌後の受入れの絶対枚数だけでなく、良形テンパイにつながる受入れ（両面など）と
        # 愚形テンパイにつながる受入れ（カンチャンなど）の内訳を算出し、手作りの質を詳細に評価するためです。
        # 34 は麻雀の全牌種類数、4 は山に残る各牌の最大枚数です。
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        is_tenpai = current_shanten <= 0
        n_good = 0
        n_bad = 0
        total = 0
        visible = self.state.all_visible_counts()
        for tid in range(34):
            if new_counts[tid] >= 4:
                continue
            test = list(new_counts)
            test[tid] += 1
            if open_meld_count == 0:
                ns = ShantenCalculator.calculate_closed_effective(test)
            else:
                ns = ShantenCalculator.calculate_open(test, open_meld_count)
            if ns >= current_shanten:
                continue
            remaining = 4 - visible[tid]
            if remaining <= 0:
                continue
            total += remaining
            if is_honor(tid):
                n_bad += remaining
            elif is_tenpai:
                off = tid % 9
                base = (tid // 9) * 9
                has_l = off > 0 and new_counts[base + off - 1] >= 1
                has_r = off < 8 and new_counts[base + off + 1] >= 1
                if has_l and has_r:
                    n_good += remaining
                else:
                    n_bad += remaining
            else:
                off = tid % 9
                base = (tid // 9) * 9
                has_l = off > 0 and new_counts[base + off - 1] > 0
                has_r = off < 8 and new_counts[base + off + 1] > 0
                if has_l and has_r:
                    n_good += remaining
                else:
                    n_bad += remaining
        return {'total': total, 'good': n_good, 'bad': n_bad}

    def _count_pairs(self, counts=None) -> int:
        """
        @title 対子数カウント
        @description 手牌（または指定された牌数リスト）における対子（同じ牌が2枚以上）の数をカウントします。
        @param {list} counts - 牌数リスト（None の場合は現在の手牌）
        @returns {int} 対子数
        """
        # なぜこのようにするか：七対子や対々和（トイトイ）の移行判断に必要な対子数を正確に把握するためです。
        # 2 は対子とみなす最小の重複枚数です。
        if counts is None:
            counts = self.state.my_hand_counts()
        return sum(1 for c in counts if c >= 2)

    def _is_chiitoi_toitoi_mode(self, counts=None) -> str:
        """
        @title 七対子/対々和移行モード判定
        @description 現在の手牌が七対子（チートイ）または対々和（トイトイ）の進行に適しているか判定します。
        @param {list} counts - 牌数リスト（None の場合は現在の手牌）
        @returns {str} 'chiitoi'、'toitoi'、または 'none'
        """
        # なぜこのようにするか：対子が多く（閾値以上）、通常の順子手（標準シャンテン）の進行が遅い場合に、
        # 特殊な対子手（七対子）や鳴き対子手（対々和）へシフトするべきかを判断するためです。
        # 4 は対子手移行を考慮する最小対子数の閾値、3 は移行を許容する標準手の最低シャンテン数です。
        if counts is None:
            counts = self.state.my_hand_counts()
        n_pairs = sum(1 for c in counts if c >= 2)
        if n_pairs < self.params.get('CHIITOI_PAIRS_THRESHOLD', 4):
            return 'none'
        has_valuable_pair = False
        for tid in range(34):
            if counts[tid] >= 2:
                if tid in SANGEN:
                    has_valuable_pair = True
                    break
                seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
                round_wind = 27 + (self.state.chang % 4)
                if tid == seat_wind or tid == round_wind:
                    has_valuable_pair = True
                    break
        if not has_valuable_pair:
            for d in self.state.actual_doras:
                if counts[tile_to_id(d)] >= 2:
                    has_valuable_pair = True
                    break
        if has_valuable_pair:
            return 'toitoi'
        shanten = self.state.tsumo_count  # approximate
        from strategy_manager import ShantenCalculator
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        std_shanten = ShantenCalculator.calculate_standard(counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(counts, open_meld_count)
        if std_shanten >= self.params.get('CHIITOI_MODE_SHANTEN_LIMIT', 3):
            if open_meld_count == 0 and self._has_ryanmen_taatsu(counts):
                return 'none'
            return 'chiitoi'
        return 'none'

    def _has_ryanmen_taatsu(self, counts) -> bool:
        """
        @title 両面塔子存在判定
        @description 手牌の中に両面待ちとなる塔子（隣り合う2枚の数牌。ただし端牌を除く）が存在するか判定します。
        @param {list} counts - 牌数リスト
        @returns {bool} 存在する場合は True
        """
        # なぜこのようにするか：七対子への移行判断時、両面塔子（将来 of 良形待ち）が手牌にある場合は、
        # 通常のメンツ手（順子手）を優先した方がアガリやすいため、七対子移行を抑制するために使用します。
        # 0, 9, 18 は萬子・筒子・索子の開始ID、7 は1〜7の範囲で隣り合う牌を調べるためのループ上限です。
        for base in [0, 9, 18]:
            for i in range(7):
                if counts[base + i] >= 1 and counts[base + i + 1] >= 1:
                    return True
        return False

    def _run_1shanten_dfs(self, discard_tile: str) -> float:
        """
        @title 1〜2向聴DFS期待値計算
        @description 指定された牌を切った後の「テンパイ時の待ちの広さ・期待飜数」をシミュレーションします。
                    1向聴局面（切ってテンパイ）と2向聴維持（切って1向聴）の両方に対応。
        @param {str} discard_tile - 切る牌の文字列
        @returns {float} 期待値スコア（期待飜数ベースの擬似スコア）
        """
        # なぜこのようにするか：1向聴の局面はアガリへの最終段階であり、即時テンパイ（両面/愚形）をとるべきか、
        # あるいは1向聴を維持して手役や良形テンパイへの変化を待つべきかの判断ミスを完全に防ぐため、
        # 次のツモによる期待値（和了期待値・テンパイ期待値）を全探索で算出するからです。
        # また、得点ではなく「期待飜数（Han）」を用いることで、評価値の異常なインフレを防ぎ、
        # 手効率と安全度・形状維持ペナルティのバランスを最適に保ちます。
        # 34 は麻雀の全牌種類数、4 は山に残る各牌の最大枚数です。
        
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        is_closed = (open_meld_count == 0)
        visible = self.state.all_visible_counts()
        
        # 切った後のシャンテン数
        shanten_after = ShantenCalculator.calculate_closed_effective(new_counts) if is_closed else ShantenCalculator.calculate_open(new_counts, open_meld_count)
        
        from hand_value import estimate_han_advanced
        wind_idx = (self.state.my_seat - self.state.ju) % 4

        # テンパイ時の期待値計算（切った時点でテンパイになる場合）
        if shanten_after == 0:
            total_ev = 0.0
            # 待ち牌（和了牌）を探索
            for tile_id in range(34):
                if new_counts[tile_id] >= 4:
                    continue
                temp_counts = list(new_counts)
                temp_counts[tile_id] += 1
                
                # アガれるか判定
                ns = ShantenCalculator.calculate_closed_effective(temp_counts) if is_closed else ShantenCalculator.calculate_open(temp_counts, open_meld_count)
                if ns < 0:
                    remaining = 4 - visible[tile_id]
                    if remaining <= 0:
                        continue
                    
                    # この和了牌を引いたときの手牌を構築
                    temp_hand = []
                    for i in range(34):
                        temp_hand.extend([id_to_tile(i)] * temp_counts[i])
                    
                    # 和了時の期待飜数（ツモアガリかつリーチ想定）
                    han = estimate_han_advanced(
                        temp_hand, self.state.my_melds, self.state.doras,
                        is_open=not is_closed, has_reach=is_closed, is_ippatsu=False,
                        is_tsumo=True, seat=wind_idx, chang=self.state.chang, ju=self.state.ju
                    )
                    
                    # 副露時は役がないと和了できないため、0飜ならスキップ
                    if not is_closed and han == 0:
                        continue
                    
                    # 和了確率（残り枚数）× 飜数期待値（最低1飜を保証）
                    # 両面待ちの場合は、アガりやすさが劇的に上がるため、和了率にボーナス（1.5倍）を掛ける
                    # 1.5 は両面待ちのアガりやすさ補正係数です。
                    is_ryanmen = False
                    if tile_id < 27:
                        base = (tile_id // 9) * 9
                        off = tile_id - base
                        has_l = off > 0 and new_counts[base + off - 1] >= 1
                        has_r = off < 8 and new_counts[base + off + 1] >= 1
                        is_ryanmen = has_l and has_r
                    
                    mult = 1.5 if is_ryanmen else 1.0
                    total_ev += remaining * max(1, han) * mult
            return total_ev

        # 1向聴維持時の期待値計算（切った後も1向聴のままの場合）
        elif shanten_after == 1:
            total_ev = 0.0
            # 次にツモる牌をループ（テンパイする牌を探す）
            for draw_id in range(34):
                if new_counts[draw_id] >= 4:
                    continue
                temp_counts = list(new_counts)
                temp_counts[draw_id] += 1
                
                ns = ShantenCalculator.calculate_closed_effective(temp_counts) if is_closed else ShantenCalculator.calculate_open(temp_counts, open_meld_count)
                if ns == 0:
                    # テンパイになるツモ牌
                    remaining = 4 - visible[draw_id]
                    if remaining <= 0:
                        continue
                    
                    # テンパイした手牌から、次に何を切れば最も強いテンパイになるかの最大値を計算
                    best_temp_ev = 0.0
                    for disc_id2 in range(34):
                        if temp_counts[disc_id2] <= 0:
                            continue
                        # テンパイ後の手牌
                        counts_tenpai = list(temp_counts)
                        counts_tenpai[disc_id2] -= 1
                        
                        # そのテンパイの待ちの広さと打点を評価
                        temp_ev = 0.0
                        for wait_id in range(34):
                            if counts_tenpai[wait_id] >= 4:
                                continue
                            counts_agari = list(counts_tenpai)
                            counts_agari[wait_id] += 1
                            ns2 = ShantenCalculator.calculate_closed_effective(counts_agari) if is_closed else ShantenCalculator.calculate_open(counts_agari, open_meld_count)
                            if ns2 < 0:
                                rem_wait = 4 - visible[wait_id]
                                if rem_wait <= 0:
                                    continue
                                
                                # 和了手牌構築
                                hand_agari = []
                                for i in range(34):
                                    hand_agari.extend([id_to_tile(i)] * counts_agari[i])
                                    
                                han = estimate_han_advanced(
                                    hand_agari, self.state.my_melds, self.state.doras,
                                    is_open=not is_closed, has_reach=is_closed, is_ippatsu=False,
                                    is_tsumo=True, seat=wind_idx, chang=self.state.chang, ju=self.state.ju
                                )
                                if not is_closed and han == 0:
                                    continue
                                    
                                is_ryanmen = False
                                if wait_id < 27:
                                    base = (wait_id // 9) * 9
                                    off = wait_id - base
                                    has_l = off > 0 and counts_tenpai[base + off - 1] >= 1
                                    has_r = off < 8 and counts_tenpai[base + off + 1] >= 1
                                    is_ryanmen = has_l and has_r
                                
                                mult = 1.5 if is_ryanmen else 1.0
                                temp_ev += rem_wait * max(1, han) * mult
                        if temp_ev > best_temp_ev:
                            best_temp_ev = temp_ev
                            
                    # ツモ確率（残り枚数）× そのテンパイの最大期待値
                    # 0.02 は「1巡先（ツモが1回遅れる）」ことによる速度遅延および他家リーチリスクの減衰率です（山全体の総数による除算の近似値）。
                    # 期待飜数のスケールに合わせるための値です。
                    total_ev += remaining * best_temp_ev * 0.02
            return total_ev
            
        return 0.0

    def _hand_value_bonus(self, tile: str) -> int:
        """
        @title 手牌評価の補正値（ボーナス/ペナルティ）計算
        @description 孤立牌の状況、字牌の安全度、染め手への移行状況、および進行度（シャンテン・ブロック数）に応じて打牌評価にボーナスを加減算する。
        @param {str} tile - 捨てる牌の文字列
        @returns {int} 補正スコア
        """
        from hand_value import estimate_hand_value
        hand = list(self.state.my_hand)
        melds = self.state.my_melds
        discard_id = tile_to_id(tile)
        after_hand = [t for t in hand if tile_to_id(t) != discard_id or hand.count(t) > 1]
        if tile in after_hand:
            after_hand.remove(tile)
        open_meld_count = sum(1 for m in melds if m.is_open)
        has_reach = any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat)
        wind_idx = (self.state.my_seat - self.state.ju) % 4
        is_dealer = wind_idx == 0
        score = estimate_hand_value(after_hand, melds, self.state.actual_doras,
                                     is_open=open_meld_count > 0,
                                     has_reach=has_reach, is_ippatsu=False,
                                     is_tsumo=False, is_dealer=is_dealer,
                                     seat=wind_idx, chang=self.state.chang,
                                     ju=self.state.ju)
        bonus = score // 10
        counts = self.state.my_hand_counts()
        shanten = ShantenCalculator.calculate_closed_effective(counts) if open_meld_count == 0 else ShantenCalculator.calculate_open(counts, open_meld_count)
        if bonus > 0:
            if shanten >= 3 and open_meld_count > 0:
                damp = max(0.1, 1.0 - (shanten - 2) * 0.35)
                bonus = int(bonus * damp)
            self.record_detail(tile, f"手役・打点評価ボーナス (+{bonus})")
        blocks = ShantenCalculator.calculate_blocks(counts, open_meld_count)
        turn = (self.state.tsumo_count - 1) // 4 + 1

        # ホンイツ・清一色への移行判断
        # Why: 染めバイアス（および染め手移行推進ボーナス）は、他家を気にせず攻める全力攻撃中の3種（「全力攻撃」「押し気味」「危険度勝負」）では適用しません。
        # 攻撃局面では純粋な手効率を優先し、元々染まっている場合は手役価値評価（estimate_hand_value）によって自然に選択されるためです。
        mode = self.evaluator.strategy.get_strategy_mode() if (self.evaluator and self.evaluator.strategy) else None
        if mode not in ("全力攻撃", "押し気味", "危険度勝負"):
            # 萬子、筒子、索子の枚数を数える（字牌を除く）
            all_ids = [tile_to_id(t) for t in hand]
            for m in melds:
                all_ids.extend(tile_to_id(t) for t in getattr(m, 'tiles', []))
            
            suit_counts = {'m': 0, 'p': 0, 's': 0}
            z_count = 0
            for tid in all_ids:
                if tid < 9: suit_counts['m'] += 1
                elif tid < 18: suit_counts['p'] += 1
                elif tid < 27: suit_counts['s'] += 1
                else: z_count += 1
            
            dominant_suit = max(suit_counts, key=suit_counts.get)
            dominant_count = suit_counts[dominant_suit]

            # 色バイアス: 主色の孤立中張牌を残す動機付け（控えめに）
            honitsu_cfg = self.params.get('yaku_strategy', {}).get('honitsu', {})
            if honitsu_cfg.get('enabled', True) and dominant_count >= honitsu_cfg.get('suit_threshold', 6):
                bonus_per = 20
                max_bonus = 200
                concentration_bonus = min((dominant_count - 5) * bonus_per, max_bonus)
                if concentration_bonus > 0:
                    bonus += concentration_bonus
                    self.record_detail(tile, f"染めバイアス (+{concentration_bonus})")
            
            # 染め手（主力色が7枚以上かつ、通常進行がまだ遅い2向聴以上の状況）
            is_dyeing = (dominant_count >= 7) and (shanten >= 2)
            if is_dyeing and not is_honor(discard_id):
                tile_suit = None
                if discard_id < 9: tile_suit = 'm'
                elif discard_id < 18: tile_suit = 'p'
                elif discard_id < 27: tile_suit = 's'
                
                # 染める色以外に既に完成面子(3連続)がある場合は染め手移行を抑制
                has_other_meld = False
                if tile_suit != dominant_suit:
                    for sb in [0, 9, 18]:
                        sn = ['m', 'p', 's'][sb // 9]
                        if sn == dominant_suit:
                            continue
                        for i in range(7):
                            if all(counts[sb + i + j] >= 1 for j in range(3)):
                                has_other_meld = True
                                break
                        if has_other_meld:
                            break
                
                # 染める色以外を捨てる際にボーナスを加算して移行を推進（赤5は除く）
                if tile_suit != dominant_suit and not has_other_meld and not is_red_five(tile):
                    dye_bonus = self.params.get('BETAORI_HONITSU_BONUS', 40)
                    bonus += dye_bonus
                    self.record_detail(tile, f"染め手移行推進ボーナス (+{dye_bonus})")

        # --- タンヤオ適合度（提案B） ---
        # なぜこのようにするか：手牌の大部分（11枚以上など）が中張牌（2〜8）で構成されている場合、
        # わずかに残ったヤオ九牌（1/9牌、オタ風等）を速やかに処理してタンヤオへ向かわせるためです。
        # 11 はタンヤオ適合とみなす中張牌の最小枚数、40 はタンヤオへ移行するための不要牌整理ボーナスです。
        all_ids = [tile_to_id(t) for t in hand]
        for m in melds:
            all_ids.extend(tile_to_id(t) for t in getattr(m, 'tiles', []))
        
        middle_count = sum(1 for tid in all_ids if tid < 27 and 1 <= (tid % 9) <= 7)
        is_tanyao_fit = (middle_count >= 11)
        if is_tanyao_fit and (shanten >= 2 or open_meld_count > 0):
            # 捨てる牌がヤオ九牌（1/9牌、またはオタ風や重なっていない字牌）の場合、整理ボーナス
            is_yq = is_terminal(discard_id) or is_honor(discard_id)
            if is_yq and not is_red_five(tile):
                # 役牌対子などの価値ある牌は保護するため、手牌に1枚（孤立）の場合のみ加点
                if counts[discard_id] == 1:
                    tanyao_bonus = self.params.get('TANYAO_FIT_DISCARD_BONUS', 40)
                    bonus += tanyao_bonus
                    self.record_detail(tile, f"タンヤオ適合ヤオ九牌整理ボーナス (+{tanyao_bonus})")

        # --- 平回適合度（提案B） ---
        # なぜこのようにするか：門前かつ対子が少なく（2対子以下）、リャンメンのタネが多い場合は平和の適合度が高いため、
        # 役牌や孤立字牌を早めに整理し、好形維持を優先させるためです。
        # 2 は平和適合とみなす最大対子数、30 は不要な役牌・客風を先に処理するための整理ボーナスです。
        n_pairs = sum(1 for c in counts if c >= 2)
        is_pinfu_fit = (open_meld_count == 0) and (n_pairs <= 2)
        if is_pinfu_fit and shanten >= 2:
            # 平和狙い時の孤立字牌整理の優先
            if is_honor(discard_id) and counts[discard_id] == 1:
                pinfu_honor_bonus = self.params.get('PINFU_FIT_HONOR_BONUS', 30)
                bonus += pinfu_honor_bonus
                self.record_detail(tile, f"平和適合孤立字牌整理ボーナス (+{pinfu_honor_bonus})")

        # 刻子・対子・順子構築に関する評価
        if counts[discard_id] == 2:
            if discard_id in SANGEN:
                penalty = self.params.get('YAKUHAI_PAIR_PENALTY', 30)
                bonus -= penalty
                self.record_detail(tile, f"三元牌対子キープペナルティ (-{penalty})")
            if discard_id in (27, 28, 29, 30):
                penalty = self.params.get('YAKUHAI_PAIR_PENALTY', 30)
                bonus -= penalty
                self.record_detail(tile, f"自風・場風対子キープペナルティ (-{penalty})")

        if not is_honor(discard_id):
            base = (discard_id // 9) * 9
            off = discard_id - base
            counts_after = hand_to_counts(after_hand)
            if off > 0 and counts_after[base + off - 1] >= 1:
                ryan_bonus = self.params.get('RYANMEN_KEEP_BONUS', 15)
                bonus += ryan_bonus
                self.record_detail(tile, f"両面変化維持ボーナス (+{ryan_bonus})")
            if off < 8 and counts_after[base + off + 1] >= 1:
                ryan_bonus = self.params.get('RYANMEN_KEEP_BONUS', 15)
                bonus += ryan_bonus
                self.record_detail(tile, f"両面変化維持ボーナス (+{ryan_bonus})")

            left = off > 0 and counts[base + off - 1] > 0
            right = off < 8 and counts[base + off + 1] > 0
            if left or right:
                penalty = self.params.get('SHAPE_BREAK_PENALTY', 20)
                bonus -= penalty
                self.record_detail(tile, f"搭子破壊ペナルティ (-{penalty})")

        if is_honor(discard_id):
            is_pair = counts[discard_id] >= 2
            is_dora = any(tile_to_id(d) == discard_id for d in self.state.actual_doras)
            if is_dora:
                penalty = self.params.get('DORA_DISCARD_PENALTY', 40)
                bonus -= penalty
                self.record_detail(tile, f"ドラ字牌放出ペナルティ (-{penalty})")
            
            # Why: 攻撃的な3モード（「全力攻撃」「積極駒組み」「押し気味」）のときは、手効率優先で孤立した不要字牌を速やかに切り飛ばすため、整理ペナルティを課さないようにします。
            is_aggressive_mode = mode in ("全力攻撃", "積極駒組み", "押し気味")

            visible_all = self.state.all_visible_counts()
            remaining = 4 - visible_all[discard_id]
            
            # 字牌の「他家役牌危険度・安全度」に応じた動的スケーリング
            # 場に見えている枚数が多いほど安全牌として保持したいため、捨てるボーナスを減衰させる
            vis_factor = 1.0 - (visible_all[discard_id] / 4.0)
            if shanten <= 2 and blocks >= 5:
                # 進行度が高く、十分なブロックがある場合は安全牌の抱えを優先（0.3は保持を強く動機付けるための定数）
                vis_factor *= 0.3

            base_penalty = self.params.get('HONOR_VALUE_PENALTY', 20)
            if discard_id in SANGEN:
                if is_pair and remaining >= 2:
                    bonus -= base_penalty
                    self.record_detail(tile, f"三元牌対子保持ペナルティ (-{base_penalty})")
                elif not is_pair and not is_aggressive_mode:
                    # なぜこのようにするか：3シャンテン以上（手が遠い）または5ブロック以上（十分なブロック数）のときは、
                    # 孤立役牌を重ねてブロックを作る価値よりも手効率を最優先すべきなため、整理ペナルティを除外します。
                    if shanten < 3 and blocks < 5:
                        sangen_mult = self.params.get('SANGEN_PENALTY_MULTIPLIER', 0.75)
                        val_penalty = int(base_penalty * sangen_mult * vis_factor)
                        bonus -= val_penalty
                        self.record_detail(tile, f"三元牌整理ペナルティ (-{val_penalty})")
            bakaze = 27 + (self.state.chang % 4)
            wind_idx = (self.state.my_seat - self.state.ju) % 4
            jikaze = 27 + wind_idx
            is_double_wind = (bakaze == jikaze) and (discard_id == bakaze)
            if discard_id == bakaze:
                if is_pair and remaining >= 2:
                    bonus -= base_penalty
                    self.record_detail(tile, f"場風対子保持ペナルティ (-{base_penalty})")
                elif is_double_wind:
                    if not is_pair and not is_aggressive_mode:
                        # 3シャンテン以上、または5ブロック以上の場合は不要なのでペナルティを除外します
                        if shanten < 3 and blocks < 5:
                            val_penalty = int(base_penalty * 1.5 * vis_factor)
                            bonus -= val_penalty
                            self.record_detail(tile, f"ダブ風切りペナルティ (-{val_penalty})")
                else:
                    if not is_pair and not is_aggressive_mode:
                        # 3シャンテン以上、または5ブロック以上の場合は不要なのでペナルティを除外します
                        if shanten < 3 and blocks < 5:
                            val_penalty = int(base_penalty * 0.5 * vis_factor)
                            bonus -= val_penalty
                            self.record_detail(tile, f"不要場風切りペナルティ (-{val_penalty})")
            if discard_id == jikaze:
                if not is_pair and not is_double_wind and not is_aggressive_mode:
                    # 3シャンテン以上、または5ブロック以上の場合は不要なのでペナルティを除外します
                    if shanten < 3 and blocks < 5:
                        val_penalty = int(base_penalty * 1.0 * vis_factor)
                        bonus -= val_penalty
                        self.record_detail(tile, f"不要自風切りペナルティ (-{val_penalty})")
            elif not is_pair and discard_id not in SANGEN and discard_id != bakaze:
                val_bonus = int(self.params.get('HONOR_DISCARD_BONUS', 20) * vis_factor)
                bonus += val_bonus
                self.record_detail(tile, f"不要客風整理ボーナス (+{val_bonus})")

            # 多対子手（4対子以上）では、役牌単騎でも切りやすくする
            if not is_pair:
                n_pairs = sum(1 for c in counts if c >= 2)
                if n_pairs >= self.params.get('CHITOI_PAIRS_THRESHOLD', 4):
                    pair_offset = self.params.get('PAIR_OVERFLOW_HONOR_OFFSET', 10)
                    bonus += pair_offset
                    self.record_detail(tile, f"多対子字牌整理オフセット (+{pair_offset})")

            ratio_base = self.params.get('VISIBLE_RATIO_HONOR', 80)
            is_keeping_safe = False
            if shanten <= 2 and blocks >= 5:
                # 安牌（見えている字牌）を残すため、捨てる際のボーナスをマイナス化（保持へ誘導）
                ratio_base = -ratio_base // 2
                is_keeping_safe = True
            
            vis = visible_all[discard_id]
            if vis >= 1:
                safe_start = self.params.get('SAFE_TILE_TURN_START', 6)
                safe_ramp = self.params.get('SAFE_TILE_RAMP_DURATION', 10)
                has_threat = self.state.is_any_opponent_reach() or Evaluator._any_opponent_has_open_meld(self.state)
                if has_threat:
                    effective_turn = max((self.state.tsumo_count - 1) // 4 + 1, safe_start)
                else:
                    effective_turn = (self.state.tsumo_count - 1) // 4 + 1
                turn_factor = max(0.0, min(1.0, (effective_turn - safe_start) / safe_ramp))
                if is_keeping_safe or turn_factor > 0:
                    ratio = 4.0 / max(1, 4 - vis) - 1.0
                    offset = int(ratio * ratio_base)
                    if not is_keeping_safe and turn_factor < 1.0:
                        offset = int(offset * turn_factor)
                    bonus += offset
                    if is_keeping_safe:
                        self.record_detail(tile, f"安全字牌抱えペナルティ ({offset})")
                    else:
                        self.record_detail(tile, f"安牌字牌整理ボーナス (+{offset})")
            # 序盤の孤立字牌優先整理ボーナス: 孤立字牌は巡目が浅いうちに切るほど価値が高い
            if turn <= 8 and not is_pair and not is_dora and not is_keeping_safe:
                early_honor_bonus = self.params.get('EARLY_HONOR_DISCARD_BONUS', 50)
                bonus += early_honor_bonus
                self.record_detail(tile, f"序盤字牌整理促進ボーナス (+{early_honor_bonus})")
        else:
            is_dora = any(tile_to_id(d) == discard_id for d in self.state.actual_doras)
            if is_dora:
                penalty = self.params.get('DORA_DISCARD_PENALTY', 60)
                bonus -= penalty
                self.record_detail(tile, f"ドラ放出ペナルティ (-{penalty})")

            ratio_base = self.params.get('VISIBLE_RATIO_BASE', 20)
            visible_all = self.state.all_visible_counts()
            vis = visible_all[discard_id]
            safe_start = self.params.get('SAFE_TILE_TURN_START', 6)
            safe_ramp = self.params.get('SAFE_TILE_RAMP_DURATION', 10)
            has_threat = self.state.is_any_opponent_reach() or Evaluator._any_opponent_has_open_meld(self.state)
            if has_threat:
                effective_turn = max((self.state.tsumo_count - 1) // 4 + 1, safe_start)
            else:
                effective_turn = (self.state.tsumo_count - 1) // 4 + 1
            turn_factor = max(0.0, min(1.0, (effective_turn - safe_start) / safe_ramp))
            if vis >= 1 and counts[discard_id] == 1 and turn_factor > 0:
                ratio = 4.0 / max(1, 4 - vis) - 1.0
                offset = int(ratio * ratio_base)
                if turn_factor < 1.0:
                    offset = int(offset * turn_factor)
                bonus += offset
                self.record_detail(tile, f"安牌整理ボーナス (+{offset})")

            all_ids = [tile_to_id(t) for t in self.state.my_hand]
            all_ids.extend(tile_to_id(t) for m in self.state.my_melds for t in getattr(m, 'tiles', []))

            has_term = any(is_terminal(tid) for tid in all_ids)
            has_hon = any(is_honor(tid) for tid in all_ids)
            can_tanyao = not has_term and not has_hon
            if can_tanyao and not is_honor(discard_id):
                off = discard_id % 9
                if off == 0 or off == 8:
                    tan_bonus = self.params.get('TANYAO_TERMINAL_BONUS', 40)
                    bonus += tan_bonus
                    self.record_detail(tile, f"断么九変化端牌整理ボーナス (+{tan_bonus})")

            is_red = is_red_five(tile)
            if is_red:
                aka_bonus = self.params.get('AKA_KEEP_BONUS', 60)
                bonus += aka_bonus
                self.record_detail(tile, f"赤5整理ボーナス (+{aka_bonus})")

            if not is_honor(discard_id) and counts[discard_id] == 1:
                base = (discard_id // 9) * 9
                off = discard_id - base
                connect = 0
                if off > 0: connect += counts[base + off - 1] if counts[base + off - 1] > 0 else 0
                if off < 8: connect += counts[base + off + 1] if counts[base + off + 1] > 0 else 0
                has_kanchan_l = off >= 2 and counts[base + off - 2] > 0
                has_kanchan_r = off <= 6 and counts[base + off + 2] > 0
                is_truly_isolated = connect == 0 and not has_kanchan_l and not has_kanchan_r
                if is_truly_isolated:
                    if 2 <= off <= 6:
                        # 孤立中張牌: 序盤は手幅のために保持したいが、巡目が進むほど危険なため徐々に嫌う（ペナルティの減衰）
                        middle_penalty = self.params.get('ISOLATED_MIDDLE_BONUS', 10)
                        decay = max(-1.0, 1.0 - turn / 10.0) # 10巡目以降は逆に廃棄ボーナスに転じる
                        offset = int(middle_penalty * decay)
                        bonus -= offset
                        if offset > 0:
                            self.record_detail(tile, f"孤立中張牌保持ペナルティ (-{offset})")
                        elif offset < 0:
                            self.record_detail(tile, f"孤立中張牌整理ボーナス (+{-offset})")
                        
                        # 進行度が高くブロックが十分な場合は、不要な孤立中張牌を率先して捨てる
                        if shanten <= 2 and blocks >= 5:
                            disc_bonus = self.params.get('ISOLATED_MIDDLE_DISCARD_BONUS_5BLOCK', 30)
                            bonus += disc_bonus
                            self.record_detail(tile, f"5ブロック不要中張牌整理ボーナス (+{disc_bonus})")
                    elif off == 0 or off == 8:
                        # 孤立1/9（端牌）: 最も効率が低いため率先して捨てる（巡目減衰）
                        edge_bonus = self.params.get('ISOLATED_EDGE_BONUS', 25)
                        decayed_edge = int(edge_bonus * max(0.2, 1.0 - turn / 18.0))
                        bonus += decayed_edge
                        self.record_detail(tile, f"孤立端牌整理ボーナス (+{decayed_edge})")
                    else:
                        # 孤立2/8: 1/9よりは両面変化があるため少し残しやすい（巡目減衰）
                        bonus_28 = self.params.get('ISOLATED_28_BONUS', 10)
                        decayed_28 = int(bonus_28 * max(0.2, 1.0 - turn / 18.0))
                        bonus += decayed_28
                        self.record_detail(tile, f"孤立2/8牌整理ボーナス (+{decayed_28})")

        # 孤立字牌が手牌に残っている状態で搭子を崩すのを抑制
        if not is_honor(discard_id) and turn <= 10 and shanten >= 2:
            isolated_honor_ids = [t for t in range(27, 34) if counts[t] == 1]
            if isolated_honor_ids and discard_id < 27:
                base = (discard_id // 9) * 9
                off = discard_id - base
                has_shape = (off > 0 and counts[base + off - 1] > 0) or \
                            (off < 8 and counts[base + off + 1] > 0)
                if has_shape:
                    penalty = self.params.get('SHAPE_BREAK_WHILE_HONOR_PENALTY', 100)
                    bonus -= penalty
                    self.record_detail(tile, f"孤立字牌({len(isolated_honor_ids)}枚)残存で搭子破壊ペナルティ (-{penalty})")

        # 5ブロックスリム化ボーナス（6ブロック以上で弱いブロック破壊時）
        # Why: 「全力攻撃」「押し気味」「積極駒組み」「危険度勝負」の攻撃系4モードのときは、
        # 広く受け入れるために6ブロック維持を許容するため、5ブロックスリム化ボーナスを適用しません。
        if blocks >= 6 and not is_honor(discard_id) and mode not in ("全力攻撃", "押し気味", "積極駒組み", "危険度勝負"):
            base = (discard_id // 9) * 9
            off = discard_id - base
            has_l = off > 0 and counts[base + off - 1] > 0
            has_r = off < 8 and counts[base + off + 1] > 0
            is_isolated = not has_l and not has_r and counts[discard_id] == 1
            is_penchan = (off == 0 and counts[base + 1] > 0) or (off == 8 and counts[base + 7] > 0)
            is_kanchan = (off >= 2 and counts[base + off - 2] > 0 and not has_l) or \
                         (off <= 6 and counts[base + off + 2] > 0 and not has_r)
            is_ryanmen = has_l and has_r and counts[discard_id] == 1
            if (is_isolated or is_penchan or is_kanchan) and not is_ryanmen:
                slim_bonus = self.params.get('SLIM_WEAK_BLOCK_BONUS', 40)
                bonus += slim_bonus
                self.record_detail(tile, f"5ブロックスリム化ボーナス (+{slim_bonus})")

        # 動的良形変化シミュレータ（1-2向聴、12巡目まで）
        turn = (self.state.tsumo_count - 1) // 4 + 1
        if 1 <= shanten <= 2 and turn <= self.params.get('GOOD_SHAPE_TURN_LIMIT', 12):
            after_counts = list(counts)
            after_counts[discard_id] = max(0, after_counts[discard_id] - 1)
            shanten_after = self.shanten_after_discard(tile)
            good_draws = 0
            total_draws = 0
            visible = self.state.all_visible_counts()
            for tid in range(34):
                if after_counts[tid] >= 4:
                    continue
                remaining = 4 - visible[tid]
                if remaining <= 0:
                    continue
                test = list(after_counts)
                test[tid] += 1
                if open_meld_count == 0:
                    ns = ShantenCalculator.calculate_closed_effective(test)
                else:
                    ns = ShantenCalculator.calculate_open(test, open_meld_count)
                if ns < shanten_after:
                    is_good = False
                    if tid < 27:
                        base2 = (tid // 9) * 9
                        off2 = tid - base2
                        has_l2 = off2 > 0 and after_counts[base2 + off2 - 1] >= 1
                        has_r2 = off2 < 8 and after_counts[base2 + off2 + 1] >= 1
                        is_good = has_l2 and has_r2
                    if is_good:
                        good_draws += remaining
                    total_draws += remaining
            if total_draws > 0:
                good_ratio = good_draws / total_draws
                shape_bonus = int(self.params.get('GOOD_SHAPE_CHANGE_BONUS', 30) * good_ratio)
                if shape_bonus > 0:
                    bonus += shape_bonus
                    self.record_detail(tile, f"良形変化ボーナス (+{shape_bonus})")

        # スジ引っ掛け（罠待ち）ボーナス（1向聴、8巡目まで）
        if shanten <= 1 and turn <= self.params.get('TRAP_WAIT_TURN_LIMIT', 8):
            for base in [0, 9, 18]:
                for i in range(5):
                    if counts[base + i] >= 1 and counts[base + i + 2] >= 1 and counts[base + i + 4] >= 1:
                        if discard_id == base + i or discard_id == base + i + 4:
                            trap_bonus = self.params.get('TRAP_WAIT_BONUS', 50)
                            bonus += trap_bonus
                            self.record_detail(tile, f"罠待ち（スジ引っ掛け）ボーナス (+{trap_bonus})")
                            break
                else:
                    continue
                break

        # 役満ボーナス
        yakuman_bonus = self._yakuman_bonus(tile)
        if yakuman_bonus > 0:
            bonus += yakuman_bonus

        return bonus

    def _yakuman_bonus(self, tile: str) -> int:
        """
        @title 役満ボーナス計算
        @description 各役満の進行度に応じてボーナスを加算する。
        @param {str} tile - 捨てる牌の文字列
        @returns {int} 役満ボーナス値
        """
        from yakuman_evaluator import YakumanEvaluator

        evaluator = YakumanEvaluator(self.state)
        results = evaluator.evaluate_all()

        total_bonus = 0
        turn = (self.state.tsumo_count - 1) // 4 + 1
        tile_id = tile_to_id(tile)

        # パラメータ読み込み
        yakuman_cfg = self.params.get('yakuman_strategy', {})
        top_necessity = yakuman_cfg.get('YAKUMAN_TOP_NECESSITY_FACTOR', 0.5)
        mangan_factor = yakuman_cfg.get('YAKUMAN_MANGAN_FACTOR', 0.75)
        over_mangan_factor = yakuman_cfg.get('YAKUMAN_OVER_MANGAN_FACTOR', 1.0)
        turn_early_threshold = yakuman_cfg.get('YAKUMAN_TURN_EARLY_THRESHOLD', 6)
        turn_mid_threshold = yakuman_cfg.get('YAKUMAN_TURN_MID_THRESHOLD', 12)
        turn_early_factor = yakuman_cfg.get('YAKUMAN_TURN_EARLY_FACTOR', 1.0)
        turn_mid_factor = yakuman_cfg.get('YAKUMAN_TURN_MID_FACTOR', 0.8)
        turn_late_factor = yakuman_cfg.get('YAKUMAN_TURN_LATE_FACTOR', 0.5)

        # 点数ラインの計算（GAで調整可能）
        score_line_name = yakuman_cfg.get('YAKUMAN_SCORE_LINE', 'mangan')
        score_lines = yakuman_cfg.get('YAKUMAN_SCORE_LINES', {
            'mangan':    { 'child': 10000, 'dealer': 16000 },
            'haneman':   { 'child': 15000, 'dealer': 24000 },
            'baiman':    { 'child': 20000, 'dealer': 32000 },
            'sanbaiman': { 'child': 30000, 'dealer': 48000 },
            'yakuman':   { 'child': 40000, 'dealer': 64000 }
        })
        line_config = score_lines.get(score_line_name, score_lines['mangan'])
        is_dealer = (self.state.my_seat - self.state.ju) % 4 == 0
        mangan_line = line_config['dealer'] if is_dealer else line_config['child']

        # 巡目補正
        if turn <= turn_early_threshold:
            turn_factor = turn_early_factor
        elif turn <= turn_mid_threshold:
            turn_factor = turn_mid_factor
        else:
            turn_factor = turn_late_factor

        # 点数必要度補正
        scores = self.state.scores
        my_score = scores[self.state.my_seat]
        top_score = max(scores)
        gap = top_score - my_score
        if gap <= 0:
            necessity_factor = top_necessity
        elif gap <= mangan_line:
            necessity_factor = mangan_factor
        else:
            necessity_factor = over_mangan_factor

        # 点差が大きい場合、遠い手でも役満を狙う（shanten上限を緩和）
        min_shanten = yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2)
        relax_cfg = yakuman_cfg.get('YAKUMAN_SHANTEN_RELAX_LINES', {})
        mult1 = relax_cfg.get('gap_multiplier_1', 1.5)
        mult2 = relax_cfg.get('gap_multiplier_2', 2.5)
        shanten_at1 = relax_cfg.get('shanten_at_multiplier_1', 3)
        shanten_at2 = relax_cfg.get('shanten_at_multiplier_2', 4)
        if gap > mangan_line * mult2:
            min_shanten = max(min_shanten, shanten_at2)
        elif gap > mangan_line * mult1:
            min_shanten = max(min_shanten, shanten_at1)

        max_yakuman_bonus = 0
        best_yakuman_name = ''
        best_selection_score = 0

        for name, result in results.items():
            if not result.is_possible:
                continue
            if result.shanten > min_shanten:
                continue

            # 牌貢献度判定: この牌が役満進行に貢献するか
            if yakuman_cfg.get('YAKUMAN_TILE_CONTRIBUTION_ENABLED', True):
                if not self._tile_contributes_to_yakuman(tile_id, name):
                    continue

            # シャンテン補正（二次関数）
            shanten_factor = max(0.0, (4 - result.shanten) ** 2 / 16.0)

            # 基本ボーナス
            base_bonus = self.params.get('YAKUMAN_BONUS_SCALE', 200)

            # 合計ボーナス（priority factorは選択用、ボーナス額には影響しない）
            yakuman_bonus = int(base_bonus * shanten_factor * turn_factor * necessity_factor * result.progress)
            if yakuman_bonus > 0:
                # priority factorを加味したスコアで最良を選択
                priority_factor = self._yakuman_priority_factor(name, result)
                selection_score = yakuman_bonus * priority_factor
                if selection_score > best_selection_score:
                    best_selection_score = selection_score
                    max_yakuman_bonus = yakuman_bonus
                    best_yakuman_name = name

        if max_yakuman_bonus > 0:
            mode = self.evaluator.strategy.get_strategy_mode()
            yakuman_scale = 1.0
            if mode == "完全撤退":
                yakuman_scale = 0.0
            elif mode in ("撤退準備", "回し打ち"):
                yakuman_scale = 0.5

            scaled_bonus = int(max_yakuman_bonus * yakuman_scale)
            if scaled_bonus > 0:
                total_bonus += scaled_bonus
                self.record_detail(tile, f"役満ボーナス[{best_yakuman_name}] (+{scaled_bonus})")

                ai = getattr(getattr(self, 'evaluator', None), '_ai_player', None)
                if ai is not None:
                    ai.yakuman_bonus_count += 1
                    if min_shanten > yakuman_cfg.get('YAKUMAN_MIN_SHANTEN', 2):
                        ai.gap_relaxation_count += 1

        return total_bonus

    def _yakuman_priority_factor(self, yakuman_name: str, result) -> float:
        """役満の成立しやすさによる優先度補正（1.0が基準）"""
        # GAで調整可能な優先度因子をJSONから読み込み
        yakuman_cfg = self.params.get('yakuman_strategy', {})
        priority_factors = yakuman_cfg.get('YAKUMAN_PRIORITY_FACTORS', {})
        progress_bonus_rate = yakuman_cfg.get('YAKUMAN_PRIORITY_PROGRESS_BONUS', 0.2)

        base_factor = priority_factors.get(yakuman_name, 1.0)

        # 進行度が高いほど優先度を上げる
        progress_bonus = result.progress * progress_bonus_rate

        return base_factor + progress_bonus

    def _tile_contributes_to_yakuman(self, tile_id: int, yakuman_type: str) -> bool:
        """指定された牌が役牌が役満進行に貢献するか"""
        from yakuman_evaluator import YAOCHU_IDS, SANGEN_IDS, KAZE_IDS, RYUU_ISOU_IDS

        if yakuman_type == 'kokushi':
            # 国士無双: 老頭・字牌なら貢献
            return tile_id in YAOCHU_IDS
        elif yakuman_type == 'suuankou':
            # 四暗刻: 暗刻にできる牌（2枚以上持っている）なら貢献
            hand_counts = self.state.my_hand_counts()
            return hand_counts[tile_id] >= 2
        elif yakuman_type == 'daisangen':
            # 大三元: 三元牌なら貢献
            return tile_id in SANGEN_IDS
        elif yakuman_type == 'tsuuiisou':
            # 字一色: 字牌なら貢献
            return tile_id >= 27
        elif yakuman_type == 'chinroutou':
            # 清老頭: 老頭牌なら貢献
            from str_converter import is_terminal
            return is_terminal(tile_id)
        elif yakuman_type == 'chuuren':
            # 九蓮宝燈: 一色の牌なら貢献（简化版）
            return tile_id < 27  # 数牌のみ
        elif yakuman_type in ('daisuushii', 'shousuushii'):
            # 大四喜・小四喜: 風牌なら貢献
            return tile_id in KAZE_IDS
        elif yakuman_type == 'ryuuiisou':
            # 緑一色: 緑一色候補牌なら貢献
            return tile_id in RYUU_ISOU_IDS
        elif yakuman_type == 'suukantsu':
            # 四槓子: どの牌でも貢献（槓にするため）
            return True
        return True


    def _get_furiten_tile_ids(self) -> set:
        my_river_ids = set()
        for t in self.state.river[self.state.my_seat]:
            try:
                my_river_ids.add(tile_to_id(t))
            except Exception:
                continue
        return my_river_ids

    def _compute_furiten_penalty(self, discard_tile: str) -> int:
        furiten_ids = self._get_furiten_tile_ids()
        if not furiten_ids:
            return 0
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(discard_tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        if current_shanten > 0:
            return 0
        furiten_wait = 0
        total_wait = 0
        for tile_id in range(34):
            if new_counts[tile_id] >= 4:
                continue
            test = list(new_counts)
            test[tile_id] += 1
            if open_meld_count == 0:
                test_shanten = ShantenCalculator.calculate_closed_effective(test)
            else:
                test_shanten = ShantenCalculator.calculate_open(test, open_meld_count)
            if test_shanten < current_shanten:
                total_wait += 1
                if tile_id in furiten_ids:
                    furiten_wait += 1
        if total_wait == 0:
            return 0
        ratio = furiten_wait / total_wait
        max_penalty = self.params.get('FURITEN_PENALTY', 300)
        return int(ratio * max_penalty)

    def _furiten_reserve_penalty(self, tile: str) -> int:
        hand_counts = self.state.my_hand_counts()
        discard_id = tile_to_id(tile)
        new_counts = list(hand_counts)
        new_counts[discard_id] = max(0, new_counts[discard_id] - 1)

        my_river_ids = set()
        for t in self.state.river[self.state.my_seat]:
            my_river_ids.add(tile_to_id(t))
        if not my_river_ids:
            return 0, ""

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            current_shanten = ShantenCalculator.calculate_closed_effective(new_counts)
        else:
            current_shanten = ShantenCalculator.calculate_open(new_counts, open_meld_count)
        if current_shanten >= 3:
            return 0, ""

        max_penalty = self.params.get('FURITEN_RESERVE_PENALTY', 300)
        total_penalty = 0
        reasons = []

        for tid in range(34):
            c = new_counts[tid]
            if c <= 0:
                continue
            if is_honor(tid):
                continue
            base = (tid // 9) * 9
            off = tid - base
            has_l = off > 0 and new_counts[base + off - 1] > 0
            has_r = off < 8 and new_counts[base + off + 1] > 0
            if has_l or has_r:
                continue
            if off > 0 and (base + off - 1) in my_river_ids:
                total_penalty += max_penalty
                reasons.append(f"{id_to_tile(tid)}")
            if off < 8 and (base + off + 1) in my_river_ids:
                total_penalty += max_penalty
                reasons.append(f"{id_to_tile(tid)}")

        total_penalty = min(max_penalty, total_penalty)
        if total_penalty > 0 and reasons:
            unique = list(dict.fromkeys(reasons))
            return total_penalty, f"フリテン予備軍: {','.join(unique)}の隣接牌が河にあるため将来フリテン待ちが含まれる (-{total_penalty})"
        return total_penalty, ""


class Evaluator:
    def __init__(self, state: GameState, params: dict = None):
        self.state = state
        self.params = params or {}
        self.details = {}  # tile -> List[str]
        self.attack = AttackEvaluator(state, params=self.params)
        self.attack.evaluator = self
        self.defense = DefenseEvaluator(state, params=self.params)
        self.defense.evaluator = self
        self.strategy = StrategyManager(state, params=self.params)
        self.strategy.evaluator = self
        self.meld_seal = MeldSealTracker()
        self._ai_player = None

    def record_detail(self, tile: str, msg: str):
        lst = self.details.setdefault(tile, [])
        if msg not in lst:
            lst.append(msg)

    def get_tile_description(self, tile: str) -> str:
        """
        @title 牌特性説明文生成
        @description 指定された牌がなぜ切りやすいかの簡潔な日本語説明を生成する。
        record_detail() で記録されたIF判定結果にも連動する。
        例: "早い順目のオタ風で孤立牌"、"孤立した端牌"、"6ブロック超過の不要牌"
        @param {str} tile - 評価対象の牌文字列 (例: "3z")
        @returns {str} 説明文字列（該当なしの場合は空文字）
        """
        try:
            tile_id = tile_to_id(tile)
        except Exception:
            return ""
        hand_counts = hand_to_counts(self.state.my_hand)
        human_turn = (self.state.tsumo_count - 1) // 4 + 1
        tile_details = self.details.get(tile, [])

        parts = []
        if human_turn <= 3:
            turn_tag = "早い順目"
        else:
            turn_tag = ""

        # ドラチェック（IF判定に連動）
        is_dora = any("ドラ" in d for d in tile_details)

        if is_honor(tile_id):
            bakaze = 27 + (self.state.chang % 4)
            wind_idx = (self.state.my_seat - self.state.ju) % 4
            jikaze = 27 + wind_idx

            if tile_id >= 31:
                wind_type = "三元牌"
            elif tile_id == bakaze and tile_id == jikaze:
                wind_type = "ダブル風"
            elif tile_id == bakaze:
                wind_type = "場風"
            elif tile_id == jikaze:
                wind_type = "自風"
            else:
                wind_type = "オタ風"

            count = hand_counts[tile_id]
            if count >= 3:
                return ""
            if count == 1:
                prefix = f"{turn_tag}の" if turn_tag else ""
                parts.append(f"{prefix}{wind_type}で孤立牌")
        else:
            base = (tile_id // 9) * 9
            off = tile_id - base
            has_l = off > 0 and hand_counts[base + off - 1] > 0
            has_r = off < 8 and hand_counts[base + off + 1] > 0
            is_isolated = not has_l and not has_r and hand_counts[tile_id] == 1

            if is_isolated:
                if off == 0 or off == 8:
                    parts.append("孤立した端牌")
                elif off == 1 or off == 7:
                    parts.append("孤立した2/8牌")
                else:
                    parts.append("孤立した中張牌")
            else:
                # details のIF判定結果から追加情報を抽出
                has_6block = any("6ブロック" in d for d in tile_details)
                has_shape_break = any("搭子破壊" in d for d in tile_details)
                if has_6block:
                    parts.append("6ブロック超過の不要牌")
                if not parts and has_shape_break:
                    # 搭子を壊す場合 → 打牌候補として不利な情報なので基本スキップ
                    pass

        # 詳細メッセージから補足タグを抽出（IF判定と連動）
        if is_dora:
            parts.append("ドラ牌")
        if any("フリテン" in d for d in tile_details):
            parts.append("フリテン懸念")
        has_yakuman_bonus = any("役満ボーナス" in d for d in tile_details)
        is_breaking_ankou = hand_counts[tile_id] >= 3
        if has_yakuman_bonus and not is_breaking_ankou:
            parts.append("役満狙い")

        if not parts:
            return ""
        return "".join(parts) + "のため"

    def _get_keiten_bonus(self, tile: str) -> int:
        """
        @title 形式テンパイ（形テン）ボーナス
        @description 終盤において、打牌後にテンパイとなる手牌に加算するボーナス値を返す。
                     放銃リスクが見合わない危険な局面では0を返し、緊急時のみ強行する。
        @param tile 捨てる牌の文字列 (例: "5m")
        @returns int ボーナス値（条件を満たさない場合は0）
        """
        # 他家テンパイ気配があり、切る牌が危険牌で、緊急事態でなければボーナス無効
        max_threat = self.strategy.compute_opponent_threat()
        v_defense = self.defense.defense_score_for_tile(tile)
        safe_threshold = self.params.get('SCORE_SUJI', 500)
        is_dealer = (self.state.my_seat - self.state.ju) % 4 == 0
        rank = self.state.my_score_rank()
        is_emergency = is_dealer and (self.state.ju == 3) and (rank >= 2)
        if max_threat >= 0.15 and v_defense < safe_threshold and not is_emergency:
            return 0

        tsumo = (self.state.tsumo_count - 1) // 4 + 1
        if 15 <= tsumo <= 17:
            shanten_after = self.attack.shanten_after_discard(tile)
            if shanten_after <= 0:
                return self.params.get('KEITEN_BONUS_15_17', KEITEN_BONUS_15_17)
        elif tsumo >= 18:
            shanten_after = self.attack.shanten_after_discard(tile)
            if shanten_after <= 0:
                return self.params.get('KEITEN_BONUS_18', KEITEN_BONUS_18)
        return 0

    @staticmethod
    def _any_opponent_has_open_meld(state: GameState) -> bool:
        for seat in range(4):
            if seat == state.my_seat:
                continue
            for m in state.melds[seat]:
                if m.is_open:
                    return True
        return False

    def _should_ignore_meld_for_defense(self) -> bool:
        turn = (self.state.tsumo_count - 1) // 4 + 1
        if turn > 6:
            return False
        threat = self.strategy.compute_opponent_threat()
        return threat < 0.15

    def evaluate_tile(self, tile: str) -> float:
        use_ev = self.params.get('USE_EV_FRAMEWORK', False)
        if use_ev:
            ev_val = self._evaluate_tile_ev(tile)
            pos_val = self._positional_ev()
            self.record_detail(tile, f"EV期待値評価 ({ev_val + pos_val:.1f})")
            return float(ev_val + pos_val)
        v_attack = self.attack.attack_score_for_tile(tile)
        v_defense = self.defense.defense_score_for_tile(tile)
        push_score = self.strategy.compute_push_score()
        mode = self.strategy.get_strategy_mode()

        alpha = self.params.get('FUZZY_VAL_ALPHA', 0.70)
        beta = self.params.get('FUZZY_VAL_BETA', 0.85)
        gamma = self.params.get('FUZZY_VAL_GAMMA', 0.40)
        safe_threshold = self.params.get('SCORE_SUJI', 500)

        if mode == "全力攻撃":
            v = float(v_attack)
            self.record_detail(tile, "戦略モード「全力攻撃」を適用")

        elif mode == "押し気味":
            v = float(alpha * v_attack + (1.0 - alpha) * v_defense)
            self.record_detail(tile, f"戦略モード「押し気味」(攻撃比率: {alpha:.2f})を適用")

        elif mode == "危険度勝負":
            v = float(beta * v_attack + (1.0 - beta) * v_defense)
            self.record_detail(tile, f"戦略モード「危険度勝負」(攻撃比率: {beta:.2f})を適用")

        elif mode == "積極駒組み":
            v = float(v_attack)
            self.record_detail(tile, "戦略モード「積極駒組み」を適用")

        elif mode == "様子見":
            v = float(push_score * v_attack + (1.0 - push_score) * v_defense)
            self.record_detail(tile, f"戦略モード「様子見」(Push={push_score:.2f})を適用")

        elif mode == "回し打ち":
            v = float(gamma * v_attack + (1.0 - gamma) * v_defense)
            self.record_detail(tile, f"戦略モード「回し打ち」(攻撃比率: {gamma:.2f})を適用")

        elif mode == "スリム化":
            slim_weight = self.params.get('FUZZY_SLIM_DEFENSE_WEIGHT', 0.3)
            v = float(v_defense * (1 - slim_weight) + v_attack * slim_weight)
            self.record_detail(tile, f"戦略モード「スリム化」(攻撃比率: {slim_weight:.2f})を適用")

        elif mode == "撤退準備":
            v = float(0.1 * v_attack + v_defense)
            self.record_detail(tile, "戦略モード「撤退準備」を適用")

        elif mode == "完全撤退":
            if v_defense >= safe_threshold:
                v = float(v_defense * 2 + v_attack * 0.01)
                self.record_detail(tile, "戦略モード「完全撤退」（安牌評価強化）を適用")
            else:
                v = float(v_defense + v_attack * 0.05)
                self.record_detail(tile, "戦略モード「完全撤退」（非安牌・危険回避）を適用")

        else:
            v = float(push_score * v_attack + (1.0 - push_score) * v_defense)

        is_ippatsu_turn = any(
            rs.is_ippatsu for i, rs in enumerate(self.state.reach_states) if i != self.state.my_seat
        )
        if is_ippatsu_turn:
            tile_id = tile_to_id(tile)
            if not self.defense.is_genbutsu(tile_id):
                reach_seats = self.defense._active_reach_seats()
                genbutsu_safe = tile_id in self.defense._common_genbutsu_ids(reach_seats)
                if not genbutsu_safe:
                    penalty = self.params.get('IPPATSU_PENALTY', 300)
                    ippatsu_pen = penalty * (1.0 - push_score)
                    v -= ippatsu_pen
                    self.record_detail(tile, f"一発放銃回避安全牌保持ペナルティ (-{ippatsu_pen:.1f})")

        keiten_bonus = self._get_keiten_bonus(tile)
        if keiten_bonus > 0:
            v += push_score * keiten_bonus
            self.record_detail(tile, f"形テンボーナス (押し補正: {push_score:.2f}) (+{push_score * keiten_bonus:.0f})")

        if is_honor(tile_to_id(tile)):
            # Why: 字牌（役牌・風牌等）の評価減衰を、単一の比例計算から「現在の戦略モードに応じた閾値と減衰係数（スレッショルド方式）」に変更します。
            # これにより、攻撃的なモードでは無闇に字牌を抱え込まず、守備的・様子見モードでは状況に応じて適切に字牌（安牌候補）を抱えるようになります。
            # 0.85/0.70などの閾値・減衰率は、config_parameters.json の 'HONOR_THREAT_THRESHOLDS' から読み込まれます。
            mode_configs = self.params.get('HONOR_THREAT_THRESHOLDS', {
                "全力攻撃": [0.85, 0.70],
                "積極駒組み": [0.75, 0.60],
                "危険度勝負": [0.60, 0.50],
                "押し気味": [0.50, 0.50],
                "様子見": [0.35, 0.40],
                "スリム化": [0.25, 0.30],
                "回し打ち": [0.20, 0.30],
                "撤退準備": [0.00, 0.30],
                "完全撤退": [0.00, 0.30]
            })
            config = mode_configs.get(mode)
            if config:
                # 0番目は他家脅威度の閾値、1番目は字牌の評価値減衰率（小さいほど強力に抱え込む）
                threshold, discount_factor = config[0], config[1]
                threat = self.strategy.compute_opponent_threat()
                if threat >= threshold:
                    # Why: 「安牌でなければ捨てづらく」するため、安牌（防御スコアがスジ安全度閾値500以上）でない場合のみ評価値を減衰させます。
                    # すでに現物などの安全牌になっている字牌は、防御時に優先して切りたいため減衰させません。
                    safe_threshold = self.params.get('SCORE_SUJI', 500)
                    if v_defense < safe_threshold:
                        v *= discount_factor
                        self.record_detail(tile, f"他家脅威による字牌評価減衰 (モード:{mode}, 脅威度:{threat:.2f} >= 閾値:{threshold:.2f}, 減衰:{discount_factor:.2f})")

        if self.params.get('USE_POSITIONAL_EV', True):
            pos_ev = self._positional_ev()
            v += pos_ev
            if pos_ev != 0:
                self.record_detail(tile, f"順位状況価値 (PositionalEV) (+{pos_ev:.1f})")
            assist_sq = self._assist_squeeze_bonus(tile)
            v += assist_sq

        if self._is_kokushi_protect_mode():
            tile_id = tile_to_id(tile)
            if tile_id in Evaluator._YAOCHU_INDICES:
                kokushi_penalty = self.params.get('KOKUSHI_DISCARD_PENALTY', 2000)
                v -= kokushi_penalty
                self.record_detail(tile, f"国士無双狙い: 么九牌温存 (-{kokushi_penalty})")
        return v

    def _is_kokushi_protect_mode(self) -> bool:
        hand_counts = self.state.my_hand_counts()
        yaochu_types = sum(1 for i in Evaluator._YAOCHU_INDICES if hand_counts[i] >= 1)
        if yaochu_types < 10:
            return False
        visible = self.state.all_visible_counts()
        for i in Evaluator._YAOCHU_INDICES:
            if visible[i] >= 4:
                return False
        if self.state.is_any_opponent_reach():
            return False
        threat = self.strategy.compute_opponent_threat()
        if threat >= 0.5:
            return False
        return True

    def _assist_squeeze_bonus(self, tile: str) -> float:
        bonus = 0.0
        scores = self.state.scores
        my_seat = self.state.my_seat
        my_score = scores[my_seat]
        sorted_seats = sorted(range(4), key=lambda s: (-scores[s], s))
        my_rank = sorted_seats.index(my_seat)
        dealer_seat = self.state.ju % 4

        is_dealer_last = sorted_seats[-1] == dealer_seat
        is_dealer_winning = dealer_seat == sorted_seats[0]

        if is_dealer_last and my_rank <= 1 and self.strategy._remaining_kyokus() <= 2:
            ally_target = sorted_seats[1] if my_rank == 0 else sorted_seats[0]
            tid = tile_to_id(tile)
            if not is_honor(tid):
                opp_discards = set()
                for t in self.state.river[ally_target]:
                    opp_discards.add(tile_to_id(t))
                if (tid // 9) in {t // 9 for t in opp_discards}:
                    ally_bonus = self.params.get('ASSIST_BONUS', 20)
                    bonus += ally_bonus
                    self.record_detail(tile, f"アシストボーナス (+{ally_bonus})")

        n_reach = sum(1 for i in range(4) if i != my_seat and self.state.reach_states[i].is_reach)
        if n_reach > 0:
            tid = tile_to_id(tile)
            if not is_honor(tid):
                base = (tid // 9) * 9
                off = tid - base
                counts = self.state.my_hand_counts()
                if counts[tid] >= 2:
                    has_l = off > 0 and counts[base + off - 1] > 0
                    has_r = off < 8 and counts[base + off + 1] > 0
                    if has_l or has_r:
                        sq_bonus = self.params.get('SQUEEZE_BONUS', 25)
                        bonus += sq_bonus
                        self.record_detail(tile, f"絞りボーナス (+{sq_bonus})")
        return bonus

    def _evaluate_tile_ev(self, tile: str) -> float:
        p_win = self._estimate_win_p(tile)
        p_deal_in = self._estimate_deal_in_p(tile)
        win_score = self._estimate_win_score()
        deal_loss = self._estimate_deal_loss(tile)
        ev_hand = p_win * win_score - p_deal_in * deal_loss
        pos_val = self._positional_ev()
        return float(ev_hand + pos_val)

    def _estimate_win_p(self, tile: str) -> float:
        ukeire_total, _ = self.attack.ukeire_for_discard(tile)
        if ukeire_total <= 0:
            return 0.0
        shanten = self.attack.shanten_after_discard(tile)
        remaining = self.state.left_tile_count
        if remaining <= 0:
            return 0.0
        draw_chance = ukeire_total / max(1, remaining)
        if shanten <= -1:
            return min(self.params.get('EV_WIN_MAX', 0.9), draw_chance * self.params.get('EV_WIN_AGARI_MULT', 4))
        elif shanten == 0:
            return min(self.params.get('EV_WIN_TENPAI_MAX', 0.7), draw_chance * self.params.get('EV_WIN_TENPAI_MULT', 3))
        elif shanten == 1:
            return min(self.params.get('EV_WIN_1S_MAX', 0.3), draw_chance * self.params.get('EV_WIN_1S_MULT', 2))
        else:
            return min(self.params.get('EV_WIN_HIGH_MAX', 0.1), draw_chance * self.params.get('EV_WIN_HIGH_MULT', 0.5))

    def _estimate_deal_in_p(self, tile: str) -> float:
        n_reach = len(self.defense._active_reach_seats())
        if n_reach == 0:
            return 0.0
        tile_id = tile_to_id(tile)
        if self.defense.is_genbutsu(tile_id):
            return 0.0
        reach_seats = self.defense._active_reach_seats()
        if tile_id in self.defense._common_genbutsu_ids(reach_seats):
            return 0.0
        if tile_id in self.defense._wall_suji_ids():
            return self.params.get('EV_DEALIN_WALL', 0.01)
        if tile_id in self.defense._no_chance_ids() and not is_honor(tile_id):
            return self.params.get('EV_DEALIN_NOCHANCE', 0.02)
        if tile_id in self.defense._reach_suji_ids(reach_seats):
            return self.params.get('EV_DEALIN_SUJI', 0.03) * n_reach
        if tile_id in self.defense._one_chance_ids() and not is_honor(tile_id):
            return self.params.get('EV_DEALIN_ONECHANCE', 0.05) * n_reach
        matagi = self.defense._matagi_danger_ids(reach_seats)
        danger = self.params.get('EV_DEALIN_MUSUJI_BASE', 0.06)
        danger += n_reach * self.params.get('EV_DEALIN_MUSUJI_PER_REACH', 0.05)
        if tile_id in matagi:
            danger += self.params.get('EV_DEALIN_MATAGI', 0.05)
        return min(self.params.get('EV_DEALIN_MAX', 0.5), danger)

    def _estimate_win_score(self) -> int:
        from hand_value import estimate_hand_value
        hand = self.state.my_hand
        melds = self.state.my_melds
        open_melds = [m for m in melds if m.is_open]
        is_open = len(open_melds) > 0
        has_reach = any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat)
        wind_idx = (self.state.my_seat - self.state.ju) % 4
        is_dealer = wind_idx == 0
        return estimate_hand_value(hand, melds, self.state.doras, is_open,
                                    has_reach=has_reach, is_ippatsu=False,
                                    is_tsumo=False, is_dealer=is_dealer,
                                    seat=wind_idx, chang=self.state.chang,
                                    ju=self.state.ju)

    def _estimate_deal_loss(self, tile: str) -> int:
        from opponent_model import estimate_opponent_state
        tile_id = tile_to_id(tile)
        total_loss = 0
        n_threats = 0
        for seat in range(4):
            if seat == self.state.my_seat:
                continue
            opp = estimate_opponent_state(self.state, seat)
            if not opp['is_tenpai'] and not opp['is_riichi']:
                continue
            danger = 0.1
            if opp['is_riichi']:
                danger = 0.8
            elif opp['is_tenpai']:
                danger = 0.5
            if opp['is_riichi'] or opp['is_tenpai']:
                from hand_value import estimate_hand_value
                est_score = estimate_hand_value(
                    [], self.state.melds[seat], self.state.doras,
                    is_open=opp['open_meld_count'] > 0,
                    has_reach=opp['is_riichi'], is_ippatsu=False,
                    is_tsumo=False, is_dealer=(seat == 0),
                    seat=seat, chang=self.state.chang, ju=self.state.ju)
                est_score = max(1000, est_score)
                seat_loss = int(est_score * danger)
                total_loss += seat_loss
                n_threats += 1
        return max(total_loss, n_threats * 1000)

    def _positional_ev(self) -> float:
        scores = self.state.scores
        my_seat = self.state.my_seat
        my_score = scores[my_seat]
        sorted_scores = sorted(enumerate(scores), key=lambda x: -x[1])
        my_rank = next(i for i, (s, _) in enumerate(sorted_scores) if s == my_seat)
        sorted_vals = [s for s, _ in sorted_scores]

        rank_pt = {0: 45, 1: 15, 2: -15, 3: -45}
        current_pt = rank_pt.get(my_rank, 0) + (my_score - 25000) // 1000

        if my_rank > 0:
            gap_to_up = sorted_vals[my_rank - 1] - my_score
            pt_gain_up = (rank_pt[my_rank - 1] + ((sorted_vals[my_rank - 1] + (gap_to_up // 2)) - 25000) // 1000) - current_pt
        else:
            gap_to_up = float('inf')
            pt_gain_up = 0

        if my_rank < 3:
            gap_to_down = my_score - sorted_vals[my_rank + 1]
            pt_loss_down = current_pt - (rank_pt[my_rank + 1] + ((sorted_vals[my_rank + 1] + (gap_to_down // 2)) - 25000) // 1000)
        else:
            gap_to_down = float('inf')
            pt_loss_down = 0

        remaining = self._remaining_kyokus()

        if remaining <= 0:
            urgency = 2.0
        elif remaining <= 2:
            urgency = 1.5
        elif remaining <= 4:
            urgency = 1.0
        else:
            urgency = 0.5

        up_prob = max(0, min(1, 1.0 - gap_to_up / max(1, remaining * 3000)))
        down_prob = max(0, min(1, 1.0 - gap_to_down / max(1, remaining * 3000)))

        naniire_bonus = self._naniire_bonus()

        positional_value = (up_prob * pt_gain_up - down_prob * pt_loss_down) * urgency + naniire_bonus
        return float(positional_value)

    def _remaining_kyokus(self) -> int:
        ju = self.state.ju
        chang = self.state.chang
        total = chang * 4 + ju + 1
        max_kyoku = 8
        remaining = max(0, max_kyoku - total)
        scores = self.state.scores
        if max(scores) < 30000 and total >= max_kyoku:
            remaining += 4
        return max(1, remaining)

    def _naniire_bonus(self) -> float:
        scores = self.state.scores
        top_score = max(scores)
        if top_score >= 29000 and top_score < 30000:
            rank = self.state.my_score_rank()
            if rank == 0:
                return 15.0
            else:
                return -5.0
        if top_score >= 30000:
            return 0.0
        if top_score < 27000 and self._remaining_kyokus() <= 2:
            rank = self.state.my_score_rank()
            if rank >= 2:
                return 10.0
        return 0.0

    def _hand_is_winning(self) -> bool:
        counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculator.calculate_closed_effective(counts) <= -1
        else:
            return ShantenCalculator.calculate_open(counts, open_meld_count) <= -1

    def best_discard(self, hand: List[str]) -> Optional[str]:
        """
        @title 最良打牌の選択
        @description 手牌の各牌タイプを評価し、最も評価値の高い牌を返す。
        完全撤退・撤退準備モード時は、best_discard_with_score の安全牌絞り込みロジックを適用します。
        @param hand 自家手牌のリスト
        @returns Optional[str] 最良打牌の文字列。handが空または和了形なら None。
        """
        # なぜこのようにするか：best_discard_with_score にのみ安全牌の絞り込み処理が実装されており、
        # 従来の best_discard は撤退モードを無視して打牌を選択してしまっていたため。
        # この関数を経由させることで、ベタオリの安全牌選択を有効化します。
        discard, _ = self.best_discard_with_score(hand)
        return discard

    def best_discard_with_score(self, hand: List[str]) -> Tuple[Optional[str], float]:
        if not hand:
            return None, float('-inf')
        if self._hand_is_winning():
            return None, float('inf')
        unique_tiles = list(dict.fromkeys(hand))
        mode = self.strategy.get_strategy_mode()
        # Why: 安牌を切るためのロジック（安全牌の強制選択）は「完全撤退」モードのときのみ適用します。
        # 「撤退準備」の段階では、安牌を手元に残す（抱える）ことを優先するため、ここでは強制フィルタリングを行いません。
        if mode == "完全撤退":
            threshold = self.params.get('SCORE_SUJI', 500)
            safe = [(self.evaluate_tile(t), t) for t in unique_tiles
                    if self.defense.defense_score_for_tile(t) >= threshold]
            if safe:
                unique_tiles = [t for _, t in safe]
        scored = [(self.evaluate_tile(t), t) for t in unique_tiles]

        wind_possible, wind_tile = self.state.is_first_turn_wind_limit_possible()
        if wind_possible and wind_tile is not None and wind_tile in unique_tiles:
            if self.strategy.is_high_hand_value_first_turn():
                wind_penalty = self.params.get('WIND_LIMIT_AVOID_PENALTY', 10000)
                scored = [(s - wind_penalty if t == wind_tile else s, t) for s, t in scored]
                self.record_detail(wind_tile, f"四風子連打回避: 手牌価値高のため風牌回避 (-{wind_penalty})")
            else:
                wind_bonus = self.params.get('WIND_LIMIT_FLOW_BONUS', 10000)
                scored = [(s + wind_bonus if t == wind_tile else s, t) for s, t in scored]
                self.record_detail(wind_tile, f"四風子連打流し: 手牌価値低のため流局狙い (+{wind_bonus})")

        scored.sort(key=lambda x: (-x[0], x[1]))
        return scored[0][1], scored[0][0]

    _YAOCHU_INDICES = [0, 8, 9, 17, 18, 26] + list(range(27, 34))

    def _kokushi_pair_tile(self) -> Optional[str]:
        counts = self.state.my_hand_counts()
        yaochu_types = sum(1 for i in self._YAOCHU_INDICES if counts[i] >= 1)
        if yaochu_types != 13:
            return None
        for i in self._YAOCHU_INDICES:
            if counts[i] >= 2:
                for t in self.state.my_hand:
                    if tile_to_id(t) == i:
                        return t
        return None

    def _kokushi_13_benefit_score(self) -> float:
        counts = self.state.my_hand_counts()
        yaochu_types = sum(1 for i in self._YAOCHU_INDICES if counts[i] >= 1)
        if yaochu_types != 13:
            return 0.0
        visible = self.state.all_visible_counts()
        total_remaining = sum(max(0, 4 - visible[i]) for i in self._YAOCHU_INDICES)
        remaining_ratio = total_remaining / (13 * 4)
        tsumo = (self.state.tsumo_count - 1) // 4 + 1
        turn_factor = max(0.0, 1.0 - tsumo / 18.0)

        my_score = self.state.scores[self.state.my_seat]
        rank = self.state.my_score_rank()
        if rank == 0:
            score_necessity = 0.0
        else:
            above_score = sorted(self.state.scores, reverse=True)[rank - 1]
            gap = above_score - my_score
            score_necessity = min(1.0, max(0.0, gap / 32000))

        benefit = remaining_ratio * 0.15 + turn_factor * 0.15 + score_necessity * 0.70
        return max(0.0, min(1.0, benefit))

    def should_go_kokushi_13(self) -> bool:
        if self._kokushi_pair_tile() is None:
            return False
        benefit = self._kokushi_13_benefit_score()
        threshold = self.params.get('KOKUSHI_13_THRESHOLD', 0.5)
        return benefit >= threshold

    def is_emergency_reverse_needed(self) -> bool:
        if not self.state.is_last_round():
            return False
        if self.state.my_score_rank() != 3:
            return False
        scores = self.state.scores
        my_score = scores[self.state.my_seat]
        sorted_scores = sorted(scores, reverse=True)
        third_score = sorted_scores[2]
        diff = third_score - my_score
        kan_cfg = self.params.get('yaku_strategy', {}).get('kan', {})
        threshold = kan_cfg.get('emergency_reverse_diff_threshold', 8000)
        return diff >= threshold

    def should_ankan(self) -> bool:
        mode = self.strategy.get_strategy_mode()
        # Why: 「完全撤退」「撤退準備」「スリム化」の守備的/様子見フェーズでは、手牌枚数の減少による防衛力低下および新ドラによる他家の打点上昇を防ぐため、暗カンを禁止します。
        if mode in ("完全撤退", "撤退準備", "スリム化"):
            return False
        kan_cfg = self.params.get('yaku_strategy', {}).get('kan', {})
        ankan_min_push_tenpai = kan_cfg.get('ankan_min_push_tenpai', 0.6)
        ankan_max_turn_non_tenpai = kan_cfg.get('ankan_max_turn_non_tenpai', 9)

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        hand_counts = self.state.my_hand_counts()
        if open_meld_count == 0:
            shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
        else:
            shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        turn = (self.state.tsumo_count - 1) // 4 + 1
        push = self.strategy.compute_push_score()
        t_max = self.strategy.compute_opponent_threat()
        has_opponent_reach = self.state.is_any_opponent_reach()

        emergency = self.is_emergency_reverse_needed()

        if emergency:
            if not has_opponent_reach:
                return True
            if shanten <= 1:
                return True
            return False

        if has_opponent_reach or t_max >= 0.5:
            if shanten == 0 and push >= ankan_min_push_tenpai:
                return True
            return False

        if shanten == 0:
            return True
        if shanten == 1 and turn < ankan_max_turn_non_tenpai:
            return True
        return False

    def should_kakan(self, tile: str) -> bool:
        mode = self.strategy.get_strategy_mode()
        # Why: 「完全撤退」「撤退準備」「スリム化」の守備的/様子見フェーズでは、新ドラ追加による他家打点上昇のリスクを避けるため、加カンを禁止します。
        if mode in ("完全撤退", "撤退準備", "スリム化"):
            return False
        kan_cfg = self.params.get('yaku_strategy', {}).get('kan', {})
        kakan_max_threat = kan_cfg.get('kakan_max_threat', 0.3)

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        hand_counts = self.state.my_hand_counts()
        if open_meld_count == 0:
            shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
        else:
            shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        push = self.strategy.compute_push_score()
        t_max = self.strategy.compute_opponent_threat()
        has_opponent_reach = self.state.is_any_opponent_reach()

        emergency = self.is_emergency_reverse_needed()

        if emergency:
            if not has_opponent_reach:
                return True
            if shanten == 0:
                return True
            return False

        if has_opponent_reach or t_max >= kakan_max_threat:
            return False

        if shanten == 0:
            return True
        if shanten == 1 and push >= 0.7:
            return True
        return False

    def should_daiminkan(self, tiles: List[str], from_seat: int) -> bool:
        mode = self.strategy.get_strategy_mode()
        # Why: 「完全撤退」「撤退準備」「スリム化」の守備的/様子見フェーズでは、手牌数減少による防衛力低下および他家打点上昇のリスクを避けるため、大明カンを禁止します。
        if mode in ("完全撤退", "撤退準備", "スリム化"):
            return False
        kan_cfg = self.params.get('yaku_strategy', {}).get('kan', {})
        daiminkan_min_turn = kan_cfg.get('daiminkan_min_turn', 15)
        daiminkan_max_threat = kan_cfg.get('daiminkan_max_threat', 0.2)

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        hand_counts = self.state.my_hand_counts()
        if open_meld_count == 0:
            shanten = ShantenCalculator.calculate_closed_effective(hand_counts)
        else:
            shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        turn = (self.state.tsumo_count - 1) // 4 + 1
        t_max = self.strategy.compute_opponent_threat()
        has_opponent_reach = self.state.is_any_opponent_reach()

        emergency = self.is_emergency_reverse_needed()

        if emergency:
            if shanten == 0 and not has_opponent_reach:
                return True
            return False

        if has_opponent_reach:
            return False
        if t_max >= daiminkan_max_threat:
            return False
        if turn < daiminkan_min_turn:
            return False

        after_counts = list(hand_counts)
        target = tile_to_id(tiles[0])
        after_counts[target] = max(0, after_counts[target] - 3)
        after_shanten = ShantenCalculator.calculate_open(after_counts, open_meld_count + 1)
        if after_shanten == 0:
            return True
        return False

    def _wait_tiles_for_tenpai(self) -> List[int]:
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        ukeire = []
        for tid in range(34):
            if hand_counts[tid] >= 4:
                continue
            test = list(hand_counts)
            test[tid] += 1
            if open_meld_count == 0:
                s = ShantenCalculator.calculate_closed_effective(test)
            else:
                s = ShantenCalculator.calculate_open(test, open_meld_count)
            if s < 0:
                ukeire.append(tid)
        return ukeire

    def _wait_quality_score(self) -> float:
        waits = self._wait_tiles_for_tenpai()
        if not waits:
            return -0.5
        n_ryanmen = 0
        n_kanchan = 0
        n_penchan = 0
        n_tanki = 0
        n_shanpon = 0
        hand_counts = self.state.my_hand_counts()
        for tid in waits:
            test = list(hand_counts)
            test[tid] += 1
            if is_honor(tid):
                n_tanki += 1
            else:
                base = (tid // 9) * 9
                off = tid - base
                left_adj = test[base + off - 1] if off > 0 else 0
                right_adj = test[base + off + 1] if off < 8 else 0
                left_pair = off >= 2 and test[base + off - 2] >= 2
                right_pair = off <= 6 and test[base + off + 2] >= 2
                if left_adj >= 1 and right_adj >= 1:
                    n_ryanmen += 1
                elif (off >= 2 and test[base + off - 2] >= 1 and test[base + off - 1] >= 1):
                    n_kanchan += 1
                elif (off <= 6 and test[base + off + 1] >= 1 and test[base + off + 2] >= 1):
                    n_kanchan += 1
                elif off == 0 and right_adj >= 1 and test[base + off + 2] >= 1:
                    n_penchan += 1
                elif off == 8 and left_adj >= 1 and test[base + off - 2] >= 1:
                    n_penchan += 1
                else:
                    n_tanki += 1

        total = n_ryanmen + n_kanchan + n_penchan + n_tanki + n_shanpon
        if total == 0:
            return 0.0
        wr = lambda k, d: self.params.get(k, d)
        return (n_ryanmen * wr('RIICHI_WAIT_RYANMEN', 0.3)
                + n_shanpon * wr('RIICHI_WAIT_SHANPON', 0.1)
                - n_kanchan * wr('RIICHI_WAIT_KANCHAN', 0.1)
                - n_penchan * wr('RIICHI_WAIT_PENCHAN', 0.2)
                - n_tanki * wr('RIICHI_WAIT_TANKI', 0.05)) / total

    def _compare_riichi_vs_damaten(self) -> Tuple[float, float]:
        wait_tiles = self._wait_tiles_for_tenpai()
        if not wait_tiles:
            return (-999.0, -999.0)
        from hand_value import estimate_han_advanced, estimate_win_score
        is_dealer = (self.state.my_seat == getattr(self.state, 'dealer_seat', 0))
        base_han = estimate_han_advanced(
            self.state.my_hand, self.state.my_melds, self.state.doras,
            is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
            seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju)
        base_han = max(base_han, 1)
        base_score = estimate_win_score(base_han, 30, is_dealer)

        riichi_han = base_han + 1
        riichi_score = int(estimate_win_score(riichi_han, 30, is_dealer)
                          * self.params.get('RIICHI_URA_MULT', 1.15))
        tsumo_riichi_score = int(estimate_win_score(riichi_han + 1, 30, is_dealer)
                                * self.params.get('RIICHI_URA_MULT', 1.15))
        tsumo_base_score = estimate_win_score(base_han + 1, 30, is_dealer)

        value_ratio = riichi_score / max(base_score, 1)
        tsumo_rate = self.params.get('RIICHI_TSUMO_RATE', 0.4)

        wait_q = self._wait_quality_score()
        remaining = self.state.remaining_counts()
        total_remaining = sum(max(0, remaining[tid]) for tid in wait_tiles)
        q_norm = (wait_q + 1.0) / 2.0
        r_norm = min(1.0, total_remaining / 12.0)
        win_prob = max(0.01, q_norm * r_norm)
        turn = (self.state.tsumo_count - 1) // 4 + 1

        opp_fold = self.params.get('RIICHI_FOLD_RATE', 0.45)
        riichi_win = win_prob * (tsumo_rate * 1.15 + (1 - tsumo_rate) * (1 - opp_fold))
        riichi_exp_score = int(tsumo_rate * tsumo_riichi_score + (1 - tsumo_rate) * riichi_score)
        riichi_stick = self.params.get('RIICHI_STICK_COST', 0.3)
        riichi_ev = riichi_win * riichi_exp_score / 1000.0 - riichi_stick
        if self.state.is_any_opponent_reach():
            riichi_ev *= self.params.get('RIICHI_OPP_REACH_PENALTY', 0.8)
        if turn >= 14 or turn >= self.params.get('RIICHI_LATE_TURN', 14):
            riichi_ev *= self.params.get('RIICHI_LATE_PENALTY', 0.7)
        opp_threat = self.strategy.compute_opponent_threat()
        riichi_ev -= opp_threat * riichi_exp_score / 1000.0 * self.params.get('RIICHI_DEFENSE_COST', 0.2)

        damaten_tsumo_rate = self.params.get('DAMATEN_TSUMO_RATE', 0.2)
        damaten_win = win_prob * (damaten_tsumo_rate * 1.0 + (1 - damaten_tsumo_rate) * 1.0)
        damaten_exp_score = int(damaten_tsumo_rate * tsumo_base_score + (1 - damaten_tsumo_rate) * base_score)
        damaten_ev = damaten_win * damaten_exp_score / 1000.0
        damaten_ev += self.params.get('DAMATEN_FLEX_BONUS', 30) / 1000.0

        # 手変わり評価: 高打点役の完成期待や待ち改善の可能性 → ダマテン有利
        try:
            from yaku_detector import analyze_all
            yis = analyze_all(self.state.my_hand, self.state.my_melds,
                              seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju)
            imp = 0.0
            has_sanshoku_ittsuu = False
            for yi in yis.values():
                if yi.progress > 0.4 and not yi.is_complete:
                    if yi.name in ('sanshoku', 'ittsuu'):
                        imp += yi.progress * 0.3
                        has_sanshoku_ittsuu = True
            if has_sanshoku_ittsuu and wait_q < 0.2 and turn < 12:
                damaten_ev += self.params.get('DAMATEN_YAKU_IMP_BONUS', 0.15)
        except Exception:
            pass

        # 待ち改善可能性: 悪形を引ける牌がある → ダマテン有利
        if wait_q < 0.1:
            hand_counts = self.state.my_hand_counts()
            mejoras = 0
            for draw_id in range(34):
                if hand_counts[draw_id] >= 4:
                    continue
                test = list(hand_counts)
                test[draw_id] += 1
                for discard_id in range(34):
                    if test[discard_id] <= 0:
                        continue
                    test2 = list(test)
                    test2[discard_id] -= 1
                    omc = sum(1 for m in self.state.my_melds if m.is_open)
                    if omc == 0:
                        ns = ShantenCalculator.calculate_closed_effective(test2)
                    else:
                        ns = ShantenCalculator.calculate_open(test2, omc)
                    if ns < 0:
                        mejoras += 1
                        break
            mejora_ratio = min(1.0, mejoras / 12.0)
            if mejora_ratio > 0.2:
                damaten_ev += mejora_ratio * self.params.get('DAMATEN_WAIT_IMP_BONUS', 0.1)

        mode = self.strategy.get_strategy_mode()
        riichi_mode_bias = self.params.get('RIICHI_MODE_AGGRO', 0.15)
        if mode in ('全力攻撃', '押し気味', '危険度勝負', '積極駒組み'):
            riichi_ev += riichi_mode_bias
        elif mode in ('撤退準備', '完全撤退'):
            riichi_ev -= riichi_mode_bias * 2

        return (riichi_ev, damaten_ev)

    def get_riichi_decision_details(self) -> dict:
        """
        @title 立直判断の根拠詳細化
        @description 現在のテンパイ手牌において、立直推奨値を計算しその内訳と判断理由を日本語で返します。
        @returns {dict} {"should_riichi": bool, "score": float, "threshold": float, "reason": str}
        """
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        
        # 前提条件のチェック
        if any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat):
            return {"should_riichi": False, "score": 0.0, "threshold": 0.0, "reason": "すでに立直しています。"}
        if open_meld_count > 0:
            return {"should_riichi": False, "score": 0.0, "threshold": 0.0, "reason": "門前（メンゼン）ではないため立直できません。"}
        if self.state.scores[self.state.my_seat] < 1000:
            return {"should_riichi": False, "score": 0.0, "threshold": 0.0, "reason": "持ち点が1000点未満のため立直できません。"}

        riichi_ev, damaten_ev = self._compare_riichi_vs_damaten()
        should_riichi = riichi_ev > damaten_ev

        reason_text = f"リーチEV={riichi_ev:+.2f} / ダマテンEV={damaten_ev:+.2f}"
        if should_riichi:
            reason_text += " -> 【立直推奨】"
        else:
            reason_text += " -> 【ダマテン推奨】"

        return {
            "should_riichi": should_riichi,
            "score": round(riichi_ev, 3),
            "threshold": round(damaten_ev, 3),
            "reason": reason_text
        }

    def should_riichi(self) -> bool:
        if any(rs.is_reach for i, rs in enumerate(self.state.reach_states) if i == self.state.my_seat):
            return False
        mode = self.strategy.get_strategy_mode()
        # Why: 「完全撤退」「撤退準備」の守備重視局面では、手牌が固定されてベタオリの選択肢を失う立直（リーチ）を禁止します。
        if mode in ("完全撤退", "撤退準備"):
            return False
        hand_counts = self.state.my_hand_counts()
        if sum(hand_counts) != 14:
            return False
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count > 0:
            return False
        shanten = ShantenCalculator.calculate_closed(hand_counts)
        if shanten > 0:
            return False
        if self.state.scores[self.state.my_seat] < 1000:
            return False

        riichi_ev, damaten_ev = self._compare_riichi_vs_damaten()
        return riichi_ev > damaten_ev

    def should_kan(self) -> bool:
        hand_counts = self.state.my_hand_counts()
        # アンカン可能か（手牌に4枚ある牌が存在する）
        ankan_tile = None
        for i in range(34):
            if hand_counts[i] == 4:
                from str_converter import id_to_tile
                ankan_tile = id_to_tile(i)
                break
        if ankan_tile is not None and self.should_ankan():
            return True
        # カカン可能か（自分がポンした牌かつツモ牌が一致）
        if self.state.last_self_drawn is not None:
            for m in self.state.my_melds:
                if m.type == 2 and m.tiles[0] == self.state.last_self_drawn:
                    if self.should_kakan(self.state.last_self_drawn):
                        return True
                    break
        return False

    def _estimate_open_han(self, hand: List[str] = None, melds: List = None) -> int:
        """
        @title 鳴き時の期待飜数の見積もり
        @description 鳴いた後の仮想手牌と仮想副露から期待飜数を見積もる。
        @param hand 仮想手牌（None=現在の手牌）
        @param melds 仮想副露リスト（None=現在の副露）
        @returns {int} 期待飜数（エラー時は0）
        """
        try:
            from hand_value import estimate_han_advanced
            h = hand if hand is not None else self.state.my_hand
            m = melds if melds is not None else self.state.my_melds
            return estimate_han_advanced(
                h, m, self.state.doras,
                is_open=True, has_reach=False, is_ippatsu=False, is_tsumo=False,
                seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju
            )
        except Exception:
            return 0

    def _yaku_meld_bias(self, type_: int, tiles: List[str], hand_after: List[str] = None, melds_after: List = None) -> Optional[bool]:
        try:
            from yaku_detector import analyze_all
            h = hand_after if hand_after is not None else self.state.my_hand
            m = melds_after if melds_after is not None else self.state.my_melds
            yaku_infos = analyze_all(h, m, seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju)
        except Exception:
            return None

        yaku_strategy = self.params.get('yaku_strategy', {})

        toitoi_cfg = yaku_strategy.get('toitoi', {})
        if toitoi_cfg.get('meld_bias') == 'pon_only':
            toitoi = yaku_infos.get('toitoi')
            target_threshold = toitoi_cfg.get('pairs_threshold', 3) / 5.0
            if toitoi and toitoi.progress >= target_threshold:
                    if type_ == 0:
                        return False
                    if type_ == 1:
                        return True

        honitsu_cfg = yaku_strategy.get('honitsu', {})
        if honitsu_cfg.get('meld_bias') == 'dominant_only' and type_ == 0:
            honitsu = yaku_infos.get('honitsu')
            chinitsu = yaku_infos.get('chinitsu')
            target = honitsu or chinitsu
            if target and target.main_suit is not None:
                tile_suit = tile_to_id(tiles[0]) // 9
                if tile_suit != target.main_suit and tile_suit < 3:
                    return False

        for yaku_name in ('ittsuu', 'sanshoku'):
            cfg = yaku_strategy.get(yaku_name, {})
            if cfg.get('meld_bias') == 'accept' and type_ == 0:
                yi = yaku_infos.get(yaku_name)
                if yi and yi.progress >= cfg.get('pursue_threshold', 0.0):
                    return True

        # 役牌ポンは常に価値があるため、pinfu/chiitoitsuなどのdeclineを無視
        is_yakuhai_pon = False
        if type_ == 1:
            target_id = tile_to_id(tiles[0])
            seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
            round_wind = 27 + (self.state.chang % 4)
            is_yakuhai_pon = target_id in (31, 32, 33, seat_wind, round_wind)

        # 既に副露している場合、pinfu/chiitoitsuなど閉局専用役は不可能なのでdeclineを無視
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        for yaku_name in ('chiitoitsu', 'ryanpeikou', 'pinfu'):
            cfg = yaku_strategy.get(yaku_name, {})
            if cfg.get('meld_bias') == 'decline':
                yi = yaku_infos.get(yaku_name)
                if yi and yi.progress >= cfg.get('pursue_threshold', 0.0):
                    if open_meld_count == 0 and not is_yakuhai_pon:
                        return False

        return None

    def _meld_defense_penalty(self, type_: int, tiles: List[str]) -> int:
        cfg = self.params.get('yaku_strategy', {}).get('meld_defense', {})
        riichi_weight = cfg.get('riichi_penalty_per_tile', 300)
        threat_weight = cfg.get('threat_penalty_per_tile', 150)
        min_defense = cfg.get('min_defense_weight', 0.2)
        abs_threshold = cfg.get('absolute_threshold', 300)
        cond_threshold = cfg.get('conditional_threshold', 150)
        cond_push = cfg.get('conditional_push_min', 0.7)

        consumed = []
        if type_ == 1:
            tid = tile_to_id(tiles[0])
            consumed = [tid, tid]
        elif type_ == 0:
            consumed = [tile_to_id(t) for t in tiles[1:]]
        elif type_ == 2:
            tid = tile_to_id(tiles[0])
            consumed = [tid, tid, tid]
        else:
            return 0

        hand_counts = self.state.my_hand_counts()
        open_count = sum(1 for m in self.state.my_melds if m.is_open)
        my_shanten = ShantenCalculator.calculate_closed_effective(hand_counts) if open_count == 0 else ShantenCalculator.calculate_open(hand_counts, open_count)

        push = self.strategy.compute_push_score()
        defense_weight = max(min_defense, 1.0 - push)
        speed_factor = max(1.0, my_shanten * 0.5)

        hand_ids = [tile_to_id(t) for t in self.state.my_hand]
        total_loss = 0

        for opp in range(4):
            if opp == self.state.my_seat:
                continue
            is_riichi = self.state.reach_states[opp].is_reach
            if not is_riichi:
                opp_threat = self.strategy.compute_opponent_threat()
                if opp_threat < 0.4:
                    continue

            opp_discards = set(tile_to_id(t) for t in self.state.river[opp])
            genbutsu = {tid for tid in set(hand_ids) if tid in opp_discards}
            lost = sum(1 for c in consumed if c in genbutsu)
            if lost == 0:
                continue
            total_loss += lost * (riichi_weight if is_riichi else threat_weight)

        self._last_def_penalty = int(total_loss * defense_weight * speed_factor)
        return self._last_def_penalty

    def should_call_meld(self, type_: int, tiles: List[str], from_seat: int) -> bool:
        if not self.strategy.is_meld_open_allowed():
            return False
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count >= 4:
            return False

        # 鳴いた後の仮想手牌・仮想副露を構築
        from game_state import Meld
        hand_after = list(self.state.my_hand)
        consumed = []
        if type_ == 1:
            consumed = [tiles[0], tiles[0]]
        elif type_ == 0:
            consumed = tiles[1:]
        elif type_ == 2:
            consumed = [tiles[0], tiles[0], tiles[0]]
        for t in consumed:
            target_id = tile_to_id(t)
            for h_tile in list(hand_after):
                if tile_to_id(h_tile) == target_id:
                    hand_after.remove(h_tile)
                    break
        new_meld = Meld(type=type_, tiles=list(tiles), froms=[from_seat] * len(tiles), tile_states=[0] * len(tiles))
        melds_after = list(self.state.my_melds) + [new_meld]

        # 大明槓は専用判定に委ねる（シャンテン計算や副露封印より優先）
        if type_ == 2:
            return self.should_daiminkan(tiles, from_seat)

        bias = self._yaku_meld_bias(type_, tiles, hand_after, melds_after)
        if bias is False:
            return False
        bias_accept = (bias is True)

        hand_counts = self.state.my_hand_counts()
        before_shanten = ShantenCalculator.calculate_open(hand_counts, open_meld_count)
        after_counts = list(hand_counts)
        if type_ == 1:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 2)
        elif type_ == 0:
            for t in tiles[1:]:
                tid = tile_to_id(t)
                after_counts[tid] = max(0, after_counts[tid] - 1)
        elif type_ == 2:
            target = tile_to_id(tiles[0])
            after_counts[target] = max(0, after_counts[target] - 3)
        after_shanten = ShantenCalculator.calculate_open(after_counts, open_meld_count + 1)
        if after_shanten >= before_shanten:
            return False

        turn = (self.state.tsumo_count - 1) // 4 + 1

        # 防御姿勢（完全撤退・撤退準備）のときは原則副露（鳴き）禁止
        if self.strategy.get_strategy_mode() in ("完全撤退", "撤退準備"):
            if after_shanten <= 0:
                # 形式テンパイ: 12-15巡かつ必要性がある場合のみ許可
                if turn < 12 or turn > 15:
                    return False
                rank = self.state.my_score_rank()
                if rank < 2:
                    return False
                # 副露後に安全な捨て牌があるか
                consumed = set()
                if type_ == 0:
                    consumed = {tile_to_id(t) for t in tiles[1:]}
                elif type_ == 1:
                    consumed = {tile_to_id(tiles[0])}
                remain = [tid for tid in [tile_to_id(t) for t in self.state.my_hand]
                          if tid not in consumed]
                opp_discards = set()
                for opp in range(4):
                    if opp == self.state.my_seat: continue
                    for t in self.state.river[opp]:
                        opp_discards.add(tile_to_id(t))
                if any(tid in opp_discards for tid in remain):
                    return True
                return False
            return False
        is_closed = open_meld_count == 0

        expected_han = self._estimate_open_han(hand_after, melds_after)

        # 役牌ポン or 高価値手は防御ペナルティを無視
        is_yakuhai_meld = False
        if type_ == 1:
            target_id = tile_to_id(tiles[0])
            seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
            round_wind = 27 + (self.state.chang % 4)
            is_yakuhai_meld = target_id in (31, 32, 33, seat_wind, round_wind)

        # 【追加】防御ペナルティ: 安全牌喪失リスクを評価
        def_cfg = self.params.get('yaku_strategy', {}).get('meld_defense', {})
        push = self.strategy.compute_push_score()
        def_penalty = self._meld_defense_penalty(type_, tiles)
        abs_th = def_cfg.get('absolute_threshold', 300)
        cond_th = def_cfg.get('conditional_threshold', 150)
        cond_push = def_cfg.get('conditional_push_min', 0.7)
        if not is_yakuhai_meld and expected_han < 2:
            if def_penalty >= abs_th:
                return False
            if def_penalty >= cond_th and push < cond_push:
                return False

        # 副露に使う牌を手牌から除いた残り
        hand_ids = [tile_to_id(t) for t in self.state.my_hand]
        consumed_ids = []
        if type_ == 0:
            consumed_ids = [tile_to_id(t) for t in tiles[1:]]
        elif type_ == 1:
            consumed_ids = [tile_to_id(tiles[0]), tile_to_id(tiles[0])]
        elif type_ == 2:
            consumed_ids = [tile_to_id(tiles[0]), tile_to_id(tiles[0]), tile_to_id(tiles[0])]

        # なぜこのように手牌残りIDリストを作成するか：鳴きに使用した枚数だけ正確に手牌から除外するためです。
        remaining_ids = list(hand_ids)
        for cid in consumed_ids:
            if cid in remaining_ids:
                remaining_ids.remove(cid)

        # 残り手牌の安全牌カウント（安全度スコアが 500 以上のものを安牌とみなす）
        # 500 はスジ牌以上の安全度を持つスコアの閾値です。
        safe_threshold = self.params.get('SCORE_SUJI', 500)
        safe_count = 0
        for tid in remaining_ids:
            tile_str = id_to_tile(tid)
            if self.defense.defense_score_for_tile(tile_str) >= safe_threshold:
                safe_count += 1

        # なぜこのようにするか：2向聴以上（テンパイから遠い）の状態で安易に鳴くと、アガリが遠い上に守備力が激減するため、
        # 満貫以上の大物手や、役牌ポンによる最低限の速度が担保されており、かつ安牌が十分（2枚以上）ある場合のみ鳴くように制限します。
        # 2 は2向聴の閾値、4 は満貫期待飜数の閾値、2 は安全牌が2枚以上必要という閾値です。
        if before_shanten >= 2:
            is_high_value = expected_han >= 4
            if not is_yakuhai_meld and not is_high_value:
                return False
            if safe_count < 2:
                return False

        # なぜこのようにするか：他家リーチがいる、または他家脅威に対して押し引きスコアが低く（push < 0.5）、
        # かつアガリ打点が低い（2飜未満）場合、安牌が手牌に1枚もない（safe_count == 0）状態で鳴くのは極めて危険なため拒否します。
        # 0.5 は押し引き判断の閾値、2 は期待飜数の閾値です。
        opp_reach = sum(1 for i in range(4) if i != self.state.my_seat and self.state.reach_states[i].is_reach)
        if (opp_reach >= 1 or push < 0.5) and expected_han < 2 and not is_yakuhai_meld:
            if safe_count == 0:
                return False

        turn = (self.state.tsumo_count - 1) // 4 + 1
        is_dealer = self.state.my_seat == 0

        # 副露封印モード
        sealed = self.meld_seal.evaluate(self.state.my_hand, self.state.my_melds,
                                          self.state.my_seat, self.state.chang,
                                          self.state.ju)
        if sealed and is_closed:
            # 封印中: テンパイのみ許可（役牌すらポンしない）
            if after_shanten <= 0 and expected_han >= 1:
                return True
            return False

        # 役牌ポン（封印解除時のみ: 守備力変わらないので鳴く）
        if type_ == 1:
            target_id = tile_to_id(tiles[0])
            seat_wind = 27 + ((self.state.my_seat - self.state.ju) % 4)
            round_wind = 27 + (self.state.chang % 4)
            if target_id in (31,32,33,seat_wind,round_wind) and expected_han >= 1:
                return True

        # 0飜開局 = 和了れない → 絶対に鳴かない
        if expected_han < 1:
            return False

        # 役バイアスで鳴きが肯定されており、最低限の役とシャンテン進行、安全性が確認できたなら鳴く
        if bias_accept:
            return True

        # テンパイ → 鳴く（速度優先）
        if after_shanten <= 0:
            return True

        # 既開局 → コミットしているので鳴く
        if not is_closed:
            return True

        # 強い門前一向聴（両面x両面＋高打点）は鳴かない
        if is_closed and before_shanten <= 1 and expected_han >= 2 and turn < 6:
            return False

        # 終盤制限の緩和: 押し引きと巡目に応じて適用
        if turn >= 12 or push < 0.4:
            if after_shanten <= 0:
                return True
            if self.state.my_score_rank() == 3 and self.state.left_tile_count <= 20:
                return True
            return False

        # --- 価値比較 ---
        from hand_value import estimate_han_advanced, estimate_win_score
        is_dealer = self.state.my_seat == 0

        closed_han = estimate_han_advanced(
            self.state.my_hand, self.state.my_melds, self.state.doras,
            is_open=False, has_reach=False, is_ippatsu=False, is_tsumo=False,
            seat=self.state.my_seat, chang=self.state.chang, ju=self.state.ju)
        try:
            from yaku_detector import analyze_all
            yi = analyze_all(self.state.my_hand, self.state.my_melds,
                             seat=self.state.my_seat, chang=self.state.chang,
                             ju=self.state.ju)
            for name, y in yi.items():
                if y.progress > 0.3:
                    closed_han += max(0, y.closed_han - y.open_han)
        except Exception:
            pass
        if before_shanten <= 1:
            closed_han += 2

        closed_score = estimate_win_score(closed_han, 30, is_dealer)
        open_score = estimate_win_score(expected_han, 30, is_dealer)
        speed_bonus = (before_shanten - after_shanten) * 1000

        gap = closed_score - open_score
        if gap <= 500:
            return True
        elif gap >= 3000:
            return False
        else:
            return speed_bonus > gap

