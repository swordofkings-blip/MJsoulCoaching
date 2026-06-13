# -*- coding: utf-8 -*-

class FuzzyLogicEngine:
    def __init__(self, params: dict):
        self.params = params

    def _membership_low(self, val: float, bound: float) -> float:
        if bound <= 0.0:
            return 1.0 if val <= 0.0 else 0.0
        return max(0.0, 1.0 - val / bound)

    def _membership_medium(self, val: float, peak: float, width: float) -> float:
        if width <= 0.0:
            return 1.0 if val == peak else 0.0
        return max(0.0, 1.0 - abs(val - peak) / width)

    def _membership_high(self, val: float, bound: float) -> float:
        if bound >= 1.0:
            return 1.0 if val >= 1.0 else 0.0
        return max(0.0, (val - bound) / (1.0 - bound))

    def evaluate_strategy(self, base_attack: float, max_threat: float) -> tuple[str, dict]:
        y_low_bound = self.params.get('FUZZY_Y_LOW_BOUND', 0.25)
        y_med_peak = self.params.get('FUZZY_Y_MED_PEAK', 0.50)
        y_med_width = self.params.get('FUZZY_Y_MED_WIDTH', 0.25)
        y_high_bound = self.params.get('FUZZY_Y_HIGH_BOUND', 0.60)

        x_low_bound = self.params.get('FUZZY_X_LOW_BOUND', 0.15)
        x_med_peak = self.params.get('FUZZY_X_MED_PEAK', 0.40)
        x_med_width = self.params.get('FUZZY_X_MED_WIDTH', 0.25)
        x_high_bound = self.params.get('FUZZY_X_HIGH_BOUND', 0.65)

        y_low = self._membership_low(base_attack, y_low_bound)
        y_med = self._membership_medium(base_attack, y_med_peak, y_med_width)
        y_high = self._membership_high(base_attack, y_high_bound)

        x_low = self._membership_low(max_threat, x_low_bound)
        x_med = self._membership_medium(max_threat, x_med_peak, x_med_width)
        x_high = self._membership_high(max_threat, x_high_bound)

        scores = {
            "全力攻撃": min(y_high, x_low),
            "押し気味": min(y_high, x_med),
            "危険度勝負": min(y_high, x_high),
            "積極駒組み": min(y_med, x_low),
            "様子見": min(y_med, x_med),
            "回し打ち": min(y_med, x_high),
            "スリム化": min(y_low, x_low),
            "撤退準備": min(y_low, x_med),
            "完全撤退": min(y_low, x_high)
        }

        priority_order = [
            "完全撤退",
            "撤退準備",
            "スリム化",
            "回し打ち",
            "様子見",
            "積極駒組み",
            "危険度勝負",
            "押し気味",
            "全力攻撃"
        ]

        best_mode = "完全撤退"
        max_score = -1.0
        for mode in priority_order:
            score = scores[mode]
            if score > max_score:
                max_score = score
                best_mode = mode

        return best_mode, scores
