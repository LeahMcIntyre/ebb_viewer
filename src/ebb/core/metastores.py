"""A module for creating objects that represent numpy arrays and carry metadata.

Classes:
    MetaArray:
        A representation of N-dimensional arrays with a full coordinate system
        carrying labels at each index along each axis. This object provides
        support for label indexing like pandas or xarrays but does not support
        numpy array operations.
    MetaMask:
        A callable that names and stores 1D boolean mask. On call, it can
        combine any combination of these stored masks using any callable
        implementing element-wise logic rules.
"""

import copy
import functools
import itertools
import pickle
import warnings
from numbers import Number
from pathlib import Path
from typing import (
    Callable,
    Dict,
    Iterator,
    Optional,
    Sequence,
    Tuple,
    Union,
)

import numpy as np
import numpy.typing as npt
from ebb.core import mixins

# Type definitions
Coords = Dict[str, Union[Sequence, npt.NDArray, range]]


class MetaArray(mixins.ViewInstance):
    """An interface to a numpy array that stores a mapping of user defined
    coordinates one per dimension in the array that can be used to select
    subarrays by name.

    MetaArrays are not drop-in replacements for numpy arrays as they do not
    implement the protocol expected of numpy arrays (slicing, ufuncs etc.) More
    sophisticated programs such as xarray do implement these protocols.

    Attrs:
        data:
            An N-dimensional numpy array to represent.
        coords:
            A dictionary of axis string name keys and index label values.

    Examples:
        >>> data = np.random.random((3, 4, 6))
        >>> trials = [f'trial_{idx}' for idx in range(data.shape[0])]
        >>> counts = [f'count_{idx}' for idx in range(data.shape[1])]
        >>> times = np.arange(data.shape[-1])
        >>> # build a MetaArray
        >>> m = MetaArray(data, trial=trials, count=counts, time=times)
        >>> m.shape
        (3, 4, 6)
        >>> for axis, indices in m.coords.items():
        ...     print(f'{axis}: {indices}')
        trial: ['trial_0', 'trial_1', 'trial_2']
        count: ['count_0', 'count_1', 'count_2', 'count_3']
        time: [0, 1, 2, 3, 4, 5]
        >>> z = m.select(trial=['trial_0', 'trial_2'], time=np.arange(6))
        >>> z.shape
        (2, 4, 6)
        >>> # compare slice of m's data to z's data
        >>> np.allclose(m.data[[0,2], :, 0:6], z.data)
        True
    """

    def __init__(
        self,
        data: npt.NDArray,
        metadata: Optional[Dict] = None,
        **coords: Coords,
    ) -> None:
        """Initialize this MetaArray with an array & coordinates dictionary.

        Args:
            data:
                An N-dimensional numpy array to represent.
            metadata:
                Any supplemental data a user may wish to store.
            coords:
                A dictionary of axis name keys and index label values. The axis
                names must be strings and label values must be sequence-like
                objects (list, tuples, 1d arrays) or range instances.  If
                a sequence, the elements may be of any type. The count & order
                of the axes in coords must match the count & order of axes in
                data and the number of labels for an axis must match the
                corresponding length of data along axis. If using 1-D array(s)
                for labeling, be aware these will be converted to list with
                slower label lookup. If possible, consider replacing with
                range(s).
        """

        self.data = data
        self.metadata = metadata if metadata else {}
        self.coords = self._assign_coords(coords)

    def _assign_coords(self, coords: Dict) -> Dict[str, Sequence]:
        """Validates and assigns coordinates to this MetaArray.

        Args:
            coords:
                See MetaArray's initializer for argument description.

        Returns:
            A dictionary of coordinates.

        Raises:
            A ValueError is issued if the dimensionality or shape of the
            coordinates does not match data's dims. or shape
        """

        default = {f'axis{ix}': range(s) for ix, s in enumerate(self.shape)}
        result = copy.deepcopy(coords) if coords else default

        # convert labels for all axes to list instances
        result = {
            name: list(labels) if not isinstance(labels, range) else labels
            for name, labels in result.items()
        }

        # validate dims & shape of coordinates
        coord_shape = tuple(len(v) for v in result.values())
        if coord_shape != self.shape:
            msg = (
                "The shape of the coordinates must match data's shape"
                f"{coord_shape} != {self.shape}"
            )
            raise ValueError(msg)

        return result

    @property
    def shape(self):
        """Returns the shape of this MetaArray."""

        return self.data.shape

    def to_indices(
        self,
        name: str,
        labels: Sequence,
    ) -> Tuple[int, Sequence]:
        """Converts labels along a named axis in coordinates to numeric indices.

        Args:
            name:
                The name of an axis in coordinates.
            labels:
                The name(s) of labels along axis to convert to indices.

        Returns:
            A tuple containing the numeric axis & indices of data that match the
            supplied axis name and labels.
        """

        axis = tuple(self.coords).index(name)
        indices = [self.coords[name].index(label) for label in labels]

        return axis, indices

    def select(
        self,
        **selections: Union[Number, str, Sequence, npt.NDArray],
    ) -> 'MetaArray':
        """Returns a new MetaArray by slicing this MetaArray with axis names &
        labels in selections.

        Args:
            **selections:
                Keyword arguments specifying an axis name and labels to slice
                this MetaArray with.

        Returns:
            A MetaArray whose data & coordinates contain only selections.
            MetaArray attributes from the presliced MetaArray are copied without
            change to the new (returned) instance.
        """

        # coords will be mutated so copy for new instance
        coords = copy.deepcopy(self.coords)
        data = self.data

        for name, labels in selections.items():
            # all labels converted to list for to_indices
            labels = [labels] if isinstance(labels, Number) else list(labels)
            axis, indices = self.to_indices(name, labels)

            # filter the data and update axes indices
            data = np.take(data, indices, axis=axis)
            coords.update({name: labels})

        # build an instance and reassign metadata without change
        cls = type(self)
        instance = cls(data, **coords)
        instance.__dict__.update(self.metadata)

        return instance

    def to_dict(self) -> Dict:
        """Returns a dictionary representation of this MetaArray."""

        return dict(data=self.data, coords=self.coords, metadata=self.metadata)

    def save(self, path: Union[str, Path]) -> None:
        """Pickles a dict representation of this MetaArray to a file at path.

        Args:
            path:
                Save location of this MetaArray's dict representation.

        Returns:
            None
        """

        path = Path(path)
        with open(path, 'wb') as outfile:
            pickle.dump(self.to_dict(), outfile)

    @classmethod
    def load(cls, path: Union[str, Path]) -> 'MetaArray':
        """Creates a new MetaArray instance from a dict representation on disk.

        Args:
            path:
                Path to file containing a dict representation of a MetaArray.

        Returns:
            A new MetaArray instance.
        """

        path = Path(path)
        with open(path, 'rb') as infile:
            metadict = pickle.load(infile)

        # construct and return a new instance
        data = metadict['data']
        metadata = metadict['metadata']
        coords = metadict['coords']
        return cls(data, metadata, **coords)


