import functools
from itertools import zip_longest

import numpy as np
from openseize.core.producer import producer

# DEPRECATION NOTICE
# The next release of openseize will handle producing between values along axis
# so the following will be removed when openseize v1.3.0 is released.

#TODO: Is the new version of openseize released? Change how I use these two?
#TODO: Type annotations? Is this the best way to do this?
def _between_gen(reader, start, stop, chunksize, axis):
    """A generating function returns a generator of ndarrays of samples between
    start and stop.

    Args:
        reader:
            An openseize reader instance.
        start:
            The index at which production of values from reader begins.
        stop:
            The index at which production of values from reader ends.
        chunksize:
            The number of samples to return along axis of each yield ndarray.
        axis:
            The axis along which samples will be produced.
    
    Returns:
        A generator of ndarrays of chunksize shape along axis between start and
        stop.

    Notes:
        This is a protected module-level function that is not intended for
        external calling. Its placement at module level versus nesting is to
        support concurrent processing.
    """

    starts = np.arange(start, stop, int(chunksize))
    for a, b in zip_longest(starts, starts[1:], fillvalue=stop):
        yield reader.read(a,b)

def between_pro(reader, start, stop, chunksize, axis=-1):
    """Returns a producer from a reader instance that produces values between
    start and stop.

    Args:
        reader:
            An openseize reader instance.
        start:
            The index at which production of values from reader begins.
            The index at which production of values from reader ends.
        axis:
            The axis along which production should occur. Defaults to last axis.

    Examples:
        >>> from openseize.demos import paths
        >>> from openseize.file_io import edf
        >>> path = paths.locate('recording_001.edf')
        >>> reader = edf.Reader(path)
        >>> reader.channels = [0,1,2]
        >>> # read samples 10 to 1155 in chunks of 100
        >>> pro = between_pro(reader, 10, 1155, chunksize=100)
        >>> np.allclose(pro.to_array(), reader.read(10, 1155))
        True

    Returns:
        A producer instance producing samples between start and stop along axis.
    """

    # build a partial freezing all arg of _between_gen
    gen_func = functools.partial(_between_gen, reader, start, stop, chunksize,
                                 axis)
    # compute the shape of the new producer
    shape = list(reader.shape)
    shape[axis] = stop - start

    return producer(gen_func, chunksize, axis, shape=shape)

