"""ViewInstance mixin providing default __repr__ and __str__ behavior."""

import inspect


class ViewInstance:
    """Mixin endowing inheritors with echo and print str representations.

    The returned string reprs do not include protected attrs and methods
    (anything starting with `_`).
    """

    def _fetch_attributes(self) -> dict:
        """Returns a dict of all non-protected attrs."""

        return {key: value for key, value in self.__dict__.items() if not key.startswith("_")}

    def _fetch_properties(self) -> dict:
        """Returns non-protected properties defined on this instance's class."""

        # properties live on the class, not the instance
        props = inspect.getmembers(type(self), lambda v: isinstance(v, property))
        return {name: getattr(self, name) for name, _ in props if not name.startswith("_")}

    def __repr__(self) -> str:
        """Returns a constructor-style representation: ClassName(<signature>)."""

        signature = inspect.signature(self.__init__)
        return f"{type(self).__name__}{signature}"

    def __str__(self) -> str:
        """Print representation: class name + public attrs and properties."""

        cls_name = type(self).__name__
        attrs = self._fetch_attributes()
        attrs.update(self._fetch_properties())

        attr_lines = "\n".join(f"{name}: {val}" for name, val in attrs.items())
        return (
            f"{cls_name} Object\n"
            "---Attributes---\n"
            f"{attr_lines}\n\n"
            f"Type help({cls_name}) for full documentation"
        )
