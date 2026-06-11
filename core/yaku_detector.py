# -*- coding: utf-8 -*-
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from functools import lru_cache

from str_converter import (
    hand_to_counts, tile_to_id, id_to_tile,
    is_honor, is_terminal, is_red_five, is_yaochu,
)

# suit constants
SUIT_MAN, SUIT_PIN, SUIT_SOU, SUIT_HONOR = 0, 1, 2, 3

# honor IDs
EAST, SOUTH, WEST, NORTH = 27, 28, 29, 30
HAKU, HATSU, CHUN = 31, 32, 33


@dataclass
class YakuInfo:
    name: str
    progress: float = 0.0
    closed_han: int = 0
    open_han: int = 0
    is_complete: bool = False
    main_suit: Optional[int] = None
    suit_count: int = 0


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _suit_of(tid: int) -> int:
    if tid < 9:
        return SUIT_MAN
    if tid < 18:
        return SUIT_PIN
    if tid < 27:
        return SUIT_SOU
    return SUIT_HONOR


def _number_of(tid: int) -> int:
    if is_honor(tid):
        return tid - 27
    return (tid % 9) + 1


def _all_tile_ids(hand: List[str], melds: List) -> List[int]:
    ids = [tile_to_id(t) for t in hand]
    for m in melds:
        for t in m.tiles:
            ids.append(tile_to_id(t))
    return ids


def _count_per_suit(ids: List[int]) -> Dict[int, int]:
    counts = {SUIT_MAN: 0, SUIT_PIN: 0, SUIT_SOU: 0, SUIT_HONOR: 0}
    for tid in ids:
        counts[_suit_of(tid)] += 1
    return counts


# ---------------------------------------------------------------------------
# mentsu decomposition (complete hand 13/14 tiles)
# ---------------------------------------------------------------------------

@dataclass
class MentsuBlock:
    kind: str         # 'seq' / 'tri' / 'pair' / 'kan'
    suit: int         # 0-3
    num: int          # 1-9 for suits, 1-7 for honors
    tile_ids: List[int] = field(default_factory=list)

    def is_sequence(self) -> bool:
        return self.kind == 'seq'

    def is_triplet(self) -> bool:
        return self.kind == 'tri'

    def is_pair(self) -> bool:
        return self.kind == 'pair'


def _mentsu_from_counts(counts9: Tuple[int, ...], suit: int) -> List[List[MentsuBlock]]:
    """戻り値: 全ての有効な面子分解のリスト（各分解は MentsuBlock のリスト）"""
    c = list(counts9)
    return _solve_mentsu(c, suit)


def _solve_mentsu(c: List[int], suit: int, start: int = 0) -> List[List[MentsuBlock]]:
    for i in range(start, 9):
        if c[i] > 0:
            first = i
            break
    else:
        return [[]]

    results = []
    num = first + 1

    # 刻子
    if c[first] >= 3:
        c2 = list(c)
        c2[first] -= 3
        for rest in _solve_mentsu(c2, suit, first):
            results.append([MentsuBlock('tri', suit, num, [suit * 9 + first] * 3)] + rest)
        if c[first] >= 4:
            c3 = list(c)
            c3[first] -= 4
            for rest in _solve_mentsu(c3, suit, first):
                results.append([MentsuBlock('tri', suit, num, [suit * 9 + first] * 4)] + rest)

    # 対子
    if c[first] >= 2:
        c2 = list(c)
        c2[first] -= 2
        for rest in _solve_mentsu(c2, suit, first):
            results.append([MentsuBlock('pair', suit, num, [suit * 9 + first] * 2)] + rest)

    # 順子
    if first <= 6 and c[first+1] > 0 and c[first+2] > 0:
        c2 = list(c)
        c2[first] -= 1
        c2[first+1] -= 1
        c2[first+2] -= 1
        for rest in _solve_mentsu(c2, suit, first):
            tids = [suit * 9 + first, suit * 9 + first + 1, suit * 9 + first + 2]
            results.append([MentsuBlock('seq', suit, num, tids)] + rest)

    # 孤立牌扱い（skip）
    c2 = list(c)
    c2[first] -= 1
    for rest in _solve_mentsu(c2, suit, first):
        results.append(rest)

    return results


