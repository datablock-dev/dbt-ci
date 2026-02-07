from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Any, List
import sys

def run_multithreaded(
    func_list: List[Callable[[], Any]],
    threads: int = 4,
    exit_on_exception: bool = False
) -> List[Any]:
    """
    Run a list of functions concurrently using multithreading.

    Args:
        func_list: List of callable functions (no-argument functions).
        threads: Number of worker threads to use.
        exit_on_exception: If True, immediately stop all threads and exit on first exception.

    Returns:
        List of results in the same order as func_list.
        Exceptions are stored in the list if exit_on_exception is False.
    """
    results = [None] * len(func_list)

    with ThreadPoolExecutor(max_workers=threads) as executor:
        future_to_index = {executor.submit(f): i for i, f in enumerate(func_list)}

        for future in as_completed(future_to_index):
            idx = future_to_index[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                if exit_on_exception:
                    print(f"Exception in task {idx}: {e}", file=sys.stderr)
                    # Shut down remaining threads immediately
                    executor.shutdown(wait=False)
                    sys.exit(1)
                else:
                    results[idx] = e

    return results
