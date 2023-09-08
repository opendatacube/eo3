import enum
import gzip
import itertools
import json
import math
import os
import re
import threading
from collections import OrderedDict
from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, Tuple, Union
from urllib.parse import urlparse
from urllib.request import urlopen
from uuid import UUID

import ciso8601
import click
import dateutil.parser
import numpy
from ruamel.yaml import YAML, YAMLError

from .uris import as_url, mk_part_uri, uri_to_local_path

# TODO: ideally the functions marked as 'general util' (originally copied
# over from core) would eventually be moved to a lower-level utils package


class ItemProvider(enum.Enum):
    PRODUCER = "producer"
    PROCESSOR = "processor"
    HOST = "host"
    LICENSOR = "licensor"


class ClickDatetime(click.ParamType):
    """
    Take a datetime parameter, supporting any ISO8601 date/time/timezone combination.
    """

    name = "date"

    def convert(self, value, param, ctx):
        if value is None:
            return value

        if isinstance(value, datetime):
            return value

        try:
            return ciso8601.parse_datetime(value)
        except ValueError:
            self.fail(
                (
                    "Invalid date string {!r}. Expected any ISO date/time format "
                    '(eg. "2017-04-03" or "2014-05-14 12:34")'.format(value)
                ),
                param,
                ctx,
            )


def read_paths_from_file(listing: Path) -> Iterable[Path]:
    """
    A generator that yields path from a file; paths encoded one per line
    """
    with listing.open("r") as f:
        for loc in f.readlines():
            path = Path(loc.strip())
            if not path.exists():
                raise FileNotFoundError(
                    f"No such file or directory: {os.path.abspath(loc)}"
                )

            yield path.absolute()


