import collections.abc
import warnings
from abc import abstractmethod
from collections import defaultdict
from datetime import datetime
from enum import Enum, EnumMeta
from textwrap import dedent
from typing import Any, Callable, Dict, Mapping, Optional, Set, Tuple, Union
from urllib.parse import urlencode

import ciso8601
from ruamel.yaml.timestamp import TimeStamp as RuamelTimeStamp

from eo3.utils import default_utc


class FileFormat(Enum):
    GeoTIFF = 1
    NetCDF = 2
    Zarr = 3
    JPEG2000 = 4


def nest_properties(d: Mapping[str, Any], separator=":") -> Dict[str, Any]:
    """
    Split keys with embedded colons into sub dictionaries.

    Intended for stac-like properties

    >>> nest_properties({'landsat:path':1, 'landsat:row':2, 'clouds':3})
    {'landsat': {'path': 1, 'row': 2}, 'clouds': 3}
    """
    out = defaultdict(dict)
    for key, val in d.items():
        section, *remainder = key.split(separator, 1)
        if remainder:
            [sub_key] = remainder
            out[section][sub_key] = val
        else:
            out[section] = val

    for key, val in out.items():
        if isinstance(val, dict):
            out[key] = nest_properties(val, separator=separator)

    return dict(out)


def datetime_type(value):
    # Ruamel's TimeZone class can become invalid from the .replace(utc) call.
    # (I think it no longer matches the internal ._yaml fields.)
    # Convert to a regular datetime.
    if isinstance(value, RuamelTimeStamp):
        value = value.isoformat()

    if isinstance(value, str):
        value = ciso8601.parse_datetime(value)

    # Store all dates with a timezone.
    # yaml standard says all dates default to UTC.
    # (and ruamel normalises timezones to UTC itself)
    return default_utc(value)


def of_enum_type(
    vals: Union[EnumMeta, Tuple[str, ...]] = None, lower=False, upper=False, strict=True
) -> Callable[[str], str]:
    if isinstance(vals, EnumMeta):
        vals = tuple(vals.__members__.keys())

    def normalise(v: str):
        if isinstance(v, Enum):
            v = v.name

        if upper:
            v = v.upper()
        if lower:
            v = v.lower()

        if v not in vals:
            msg = f"Unexpected value {v!r}. Expected one of: {', '.join(vals)},"
            if strict:
                raise ValueError(msg)
            else:
                warnings.warn(msg)
        return v

    return normalise


def percent_type(value):
    value = float(value)

    if not (0.0 <= value <= 100.0):
        raise ValueError("Expected percent between 0,100")
    return value


def degrees_type(value):
    value = float(value)

    if not (-360.0 <= value <= 360.0):
        raise ValueError("Expected degrees between -360,+360")

    return value


def identifier_type(v: str):
    v = v.replace("-", "_")
    if not v.isidentifier() or not v.islower():
        warnings.warn(
            f"{v!r} is expected to be an identifier "
            "(alphanumeric with underscores, typically lowercase)"
        )
    return v


# The primitive types allowed as stac values.
PrimitiveType = Union[str, int, float, datetime]

ExtraProperties = Dict
# A function to normalise a value.
# (eg. convert to int, or make string lowercase).
# They throw a ValueError if not valid.
NormaliseValueFn = Callable[
    [Any],
    # It returns the normalised value, but can optionally also return extra property values extracted from it.
    Union[PrimitiveType, Tuple[PrimitiveType, ExtraProperties]],
]