def _choose_best_mentsu(decomps: List[List[MentsuBlock]]) -> List[MentsuBlock]:
    """4面子＋1雀頭を優先する。該当がなければ最大面子数を返す"""
    best = []
    best_groups = -1
    for d in decomps:
        groups = sum(1 for b in d if b.kind in ('seq', 'tri'))
        if groups == 4 and any(b.kind == 'pair' for b in d):
            return d  # 最適
        if groups > best_groups:
            best_groups = groups
            best = d
    return best


def decompose_hand(hand_counts: List[int], melds: List = None) -> Dict:
    """
    @title 手牌・副露の面子分解
    @description 手牌と副露の牌構成から、面子および雀頭の組み合わせを解析する。各スートの全分解直積から、最適な全体構成を探索する。
    @param {List[int]} hand_counts - 手牌の34種牌カウント
    @param {List} [melds=None] - 副露リスト
    @returns {Dict} 面子ブロック、雀頭、残り牌、完成フラグを含む辞書
    """
    # 副露面子
    blocks: List[MentsuBlock] = []

    if melds:
        for m in melds:
            tids = [tile_to_id(t) for t in m.tiles]
            suit = _suit_of(tids[0])
            # 槓子は4枚、順子/刻子は3枚の牌数に基づく判定
            if len(tids) >= 4:
                blocks.append(MentsuBlock('kan', suit, _number_of(tids[0]), tids))
            elif len(tids) == 3:
                num = _number_of(tids[0])
                if len(set(tids)) == 1:
                    blocks.append(MentsuBlock('tri', suit, num, tids))
                else:
                    blocks.append(MentsuBlock('seq', suit, num, tids))

    # 手牌の面子分解（萬子・筒子・索子の3色についてループ）
    hand_only_counts = list(hand_counts)
    decomps = []
    for suit in range(3):
        base = suit * 9
        counts9 = tuple(hand_only_counts[base:base+9])
        decomps.append(_mentsu_from_counts(counts9, suit))
    # 字牌（27から33のIDが字牌）
    honor_blocks = []
    for i in range(27, 34):
        if hand_only_counts[i] >= 3:
            honor_blocks.append(MentsuBlock('tri', SUIT_HONOR, i - 27 + 1, [i] * hand_only_counts[i]))
        elif hand_only_counts[i] == 2:
            honor_blocks.append(MentsuBlock('pair', SUIT_HONOR, i - 27 + 1, [i] * 2))
        elif hand_only_counts[i] == 4:
            honor_blocks.append(MentsuBlock('kan', SUIT_HONOR, i - 27 + 1, [i] * 4))

    # スートごとの分解パターンの直積を探索し、手牌全体で最適な組み合わせ（4面子1雀頭、またはグループ＋対子最大）を選択する
    import itertools
    best_hand_blocks = []
    best_groups_count = -1
    best_pairs_count = -1
    complete_hand_blocks = None

    d_man_list = decomps[0] if decomps[0] else [[]]
    d_pin_list = decomps[1] if decomps[1] else [[]]
    d_sou_list = decomps[2] if decomps[2] else [[]]

    for d_man, d_pin, d_sou in itertools.product(d_man_list, d_pin_list, d_sou_list):
        current_hand_blocks = list(honor_blocks) + d_man + d_pin + d_sou
        all_blocks = blocks + current_hand_blocks
        
        # 面子（順子・刻子・槓子）と対子をカウント
        groups_count = sum(1 for b in all_blocks if b.kind in ('seq', 'tri', 'kan'))
        pairs_count = sum(1 for b in all_blocks if b.kind == 'pair')
        
        # 4面子1雀頭（麻雀の標準的な和了形）を構成可能か判定
        if groups_count == 4 and pairs_count == 1:
            complete_hand_blocks = current_hand_blocks
            break
            
        # 完成しない場合は、面子数が多く、次いで対子数が多い分解を優先する
        if groups_count > best_groups_count:
            best_groups_count = groups_count
            best_pairs_count = pairs_count
            best_hand_blocks = current_hand_blocks
        elif groups_count == best_groups_count:
            if pairs_count > best_pairs_count:
                best_pairs_count = pairs_count
                best_hand_blocks = current_hand_blocks

    selected_hand_blocks = complete_hand_blocks if complete_hand_blocks is not None else best_hand_blocks
    blocks.extend(selected_hand_blocks)

    # 雀頭の抽出
    pair = None
    non_pair = []
    for b in blocks:
        if b.kind == 'pair':
            if pair is None:
                pair = b
            else:
                non_pair.append(b)
        else:
            non_pair.append(b)

    # 完成判定: 4面子 + 1雀頭
    groups = [b for b in non_pair if b.kind in ('seq', 'tri')]
    complete = len(groups) == 4 and pair is not None

    return {
        'blocks': non_pair,
        'pair': pair,
        'remaining': [],
        'complete': complete,
    }


