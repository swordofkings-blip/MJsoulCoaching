from .pai import Pai

NUM_PIDS = 9 * 3 + 7
CHOWS = [0, 1, 2, 3, 4, 5, 6, 9, 10, 11, 12, 13, 14, 15, 18, 19, 20, 21, 22, 23, 24]


class ShantenAnalysis:
    __slots__ = ('_shanten', '_goals', '_params')

    def __init__(self, pids, params=None):
        self._params = {
            'allowed_extra_pais': 0,
            'upperbound': float('inf'),
        }
        if params:
            self._params.update(params)

        current_vector = [0] * NUM_PIDS
        for pid in pids:
            current_vector[pid] += 1

        target_vector = [0] * NUM_PIDS
        num_melds = len(pids) // 3
        goals = []
        upperbound = [self._params['upperbound']]
        mentsus = []

        self._calculate_shantensu_internal(
            current_vector, target_vector, -1, num_melds, 0,
            upperbound, mentsus, goals
        )

        cutoff = min(upperbound[0] + self._params['allowed_extra_pais'], self._params['upperbound'])
        self._goals = []
        for goal in goals:
            if goal[0] <= cutoff:
                cv = goal[2]
                self._goals.append({
                    'shanten': goal[0],
                    'mentsus': goal[1],
                    'count_vector': cv,
                    'required_vector': [max(cv[pid] - current_vector[pid], 0) for pid in range(Pai.NUM_IDS)],
                    'throwable_vector': [max(current_vector[pid] - cv[pid], 0) for pid in range(Pai.NUM_IDS)],
                })
        raw_shantens = sorted(set(g[0] for g in goals))
        self._shanten = raw_shantens[0] if raw_shantens else float('inf')

    @property
    def shanten(self):
        return self._shanten

    @property
    def goals(self):
        return self._goals

    def _calculate_shantensu_internal(self, vector0, vector1, current, num_melds_left,
                                       min_meld_id, upperbound, mentsus, goals):
        if num_melds_left == 0:
            for i in range(NUM_PIDS):
                delta = (vector1[i] + 2) - vector0[i]
                if delta <= 0:
                    delta = 0
                if delta >= 2:
                    continue
                new_shanten = current + delta
                if new_shanten <= self._params['upperbound'] + self._params['allowed_extra_pais']:
                    gv = vector1.copy()
                    gv[i] += 2
                    goals.append((new_shanten, list(mentsus) + [('toitsu', i, i)], gv))
                    if new_shanten < upperbound[0]:
                        upperbound[0] = new_shanten
            return

        start_chow_id = min_meld_id - NUM_PIDS if min_meld_id >= NUM_PIDS else 0
        for chow_id in range(start_chow_id, len(CHOWS)):
            i = CHOWS[chow_id]
            if vector1[i] >= 4 or vector1[i + 1] >= 4 or vector1[i + 2] >= 4:
                continue
            current1 = current
            if vector0[i] <= vector1[i]:
                current1 += 1
            if vector0[i + 1] <= vector1[i + 1]:
                current1 += 1
            if vector0[i + 2] <= vector1[i + 2]:
                current1 += 1
            if current1 < current + 3 and current1 <= upperbound[0] + self._params['allowed_extra_pais']:
                vector1[i] += 1
                vector1[i + 1] += 1
                vector1[i + 2] += 1
                mentsus.append(('shuntsu', i, i + 1, i + 2))
                self._calculate_shantensu_internal(
                    vector0, vector1, current1, num_melds_left - 1, chow_id + NUM_PIDS, upperbound,
                    mentsus, goals
                )
                mentsus.pop()
                vector1[i] -= 1
                vector1[i + 1] -= 1
                vector1[i + 2] -= 1

        if upperbound[0] <= 0:
            return

        if min_meld_id < NUM_PIDS:
            for i in range(min_meld_id, NUM_PIDS):
                if vector1[i] >= 2 or vector0[i] < 2:
                    continue
                v0i = vector0[i]
                v1i = vector1[i]
                if v0i <= v1i:
                    current1 = current + 3
                elif v0i < v1i + 3:
                    current1 = current + (v1i + 3) - v0i
                else:
                    current1 = current
                if current1 < current + 3 and current1 <= upperbound[0] + self._params['allowed_extra_pais']:
                    vector1[i] += 3
                    mentsus.append(('kotsu', i, i, i))
                    self._calculate_shantensu_internal(
                        vector0, vector1, current1, num_melds_left - 1, i, upperbound,
                        mentsus, goals
                    )
                    mentsus.pop()
                    vector1[i] -= 3
