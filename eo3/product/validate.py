import collections
import re
from typing import Any, Generator, Iterable, Sequence

import numpy as np
from odc.geo import CRS
from pyproj.exceptions import CRSError

from eo3 import schema
from eo3.utils.utils import _is_nan
from eo3.validation_msg import ValidationMessage, ValidationMessages


def validate_product(doc: dict[str, Any]) -> ValidationMessages:
    """
    Check for common product mistakes
    """

    # Validate it against ODC's product schema.
    has_doc_errors = False
    for error in schema.PRODUCT_SCHEMA.iter_errors(doc):
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

    if not isinstance(doc.get("metadata_type"), str):
        yield ValidationMessage.warning(
            "embedded_metadata_type",
            "Embedded metadata types are deprecated, please reference metatdata type by name",
        )

    yield from validate_product_metadata(doc.get("metadata", {}), doc["name"])
    extra_dims: dict[str, dict] = {}
    yield from validate_extra_dimensions(
        doc.get("extra_dimensions", []), doc["name"], extra_dims
    )
    yield from validate_load_hints(doc)

    if doc.get("managed"):
        yield ValidationMessage.warning(
            "ingested_product", "Data ingestion and the managed flag are deprecated"
        )

    # Check measurement name clashes etc.
    if not measurements:
        # Products have historically not had to have measurements. (eg. provenance-only products)
        yield ValidationMessage.warning(
            "no_measurements", "Products with no measurements are deprecated."
        )
    else:
        seen_names_and_aliases = collections.defaultdict(list)  # type: ignore[var-annotated]
        for measurement in measurements:
            yield from validate_product_measurement(
                measurement, seen_names_and_aliases, extra_dims
            )


def validate_product_metadata(
    template: dict[str, Any], name: str
) -> ValidationMessages:
    for key, value in template.items():
        if key == "product":
            for prod_key, prod_val in value.items():
                if prod_key == "name":
                    if prod_val != name:
                        yield ValidationMessage.error(
                            "product_name_mismatch",
                            "If specified, metadata::product::name must match the product name "
                            f"(Expected {name}, got {prod_val})",
                        )
                    else:
                        yield ValidationMessage.warning(
                            "product_name_metadata_deprecated",
                            "Specifying product::name in the metadata section is deprecated",
                        )
                else:
                    yield ValidationMessage.error(
                        "invalid_product_metadata",
                        f"Only the name field is permitted in metadata::product::name ({prod_key})",
                    )
        elif key == "properties":
            for prop_key, prop_val in value.items():
                if isinstance(prop_val, dict):
                    yield ValidationMessage.error(
                        "nested_metadata",
                        "Nesting of metadata properties is not supported in EO3",
                    )
                elif not re.match(r"^[\w:]+$", prop_key):
                    yield ValidationMessage.error(
                        "invalid_metadata_properties_key",
                        f"Invalid metadata field name {prop_key}",
                        hint="Metadata field names can only contain alphanumeric characters, underscores and colons",
                    )
        else:
            yield ValidationMessage.error(
                "invalid_metadata_key",
                f"Invalid metadata subsection {key}",
                hint="Metadata section can only contain a properties subsection.",
            )


def validate_load_hints(doc) -> ValidationMessages:
    load = doc.get("load")
    if "storage" in doc and "load" in doc:
        yield ValidationMessage.warning(
            "storage_and_load",
            f"Product {doc['name']} contains both storage and load sections. "
            "Storage section is ignored if load section is provided.",
            hint="Remove storage section",
        )
    elif "storage" in doc:
        yield ValidationMessage.warning(
            "storage_section",
            "The storage section is deprecated. Please replace with a 'load' section or remove.",
        )
        storage = doc["storage"]
        if "crs" in storage and "resolution" in storage:
            if "tile_size" in storage:
                yield ValidationMessage.warning(
                    "storage_tilesize",
                    "Tile size in the storage section is no longer supported and should be removed.",
                )
        load = doc["storage"]
    if load:
        crs = None
        if "crs" not in load:
            yield ValidationMessage.error(
                "storage_nocrs",  # Can only occur via storage because of json schema
                "No CRS provided in load hints",
                hint="Add a CRS to the load section, or remove the load section",
            )
            return
        else:
            try:
                crs = CRS(load["crs"])
            except CRSError:
                yield ValidationMessage.error(
                    "load_invalid_crs",
                    "CRS in load hints is not a valid CRS",
                    hint="Use an EPSG code or WKT representation",
                )
                return
        if "align" in load:
            for dimname in crs.dimensions:
                if dimname not in load["align"]:
                    yield ValidationMessage.error(
                        "invalid_align_dim",
                        f"align does not have {dimname} dimension in load hints",
                        hint="Use the CRS coordinate names in align",
                    )
                elif not isinstance(load["align"][dimname], (int, float)):
                    yield ValidationMessage.error(
                        "invalid_align_type",
                        f"align for {dimname} dimension in load hints is not a number",
                        hint="Use a number between zero and one",
                    )
                elif load["align"][dimname] < 0 or load["align"][dimname] > 1:
                    yield ValidationMessage.warning(
                        "unexpected_align_val",
                        f"align for {dimname} dimension in outside range [0,1]",
                        hint="Use a number between zero and one",
                    )
        for dimname in crs.dimensions:
            if dimname not in load["resolution"]:
                yield ValidationMessage.error(
                    "invalid_resolution_dim",
                    f"resolution does not have {dimname} dimension in load hints",
                    hint="Use the CRS coordinate names in resolution",
                )
            elif not isinstance(load["resolution"][dimname], (int, float)):
                yield ValidationMessage.error(
                    "invalid_resolution_type",
                    f"resolution for {dimname} dimension in load hints is not a number",
                    hint="Use a number in the CRS units",
                )