class Eo3DictBase(collections.abc.MutableMapping):
    """
    Base class for a properties dictionary.  Mostly content-agnostic except where
    relevant for datacube-core.

    Normally use an extension with better knowledge of properties of interest.

    This acts like a dictionary, but will normalise known properties (consistent
    case, types etc) and warn about common mistakes.

    It wraps an inner dictionary. By default it will normalise the fields in
    the input dictionary on creation, but you can disable this with `normalise_input=False`.
    """

    # Every property we know about.  Subclasses should extend this mapping.
    KNOWN_PROPERTIES: Mapping[str, Optional[NormaliseValueFn]] = {
        "datetime": datetime_type,
        "dtr:end_datetime": datetime_type,
        "dtr:start_datetime": datetime_type,
        "odc:file_format": of_enum_type(FileFormat, strict=False),
        "odc:processing_datetime": datetime_type,
        "odc:product": None,
    }

    def __init__(self, properties: Mapping = None, normalise_input=True) -> None:
        if properties is None:
            properties = {}
        self._props = properties
        # We normalise the properties they gave us.
        for key in list(self._props):
            # We always want to normalise dates as datetime objects rather than strings
            # for consistency.
            if normalise_input or ("datetime" in key):
                self.normalise_and_set(key, self._props[key], expect_override=True)
        self._finished_init_ = True

    def __setattr__(self, name: str, value: Any) -> None:
        """
        Prevent against users accidentally setting new properties (it has happened multiple times).
        """
        if hasattr(self, "_finished_init_") and not hasattr(self, name):
            raise TypeError(
                f"Cannot set new field '{name}' on a dict. "
                f"(Perhaps you meant to set it as a dictionary field??)"
            )
        super().__setattr__(name, value)

    def __getitem__(self, item):
        return self._props[item]

    def __iter__(self):
        return iter(self._props)

    def __len__(self):
        return len(self._props)

    def __delitem__(self, name: str) -> None:
        del self._props[name]

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self._props!r})"

    def __setitem__(self, key, value):
        self.normalise_and_set(
            key,
            value,
            # They can override properties but will receive a warning.
            allow_override=True,
        )

    def normalise_and_set(self, key, value, allow_override=True, expect_override=False):
        """
        Set a property with the usual normalisation.

        This has some options that are not available on normal dictionary item
        setting (``self[key] = val``)

        The default behaviour of this class is very conservative in order to catch common errors
        of users. You can loosen the settings here.

        :argument allow_override: Is it okay to overwrite an existing value? (if not, error will be thrown)
        :argument expect_override: We expect to overwrite a property, so don't produce a warning or error.
        """
        if key not in self.KNOWN_PROPERTIES:
            warnings.warn(
                f"Unknown Stac property {key!r}. "
            )

        if value is not None:
            normalise = self.KNOWN_PROPERTIES.get(key)
            if normalise:
                value = normalise(value)
                # If the normaliser has extracted extra properties, we'll get two return values.
                if isinstance(value, Tuple):
                    value, extra_properties = value
                    for k, v in extra_properties.items():
                        if k == key:
                            raise RuntimeError(
                                f"Infinite loop: writing key {k!r} from itself"
                            )
                        self.normalise_and_set(k, v, allow_override=allow_override)

        if key in self._props and value != self[key] and (not expect_override):
            message = (
                f"Overriding property {key!r} " f"(from {self[key]!r} to {value!r})"
            )
            if allow_override:
                warnings.warn(message, category=PropertyOverrideWarning)
            else:
                raise KeyError(message)

        self._props[key] = value

    def nested(self):
        return nest_properties(self._props)


class PropertyOverrideWarning(UserWarning):
    """A warning that a property was set twice with different values."""


class Eo3InterfaceBase:
    """
    These are convenience properties for common metadata fields. They are available
    on DatasetAssemblers and within other naming APIs.

    (This is abstract. If you want one of these of your own, you probably want to create
    an :class:`eo3.DatasetDoc`)

    """

    @property
    @abstractmethod
    def properties(self) -> Eo3DictBase:
        raise NotImplementedError

    @property
    def product_name(self) -> Optional[str]:
        """
        The ODC product name
        """
        return self.properties.get("odc:product")

    @product_name.setter
    def product_name(self, value: str):
        self.properties["odc:product"] = value

    @property
    def datetime_range(self) -> Tuple[datetime, datetime]:
        """
        An optional date range for the dataset.

        The ``datetime`` is still mandatory when this is set.

        This field is a shorthand for reading/setting the datetime-range
        stac 0.6 extension properties: ``dtr:start_datetime`` and ``dtr:end_datetime``
        """
        return (
            self.properties.get("dtr:start_datetime"),
            self.properties.get("dtr:end_datetime"),
        )

    @datetime_range.setter
    def datetime_range(self, val: Tuple[datetime, datetime]):
        # TODO: string type conversion, better validation/errors
        start, end = val
        self.properties["dtr:start_datetime"] = start
        self.properties["dtr:end_datetime"] = end

    @property
    def processed(self) -> datetime:
        """When the dataset was created (Defaults to UTC if not specified)

        Shorthand for the ``odc:processing_datetime`` field
        """
        return self.properties.get("odc:processing_datetime")

    @processed.setter
    def processed(self, value: Union[str, datetime]):
        self.properties["odc:processing_datetime"] = value

    def processed_now(self):
        """
        Shorthand for when the dataset was processed right now on the current system.
        """
        self.properties["odc:processing_datetime"] = datetime.utcnow()

    # Note that giving a method the name 'datetime' will override the 'datetime' type
    # for class-level declarations (ie, for any types on functions!)
    # So we make an alias:
    from datetime import datetime as datetime_

    @property
    def datetime(self) -> datetime_:
        """
        The searchable date and time of the assets. (Default to UTC if not specified)
        """
        return self.properties.get("datetime")

    @datetime.setter
    def datetime(self, val: datetime_):
        self.properties["datetime"] = val
