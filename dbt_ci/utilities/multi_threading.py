"""Utility functions for multithreading."""

from concurrent.futures import ThreadPoolExecutor
from collections.abc import Callable, Sequence
from typing import Any


def run_multithreaded(func_list: Sequence[Callable[[], Any]], threads: int = 4) -> list[Any]:
    """
    Run zero-argument functions concurrently and return their results in order.

    Every function runs to completion even when another fails, so a batch of drops is
    never left half-submitted. The first exception raised, in list order, is re-raised.
    """
    with ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(func) for func in func_list]
    return [future.result() for future in futures]
