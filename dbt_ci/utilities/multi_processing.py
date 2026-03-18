"""Utility functions for multiprocessing."""
import sys
import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Callable, Any

logger = logging.getLogger(__name__)

def run_multiprocessed(
    func_list: list[Callable[..., Any]],
    max_workers: int = 4,
    exit_on_exception: bool = False
) -> list[Any]:
    """
    Run a list of zero-argument callables concurrently using separate processes.

    Note: callables must be picklable (i.e. module-level or class functions,
    not lambdas) for ProcessPoolExecutor to work correctly.

    Args:
        func_list: List of zero-argument callables to execute concurrently.
        max_workers: Maximum number of worker processes.
        exit_on_exception: If True, stop on first exception.

    Returns:
        List of results in the same order as func_list.
        Exceptions are stored in the list if exit_on_exception is False.
    """
    results: list[Any] = [None] * len(func_list)

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        future_to_index = {executor.submit(f): i for i, f in enumerate(func_list)}
        for future in as_completed(future_to_index):
            index = future_to_index[future]
            try:
                results[index] = future.result()
            except Exception as e:
                if exit_on_exception:
                    logger.error(f"Exception in worker: {e}")
                    sys.exit(1)
                else:
                    results[index] = e

    return results