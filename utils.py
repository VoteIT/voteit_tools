# Use with shell
from contextlib import contextmanager
from time import perf_counter


@contextmanager
def exectime() -> float:
    start = perf_counter()
    yield lambda: perf_counter() - start
