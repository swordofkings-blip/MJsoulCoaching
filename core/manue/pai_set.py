from .pai import Pai


class PaiSet:
    def __init__(self, arg=None):
        self._array = [0] * Pai.NUM_IDS
        if arg is not None:
            if isinstance(arg, dict) and 'array' in arg:
                self._array = arg['array']
            elif isinstance(arg, list):
                self.add_pais(arg)

    def to_pais(self):
        pais = []
        for pid in range(Pai.NUM_IDS):
            for _ in range(self._array[pid]):
                pais.append(Pai(pid))
        return pais

    def count(self, pai):
        return self._array[pai.id()]

    def has(self, pai):
        return self._array[pai.id()] > 0

    def add_pai(self, pai, n=1):
        self._array[pai.id()] += n

    def add_pais(self, pais):
        for pai in pais:
            self._array[pai.id()] += 1

    def remove_pai_set(self, other):
        other_array = other.array()
        for pid in range(Pai.NUM_IDS):
            self._array[pid] -= other_array[pid]

    def array(self):
        return self._array

    def to_string(self):
        return " ".join(str(p) for p in self.to_pais())

    @staticmethod
    def get_all():
        return PaiSet({'array': [4] * Pai.NUM_IDS})