# ---------------------------------------------------------------------------
# yaku checks
# ---------------------------------------------------------------------------

def analyze_pinfu(hand: List[str], melds: List, seat: int, chang: int, ju: int,
                  win_tile: Optional[str] = None) -> Optional[YakuInfo]:
    if melds and any(m.is_open for m in melds if hasattr(m, 'is_open')):
        return None
    counts = hand_to_counts(hand)
    dec = decompose_hand(counts, melds)
    if not dec['complete']:
        return None
    pair = dec['pair']
    pair_tid = pair.tile_ids[0] if pair else -1
    # 雀頭が役牌でない
    if is_honor(pair_tid):
        return None
    # 自風・場風の確認
    seat_wind = {0: EAST, 1: SOUTH, 2: WEST, 3: NORTH}[seat]
    round_wind = {0: EAST, 1: SOUTH, 2: WEST, 3: NORTH}[chang % 4]
    if pair_tid in (seat_wind, round_wind, HAKU, HATSU, CHUN):
        return None
    # 全面子が順子
    for b in dec['blocks']:
        if not b.is_sequence():
            return None
    # 待ちチェック（win_tile が与えられている場合）
    if win_tile:
        win_id = tile_to_id(win_tile)
        for b in dec['blocks']:
            if not b.is_sequence():
                continue
            for pos, pid in enumerate(b.tile_ids):
                if pid == win_id:
                    if pos == 1:
                        return None  # 嵌張
                    if pos == 0 and (win_id % 9) <= 1:
                        return None  # 辺張 (1-2待ち3)
                    if pos == 2 and (win_id % 9) >= 7:
                        return None  # 辺張 (8-9待ち7)
    return YakuInfo('pinfu', progress=1.0, closed_han=1, open_han=0, is_complete=True)


