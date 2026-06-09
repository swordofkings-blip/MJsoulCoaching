from . import util

HONOR_MAP_INTERNAL = {'1z': 'E', '2z': 'S', '3z': 'W', '4z': 'N', '5z': 'P', '6z': 'F', '7z': 'C'}
REV_HONOR_MAP = {v: k for k, v in HONOR_MAP_INTERNAL.items()}


def convert_to_mjai_format(tile_str):
    if tile_str in HONOR_MAP_INTERNAL:
        return HONOR_MAP_INTERNAL[tile_str]
    return tile_str


def convert_to_internal_format(tile_str):
    if tile_str in REV_HONOR_MAP:
        return REV_HONOR_MAP[tile_str]
    return tile_str


class Pai:
    NUM_IDS = 9 * 3 + 7
    TYPE_STRS = ["m", "p", "s", "t"]
    TSUPAI_STRS = [None, "E", "S", "W", "N", "P", "F", "C"]
    UNKNOWN = None  # Will be set after class definition

    def __init__(self, *args):
        self._id = None
        self._red = False

        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, int):
                self._id = arg
                self._red = False
            elif isinstance(arg, str):
                import re
                arg = convert_to_mjai_format(arg)
                if arg == "?":
                    self._id = None
                    self._red = False
                else:
                    m = re.match(r'^([0-9])([mps])(r)?$', arg)
                    if m:
                        number = int(m.group(1))
                        type_str = m.group(2)
                        self._red = (m.group(3) is not None) or (number == 0)
                        if number == 0:
                            number = 5
                        type_index = self.TYPE_STRS.index(type_str)
                        self._id = type_index * 9 + (number - 1)
                    else:
                        number = self.TSUPAI_STRS.index(arg) if arg in self.TSUPAI_STRS else -1
                        if number > 0:
                            self._id = 3 * 9 + (number - 1)
                            self._red = False
                        else:
                            raise ValueError(f"Unknown pai string: {arg}")
        elif len(args) >= 2:
            type_str = args[0]
            number = args[1]
            self._red = args[2] if len(args) > 2 else False
            if type_str is not None:
                type_index = self.TYPE_STRS.index(type_str)
                self._id = type_index * 9 + (number - 1)
            else:
                self._id = None
        else:
            raise ValueError("Wrong number of arguments")

    def type(self):
        if self._id is None:
            return None
        return self.TYPE_STRS[self._id // 9]

    def number(self):
        if self._id is None:
            return None
        return self._id % 9 + 1

    def id(self):
        return self._id

    def red(self):
        return self._red

    def equal(self, other):
        return other is not None and isinstance(other, Pai) and self._id == other._id and self._red == other._red

    def has_same_symbol(self, other):
        return other is not None and self._id == other._id

    def is_yaochu(self):
        t = self.type()
        n = self.number()
        return t == "t" or n == 1 or n == 9

    def remove_red(self):
        return Pai(self._id)

    def next(self, n):
        t = self.type()
        number = self.number() + n
        if t != "t" and 1 <= number <= 9:
            return Pai(t, number)
        return None

    def next_for_dora(self):
        t = self.type()
        n = self.number()
        if (t == "t" and n == 4) or (t != "t" and n == 9):
            next_number = 1
        elif t == "t" and n == 7:
            next_number = 5
        else:
            next_number = n + 1
        return Pai(t, next_number)

    def to_string(self):
        t = self.type()
        n = self.number()
        if t is None:
            return "?"
        if t == "t":
            return self.TSUPAI_STRS[n]
        return f"{n}{t}{'r' if self._red else ''}"

    @staticmethod
    def compare(lhs, rhs):
        return lhs.id() - rhs.id()

    @staticmethod
    def pais_to_str(pais):
        return " ".join(str(p) for p in pais) if pais else None

    @staticmethod
    def str_to_pais(s):
        return [Pai(f) for f in s.split()]


Pai.UNKNOWN = Pai("?")
