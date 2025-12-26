import pickle
from psutil import cpu_count, Process

def hyperthreaded():
    """Returns True if system is using hyperthreading."""
    
    return cpu_count(logical=True) > cpu_count(logical=False)
        
def set_cores(requested, num_ops):
    """Returns the minimun of the requested cores, the system available cores
    and the number of operations to be performed.
    
    Args: 
        requested (int or None):       number of cores to utilize
                                       if None use all available upto
                                       num_ops
        numm_ops (int):                number of multicore operations to
                                       perform, must be > 0
    """

    if hyperthreaded():
        available = len(Process().cpu_affinity()) - cpu_count(logical=False)
    else:
        available = len(Process().cpu_affinity())
    if not requested:
        return min(available, num_ops)
    return min((requested, available, num_ops))

def is_pickleable(obj):
    """Test wheter an object supports multiprocessing."""

    try:
        pickle.dumps(obj)
        return 'Pickled Successfully'
    except Exception as e:
        print(e)
        return 'Pickling FAILED'