def analyze_iipeikou(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    if melds and any(m.is_open for m in melds if hasattr(m, 'is_open')):
        return None
    counts = hand_to_counts(hand)
    dec = decompose_hand(counts, melds)
    seqs = [b for b in dec['blocks'] if b.is_sequence()]
    for i in range(len(seqs)):
        for j in range(i + 1, len(seqs)):
            if seqs[i].suit == seqs[j].suit and seqs[i].num == seqs[j].num:
                return YakuInfo('iipeikou', progress=1.0, closed_han=1, open_han=0, is_complete=True)
    return None


def analyze_ittsuu(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    for suit in range(3):
        base = suit * 9
        has_123 = any(t in range(base, base+3) for t in all_ids if not is_honor(t))
        has_456 = any(t in range(base+3, base+6) for t in all_ids if not is_honor(t))
        has_789 = any(t in range(base+6, base+9) for t in all_ids if not is_honor(t))
        if has_123 and has_456 and has_789:
            # 完全成立確認: 各3枚が実際に順子として存在するか
            counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
            seg1 = sum(counts[base:base+3])
            seg2 = sum(counts[base+3:base+6])
            seg3 = sum(counts[base+6:base+9])
            complete = seg1 >= 3 and seg2 >= 3 and seg3 >= 3
            if complete:
                is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
                return YakuInfo('ittsuu', progress=1.0, closed_han=2, open_han=1, is_complete=True,
                                main_suit=suit)
            # 進行度
            progress = sum([seg1 >= 3, seg2 >= 3, seg3 >= 3]) / 3.0
            return YakuInfo('ittsuu', progress=progress, closed_han=2, open_han=1,
                            is_complete=False, main_suit=suit)
    return None


def analyze_sanshoku(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    dec = decompose_hand(counts, melds)

    if dec['complete']:
        seqs = [b for b in dec['blocks'] if b.is_sequence()]
        for num in range(1, 8):
            has_m = any(s.suit == SUIT_MAN and s.num == num for s in seqs)
            has_p = any(s.suit == SUIT_PIN and s.num == num for s in seqs)
            has_s = any(s.suit == SUIT_SOU and s.num == num for s in seqs)
            if has_m and has_p and has_s:
                is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
                return YakuInfo('sanshoku', progress=1.0, closed_han=2, open_han=1, is_complete=True)

    for num in range(1, 8):
        ids_needed = [num - 1, num, num + 1]
        suits_found = 0
        for suit in range(3):
            base = suit * 9
            if all(counts[base + n] >= 1 for n in ids_needed):
                suits_found += 1
        if suits_found == 2:
            return YakuInfo('sanshoku', progress=2/3, closed_han=2, open_han=1, is_complete=False)

    return None


def analyze_sanshoku_doukou(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    for num in range(1, 10):
        suits_found = 0
        for suit in range(3):
            tid = suit * 9 + (num - 1)
            if counts[tid] >= 3:
                suits_found += 1
        if suits_found >= 3:
            is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
            return YakuInfo('sanshoku_doukou', progress=1.0, closed_han=2, open_han=2, is_complete=True)
        if suits_found == 2:
            return YakuInfo('sanshoku_doukou', progress=2/3, closed_han=2, open_han=2, is_complete=False)
    return None


def analyze_toitoi(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    """
    @title 対々和の判定
    @description 手牌および副露の構成から、対々和（トイトイ）の完成度または進行度を判定する。
    @param {List[str]} hand - 手牌リスト
    @param {List} melds - 副露リスト
    @returns {Optional[YakuInfo]} 対々和の役情報。条件を満たさない場合は None
    """
    counts = hand_to_counts(hand)
    dec = decompose_hand(counts, melds)

    n_triplets = sum(1 for b in dec['blocks'] if b.is_triplet() or b.kind == 'kan')
    n_pairs = sum(1 for b in dec['blocks'] if b.is_pair())
    if dec['pair']:
        n_pairs += 1

    raw_count = n_triplets + n_pairs
    is_complete = dec['complete']

    # 順子チェックは完成時のみ（進行中は順子を壊してトイトイへ向かえる）
    if is_complete:
        has_sequence = any(b.is_sequence() for b in dec['blocks'])
        if has_sequence:
            return None
        return YakuInfo('toitoi', progress=1.0, closed_han=2, open_han=2, is_complete=True)
    elif raw_count >= 3:
        progress_val = min(float(raw_count) / 5.0, 0.95)
        return YakuInfo('toitoi', progress=progress_val, closed_han=2, open_han=2, is_complete=False)

    return None


def _calc_chanta_progress(hand: List[str], melds: List, allow_honors: bool) -> float:
    """混全(allow_honors=True) or 純全(allow_honors=False) の進行度"""
    all_ids = _all_tile_ids(hand, melds)
    total_groups = len(melds) if melds else 0
    # 手牌内のグループ数を概算
    hand_counts = hand_to_counts(hand)
    dec = decompose_hand(hand_counts, melds)
    groups = [b for b in dec['blocks'] if b.kind in ('seq', 'tri')]
    total = len(groups)
    if total == 0:
        return 0.0

    yaochu_groups = 0
    for b in groups:
        has_yao = any(is_yaochu(t) for t in b.tile_ids)
        if allow_honors:
            if has_yao:
                yaochu_groups += 1
        else:
            if has_yao and not any(is_honor(t) for t in b.tile_ids):
                yaochu_groups += 1

    # 雀頭もチェック
    pair = dec.get('pair')
    if pair:
        total += 1
        if allow_honors:
            if any(is_yaochu(t) for t in pair.tile_ids):
                yaochu_groups += 1
        else:
            if any(is_yaochu(t) for t in pair.tile_ids) and not any(is_honor(t) for t in pair.tile_ids):
                yaochu_groups += 1

    return yaochu_groups / max(total, 1)


def analyze_chanta(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    dec = decompose_hand(counts, melds)
    progress = _calc_chanta_progress(hand, melds, allow_honors=True)
    if dec['complete'] and progress >= 1.0:
        is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
        return YakuInfo('chanta', progress=1.0, closed_han=2, open_han=1, is_complete=True)
    if progress > 0:
        return YakuInfo('chanta', progress=min(progress, 0.95), closed_han=2, open_han=1, is_complete=False)
    return None


def analyze_junchan(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    if any(is_honor(t) for t in all_ids):
        return None
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    dec = decompose_hand(counts, melds)
    progress = _calc_chanta_progress(hand, melds, allow_honors=False)
    if dec['complete'] and progress >= 1.0:
        is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
        return YakuInfo('junchan', progress=1.0, closed_han=3, open_han=2, is_complete=True)
    if progress > 0:
        return YakuInfo('junchan', progress=min(progress, 0.95), closed_han=3, open_han=2, is_complete=False)
    return None


def analyze_honroutou(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    for tid in all_ids:
        if not is_yaochu(tid):
            return None
    is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
    return YakuInfo('honroutou', progress=1.0, closed_han=2, open_han=2, is_complete=True,
                    suit_count=len(all_ids))


def analyze_shousangen(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    san_gen = [HAKU, HATSU, CHUN]
    triplets = 0
    has_pair = False
    for sg in san_gen:
        if counts[sg] >= 3:
            triplets += 1
        elif counts[sg] == 2:
            has_pair = True
    if triplets >= 2 and has_pair:
        is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
        return YakuInfo('shousangen', progress=1.0, closed_han=2, open_han=2, is_complete=True)
    progress = triplets / 2.0 + (0.5 if has_pair else 0)
    if progress > 0:
        return YakuInfo('shousangen', progress=min(progress, 1.0), closed_han=2, open_han=2, is_complete=False)
    return None


def analyze_ryanpeikou(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    if melds and any(m.is_open for m in melds if hasattr(m, 'is_open')):
        return None
    counts = hand_to_counts(hand)
    dec = decompose_hand(counts, melds)
    seqs = [b for b in dec['blocks'] if b.is_sequence()]
    # 同じ順子のペアを数える
    pairs_found = 0
    used = [False] * len(seqs)
    for i in range(len(seqs)):
        if used[i]:
            continue
        for j in range(i + 1, len(seqs)):
            if used[j]:
                continue
            if seqs[i].suit == seqs[j].suit and seqs[i].num == seqs[j].num:
                pairs_found += 1
                used[i] = used[j] = True
                break
    if pairs_found >= 2:
        return YakuInfo('ryanpeikou', progress=1.0, closed_han=3, open_han=0, is_complete=True)
    if pairs_found == 1:
        return YakuInfo('ryanpeikou', progress=0.5, closed_han=3, open_han=0, is_complete=False)
    return None


def analyze_honitsu(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    counts = _count_per_suit(all_ids)
    non_honor = {k: v for k, v in counts.items() if k != SUIT_HONOR}
    dominant = max(non_honor, key=non_honor.get) if non_honor else 0
    dominant_count = non_honor.get(dominant, 0)
    honor_count = counts.get(SUIT_HONOR, 0)
    total_non_honor = sum(non_honor.values())

    if dominant_count > 0 and honor_count > 0 and dominant_count + honor_count == len(all_ids):
        is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
        return YakuInfo('honitsu', progress=1.0, closed_han=3, open_han=2,
                        is_complete=True, main_suit=dominant, suit_count=dominant_count)

    # 進行度: 主色の割合
    if dominant_count >= 5:
        progress = (dominant_count - 5) / (14 - 5)
        return YakuInfo('honitsu', progress=min(progress, 1.0), closed_han=3, open_han=2,
                        is_complete=False, main_suit=dominant, suit_count=dominant_count)
    return None


def analyze_chinitsu(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    if any(is_honor(t) for t in all_ids):
        # 進行度: 字牌がない状態での単色率
        counts = _count_per_suit(all_ids)
        counts.pop(SUIT_HONOR, None)
        dominant = max(counts, key=counts.get) if counts else 0
        dominant_count = counts.get(dominant, 0)
        if dominant_count >= 7:
            progress = (dominant_count - 7) / (14 - 7)
            return YakuInfo('chinitsu', progress=min(progress, 1.0), closed_han=6, open_han=5,
                            is_complete=False, main_suit=dominant, suit_count=dominant_count)
        return None

    suit = _suit_of(all_ids[0]) if all_ids else 0
    same = all(_suit_of(t) == suit for t in all_ids) if all_ids else False
    if same:
        is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
        return YakuInfo('chinitsu', progress=1.0, closed_han=6, open_han=5,
                        is_complete=True, main_suit=suit, suit_count=len(all_ids))

    counts = _count_per_suit(all_ids)
    counts.pop(SUIT_HONOR, None)
    dominant = max(counts, key=counts.get) if counts else 0
    dominant_count = counts.get(dominant, 0)
    if dominant_count >= 7:
        progress = (dominant_count - 7) / (14 - 7)
        return YakuInfo('chinitsu', progress=min(progress, 1.0), closed_han=6, open_han=5,
                        is_complete=False, main_suit=dominant, suit_count=dominant_count)
    return None


def analyze_chiitoitsu(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    if melds and any(m.is_open for m in melds if hasattr(m, 'is_open')):
        return None
    counts = hand_to_counts(hand)
    pairs = sum(1 for c in counts if c >= 2)
    if pairs >= 7:
        return YakuInfo('chiitoitsu', progress=1.0, closed_han=2, open_han=0, is_complete=True)
    if pairs >= 4:
        return YakuInfo('chiitoitsu', progress=pairs / 7.0, closed_han=2, open_han=0, is_complete=False)
    return None


def analyze_yakuhai(hand: List[str], melds: List, seat: int, chang: int, ju: int,
                    **kwargs) -> Optional[YakuInfo]:
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    seat_wind = {0: EAST, 1: SOUTH, 2: WEST, 3: NORTH}[seat]
    round_wind = {0: EAST, 1: SOUTH, 2: WEST, 3: NORTH}[chang % 4]
    targets = [seat_wind, round_wind, HAKU, HATSU, CHUN]
    # 重複排除
    unique_targets = list(dict.fromkeys(targets))

    total_han = 0
    for t in unique_targets:
        if counts[t] >= 3:
            total_han += 1

    if total_han > 0:
        is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
        return YakuInfo('yakuhai', progress=1.0, closed_han=total_han, open_han=total_han,
                        is_complete=True)

    # 進行度 (対子があれば進んでいる)
    for t in unique_targets:
        if counts[t] == 2:
            return YakuInfo('yakuhai', progress=0.5, closed_han=1, open_han=1, is_complete=False)
    return None


def analyze_daburi(hand: List[str], melds: List, tsumo_turn: int = 0, **kwargs) -> Optional[YakuInfo]:
    if tsumo_turn <= 1 and not melds:
        return YakuInfo('daburi', progress=1.0, closed_han=2, open_han=0, is_complete=True)
    return None


def analyze_tanyao(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    all_ids = _all_tile_ids(hand, melds)
    for tid in all_ids:
        if is_yaochu(tid):
            return None
    is_open = any(m.is_open for m in melds if hasattr(m, 'is_open'))
    return YakuInfo('tanyao', progress=1.0, closed_han=1, open_han=1, is_complete=True)


def analyze_sanankou(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    counts = hand_to_counts(hand)
    # 手牌内の暗刻数をカウント
    concealed_triplets = sum(1 for i in range(34) if counts[i] >= 3)
    if concealed_triplets >= 3:
        return YakuInfo('sanankou', progress=1.0, closed_han=2, open_han=2, is_complete=True)
    if concealed_triplets >= 2:
        return YakuInfo('sanankou', progress=concealed_triplets / 3.0, closed_han=2, open_han=2,
                        is_complete=False)
    return None


def analyze_sankantsu(hand: List[str], melds: List, **kwargs) -> Optional[YakuInfo]:
    if not melds:
        return None
    kans = sum(1 for m in melds if hasattr(m, 'type') and m.type in (3, 4))
    if kans >= 3:
        return YakuInfo('sankantsu', progress=1.0, closed_han=2, open_han=2, is_complete=True)
    return None


# ---------------------------------------------------------------------------
# progress helper for unfinished sanshoku / ittsuu (for use mid-game)
# ---------------------------------------------------------------------------

def _sanshoku_progress_3sided(hand: List[str], melds: List) -> Optional[YakuInfo]:
    """3色同順の進行度を「あと何色足りないか」ベースで計算"""
    counts = hand_to_counts(hand + [t for m in melds for t in m.tiles])
    best_num = 0
    best_suits = 0
    for num in range(1, 8):
        suits = 0
        for suit in range(3):
            base = suit * 9
            n = num - 1
            if all(counts[base + n + d] >= 1 for d in range(3)):
                suits += 1
        if suits > best_suits:
            best_suits = suits
            best_num = num
    if best_suits >= 2:
        return YakuInfo('sanshoku', progress=best_suits / 3.0, closed_han=2, open_han=1,
                        is_complete=False)
    return None


# ---------------------------------------------------------------------------
# main entry point
# ---------------------------------------------------------------------------

# 検出関数のレジストリ
_DETECTORS: List[dict] = [
    {'name': 'daburi',       'fn': analyze_daburi,       'use_hand': True, 'use_melds': True, 'needs_turn': True},
    {'name': 'tanyao',       'fn': analyze_tanyao,       'use_hand': True, 'use_melds': True},
    {'name': 'yakuhai',      'fn': analyze_yakuhai,      'use_hand': True, 'use_melds': True, 'needs_seat': True},
    {'name': 'pinfu',        'fn': analyze_pinfu,        'use_hand': True, 'use_melds': True, 'needs_seat': True, 'needs_wintile': True},
    {'name': 'iipeikou',     'fn': analyze_iipeikou,     'use_hand': True, 'use_melds': True},
    {'name': 'chiitoitsu',   'fn': analyze_chiitoitsu,   'use_hand': True, 'use_melds': True},
    {'name': 'sanshoku',     'fn': analyze_sanshoku,     'use_hand': True, 'use_melds': True},
    {'name': 'ittsuu',       'fn': analyze_ittsuu,       'use_hand': True, 'use_melds': True},
    {'name': 'honitsu',      'fn': analyze_honitsu,      'use_hand': True, 'use_melds': True},
    {'name': 'chinitsu',     'fn': analyze_chinitsu,     'use_hand': True, 'use_melds': True},
    {'name': 'toitoi',       'fn': analyze_toitoi,       'use_hand': True, 'use_melds': True},
    {'name': 'sanshoku_doukou', 'fn': analyze_sanshoku_doukou, 'use_hand': True, 'use_melds': True},
    {'name': 'chanta',       'fn': analyze_chanta,       'use_hand': True, 'use_melds': True},
    {'name': 'junchan',      'fn': analyze_junchan,      'use_hand': True, 'use_melds': True},
    {'name': 'honroutou',    'fn': analyze_honroutou,    'use_hand': True, 'use_melds': True},
    {'name': 'shousangen',   'fn': analyze_shousangen,   'use_hand': True, 'use_melds': True},
    {'name': 'ryanpeikou',   'fn': analyze_ryanpeikou,    'use_hand': True, 'use_melds': True},
    {'name': 'sanankou',     'fn': analyze_sanankou,     'use_hand': True, 'use_melds': True},
    {'name': 'sankantsu',    'fn': analyze_sankantsu,    'use_hand': True, 'use_melds': True},
]


def analyze_all(hand: List[str], melds: List,
                seat: int = 0, chang: int = 0, ju: int = 0,
                win_tile: Optional[str] = None,
                tsumo_turn: int = 0) -> Dict[str, YakuInfo]:
    results = {}
    for det in _DETECTORS:
        try:
            kwargs = {
                'hand': hand,
                'melds': melds,
                'seat': seat,
                'chang': chang,
                'ju': ju,
                'win_tile': win_tile,
                'tsumo_turn': tsumo_turn,
            }
            yi = det['fn'](**kwargs)
            if yi is not None:
                results[yi.name] = yi
        except Exception:
            continue
    return results
