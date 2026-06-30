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
        @title モード別タプル
        @description 現在のモードに応じてタプルの優先順位を変える:
                    - URGENT_ATTACK: 受入を最優先
                    - ATTACK: 戦術ランクより受入優先
                    - BALANCED: 戦術ランク優先
                    - DEFEND: 安全度優先
                    - FOLD: 安全度を最上位に

        動的スイッチ: shanten_after <= 1 で DFS 経路に分岐
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
            # 1 向聴 or テンパイ: DFS 期待値で評価
            dfs = self._get_dfs(tile)
            mode = self.get_mode()
            if mode == Mode.URGENT_ATTACK:
                # URGENT: 受入最優先 (-dfs を上に)
                return (shanten_after, -dfs, -dora_loss, rank, -saf)
            elif mode == Mode.ATTACK:
                return (shanten_after, -dfs, -dora_loss, rank, -saf)
            elif mode == Mode.DEFEND:
                # DEFEND: 安全度を上に
                return (shanten_after, -saf, -dfs, rank, dora_loss)
            elif mode == Mode.FOLD:
                # FOLD: 安全度最優先
                return (-saf, shanten_after, -dfs, rank, dora_loss)
            else:
                # BALANCED
                return (shanten_after, -dfs, rank, dora_loss, -saf)
        else:
            # 2 向聴以上: 良形/愚形に分解した受入
            good, bad = count_good_bad_ukeire(self.state, tile)
            mode = self.get_mode()
            if mode == Mode.URGENT_ATTACK:
                # URGENT: 受入を最優先
                return (shanten_after, -good, -bad, -dora_loss, rank, -saf)
            elif mode == Mode.ATTACK:
                return (shanten_after, -good, -bad, -dora_loss, rank, -saf)
            elif mode == Mode.DEFEND:
                # DEFEND: 安全度優先
                return (shanten_after, -saf, rank, -good, -bad, dora_loss)
            elif mode == Mode.FOLD:
                # FOLD: 安全度最優先
                return (-saf, shanten_after, rank, -good, -bad, dora_loss)
            else:
                # BALANCED
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

    def _v1_evaluator(self):
        """ver.1 Evaluator への委譲 (should_riichi 等の複雑なメソッド用)"""
        from core.evaluator import Evaluator
        return Evaluator(self.state, params=self.params)

    def should_tsumo(self) -> bool:
        """@title ツモ和了判定 (v1 委譲)"""
        try:
            return self._v1_evaluator().should_tsumo()
        except Exception:
            return bool(len(self.state.my_hand) >= 14)

    def should_ron(self) -> bool:
        """@title ロン和了判定 (v1 委譲)"""
        try:
            return self._v1_evaluator().should_ron()
        except Exception:
            return False

    def should_riichi(self) -> bool:
        """
        @title 立直判定 (ver.2 加減算モデル)
        @description core/riichi_v2.py の 自前実装
        """
        from core.riichi_v2 import should_riichi as _should_riichi_v2
        try:
            return _should_riichi_v2(self.state, self.params)
        except Exception:
            return False

    def should_call_meld(self, call_type: int, tiles: list, from_seat: int) -> bool:
        """@title 鳴き判定 (v1 委譲)"""
        try:
            return self._v1_evaluator().should_call_meld(call_type, tiles, from_seat)
        except Exception:
            return False

    def should_kan(self) -> bool:
        """
        @title 槓判定 (暗槓・加槓・大明槓)
        @description core/riichi_v2.py の 自前実装 (meld_v2 委譲)
        """
        from core.riichi_v2 import should_kan as _should_kan_v2
        try:
            # 加槓は 嶺上牌 + 1 枚 を加えるので call_type=1 (ポン) として
            # 槓元の牌 + 嶺上牌 で ポン判定 する代わりに
            # ここでは meld_v2.should_call_meld に 委譲 する 簡易版
            from core.meld_v2 import should_call_meld
            return should_call_meld(self.state, 1, self.state.my_hand[-1:] * 2, 0, self.params)
        except Exception:
            return False

    def should_ankan(self) -> bool:
        """@title 暗槓判定"""
        try:
            return self._v1_evaluator().should_ankan()
        except Exception:
            return False

    def should_kakan(self, tile: str) -> bool:
        """@title 加槓判定"""
        try:
            return self._v1_evaluator().should_kakan(tile)
        except Exception:
            return False

    def should_daiminkan(self, tile: str, from_seat: int) -> bool:
        """@title 大明槓判定"""
        try:
            return self._v1_evaluator().should_daiminkan(tile, from_seat)
        except Exception:
            return False

    def should_call_meld(self, call_type: int, tiles: List[str], from_seat: int) -> bool:
        """
        @title 鳴き判定 (ver.2 加減算モデル)
        @description 22 要素の加重スコアで判定、ver.1 よりも明示的・調整可能
        @returns (鳴くべきか, 理由)
        """
        from core.meld_v2 import should_call_meld as _should_call_meld_v2
        try:
            decision, reason = _should_call_meld_v2(self.state, call_type, tiles, from_seat, self.params)
            self.last_meld_reason = reason
            return decision
        except Exception as e:
            self.last_meld_reason = f"ver.2 meld error: {e}"
            return False

    def should_go_kokushi_13(self) -> bool:
        """
        @title 国士無双 13 面待ち判定
        @description テンパイ時に 13 種全部 幺九牌ならツモる (国士)
        """
        from str_converter import hand_to_counts
        hand_counts = hand_to_counts(self.state.my_hand)
        yaochu_ids = [0, 8, 9, 17, 18, 26] + list(range(27, 34))
        yaochu_kinds = sum(1 for i in yaochu_ids if hand_counts[i] >= 1)
        return yaochu_kinds >= 13

    def get_tile_description(self, tile: str) -> str:
        """@title 牌の日本語説明"""
        return _to_japanese(tile)

    def record_detail(self, label: str, value) -> None:
        """@title デバッグ用: 詳細ログ (no-op)"""
        pass

    def describe_hand_structure(self) -> str:
        """
        @title 手牌構造の解説
        @description 面子手 (雀頭・塔子・面子) の構成を日本語で説明する。
                    例: 「3 面子 + 1 雀頭 + 0 塔子 (1 向聴)」
        @returns 日本語の説明文
        """
        hand_counts = list(self.state.my_hand_counts())
        open_meld_count = sum(1 for m in self.state.my_melds if m.is_open)
        sh, melds, pairs, taatsu = ShantenCalculatorV2.explain_hand_structure(hand_counts, open_meld_count)
        if sh <= -1:
            return f"和了形 ({melds} 面子 + {pairs} 雀頭)"
        label = {0: 'テンパイ', 1: '1 向聴', 2: '2 向聴', 3: '3 向聴',
                 4: '4 向聴', 5: '5 向聴', 6: '6 向聴', 7: '7 向聴', 8: '8 向聴'}.get(sh, f'{sh} 向聴')
        parts = [f"{melds} 面子"]
        if pairs > 0:
            parts.append(f"{pairs} 雀頭")
        if taatsu > 0:
            parts.append(f"{taatsu} 塔子")
        return f"{label} (" + " + ".join(parts) + ")"


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


def _to_japanese(tile: str) -> str:
    """@title 牌の日本語表記"""
    from str_converter import tile_to_id
    tid = tile_to_id(tile)
    if tid is None or tid < 0:
        return tile
    if 0 <= tid <= 26:  # 数牌
        n = (tid % 9) + 1
        suit = '萬' if tid < 9 else ('筒' if tid < 18 else '索')
        if tile.startswith('0'):
            return f"赤{n}{suit}"
        return f"{n}{suit}"
    # 字牌
    honors = ['東', '南', '西', '北', '白', '發', '中']
    return honors[tid - 27]


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
