import math


class BitVector:
    def __init__(self, array):
        self.data = [0] * math.ceil(len(array) / 32)
        for i, val in enumerate(array):
            if val:
                self.data[i >> 5] |= (1 << (i % 32))

    def is_subset_of(self, other):
        for i in range(len(self.data)):
            if (self.data[i] & other.data[i]) != self.data[i]:
                return False
        return True

    def has_intersection_with(self, other):
        for i in range(len(self.data)):
            if (self.data[i] & other.data[i]) != 0:
                return True
        return False
