# -*- coding: utf-8 -*-
"""
@title ベイズ聴牌確率推定
@description 模擬打牌履歴（摸切か手出しか）と副露数から、
              他家の聴牌確率をベイズ的に推定する簡易関数。
"""

def estimate_tenpai_prob(moqie, damaten_rate: float = 0.15, open_melds: int = 0) -> float:
    tedashi = sum(1 for m in moqie if not m)
    total = len(moqie)

    if total == 0:
        return 0.002

    est_shanten = max(0.0, 3.3 - tedashi * 0.7 - open_melds * 0.3)
    if est_shanten <= 0.5:
        prob = 0.5 + 0.5 * (tedashi / max(total, 1))
    elif est_shanten <= 2.0:
        prob = 0.3 * (1.0 - (est_shanten - 0.5) / 1.5)
    else:
        prob = 0.02 * (1.0 - (est_shanten - 2.0) / 3.0)

    prob = max(prob, damaten_rate * 0.05)
    return min(1.0, prob)
