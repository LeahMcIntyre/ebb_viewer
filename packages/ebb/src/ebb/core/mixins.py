import inspect
import reprlib
from copy import deepcopy
from collections import abc

class ViewInstance:
    """Mixin endowing inheritors with echo and print str representations.
    
    The returned string reprs will not include protected attrs and methods.
    These attrs/methods start with '_' are never intended to be part of
    a public interface. (Note: this exclusion will also exclude private
    attrs starting with '__' the "dunder" attrs/methods.
    """

    def _fetch_attributes(self):
        """Returns a dict of all non-protected attrs."""

        return {key: value for key, value in self.__dict__.items() 
                if not key.startswith('_')}
            
    def _fetch_methods(self):
        """Returns non-protected instance and class methods."""
        
        methods = dict(inspect.getmembers(self, inspect.ismethod))
        return {name: method for name, method in methods.items() 
                if not name.startswith('_')}

    def _fetch_properties(self):
        """Returns non_protected properties."""

        def isproperty(item):
            """Helper returing True if item is a property."""

            return isinstance(item, property)

        #recall properties are class level attrs
        props = inspect.getmembers(type(self), isproperty)
        return {name: getattr(self, name) for name,_ in props 
                if not name.startswith('_')}

    def __repr__(self):
        """Returns the __init__'s signature as the echo representation.
        
        Returns: str
        """

        #build a signature and get its args and class name
        signature = inspect.signature(self.__init__)
        args = str(signature)
        cls_name = type(self).__name__
        return '{}{}'.format(cls_name, args)

    def __str__(self):
        """Returns this instances print representation.
        
        The print representation string will consist of the class name and 
        publicly accessible attributes and properties as well as a small
        help message.
        """

        cls_name = type(self).__name__
        #get the attributes and properties and combine
        attrs = self._fetch_attributes()
        props = self._fetch_properties()
        attrs.update(props)
        #make strings of name, value pairs for each attr
        #attr_strs = [name + ': ' + reprlib.repr(val) for 
        #             name, val in attrs.items()]
        attr_strs = [name + ': ' + str(val) for name, val in attrs.items()]
        #make a help msg
        help_msg = 'Type help({}) for full documentation'.format(cls_name)
        #construct print string
        msg = '{}\n{}\n{}\n\n{}'
        print_str = msg.format(cls_name + ' Object',
                               '---Attributes---',
                               '\n'.join(attr_strs),
                               help_msg)
        return print_str

