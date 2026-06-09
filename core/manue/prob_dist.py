from .hash_map import HashMap


class ProbDist:
    def __init__(self, arg):
        self._dist = HashMap()
        if isinstance(arg, HashMap):
            def collect(value, prob):
                if prob > 0:
                    self._dist.set(value, prob)
            arg.for_each(collect)
        elif isinstance(arg, ProbDist):
            def collect2(value, prob):
                if prob > 0:
                    self._dist.set(value, prob)
            arg.dist.for_each(collect2)
        else:
            self._dist.set(arg, 1)

    @property
    def dist(self):
        return self._dist

    def expected(self):
        result = None
        def process(value, prob):
            nonlocal result
            weighted = ProbDist.mult(prob, value)
            if result is None:
                result = weighted
            else:
                result = ProbDist.add(result, weighted)
        self._dist.for_each(process)
        if result is None:
            return [0, 0, 0, 0]
        return result

    def replace(self, old_value, new_pb):
        dist = HashMap()
        prob = [0]
        def collect(v, p):
            if ProbDist.equal(v, old_value):
                prob[0] = p
            else:
                dist.set(v, p)
        self._dist.for_each(collect)

        def merge_new(v, p):
            existing = dist.get(v, 0)
            dist.set(v, existing + p * prob[0])
        new_pb.dist.for_each(merge_new)
        return ProbDist(dist)

    def map_value(self, map_func):
        dist = HashMap()
        def process(v, p):
            new_value = map_func(v)
            existing = dist.get(new_value, 0)
            dist.set(new_value, existing + p)
        self._dist.for_each(process)
        return ProbDist(dist)

    def __repr__(self):
        items = []
        def collect(v, p):
            items.append((v, p))
        self._dist.for_each(collect)
        items.sort(key=lambda x: -x[1])
        lines = [f"  {v}: {p:.3f}," for v, p in items]
        return f"ProbDist {{\n{''.join(lines)}\n}}"

    @staticmethod
    def add(lhs, rhs):
        if isinstance(lhs, ProbDist) or isinstance(rhs, ProbDist):
            if not isinstance(lhs, ProbDist):
                lhs = ProbDist(lhs)
            if not isinstance(rhs, ProbDist):
                rhs = ProbDist(rhs)
            dist = HashMap()
            def process_lhs(v1, p1):
                def process_rhs(v2, p2):
                    v = ProbDist.add(v1, v2)
                    existing = dist.get(v, 0)
                    dist.set(v, existing + p1 * p2)
                rhs.dist.for_each(process_rhs)
            lhs.dist.for_each(process_lhs)
            return ProbDist(dist)
        elif isinstance(lhs, list) and isinstance(rhs, list):
            assert len(lhs) == len(rhs)
            return [lhs[i] + rhs[i] for i in range(len(lhs))]
        elif isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
            return lhs + rhs
        else:
            raise ValueError(f"Unexpected types: {type(lhs)}, {type(rhs)}")

    @staticmethod
    def mult(lhs, rhs):
        if isinstance(lhs, ProbDist) or isinstance(rhs, ProbDist):
            if not isinstance(lhs, ProbDist):
                lhs = ProbDist(lhs)
            if not isinstance(rhs, ProbDist):
                rhs = ProbDist(rhs)
            dist = HashMap()
            def process_lhs(v1, p1):
                def process_rhs(v2, p2):
                    v = ProbDist.mult(v1, v2)
                    existing = dist.get(v, 0)
                    dist.set(v, existing + p1 * p2)
                rhs.dist.for_each(process_rhs)
            lhs.dist.for_each(process_lhs)
            return ProbDist(dist)
        elif isinstance(lhs, (int, float)) and isinstance(rhs, list):
            return [lhs * v for v in rhs]
        elif isinstance(lhs, (int, float)) and isinstance(rhs, (int, float)):
            return lhs * rhs
        else:
            raise ValueError(f"Unexpected types: {type(lhs)}, {type(rhs)}")

    @staticmethod
    def merge(items):
        dist = HashMap()
        for pd, prob in items:
            def process(v, p):
                existing = dist.get(v, 0)
                dist.set(v, existing + p * prob)
            pd.dist.for_each(process)
        return ProbDist(dist)

    @staticmethod
    def equal(lhs, rhs):
        import json
        return json.dumps(lhs, sort_keys=True) == json.dumps(rhs, sort_keys=True)
