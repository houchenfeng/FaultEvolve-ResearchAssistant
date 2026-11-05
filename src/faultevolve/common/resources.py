"""CPU limits shared by local evolution and evaluator subprocesses."""

from contextlib import contextmanager
import os

from threadpoolctl import threadpool_info, threadpool_limits


THREAD_ENV = ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")


def limit_resources(cpu_limit: int) -> int:
    """Limit this execution thread and children before native libraries start."""
    if cpu_limit < 1:
        raise ValueError("CPU 配额必须大于 0")
    if hasattr(os, "sched_getaffinity"):
        allowed = sorted(os.sched_getaffinity(0))[:cpu_limit]
        os.sched_setaffinity(0, allowed)
        cpu_limit = len(allowed)
    for key in THREAD_ENV:
        os.environ[key] = str(cpu_limit)
    os.environ["FE_RESEARCH_CPU_LIMIT"] = str(cpu_limit)
    return cpu_limit


@contextmanager
def execution_resources(cpu_limit: int):
    """Restore affinity, environment and already loaded native pools on exit."""
    keys = (*THREAD_ENV, "FE_RESEARCH_CPU_LIMIT")
    previous = {key: os.environ.get(key) for key in keys}
    affinity = os.sched_getaffinity(0) if hasattr(os, "sched_getaffinity") else None
    try:
        effective = limit_resources(cpu_limit)
        with threadpool_limits(limits=effective):
            yield {"requested_cpu_limit": cpu_limit, "effective_cpu_limit": effective,
                   "thread_env": {key: os.environ[key] for key in THREAD_ENV},
                   "native_pools": [{key: pool.get(key) for key in
                                     ("user_api", "internal_api", "num_threads")}
                                    for pool in threadpool_info()]}
    finally:
        if affinity is not None:
            os.sched_setaffinity(0, affinity)
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