class MetaMask(mixins.ViewInstance):
    """A callable container that stores & returns element-wise combinations
    of boolean masks.

    Examples:
        >>> m = MetaMask(x=[1, 0, 0, 1], y=[0, 1, 0, 1])
        >>> m('x', 'y', logical=np.logical_and)
        (('x', 'y'), array([False, False, False,  True]))
    """

    def __init__(
        self,
        metadata: Optional[Dict] = None,
        **named_masks,
    ) -> None:
        """Initialize this MetaMask with metadata and named mask to store.

        Args:
            metadata:
                Any desired metadata to associate with the named masks.
            named_masks:
                A mapping of named submasks to store.
        """

        self.__dict__.update(**named_masks)
        self.metadata = {} if metadata is None else metadata

    @property
    def names(self):
        """Returns the list of named masks in this Metamask."""

        return [name for name in self.__dict__ if name != 'metadata']

    def combinations(
        self,
        r: int = 2,
        logical: Callable[..., npt.NDArray] = np.logical_and,
    ) -> Iterator[Tuple[Tuple[str, ...], npt.NDArray[np.bool_]]]:
        """Yields unique r-lenghted combinations of the masks in this MetaMask.

        Args:
            r:
                The number of mask included in each combination.
            logical:
                A function used to combine the r-masks in each combination. This
                function must accept any number of lengthed 1-D booleans.

        Yields:
            names, combined array tuples of length r.

        Examples:
            >>> x = [1,0,0,1]
            >>> y = [0,1,1,1]
            >>> z = [0,0,1,1]
            >>> metamask = MetaMask(x=x, y=y, z=z)
            >>> for tup in metamask.combinations(r=2):
            ...     print(tup)
            (('x', 'y'), array([False, False, False,  True]))
            (('x', 'z'), array([False, False, False,  True]))
            (('y', 'z'), array([False, False,  True,  True]))
        """

        for names in itertools.combinations(self.names, r=r):
            yield self(*names, logical=logical)

    def __call__(
        self,
        *names,
        logical=np.logical_and,
        **kwargs,
    ) -> Tuple[Tuple[str, ...], npt.NDArray[np.bool_]]:
        """Returns the element-wise logical combination of named masks.

        Args:
            names:
                The string name(s) of mask to logically combine.
            logical:
                A callable that accepts and combines 1-D boolean masks.

        Returns:
            A tuple containing a combined string name and a 1-D boolean array,
            the element-wise combination of each named mask.
        """

        submasks = [getattr(self, name) for name in names]

        lengths = np.array([len(m) for m in submasks])
        min_length = np.min(lengths)
        if any(lengths - min_length):
            msg = (
                f'Mask lengths are inconsistent lengths = {lengths}.'
                f'Truncating masks to minimum length = {min_length}'
            )
            warnings.warn(msg)

            submasks = [mask[:min_length] for mask in submasks]

        return names, functools.reduce(logical, submasks)

    def __contains__(self, name: str) -> bool:
        """Test membership of named mask in this MetaMask.

        Args:
            name:
                Name of mask to search this MetaMask for.

        Returns:
            True if this Metamask contains a mask with name else False.
        """

        return name in self.names
