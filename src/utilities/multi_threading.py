"""Utility functions for multithreading."""
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, Any, List

def run_multithreaded(
    func_list: List[Callable[..., Any]],
    threads: int = 4,
    exit_on_exception: bool = False
) -> List[Any]:
    """
    Run a list of functions concurrently using multithreading.

    Args:
        func_list: List of functions that may take any arguments.
        threads: Number of worker threads.
        exit_on_exception: If True, stop on first exception.

    Returns:
        List of results in the same order as func_list.
        Exceptions are stored in the list if exit_on_exception is False.
    """
    results = []

    with ThreadPoolExecutor(max_workers=threads) as executor:
        try:
            for result in executor.map(lambda f: f(), func_list):
                results.append(result)
        except Exception as e:
            if exit_on_exception:
                print(f"Exception: {e}", file=sys.stderr)
                sys.exit(1)
            else:
                results.append(e)

    return results