def validate_extra_dimensions(
    extra_dimensions: Sequence[dict], prod_name: str, extra_dims: dict[str, dict]
) -> ValidationMessages:
    for dim in extra_dimensions:
        if dim["name"] in extra_dims:
            yield ValidationMessage.error(
                "duplicate_extra_dimension",
                f"Extra dimension {dim['name']} is defined twice in product {prod_name}",
            )
            continue
        dtype = dim["dtype"]
        for val in dim["values"]:
            if not numpy_value_fits_dtype(val, dtype):
                yield ValidationMessage.error(
                    "unsuitable_coords",
                    f"Extra dimension {dim['name']} value {val} does not fit a {dtype}",
                )
        extra_dims[dim["name"]] = dim


def validate_product_measurement(
    measurement, seen_names_and_aliases, extra_dims
) -> ValidationMessages:
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
                repr(s) for s in ([measurement_name] + measurements_with_this_name)
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

    # Validate extra_dim
    if "extra_dim" in measurement:
        if measurement["extra_dim"] not in extra_dims:
            yield ValidationMessage.error(
                "unknown_extra_dimension",
                f"Measurement {measurement_name} references unknown extra dimension {measurement['extra_dim']}",
                hint="Extra dimensions must be defined in the extra_dimensions section",
            )
        else:
            # For extra dimension measurements, expect a list of spectral definitions, with length
            # equal to length of dimension coordinate list
            if "spectral_definition" in measurement:
                if len(measurement["spectral_definition"]) != len(
                    extra_dims[measurement["extra_dim"]].get("values", [])
                ):
                    yield ValidationMessage.error(
                        "bad_extradim_spectra",
                        f"Measurement {measurement_name} referencing unknown extra dimension "
                        f"{measurement['extra_dim']} has spectral definition that does not match dimension coordinates",
                        hint="Extra dimension measurements should have "
                        "one spectral definition per dimension coordinate value",
                    )
                for spec_def in measurement["spectral_definition"]:
                    yield from validate_spectral_definition(spec_def)
    else:
        if "spectral_definition" in measurement:
            yield from validate_spectral_definition(measurement["spectral_definition"])

    if "flags_definition" in measurement:
        yield from validate_flags_definition(measurement["flags_definition"])


def validate_spectral_definition(spec_def: dict) -> ValidationMessages:
    # Schema does not declare wavelength and response required in spectral definition
    if "wavelength" not in spec_def or "response" not in spec_def:
        yield ValidationMessage.error(
            "invalid_spectral_definition",
            "Spectral definition must contain both a wavelength and response sequence",
        )
        return
    # Schema does not validate that wavelength and response are of equal length.
    if len(spec_def["wavelength"]) != len(spec_def["response"]):
        yield ValidationMessage.error(
            "mismatched_spectral_definition",
            "Spectral definition wavelength and response sequence must have matched lengths",
        )


def validate_flags_definition(flags: dict) -> ValidationMessages:
    for flagname, flag_def in flags.items():
        # Schema says "bits" is a number or an array.
        # Must be a postive int or an array of positive ints
        if isinstance(flag_def["bits"], float):
            yield ValidationMessage.error(
                "non_integer_bits",
                f"Flag definition bits must be a positive integer, "
                f"or a list of positive integers (found {flag_def['bits']})",
            )
            continue

        singlebit = isinstance(flag_def["bits"], int)
        if singlebit:
            if flag_def["bits"] < 0:
                yield ValidationMessage.error(
                    "non_integer_bits",
                    f"Flag definition bits must be a positive integer, "
                    f"or a list of positive integers (found {flag_def['bits']})",
                )
                continue
        if not singlebit:
            for bit in flag_def["bits"]:
                if not isinstance(bit, int):
                    yield ValidationMessage.error(
                        "non_integer_bits",
                        f"Flag definition bits must be a positive integer, "
                        f"or a list of positive integers (found {bit})",
                    )
                    continue
                elif bit < 0:
                    yield ValidationMessage.error(
                        "non_integer_bits",
                        f"Flag definition bits must be a positive integer, "
                        f"or a list of positive integers (found {bit})",
                    )
                    continue
        # Schema does not validate values.  Keys should be positive integers, values strings or true/false.
        # If bits is a single bit, the values keys should be 0 or 1.
        # If bits is a list of bits, the values key should be a positive integer that can be represented
        #    with the supplied bits.  (Skip this for now.)
        for k, v in flag_def["values"].items():
            if singlebit:
                if k not in (0, 1):
                    yield ValidationMessage.error(
                        "bad_bit_value_repr",
                        f"Flag definition values keys must be 0 or 1 where a single bit is specified (found {k})",
                    )
            else:
                if not isinstance(k, int) or k < 0:
                    yield ValidationMessage.error(
                        "bad_bits_value_repr",
                        f"Flag definition values keys must be a positive where a list of bits is specified (found {k})",
                    )
            if not isinstance(v, (str, bool)):
                yield ValidationMessage.error(
                    "bad_flag_value",
                    f"Flag definition values must be a string or a boolean (found {k})",
                )


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

    if _is_nan(value):
        return np.issubdtype(dtype, np.floating)
    else:
        return np.all(np.array([value]).astype(dtype) == [value])


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
