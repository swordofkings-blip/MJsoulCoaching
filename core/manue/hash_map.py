import json


class HashMap:
    def __init__(self, pairs=None):
        self._data = {}
        if pairs:
            for key, value in pairs:
                self.set(key, value)

    def set(self, key, value):
        assert key is not None
        assert value is not None
        self._data[json.dumps(key, sort_keys=True)] = value

    def get(self, key, default=None):
        assert key is not None
        key_json = json.dumps(key, sort_keys=True)
        if key_json in self._data:
            return self._data[key_json]
        return default

    def has_key(self, key):
        assert key is not None
        return json.dumps(key, sort_keys=True) in self._data

    def for_each(self, callback):
        for key_json, value in self._data.items():
            callback(json.loads(key_json), value)

    def items(self):
        result = []
        for key_json, value in self._data.items():
            result.append((json.loads(key_json), value))
        return result

    def __repr__(self):
        items = []
        for key_json, value in self._data.items():
            items.append(f"{key_json}: {value}")
        return f"HashMap {{{', '.join(items)}}}"
