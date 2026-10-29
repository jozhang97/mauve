"""Bounded process-local cache for immutable, decoded alignment blocks."""
from collections import OrderedDict
from threading import RLock
from sys import getsizeof


def decoded_size(value):
    """Conservative size: shared objects are counted once per occurrence."""
    size = getsizeof(value)
    if isinstance(value, dict):
        size += sum(decoded_size(k) + decoded_size(v) for k, v in value.items())
    elif isinstance(value, (list, tuple)):
        size += sum(decoded_size(v) for v in value)
    return size


class BlockCache:
    # Alignment IDs are unique and imported blocks are never edited. Callers
    # must treat returned objects as read-only. No cache survives an app restart.
    def __init__(self, max_bytes=64 * 1024 * 1024, max_entries=32):
        self.max_bytes = max_bytes
        self.max_entries = max_entries
        self.entries = OrderedDict()
        self.bytes = 0
        self.lock = RLock()

    def get(self, key, loader):
        # Coalesce concurrent page/profile requests instead of decoding the same
        # large JSON payload several times. Analysis runs outside this lock.
        with self.lock:
            if key in self.entries:
                self.entries.move_to_end(key)
                return self.entries[key][0]
            value = loader()
            size = decoded_size(value)
            if size <= self.max_bytes and self.max_entries > 0:
                while self.entries and (self.bytes + size > self.max_bytes
                                        or len(self.entries) >= self.max_entries):
                    _, (_, removed_size) = self.entries.popitem(last=False)
                    self.bytes -= removed_size
                self.entries[key] = (value, size)
                self.bytes += size
            return value
