import collections
from typing import Dict, Sequence, Iterable, Generator

import numpy as np

from eo3 import serialise
from eo3.utils import _is_nan
from eo3.validation_msg import ValidationMessages, ValidationMessage


def validate_product(doc: Dict) -> ValidationMessages:
    """
    Check for common product mistakes
    """

    # Validate it against ODC's product schema.
    has_doc_errors = False
    for error in serialise.PRODUCT_SCHEMA.iter_errors(doc):
        has_doc_errors = True
        displayable_path = ".".join(map(str, error.absolute_path))
        context = f"({displayable_path}) " if displayable_path else ""
        yield ValidationMessage.error("document_schema", f"{context}{error.message} ")

    # The jsonschema error message for this (common error) is garbage. Make it clearer.
    measurements = doc.get("measurements")
    if (measurements is not None) and not isinstance(measurements, Sequence):
        yield ValidationMessage.error(
            "measurements_list",
            f"Product measurements should be a list/sequence "
            f"(Found a {type(measurements).__name__!r}).",
        )

    # There's no point checking further if the core doc structure is wrong.
    if has_doc_errors:
        return

    if not doc.get("license", "").strip():
        yield ValidationMessage.warning(
            "no_license",
            f"Product {doc['name']!r} has no license field",
            hint='Eg. "CC-BY-4.0" (SPDX format), "various" or "proprietary"',
        )

    # Check measurement name clashes etc.
    if measurements is None:
        # Products don't have to have measurements. (eg. provenance-only products)
        ...
    else:
        seen_names_and_aliases = collections.defaultdict(list)
        for measurement in measurements:
            measurement_name = measurement.get("name")
            dtype = measurement.get("dtype")
            nodata = measurement.get("nodata")
            if not numpy_value_fits_dtype(nodata, dtype):
                yield ValidationMessage.error(
                    "unsuitable_nodata",
                    f"Measurement {measurement_name!r} nodata {nodata!r} does not fit a {dtype!r}",
                )

            # Were any of the names seen in other measurements?
            these_names = measurement_name, *measurement.get("aliases", ())
            for new_field_name in these_names:
                measurements_with_this_name = seen_names_and_aliases[new_field_name]
                if measurements_with_this_name:
                    seen_in = " and ".join(
                        repr(s)
                        for s in ([measurement_name] + measurements_with_this_name)
                    )

                    # If the same name is used by different measurements, its a hard error.
                    yield ValidationMessage.error(
                        "duplicate_measurement_name",
                        f"Name {new_field_name!r} is used by multiple measurements",
                        hint=f"It's duplicated in an alias. "
                        f"Seen in measurement(s) {seen_in}",
                    )

            # Are any names duplicated within the one measurement? (not an error, but info)
            for duplicate_name in _find_duplicates(these_names):
                yield ValidationMessage.info(
                    "duplicate_alias_name",
                    f"Measurement {measurement_name!r} has a duplicate alias named {duplicate_name!r}",
                )

            for field_ in these_names:
                seen_names_and_aliases[field_].append(measurement_name)


def numpy_value_fits_dtype(value, dtype):
    """
    Can the value be exactly represented by the given numpy dtype?

    >>> numpy_value_fits_dtype(3, 'uint8')
    True
    >>> numpy_value_fits_dtype(3, np.dtype('uint8'))
    True
    >>> numpy_value_fits_dtype(-3, 'uint8')
    False
    >>> numpy_value_fits_dtype(3.5, 'float32')
    True
    >>> numpy_value_fits_dtype(3.5, 'int16')
    False
    >>> numpy_value_fits_dtype(float('NaN'), 'float32')
    True
    >>> numpy_value_fits_dtype(float('NaN'), 'int32')
    False
    """
    dtype = np.dtype(dtype)

    if value is None:
        value = 0

    if _is_nan(value):
        return np.issubdtype(dtype, np.floating)
    else:
        return np.all(np.array([value], dtype=dtype) == [value])


def _find_duplicates(values: Iterable[str]) -> Generator[str, None, None]:
    """Return any duplicate values in the given sequence

    >>> list(_find_duplicates(('a', 'b', 'c')))
    []
    >>> list(_find_duplicates(('a', 'b', 'b')))
    ['b']
    >>> list(_find_duplicates(('a', 'b', 'b', 'a')))
    ['a', 'b']
    """
    previous = None
    for v in sorted(values):
        if v == previous:
            yield v
        previous = v
