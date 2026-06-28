# -*- coding: utf-8 -*-
"""
@title ver.2 メイン評価器
@description モード判定に基づいてタプルを構築し、打牌候補を lexicographic (辞書式) に比較する。
              各打牌の説明もタプル比較結果から自動生成する。

記号規約 (厳守):
- min() で打牌を選ぶ (小さいほど AI が選びたくなる)
- 「多いほど良い」値は符号反転 (-)
- 戦術ランクは 0-99 (小さいほど切りやすい)
- 安全度は符号反転 (-)

動的タプル長:
- 2 向聴以上: 6 層 (向聴, 戦術ランク, -良形, -愚形, ドラ, -安全)
- 1 向聴/テンパイ: 5 層 (向聴, -DFS, 戦術ランク, ドラ, -安全)
  → DFS 期待値で「良形+高打点」を先読み
"""
from __future__ import annotations
from typing import List, Optional, Tuple

from core.shanten_v2 import ShantenCalculatorV2
from core.tactical_rank_v2 import tactical_discard_rank
from core.ukeire_v2 import count_good_bad_ukeire
from core.dfs_v2 import run_1shanten_dfs
from core.defense_v2 import safety_score
from core.strategy_v2 import get_mode, Mode
from core.chiitoitsu_v2 import chiitoitsu_tuple
from core.yakuman_v2 import yakuman_tuple
from str_converter import tile_to_id, is_red_five


# 層名 (タプル位置 → 日本語名)
TIER_NAMES_NORMAL = [
    '向聴数',
    '戦術ランク',
    '良形受入',
    '愚形受入',
    'ドラ損失',
    '安全度',
]

TIER_NAMES_DFS = [
    '向聴数',
    'DFS期待値',
    '戦術ランク',
    'ドラ損失',
    '安全度',
]


