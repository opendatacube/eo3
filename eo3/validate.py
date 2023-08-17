"""
Validate ODC dataset documents
"""
from textwrap import indent
from typing import (
    Dict,
    Iterable,
    List,
    Mapping,
    Set,
    Tuple,
)
import warnings

from eo3 import serialise, utils
from eo3.utils import contains
from eo3.validation_msg import (
    ContextualMessager,
    Level,
    ValidationMessages,
)


def validate_ds_to_schema(doc: Dict, msg: ContextualMessager) -> ValidationMessages:
    """
    Validate against eo3 schema
    """
    for error in serialise.DATASET_SCHEMA.iter_errors(doc):
        displayable_path = ".".join(error.absolute_path)

        hint = None
        if displayable_path == "crs" and "not of type" in error.message:
            hint = "epsg codes should be prefixed with 'epsg', e.g. 'epsg:1234'"

        context = f"({displayable_path}) " if displayable_path else ""
        yield msg.error("structure", f"{context}{error.message} ", hint=hint)


def validate_ds_to_product(
    doc: Dict,
    product_definition: Mapping,
    msg: ContextualMessager,
):
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
            "Dataset template does not match product document template.",
            hint=difference_hint,
        )

    product_measurement_names = [m["name"] for m in product_definition.get("measurements")]
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


# this checks that all mdtype fields are in dataset (which they don't necessarily need to be)
# but doesn't check for ds fields that are not in mdtype (which would be more problematic)
# consider removing altogether
def validate_ds_to_metadata_type(
    doc: Dict,
    metadata_type_definition: Dict,
    msg: ContextualMessager,
):
    for field_name, offsets in _get_field_offsets(
        metadata_type=metadata_type_definition
    ):
        # If none of a field's offsets are in the document - ignore for lineage
        if field_name != "sources" and not any(_has_offset(doc, offset) for offset in offsets):
            # ... warn them.
            readable_offsets = " or ".join("->".join(offset) for offset in offsets)
            yield msg.warning(
                "missing_field",
                f"Dataset is missing field {field_name!r} "
                f"for type {metadata_type_definition['name']!r}",
                hint=f"Expected at {readable_offsets}",
            )
            continue


def _has_offset(doc: Dict, offset: List[str]) -> bool:
    """
    Is the given offset present in the document?
    """
    for key in offset:
        if key not in doc:
            return False
        doc = doc[key]
    return True


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
    dataset_section = metadata_type["dataset"]
    search_fields = dataset_section["search_fields"]

    # The fixed fields of ODC. 'id', 'label', etc.
    for field_name in dataset_section:
        if field_name != "search_fields":
            offset = dataset_section[field_name]
            if offset is not None:
                yield field_name, [offset]

    # The configurable search fields.
    for field_name, spec in search_fields.items():
        offsets = []
        if "offset" in spec:
            offsets.append(spec["offset"])
        # offsets.extend(spec.get("min_offset", []))
        # offsets.extend(spec.get("max_offset", []))

        yield field_name, offsets


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


class IncompleteDatasetError(Exception):
    """
    Raised when a dataset is missing essential things and so cannot be written.

    (such as mandatory metadata)
    """
    pass


class IncompleteDatasetWarning(UserWarning):
    """A non-critical warning for invalid or incomplete metadata"""
    pass


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
        warnings.warn(IncompleteDatasetWarning("\n".join(warns)))
    if errors:
        raise IncompleteDatasetError("\n".join(errors))
