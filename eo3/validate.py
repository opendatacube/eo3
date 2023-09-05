"""
Validate ODC dataset documents
"""
import warnings
from textwrap import indent
from typing import Dict, Iterable, List, Mapping, Set, Tuple

import toolz

from eo3 import schema, utils
from eo3.fields import all_field_offsets
from eo3.uris import get_part, is_absolute
from eo3.utils import contains
from eo3.validation_msg import ContextualMessager, Level, ValidationMessages


def validate_ds_to_schema(
    doc: Dict, msg: ContextualMessager = None
) -> ValidationMessages:
    """
    Validate against eo3 schema
    """
    if msg is None:
        msg = ContextualMessager()

    for error in schema.DATASET_SCHEMA.iter_errors(doc):
        displayable_path = ".".join(error.absolute_path)

        hint = None
        if displayable_path == "crs" and "not of type" in error.message:
            hint = "epsg codes should be prefixed with 'epsg', e.g. 'epsg:1234'"

        context = f"({displayable_path}) " if displayable_path else ""
        yield msg.error("structure", f"{context}{error.message} ", hint=hint)

    # properties detailed in the schema that are optional but recommended
    recommended = [["product", "href"], ["properties", "dea:dataset_maturity"]]
    for r in recommended:
        if toolz.get_in(r, doc) is None:
            yield msg.warning(
                "recommended_field", f"Field {'->'.join(r)} is optional but recommended"
            )


def validate_ds_to_product(
    doc: Dict,
    product_definition: Mapping,
    msg: ContextualMessager = None,
):
    """Validate dataset is consistent with product definition"""
    if msg is None:
        msg = ContextualMessager({"product": product_definition.get("name")})

    product_name = msg.context.get("product")
    ds_product_name = doc.get("product").get("name")
    if product_name and product_name != ds_product_name:
        yield msg.error(
            "product_mismatch",
            f"Dataset product name {ds_product_name!r} "
            f"does not match the given product {product_name!r}",
        )

    ds_props = doc.get("properties")
    prod_props = product_definition["metadata"].get("properties", {})
    if not contains(ds_props, prod_props):
        diffs = tuple(_get_printable_differences(ds_props, prod_props))
        difference_hint = _differences_as_hint(diffs)
        yield msg.error(
            "metadata_mismatch",
            f"Dataset template does not match product document template for product {product_name!r}.",
            hint=difference_hint,
        )

    product_measurement_names = [
        m["name"] for m in product_definition.get("measurements")
    ]
    doc_measurements = doc.get("measurements").keys()
    for name in product_measurement_names:
        if name not in doc_measurements:
            yield msg.error(
                "missing_measurement",
                f"Product {product_name} expects a measurement {name!r})",
            )
    measurements_not_in_product = set(doc_measurements).difference(
        {m["name"] for m in product_definition.get("measurements") or ()}
    )

    if measurements_not_in_product:
        things = ", ".join(sorted(measurements_not_in_product))
        yield msg.warning(
            "extra_measurements",
            f"Dataset has measurements not present in product definition for {product_name!r}: {things}",
        )


def validate_ds_to_metadata_type(
    doc: Dict,
    metadata_type_definition: Dict,
    msg: ContextualMessager = None,
):
    """
    Validate against the metadata type definition. A dataset doesn't have to include
    all metadata type fields, but users should be warned that there are missing fields.
    """
    if msg is None:
        msg = ContextualMessager()

    for field_name, offsets in _get_field_offsets(metadata_type_definition):
        # If none of a field's offsets are in the document - ignore for lineage
        if field_name != "sources" and not any(
            _has_offset(doc, offset) for offset in offsets
        ):
            # ... warn them.
            readable_offsets = " or ".join("->".join(offset) for offset in offsets)
            yield msg.warning(
                "missing_field",
                f"Dataset is missing field {field_name!r} "
                f"expected by metadata type {metadata_type_definition['name']!r}",
                hint=f"Expected at offset {readable_offsets}",
            )
            continue


def validate_measurement_path(
    name, path, msg: ContextualMessager = None
) -> ValidationMessages:
    if msg is None:
        msg = ContextualMessager()

    if is_absolute(path):
        yield msg.warning(
            "absolute_path",
            f"measurement {name!r} has an absolute path: {path!r}",
        )

    part = get_part(path)
    if part is not None:
        yield msg.warning(
            "uri_part",
            f"measurement {name!r} has a part in the path. (Use band and/or layer instead)",
        )
    if isinstance(part, int):
        if part < 0:
            yield msg.error(
                "uri_invalid_part",
                f"measurement {name!r} has an invalid part (less than zero) in the path ({part})",
            )
    elif isinstance(part, str):
        yield msg.error(
            "uri_invalid_part",
            f"measurement {name!r} has an invalid part (non-integer) in the path ({part})",
        )


def _has_offset(doc: Dict, offset: List[str]) -> bool:
    """
    Is the given offset present in the document?
    """
    try:
        toolz.get_in(offset, doc, no_default=True)
        return True
    except (KeyError, IndexError):
        return False


# Name of a field and its possible offsets in the document.
FieldNameOffsets = Tuple[str, Set[List[str]]]


def _get_field_offsets(metadata_type: Dict) -> Iterable[FieldNameOffsets]:
    """
    Yield all fields and their possible document-offsets that are expected for this metadata type.

    Eg, if the metadata type has a region_code field expected properties->region_code, this
    will yield ('region_code', {['properties', 'region_code']})

    (Properties can have multiple offsets, where ODC will choose the first non-null one, hence the
    return of multiple offsets for each field.)
    """
    yield from all_field_offsets(metadata_type).items()


def _get_printable_differences(dict1: Dict, dict2: Dict):
    """
    Get a series of lines to print that show the reason that dict1 is not a superset of dict2
    """
    dict1 = dict(utils.flatten_dict(dict1))
    dict2 = dict(utils.flatten_dict(dict2))

    for path in dict2.keys():
        v1, v2 = dict1.get(path), dict2.get(path)
        if v1 != v2:
            yield f"{path}: {v1!r} != {v2!r}"


def _differences_as_hint(product_diffs):
    return indent("\n".join(product_diffs), prefix="\t")


class InvalidDatasetError(Exception):
    """
    Raised when a dataset is missing essential things (such as mandatory metadata)
    or contains invalid values and so cannot be written.
    """


class InvalidDatasetWarning(UserWarning):
    """A non-critical warning for invalid or incomplete metadata"""


def handle_validation_messages(messages: ValidationMessages):
    """Capture multiple errors or warning messages and raise them as one"""
    warns = []
    errors = []
    for msg in messages:
        if msg.level == Level.warning:
            warns.append(str(msg))
        if msg.level == Level.error:
            errors.append(str(msg))
    if warns:
        warnings.warn(InvalidDatasetWarning("\n".join(warns)))
    if errors:
        raise InvalidDatasetError("\n".join(errors))
