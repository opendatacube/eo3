import collections.abc
import warnings
from collections import defaultdict
from datetime import datetime
from enum import Enum, EnumMeta
from typing import Any, Callable, Dict, Mapping, Optional, Tuple, Union

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


def degrees_type(value):
    value = float(value)

    if not (-360.0 <= value <= 360.0):
        raise ValueError("Expected degrees between -360,+360")

    return value


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


def producer_check(value):
    if "." not in value:
        warnings.warn(
            "Property 'odc:producer' is expected to be a domain name, "
            "eg 'usgs.gov' or 'ga.gov.au'"
        )
    return value


def normalise_platforms(value: Union[str, list, set]):
    """
    >>> normalise_platforms('LANDSAT_8')
    'landsat-8'
    >>> # Multiple can be comma-separated. They're normalised independently and sorted.
    >>> normalise_platforms('LANDSAT_8,Landsat-5,landsat-7')
    'landsat-5,landsat-7,landsat-8'
    >>> # Can be given as a list.
    >>> normalise_platforms(['sentinel-2b','SENTINEL-2a'])
    'sentinel-2a,sentinel-2b'
    >>> # Deduplicated too
    >>> normalise_platforms('landsat-5,landsat-5,LANDSAT-5')
    'landsat-5'
    """
    if not isinstance(value, (list, set, tuple)):
        value = value.split(",")

    platforms = sorted({s.strip().lower().replace("_", "-") for s in value if s})
    if not platforms:
        return None

    return ",".join(platforms)


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

    # Every property we know about. Subclasses should extend this mapping.
    KNOWN_PROPERTIES: Mapping[str, Optional[NormaliseValueFn]] = {
        "datetime": datetime_type,
        "dtr:end_datetime": datetime_type,
        "dtr:start_datetime": datetime_type,
        "odc:file_format": of_enum_type(FileFormat, strict=False),
        "odc:processing_datetime": datetime_type,
        "odc:product": None,
        "dea:dataset_maturity": of_enum_type(("final", "interim", "nrt"), lower=True),
        "odc:region_code": None,
        "odc:producer": producer_check,
        # Common STAC properties
        "eo:gsd": None,
        "eo:instrument": None,
        "eo:platform": normalise_platforms,
        "eo:constellation": None,
        "eo:off_nadir": float,
        "eo:azimuth": float,
        "eo:sun_azimuth": degrees_type,
        "eo:sun_elevation": degrees_type,
    }

    # Required properties whose presence will be enforced.
    REQUIRED_PROPERTIES = ["datetime", "odc:processing_datetime"]

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
            warnings.warn(f"Unknown Stac property {key!r}.")

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

    def validate_properties(self):
        # Enforce presence of properties identified as required
        missing_required = []
        for prop in self.REQUIRED_PROPERTIES:
            if self._props.get(prop) is None:
                missing_required.append(prop)
        if missing_required:
            raise KeyError(
                f"The following required properties are missing or None: {', '.join(missing_required)}"
            )


class PropertyOverrideWarning(UserWarning):
    """A warning that a property was set twice with different values."""
