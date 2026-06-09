from . import util
from .pai import Pai


class Furo:
    def __init__(self, type_=None, taken=None, consumed=None, target=None):
        self._type = type_
        self._taken = taken
        self._consumed = consumed or []
        self._target = target

    @property
    def type(self):
        return self._type

    @property
    def taken(self):
        return self._taken

    @property
    def consumed(self):
        return self._consumed

    @property
    def target(self):
        return self._target

    def pais(self):
        result = ([self._taken] if self._taken else []) + self._consumed
        result.sort(key=lambda p: p.id())
        return result
