"""System-level helpers for choosing worker counts in multiprocessing."""

from psutil import Process, cpu_count


def hyperthreaded() -> bool:
    """Returns True if the system is using hyperthreading."""

    return cpu_count(logical=True) > cpu_count(logical=False)


def set_cores(requested: int | None, num_ops: int) -> int:
    """Choose a worker count clamped by request, system, and operation count.

    Args:
        requested:
            Desired worker count. If None, fall back to all available cores
            (capped at num_ops).
        num_ops:
            Number of multicore operations to perform; must be > 0.

    Returns:
        The minimum of `requested` (when set), the system's available cores,
        and `num_ops`.
    """

    try:
        if hyperthreaded():
            available = len(Process().cpu_affinity()) - cpu_count(logical=False)
        else:
            available = len(Process().cpu_affinity())
    except (AttributeError, NotImplementedError, OSError):
        available = cpu_count(logical=True) or 1
    if not requested:
        return min(available, num_ops)
    return min((requested, available, num_ops))