class EvaluatorV2:
    def __init__(self, state, params: dict = None):
        self.state = state
        self.params = params or {}
        self.current_turn = (state.tsumo_count - 1) // 4 + 1
        self.is_last_round = state.is_last_round() if hasattr(state, 'is_last_round') else False
        self._mode_cache = None
        self._dfs_cache = {}

    def get_mode(self) -> Mode:
        if self._mode_cache is not None:
            return self._mode_cache
        self._mode_cache = get_mode(self.state, self.current_turn, self.is_last_round)
        return self._mode_cache

    def evaluate_tile(self, tile: str) -> Tuple:
        """
        @title 打牌評価
        @description 牌を評価してタプルを返す
        @returns 比較可能なタプル
        """
        mode = self.get_mode()
        if mode == Mode.CHIITOITSU:
            return chiitoitsu_tuple(self.state, tile)
        if mode in (Mode.KOKUSHI, Mode.YAKUMAN):
            yakuman_type = 'kokushi' if mode == Mode.KOKUSHI else _detect_yakuman_type(self.state)
            return yakuman_tuple(self.state, tile, yakuman_type)
        return self._normal_tuple(tile)

    def _normal_tuple(self, tile: str) -> Tuple:
        """
        @title 通常/ATTACK/DEFEND/FOLD/URGENT_ATTACK タプル
        @description 動的スイッチ: shanten_after <= 1 で DFS 経路に分岐
        """
        hand_counts = list(self.state.my_hand_counts())
        discard_id = tile_to_id(tile)
        if 0 <= discard_id < 34:
            hand_counts[discard_id] = max(0, hand_counts[discard_id] - 1)

        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            shanten_after = ShantenCalculatorV2.calculate_closed_effective(hand_counts)
        else:
            shanten_after = ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count)

        rank = tactical_discard_rank(self.state, tile)
        dora_loss = _dora_loss(self.state, tile)
        saf = safety_score(self.state, tile)

        if shanten_after <= 1:
            # 1 向聴 or テンパイ: DFS 期待値で評価 (5 層)
            dfs = self._get_dfs(tile)
            return (shanten_after, -dfs, rank, dora_loss, -saf)
        else:
            # 2 向聴以上: 良形/愚形に分解した受入 (6 層)
            good, bad = count_good_bad_ukeire(self.state, tile)
            return (shanten_after, rank, -good, -bad, dora_loss, -saf)

    def _get_dfs(self, tile: str) -> float:
        """@title DFS 期待値 (キャッシュ付き)"""
        if tile in self._dfs_cache:
            return self._dfs_cache[tile]
        dfs = run_1shanten_dfs(self.state, tile)
        self._dfs_cache[tile] = dfs
        return dfs

    def best_discard(self, hand: List[str]) -> Optional[str]:
        """
        @title 最良打牌の選択
        @description 候補タプルの中で min() を選ぶ。
        @returns 最良打牌の文字列
        """
        if not hand:
            return None
        if self._is_winning():
            return None

        unique_tiles = list(dict.fromkeys(hand))
        scored: List[Tuple[Tuple, str]] = []
        for tile in unique_tiles:
            t = self.evaluate_tile(tile)
            scored.append((t, tile))

        scored.sort(key=lambda x: x[0])
        return scored[0][1]

    def best_discard_with_score(self, hand: List[str]) -> Tuple[Optional[str], Tuple]:
        if not hand:
            return None, None
        if self._is_winning():
            return None, None

        unique_tiles = list(dict.fromkeys(hand))
        scored: List[Tuple[Tuple, str]] = []
        for tile in unique_tiles:
            t = self.evaluate_tile(tile)
            scored.append((t, tile))

        scored.sort(key=lambda x: x[0])
        return scored[0][1], scored[0][0]

    def explain_discard(self, hand: List[str], chosen: str) -> str:
        """
        @title 打牌の理由をタプル比較結果から生成
        @description chosen がなぜ選ばれたかを日本語で説明する。
                    候補間で比較し、最初に差がついた層で勝敗が決まったことを示す。
        """
        if not hand or chosen is None:
            return "打牌なし"

        unique_tiles = list(dict.fromkeys(hand))
        scored: List[Tuple[Tuple, str]] = []
        for tile in unique_tiles:
            t = self.evaluate_tile(tile)
            scored.append((t, tile))
        scored.sort(key=lambda x: x[0])

        chosen_tuple = None
        for t, t_str in scored:
            if t_str == chosen:
                chosen_tuple = t
                break

        if chosen_tuple is None:
            return f"{chosen} を切ります。"

        for t, t_str in scored:
            if t_str == chosen:
                continue
            for i, (a, b) in enumerate(zip(chosen_tuple, t)):
                if a != b:
                    is_dfs_path = len(chosen_tuple) == 5
                    layer_names = TIER_NAMES_DFS if is_dfs_path else TIER_NAMES_NORMAL
                    layer_name = layer_names[i] if i < len(layer_names) else f'層{i+1}'
                    return _explain_difference(chosen, t_str, i, a, b, layer_name)
        return f"{chosen} を切ります (タイ)。"

    def _is_winning(self) -> bool:
        """@title 和了形かどうか"""
        hand_counts = self.state.my_hand_counts()
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        if open_meld_count == 0:
            return ShantenCalculatorV2.calculate_closed_effective(hand_counts) <= -1
        else:
            return ShantenCalculatorV2.calculate_open(hand_counts, open_meld_count) <= -1


def _dora_loss(state, tile: str) -> int:
    """@title ドラ表示牌を捨てる際の損失"""
    loss = 0
    tile_id = tile_to_id(tile)
    for d in state.doras:
        try:
            if tile_to_id(d) == tile_id:
                loss += 1
        except Exception:
            pass
    return loss


def _detect_yakuman_type(state) -> str:
    """@title 進行中の役満タイプを返す"""
    from core.yakuman_v2 import get_active_yakuman
    y = get_active_yakuman(state)
    return y or 'kokushi'


