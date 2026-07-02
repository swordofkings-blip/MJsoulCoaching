# -*- coding: utf-8 -*-
"""
@title 役満評価器 (v1 補完)
@description 役満手の進行状態を管理し、v2 yakuman_v2 の補助として
              特殊タプル生成に必要な情報を提供する。
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from str_converter import (
    hand_to_counts, tile_to_id, id_to_tile,
    is_honor, is_terminal, is_yaochu,
)


# ---------------------------------------------------------------------------
# 定数
# ---------------------------------------------------------------------------

# 老頭・字牌のID（国士無双用）
YAOCHU_IDS = [0, 8, 9, 17, 18, 26] + list(range(27, 34))

# 三元牌のID
SANGEN_IDS = [31, 32, 33]  # 白(31), 發(32), 中(33)

# 風牌のID
KAZE_IDS = [27, 28, 29, 30]  # 東(27), 南(28), 西(29), 北(30)

# 緑一色候補牌のID
RYUU_ISOU_IDS = [10, 11, 12, 14, 16, 31, 32]  # 2s,3s,4s,6s,8s,白,發


@dataclass
class YakumanResult:
    """役満の評価結果"""
    name: str
    progress: float  # 0.0〜1.0
    shanten: int  # 役満専用シャンテン数
    is_possible: bool  # 成立可能か


class YakumanEvaluator:
    """全役満の進行度計算＋成立可能性判定"""

    def __init__(self, state):
        self.state = state

    def evaluate_all(self) -> Dict[str, YakumanResult]:
        """全役満の評価結果を返す"""
        results = {}
        hand_counts = self.state.my_hand_counts()
        visible = self.state.all_visible_counts()
        melds = self.state.my_melds

        # 門前チェック
        has_open_meld = any(m.is_open for m in melds)

        results['kokushi'] = self._eval_kokushi(hand_counts, visible)
        results['suuankou'] = self._eval_suuankou(hand_counts, melds, visible)
        results['daisangen'] = self._eval_daisangen(hand_counts, melds, visible)
        results['tsuuiisou'] = self._eval_tsuuiisou(hand_counts, melds, visible)
        results['chinroutou'] = self._eval_chinroutou(hand_counts, melds, visible)
        results['chuuren'] = self._eval_chuuren(hand_counts, visible)
        results['daisuushii'] = self._eval_daisuushii(hand_counts, melds, visible)
        results['shousuushii'] = self._eval_shousuushii(hand_counts, melds, visible)
        results['ryuuiisou'] = self._eval_ryuuiisou(hand_counts, melds, visible)
        results['suukantsu'] = self._eval_suukantsu(melds, visible)

        # 門前限定役満の無効化
        if has_open_meld:
            results['kokushi'].is_possible = False
            results['suuankou'].is_possible = False
            results['chuuren'].is_possible = False

        return results

    def best_progress(self) -> float:
        """全役満のうち最高の進行度を返す"""
        results = self.evaluate_all()
        if not results:
            return 0.0
        return max(r.progress for r in results.values())

    def best_shanten(self) -> int:
        """全役満のうち最良（最小）のシャンテン数を返す"""
        results = self.evaluate_all()
        possible = [r for r in results.values() if r.is_possible]
        if not possible:
            return 99
        return min(r.shanten for r in possible)

    # 門前限定役満の定数
    CLOSED_ONLY_YAKUMAN = {'kokushi', 'suuankou', 'chuuren'}

    def should_seal_melds(self) -> bool:
        """副露封印モード是否（門前限定役満を狙う場合）"""
        results = self.evaluate_all()

        best_progress = 0.0
        best_is_closed_only = False

        for name, result in results.items():
            if not result.is_possible:
                continue
            if result.shanten > 2:
                continue
            is_closed = name in self.CLOSED_ONLY_YAKUMAN
            # 同progress時は副露可の役満を優先（門前限定縛りを避ける）
            if result.progress > best_progress or (
                result.progress == best_progress and best_is_closed_only and not is_closed
            ):
                best_progress = result.progress
                best_is_closed_only = is_closed

        # 進行度が高く、門前限定役満が最良なら封印
        return best_progress >= 0.5 and best_is_closed_only

    def attack_boost(self) -> float:
        """攻撃度ブースト値を返す（0.0〜1.0）"""
        results = self.evaluate_all()
        max_progress = 0.0
        for r in results.values():
            if r.is_possible and r.progress > max_progress:
                max_progress = r.progress
        return max_progress

    def opponent_yakuman_threat(self, opponent_seat: int) -> float:
        """他家の役満脅威度を返す（0.0〜1.0）"""
        # パラメータ読み込み
        params = getattr(self.state, 'params', {})
        yakuman_cfg = params.get('yakuman_strategy', {})
        threat_reduction = yakuman_cfg.get('YAKUMAN_THREAT_REDUCTION', 0.2)

        threat = 0.0

        # 国士無双の警戒: 中張牌から捨てていて、么九牌が出てきている
        river = self.state.river[opponent_seat]
        yaochu_discard_count = 0
        tanyao_discard_count = 0
        for t in river:
            tid = tile_to_id(t)
            if is_yaochu(tid):
                yaochu_discard_count += 1
            elif not is_honor(tid):
                tanyao_discard_count += 1
        if tanyao_discard_count >= 3 and yaochu_discard_count >= 2:
            threat = max(threat, 0.3)

        # 四槓子の警戒: カン数
        kan_count = sum(1 for m in self.state.melds[opponent_seat]
                       if getattr(m, 'type', '') in ('ankan', 'daiminkan', 'kakan'))
        if kan_count >= 3:
            threat = max(threat, 0.4)
        elif kan_count >= 2:
            threat = max(threat, 0.2)

        # 大四喜・小四喜の警戒: 風牌の副露数
        kaze_meld_count = 0
        for m in self.state.melds[opponent_seat]:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) in KAZE_IDS:
                        kaze_meld_count += 1
                        break
        if kaze_meld_count >= 3:
            threat = max(threat, 0.5)
        elif kaze_meld_count >= 2:
            threat = max(threat, 0.3)

        # 大三元の警戒: 三元牌の副露数
        sangen_meld_count = 0
        for m in self.state.melds[opponent_seat]:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) in SANGEN_IDS:
                        sangen_meld_count += 1
                        break
        if sangen_meld_count >= 2:
            threat = max(threat, 0.4)

        return min(1.0, threat)

    # -----------------------------------------------------------------------
    # 各役満の評価メソッド
    # -----------------------------------------------------------------------

    def _eval_kokushi(self, hand_counts: List[int], visible: List[int]) -> YakumanResult:
        """国士無双の評価"""
        # 所持している老頭・字牌の種類数
        owned_types = sum(1 for i in YAOCHU_IDS if hand_counts[i] >= 1)
        # 必要な種類数（13種）
        shanten = 13 - owned_types

        # 成立可能性: 各種類が山に残っているか
        required = [i for i in YAOCHU_IDS if hand_counts[i] == 0]
        impossible = False
        for tid in required:
            remaining = 4 - visible[tid]
            if remaining <= 0:
                impossible = True
                break

        progress = owned_types / 13.0 if not impossible else 0.0
        return YakumanResult(
            name='国士無双',
            progress=progress,
            shanten=shanten,
            is_possible=not impossible
        )

    def _eval_suuankou(self, hand_counts: List[int], melds: List,
                       visible: List[int]) -> YakumanResult:
        """四暗刻の評価（門前限定）"""
        has_open_meld = any(m.is_open for m in melds)
        if has_open_meld:
            return YakumanResult(name='四暗刻', progress=0.0, shanten=99, is_possible=False)

        ankou_count = sum(1 for i in range(34) if hand_counts[i] >= 3)
        pair_count = sum(1 for i in range(34) if hand_counts[i] == 2)

        shanten = 4 - ankou_count - min(pair_count, 4 - ankou_count)

        # 成立可能性: 暗刻に使える牌種が山に充分あるか
        # 既存暗刻 + 山に残りがある対子 の合計が4未満なら不可能
        potential = ankou_count
        for i in range(34):
            if hand_counts[i] == 2:
                remaining = 4 - visible[i]
                if remaining >= 1:
                    potential += 1

        progress = ankou_count / 4.0
        if pair_count > 0:
            progress += 0.1
        progress = min(1.0, progress)

        return YakumanResult(
            name='四暗刻',
            progress=progress,
            shanten=max(0, shanten),
            is_possible=(potential >= 4)
        )

    def _eval_daisangen(self, hand_counts: List[int], melds: List,
                        visible: List[int]) -> YakumanResult:
        """大三元の評価"""
        # 三元牌の刻子数をカウント
        sangen_kouzi = sum(1 for i in SANGEN_IDS if hand_counts[i] >= 3)

        # 副露中の三元牌も加算
        for m in melds:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) in SANGEN_IDS:
                        sangen_kouzi += 1
                        break

        shanten = 3 - sangen_kouzi

        # 成立可能性: 白/發/中が全て3枚ずつ見えてたら不可
        impossible = False
        for tid in SANGEN_IDS:
            if hand_counts[tid] >= 3:
                continue
            remaining = 4 - visible[tid]
            if remaining <= 0:
                impossible = True
                break

        progress = sangen_kouzi / 3.0
        return YakumanResult(
            name='大三元',
            progress=progress,
            shanten=shanten,
            is_possible=not impossible
        )

    def _eval_tsuuiisou(self, hand_counts: List[int], melds: List,
                        visible: List[int]) -> YakumanResult:
        """字一色の評価"""
        honor_counts = hand_counts[27:34]
        honor_triplets = sum(1 for c in honor_counts if c >= 3)
        honor_pairs = sum(1 for c in honor_counts if c == 2)

        non_honor_count = sum(hand_counts[i] for i in range(27))
        honor_count = sum(hand_counts[i] for i in range(27, 34))

        # 既存の字牌面子数（副露含む）
        formed = honor_triplets
        for m in melds:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) >= 27:
                        formed += 1
                        break

        # シャンテン: 非字牌置換 + 足りない面子（対子は0.5面子とみなす）
        shanten = non_honor_count + max(0, 4 - formed - honor_pairs // 2)

        # 成立可能性
        impossible = False
        for tid in range(27, 34):
            if hand_counts[tid] >= 1:
                continue
            if 4 - visible[tid] <= 0:
                impossible = True
                break

        progress = honor_count / 14.0
        return YakumanResult(
            name='字一色',
            progress=progress,
            shanten=max(0, shanten),
            is_possible=not impossible
        )

    def _eval_chinroutou(self, hand_counts: List[int], melds: List,
                         visible: List[int]) -> YakumanResult:
        """清老頭の評価"""
        terminal_ids = [i for i in range(27) if is_terminal(i)]
        terminal_triplets = sum(1 for i in terminal_ids if hand_counts[i] >= 3)
        terminal_pairs = sum(1 for i in terminal_ids if hand_counts[i] == 2)

        terminal_count = sum(hand_counts[i] for i in terminal_ids)
        non_terminal_count = sum(hand_counts[i] for i in range(27) if not is_terminal(i))

        # シャンテン: 中張牌置換 + 足りない面子（対子は0.5面子）
        shanten = non_terminal_count + max(0, 4 - terminal_triplets - terminal_pairs // 2)

        # 成立可能性
        required_terminals = terminal_ids
        impossible = False
        for tid in required_terminals:
            if hand_counts[tid] >= 1:
                continue
            if 4 - visible[tid] <= 0:
                impossible = True
                break

        progress = terminal_count / 14.0
        return YakumanResult(
            name='清老頭',
            progress=progress,
            shanten=max(0, shanten),
            is_possible=not impossible
        )

    def _eval_chuuren(self, hand_counts: List[int], visible: List[int]) -> YakumanResult:
        """九蓮宝燈の評価"""
        best_progress = 0.0
        best_shanten = 99
        best_possible = False

        for suit_start in [0, 9, 18]:
            suit = hand_counts[suit_start:suit_start + 9]
            total = sum(suit)

            if total < 5:
                continue

            # 九蓮宝燈の必要構成: 1x3, 2x1, 3x1, 4x1, 5x1, 6x1, 7x1, 8x1, 9x3
            required = [3, 1, 1, 1, 1, 1, 1, 1, 3]  # 各枚数

            # 各牌の充足数を計算
            satisfied = sum(1 for i in range(9) if suit[i] >= required[i])

            # 不足枚数
            shanten = sum(max(0, required[i] - suit[i]) for i in range(9))

            # 2-8のうち0枚の牌も考慮（九蓮ではないため不足）
            # 九蓮の形に加えて、余剰牌も考慮（手牌には14枚あるはず）
            # 余剰牌があれば待ち牌の候補になる

            # 成立可能性
            impossible = False
            tid_1 = suit_start
            tid_9 = suit_start + 8
            if 4 - visible[tid_1] <= 0 and suit[0] < 3:
                impossible = True
            if 4 - visible[tid_9] <= 0 and suit[8] < 3:
                impossible = True

            progress = satisfied / 9.0

            if progress > best_progress:
                best_progress = progress
                best_shanten = shanten
                best_possible = not impossible

        return YakumanResult(
            name='九蓮宝燈',
            progress=best_progress,
            shanten=best_shanten,
            is_possible=best_possible
        )

    def _eval_daisuushii(self, hand_counts: List[int], melds: List,
                         visible: List[int]) -> YakumanResult:
        """大四喜の評価"""
        # 風牌の刻子数をカウント
        kaze_kouzi = 0
        for tid in KAZE_IDS:
            if hand_counts[tid] >= 3:
                kaze_kouzi += 1

        # 副露中の風牌も加算
        for m in melds:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) in KAZE_IDS:
                        kaze_kouzi += 1
                        break

        shanten = 4 - kaze_kouzi

        # 成立可能性: 風牌の刻子が4組作れないなら不可
        impossible = False
        for tid in KAZE_IDS:
            remaining = 4 - visible[tid]
            if remaining <= 0:
                impossible = True
                break

        progress = kaze_kouzi / 4.0
        return YakumanResult(
            name='大四喜',
            progress=progress,
            shanten=shanten,
            is_possible=not impossible
        )

    def _eval_shousuushii(self, hand_counts: List[int], melds: List,
                          visible: List[int]) -> YakumanResult:
        """小四喜の評価"""
        # 風牌の刻子数と対子数
        kaze_kouzi = 0
        kaze_pair = 0
        for tid in KAZE_IDS:
            if hand_counts[tid] >= 3:
                kaze_kouzi += 1
            elif hand_counts[tid] >= 2:
                kaze_pair += 1

        # 副露中の風牌も加算
        for m in melds:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) in KAZE_IDS:
                        kaze_kouzi += 1
                        break

        shanten = 3 - kaze_kouzi  # 刻子3組必要（対子は面子としてカウントしない）

        # 成立可能性: 風牌の刻子3組が作れないなら不可
        impossible = False
        kaze_available = sum(1 for tid in KAZE_IDS if 4 - visible[tid] > 0)
        if kaze_available < 3:
            impossible = True

        progress = kaze_kouzi / 3.0
        return YakumanResult(
            name='小四喜',
            progress=progress,
            shanten=shanten,
            is_possible=not impossible
        )

    def _eval_ryuuiisou(self, hand_counts: List[int], melds: List,
                        visible: List[int]) -> YakumanResult:
        """緑一色の評価"""
        ryuu_triplets = sum(1 for i in RYUU_ISOU_IDS if hand_counts[i] >= 3)
        ryuu_pairs = sum(1 for i in RYUU_ISOU_IDS if hand_counts[i] == 2)

        ryuu_count = sum(hand_counts[i] for i in RYUU_ISOU_IDS)
        total_tiles = sum(hand_counts)
        non_ryuu_count = total_tiles - ryuu_count

        # 副露も加算
        formed = ryuu_triplets
        for m in melds:
            if m.is_open:
                for t in m.tiles:
                    if tile_to_id(t) in RYUU_ISOU_IDS:
                        formed += 1
                        break

        # シャンテン: 非緑牌置換 + 足りない面子（対子は0.5面子）
        shanten = non_ryuu_count + max(0, 4 - formed - ryuu_pairs // 2)

        # 成立可能性
        total_ryuu_available = sum(4 - visible[i] for i in RYUU_ISOU_IDS)
        impossible = total_ryuu_available < total_tiles

        progress = ryuu_count / total_tiles if total_tiles > 0 else 0.0
        return YakumanResult(
            name='緑一色',
            progress=progress,
            shanten=max(0, shanten),
            is_possible=not impossible
        )

    def _eval_suukantsu(self, melds: List, visible: List[int]) -> YakumanResult:
        """四槓子の評価"""
        # 槓子数をカウント
        kan_count = 0
        for m in melds:
            if hasattr(m, 'type') and m.type in ('ankan', 'daiminkan', 'kakan'):
                kan_count += 1

        shanten = 4 - kan_count

        # 成立可能性: ①山に残ってる牌の種類が4種以下、②手牌の暗刻数が3つ以上で槓にできる対子が1つもない
        hand_counts = self.state.my_hand_counts()
        total_available = sum(1 for i in range(34) if 4 - visible[i] > 0)

        impossible = False
        if total_available < 4:
            impossible = True
        elif kan_count >= 3:
            # 暗刻数が3つ以上で、槓にできる対子が1つもない場合
            ankou_count = sum(1 for i in range(34) if hand_counts[i] >= 3)
            pair_count = sum(1 for i in range(34) if hand_counts[i] >= 2)
            if ankou_count >= 3 and pair_count <= ankou_count:
                impossible = True

        progress = kan_count / 4.0
        return YakumanResult(
            name='四槓子',
            progress=progress,
            shanten=shanten,
            is_possible=not impossible
        )