def default_utc(d: datetime) -> datetime:
    if d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def subfolderise(code: str) -> Tuple[str, ...]:
    """
    Cut a string folder name into subfolders if long.

    (Forward slashes only, as it assumes you're using Pathlib's normalisation)

    >>> subfolderise('089090')
    ('089', '090')
    >>> # Prefer fewer folders in first level.
    >>> subfolderise('12345')
    ('12', '345')
    >>> subfolderise('123456')
    ('123', '456')
    >>> subfolderise('1234567')
    ('123', '4567')
    >>> subfolderise('12')
    ('12',)
    """
    if len(code) > 2:
        return (code[: len(code) // 2], code[len(code) // 2 :])
    return (code,)


_NUMERIC_BAND_NAME = re.compile(r"(?P<number>\d+)(?P<suffix>[a-zA-Z]?)", re.IGNORECASE)


def normalise_band_name(band_name: str) -> str:
    """
    Normalise band names by our norms.

    Numeric bands have a 'band' prefix, others are lowercase with

    >>> normalise_band_name('4')
    'band04'
    >>> normalise_band_name('8a')
    'band08a'
    >>> normalise_band_name('8A')
    'band08a'
    >>> normalise_band_name('QUALITY')
    'quality'
    >>> normalise_band_name('Azimuthal-Angles')
    'azimuthal_angles'
    """

    match = _NUMERIC_BAND_NAME.match(band_name)
    if match:
        number = int(match.group("number"))
        suffix = match.group("suffix")
        band_name = f"band{number:02}{suffix}"

    return band_name.lower().replace("-", "_")


def get_collection_number(
    platform: str, producer: str, usgs_collection_number: int
) -> int:
    # This logic is in one place as it's not very future-proof...

    # We didn't do sentinel before now...
    if platform.startswith("sentinel"):
        return 3

    if producer == "usgs.gov":
        return usgs_collection_number
    elif producer == "ga.gov.au":
        # GA's collection 3 processes USGS Collection 1 and 2
        if usgs_collection_number == 1 or usgs_collection_number == 2:
            return 3
        else:
            raise NotImplementedError("Unsupported GA collection number.")
    raise NotImplementedError(
        f"Unsupported collection number mapping for org: {producer!r}"
    )


def flatten_dict(
    d: Mapping, prefix: str = None, separator: str = "."
) -> Iterable[Tuple[str, Any]]:
    """
    Flatten a nested dicts into one level, with keys that show their original nested path ("a.b.c")

    Returns them as a generator of (key, value) pairs.

    (Doesn't currently venture into other collection types, like lists)

    >>> dict(flatten_dict({'a' : 1, 'b' : {'inner' : 2},'c' : 3}))
    {'a': 1, 'b.inner': 2, 'c': 3}
    >>> dict(flatten_dict({'a' : 1, 'b' : {'inner' : {'core' : 2}}}, prefix='outside', separator=':'))
    {'outside:a': 1, 'outside:b:inner:core': 2}
    """
    for k, v in d.items():
        name = f"{prefix}{separator}{k}" if prefix else k
        if isinstance(v, Mapping):
            yield from flatten_dict(v, prefix=name, separator=separator)
        else:
            yield name, v


# CORE TODO: from datacube.utils.documents
# TODO: general util
@contextmanager
def _open_from_s3(url):
    o = urlparse(url)
    if o.scheme != "s3":
        raise RuntimeError("Abort abort I don't know how to open non s3 urls")

    from eo3.utils.aws import s3_open

    yield s3_open(url)


# CORE TODO: from datacube.utils.documents
# TODO: general util
def _open_with_urllib(url):
    return urlopen(url)  # nosec B310


# CORE TODO: from datacube.utils.documents
# TODO: general util
_PROTOCOL_OPENERS = {
    "s3": _open_from_s3,
    "ftp": _open_with_urllib,
    "http": _open_with_urllib,
    "https": _open_with_urllib,
    "file": _open_with_urllib,
}


# CORE TODO: from datacube.utils.documents
# TODO: general util
def load_from_yaml(handle):
    yield from YAML(typ="safe").load_all(handle)  # noqa: DUO109


# CORE TODO: from datacube.utils.documents
# TODO: general util
def load_from_json(handle):
    yield json.load(handle)


# TODO: general util
def load_from_netcdf(path):
    for doc in read_strings_from_netcdf(path, variable="dataset"):
        yield YAML(typ="safe").load(doc)


# TODO: general util
def netcdf_extract_string(chars):
    """
    Convert netcdf S|U chars to Unicode string.
    """
    import netCDF4  # type: ignore[import]

    if isinstance(chars, str):
        return chars

    chars = netCDF4.chartostring(chars)
    if chars.dtype.kind == "U":
        return str(chars)
    else:
        return str(numpy.char.decode(chars))


# TODO: general util
def read_strings_from_netcdf(path, variable):
    """
    Load all of the string encoded data from a variable in a NetCDF file.

    By 'string', the CF conventions mean ascii.

    Useful for loading dataset metadata information.
    """
    import netCDF4

    with netCDF4.Dataset(str(path)) as ds:
        for chars in ds[variable]:
            yield netcdf_extract_string(chars)


# TODO: general util
_PARSERS = {
    ".yaml": load_from_yaml,
    ".yml": load_from_yaml,
    ".json": load_from_json,
}


# TODO: general util
def transform_object_tree(f, o, key_transform=lambda k: k):
    """
    Apply a function (f) on all the values in the given document tree (o), returning a new document of
    the results.

    Recurses through container types (dicts, lists, tuples).

    Returns a new instance (deep copy) without modifying the original.

    :param f: Function to apply on values.
    :param o: document/object
    :param key_transform: Optional function to apply on any dictionary keys.

    """
    # CORE TODO: from datacube.utils.documents

    def recur(o_):
        return transform_object_tree(f, o_, key_transform=key_transform)

    if isinstance(o, OrderedDict):
        return OrderedDict((key_transform(k), recur(v)) for k, v in o.items())
    if isinstance(o, dict):
        return {key_transform(k): recur(v) for k, v in o.items()}
    if isinstance(o, list):
        return [recur(v) for v in o]
    if isinstance(o, tuple):
        return tuple(recur(v) for v in o)
    return f(o)


# TODO: general util
def jsonify_document(doc):
    """
    Make a document ready for serialisation as JSON.

    Returns the new document, leaving the original unmodified.
    """
    # CORE TODO: from datacube.utils.serialise

    def fixup_value(v):
        if isinstance(v, float):
            if math.isfinite(v):
                return v
            if math.isnan(v):
                return "NaN"
            return "-Infinity" if v < 0 else "Infinity"
        if isinstance(v, (datetime, date)):
            return v.isoformat()
        if isinstance(v, numpy.dtype):
            return v.name
        if isinstance(v, UUID):
            return str(v)
        if isinstance(v, Decimal):
            return str(v)
        return v

    return transform_object_tree(fixup_value, doc, key_transform=str)


# TODO: general util
def load_documents(path):
    """
    Load document/s from the specified path.

    At the moment can handle:

     - JSON and YAML locally and remotely.
     - Compressed JSON and YAML locally
     - Data Cube Dataset Documents inside local NetCDF files.

    :param path: path or URI to load documents from
    :return: generator of dicts
    """
    # CORE TODO: from datacube.utils.documents
    path = str(path)
    url = as_url(path)
    scheme = urlparse(url).scheme
    compressed = url[-3:] == ".gz"

    if scheme == "file" and path[-3:] == ".nc":
        path = uri_to_local_path(url)
        yield from load_from_netcdf(path)
    else:
        with _PROTOCOL_OPENERS[scheme](url) as fh:
            if compressed:
                fh = gzip.open(fh)
                path = path[:-3]

            suffix = Path(path).suffix

            parser = _PARSERS[suffix]

            yield from parser(fh)


# CORE TODO: from datacube.utils.documents
# TODO: general util
class InvalidDocException(Exception):  # noqa: N818
    pass


# CORE TODO: from datacube.utils.generic
# TODO: general util
def map_with_lookahead(it, if_one=None, if_many=None):
    """
    It's like normal map: creates a new generator by applying a function to every
    element of the original generator, but it applies `if_one` transform for
    single element sequences and `if_many` transform for multi-element sequences.

    If iterators supported `len` it would be equivalent to the code below::

        proc = if_many if len(it) > 1 else if_one
        return map(proc, it)

    :param it: Sequence to iterate over
    :param if_one: Function to apply for single element sequences
    :param if_many: Function to apply for multi-element sequences

    """
    if_one = if_one or (lambda x: x)
    if_many = if_many or (lambda x: x)

    it = iter(it)
    p1 = list(itertools.islice(it, 2))
    proc = if_many if len(p1) > 1 else if_one

    for v in itertools.chain(iter(p1), it):
        yield proc(v)


# TODO: general util
def read_documents(*paths, uri=False):
    """
    Read and parse documents from the filesystem or remote URLs (yaml or json).

    Note that a single yaml file can contain multiple documents.

    This function will load any dates in the documents as strings. In
    Data Cube we store JSONB in PostgreSQL and it will turn our dates
    into strings anyway.

    :param uri: When True yield URIs instead of Paths
    :param paths: input Paths or URIs
    :type uri: Bool
    :rtype: tuple[(str, dict)]
    """
    # CORE TODO: from datacube.utils.documents

    def process_file(path):
        docs = load_documents(path)

        if not uri:
            for doc in docs:
                yield path, doc
        else:
            url = as_url(path)

            def add_uri_no_part(x):
                idx, doc = x
                return url, doc

            def add_uri_with_part(x):
                idx, doc = x
                return mk_part_uri(url, idx), doc

            yield from map_with_lookahead(
                enumerate(docs), if_one=add_uri_no_part, if_many=add_uri_with_part
            )

    for path in paths:
        try:
            yield from process_file(path)
        except InvalidDocException as e:
            raise e
        except (YAMLError, ValueError) as e:
            raise InvalidDocException(f"Failed to load {path}: {e}")
        except Exception as e:
            raise InvalidDocException(f"Failed to load {path}: {e}")


# TODO: general util
def read_file(p: Path):
    """Shorthand for when you just need to get the dict representation of 1 file"""
    return next(iter(read_documents(p)))[1]


# CORE TODO: from datacube.utils.changes
# TODO: general util
# Type that can be checked for changes.
# (MyPy approximation without recursive references)
Changable = Union[str, int, None, Sequence[Any], Mapping[str, Any]]
# More accurate recursive definition:
# Changable = Union[str, int, None, Sequence["Changable"], Mapping[str, "Changable"]]


def contains(v1: Changable, v2: Changable, case_sensitive: bool = False) -> bool:
    """
    Check that v1 is a superset of v2.

    For dicts contains(v1[k], v2[k]) for all k in v2
    For other types v1 == v2
    v2 None is interpreted as {}

    """
    if not case_sensitive:
        if isinstance(v1, str):
            return isinstance(v2, str) and v1.lower() == v2.lower()

    if isinstance(v1, dict):
        return v2 is None or (
            isinstance(v2, dict)
            and all(
                contains(v1.get(k, object()), v, case_sensitive=case_sensitive)
                for k, v in v2.items()
            )
        )

    return v1 == v2


def _is_nan(v):
    # Due to JSON serialisation, nan can also be represented as a string 'NaN'
    # TODO: Do we need something similar for Inf and -Inf?
    if isinstance(v, str):
        return v == "NaN"
    return isinstance(v, float) and math.isnan(v)


# CORE TODO: from datacube.utils.dates
# TODO: general util
def parse_time(time: Union[str, datetime]) -> datetime:
    """Convert string to datetime object

    This function deals with ISO8601 dates fast, and fallbacks to python for
    other formats.

    Calling this on datetime object is a no-op.
    """
    if isinstance(time, str):
        try:
            from ciso8601 import (  # pylint: disable=wrong-import-position # noqa: F401
                parse_datetime,
            )

            return parse_datetime(time)
        except (ImportError, ValueError):  # pragma: no cover
            return dateutil.parser.parse(time)

    return time


# CORE TODO: from datacube.utils.generic.py
# TODO: general util
_LCL = threading.local()


def thread_local_cache(
    name: str, initial_value: Any = None, purge: bool = False
) -> Any:
    """Define/get thread local object with a given name.

    :param name:          name for this cache
    :param initial_value: Initial value if not set for this thread
    :param purge:         If True delete from cache (returning what was there previously)

    Returns
    -------
    value previously set in the thread or `initial_value`
    """
    absent = object()
    cc = getattr(_LCL, name, absent)
    absent = cc is absent

    if absent:
        cc = initial_value

    if purge:
        if not absent:
            delattr(_LCL, name)
    else:
        if absent:
            setattr(_LCL, name, cc)

    return cc