def _explain_difference(chosen: str, other: str, layer: int, a, b, layer_name: str) -> str:
    """
    @title 差分説明
    @description layer 番目で a vs b の大小で勝敗が決まった理由を日本語で。
                a が chosen の値、b が other の値。
    """
    if layer == 0:  # 向聴数
        if a < b:
            return f"①向聴数: {chosen} を切ると {a} 向聴、{other} を切ると {b} 向聴。前進するので {chosen} を切ります。"
        else:
            return f"①向聴数: {other} を切ったほうが前進 ({a} < {b})。{chosen} は温存します。"

    if layer == 1:  # 戦術ランク or DFS
        if layer_name == 'DFS期待値':
            if a < b:  # a が chosen の DFS (反転してるので a < b = chosen の方が DFS 高い)
                return f"②DFS期待値: {chosen} を切ると良形×打点期待値 {-a} (高い)。{other} は {-b}。{chosen} のほうが良形変化や高打点が見込めます。"
            else:
                return f"②DFS期待値: {other} のほうが DFS 期待値が高い ({other}={-b}, {chosen}={-a})。{chosen} は温存します。"
        else:  # 戦術ランク
            if a < b:
                return f"②戦術ランク: {chosen} は {a} (切りやすい)、{other} は {b} (残したい)。まず {chosen} から切ります。"
            else:
                return f"②戦術ランク: {other} は {b} (切りやすい)、{chosen} は {a} (残したい)。{chosen} は温存します。"

    if layer == 2:  # 良形受入 or 戦術ランク
        if layer_name == '戦術ランク':
            if a < b:
                return f"③戦術ランク: {chosen} は {a} (切りやすい)、{other} は {b} (残したい)。まず {chosen} から切ります。"
            else:
                return f"③戦術ランク: {other} は {b} (切りやすい)、{chosen} は {a} (残したい)。{chosen} は温存します。"
        else:  # 良形受入
            if a < b:
                return f"③良形受入: {chosen} を切ると良形受け入れが {-a} 枚。{other} を切ると {-b} 枚。{chosen} のほうが良形受入が増えます。"
            else:
                return f"③良形受入: {other} のほうが良形受入が多い ({other}={-b}, {chosen}={-a})。{chosen} は温存します。"

    if layer == 3:  # 愚形受入 or ドラ損失
        if layer_name == '愚形受入':
            if a < b:
                return f"④愚形受入: {chosen} を切ると愚形受け入れが {-a} 枚。{other} を切ると {-b} 枚。"
            else:
                return f"④愚形受入: {other} のほうが愚形受入が多い。"
        else:  # ドラ損失
            if a < b:
                return f"④ドラ損失: {chosen} を切るとドラ {a} 枚失う。{other} を切ると {b} 枚失う。{chosen} のほうがドラを残せます。"
            else:
                return f"④ドラ損失: {other} のほうがドラを残せる ({other}={b}, {chosen}={a})。{chosen} は温存します。"

    if layer == 4:  # ドラ損失 or 安全度
        if layer_name == 'ドラ損失':
            if a < b:
                return f"⑤ドラ損失: {chosen} を切るとドラ {a} 枚失う。{other} を切ると {b} 枚失う。"
            else:
                return f"⑤ドラ損失: {other} のほうがドラを残せる。"
        else:  # 安全度
            if a < b:
                return f"⑤安全度: {chosen} は安全度 {-a} (高い)。{other} は {-b}。{chosen} のほうが安全なので切ります。"
            else:
                return f"⑤安全度: {other} のほうが安全 ({other}={-b}, {chosen}={-a})。{chosen} は温存します。"

    if layer == 5:  # 安全度
        if a < b:
            return f"⑥安全度: {chosen} は安全度 {-a} (高い)。{other} は {-b}。{chosen} のほうが安全なので切ります。"
        else:
            return f"⑥安全度: {other} のほうが安全 ({other}={-b}, {chosen}={-a})。{chosen} は温存します。"

    return f"層{layer+1} ({layer_name}) で {chosen} (={a}) vs {other} (={b}) の比較結果、{chosen} を選びます。"
