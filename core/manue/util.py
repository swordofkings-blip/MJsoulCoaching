import json
import random as _random


def attr_reader(cls, names):
    for name in names:
        setattr(cls, name, property(lambda self, n=name: getattr(self, f'_{n}')))


def all_(array, func):
    return all(func(v) for v in array)


def any_(array, func):
    return any(func(v) for v in array)


def count(array, func):
    return sum(1 for v in array if func(v))


def merge_objects(lhs, rhs):
    result = {}
    result.update(lhs)
    result.update(rhs)
    return result


def camel_case(name):
    parts = name.split('_')
    return parts[0] + ''.join(p.capitalize() for p in parts[1:])


def shuffle(array, random_func, n=None):
    if n is None:
        n = len(array)
    for i in range(n):
        j = i + int(random_func() * (len(array) - i))
        array[i], array[j] = array[j], array[i]
    return array


def format_objects_as_table(objects, columns):
    arrays = [[c[0] for c in columns]]
    for obj in objects:
        arrays.append([c[2] % obj[c[1]] for c in columns])
    return format_arrays_as_table(arrays)


def format_arrays_as_table(arrays):
    widths = [0] * len(arrays[0])
    for array in arrays:
        for i, val in enumerate(array):
            widths[i] = max(widths[i], len(str(val)))
    result = ""
    for array in arrays:
        result += "| "
        for i, val in enumerate(array):
            w = widths[i]
            result += f"{str(val):+{w}s} | "
        result += "\n"
    return result
