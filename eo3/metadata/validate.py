# mypy: disable-error-code="call-arg"

from typing import Any, Callable, Optional, Sequence

from attr import define

from eo3 import schema
from eo3.validation_msg import ValidationMessage, ValidationMessages


@define
class LegacyField:
    name: str
    validator: Callable[[Sequence[str]], bool]
    description: Optional[str] = None
    hint: Optional[str] = None
    required: bool = False
    geospatial: bool = False

    def validate(self, candidate: Optional[Sequence[str]]) -> ValidationMessages:
        # self.search_field and not search_field doesn't pass schema so no need to check here
        if candidate is None:
            if self.required:
                yield ValidationMessage.error(
                    "missing_system_field",
                    f"Required field {self.name} in missing from dataset.",
                    hint=self.hint,
                )
        elif not self.validator(candidate):
            yield ValidationMessage.error(
                "bad_system_field",
                f"{self.name} in dataset is set to an EO-3 incompatible value.",
                hint=self.hint,
            )


legacy_fields = {
    "id": LegacyField(
        name="id",
        validator=lambda x: x == ["id"],
        required=True,
        hint="id must be present in the dataset section, and must be set to exactly [id]",
    ),
    "measurements": LegacyField(
        name="measurements",
        validator=lambda x: x == ["measurements"],
        geospatial=True,
        hint="measurements must be present in the dataset section, and must be set to exactly [measurements]",
    ),
    "label": LegacyField(
        name="label",
        validator=lambda x: x == ["label"],
        required=True,
        hint="label must be present in the dataset section, and must be set to exactly [label]",
    ),
    "creation_dt": LegacyField(
        name="creation_dt",
        validator=lambda x: x == ["properties", "odc:processing_datetime"],
        required=True,
        hint="Label must be present in the dataset section, "
        "and must be set to exactly [properties,odc:processing_datetime]",
    ),
    "format": LegacyField(
        name="format",
        validator=lambda x: x == ["properties", "odc:file_format"],
        geospatial=True,
        hint="measurements must be present in the dataset section, and must be set to exactly [measurements]",
    ),
    "sources": LegacyField(
        name="sources",
        validator=lambda x: x[0] == "lineage",
        hint="sources should be stored under 'lineage'",
    ),
    "grid_spatial": LegacyField(
        name="grid_spatial",
        validator=lambda x: True,
        geospatial=True,
        hint="grid_spatial is quietly ignored",
    ),
}


def validate_eo3_sharefield_offset(
    field_name: str, mdt_name: str, offset: Sequence[str]
) -> ValidationMessages:
    if not all(isinstance(element, str) for element in offset):
        # Not a simple offset, assume a compound offset
        for element in offset:
            yield from validate_eo3_sharefield_offset(field_name, mdt_name, element)
        return
    # Simple offset validation
    # Special EO3 indexable offsets
    if offset in [
        ["crs"],
        ["extent", "lat", "begin"],
        ["extent", "lat", "end"],
        ["extent", "lon", "begin"],
        ["extent", "lon", "end"],
    ]:
        return
    # Everything else should be stored flat in properties
    if offset[0] != "properties" or len(offset) != 2:
        yield ValidationMessage.error(
            "bad_offset",
            f"Search_field {field_name} in metadata type {mdt_name} "
            f"is not stored in an EO3-compliant location: {offset!r}",
        )


def validate_eo3_sharefield_offsets(
    field_name: str, mdt_name: str, defn: dict[str, Any]
) -> ValidationMessages:
    if field_name in legacy_fields:
        yield ValidationMessage.error(
            "system_field_in_search_fields",
            f"Field {field_name} is a reserved system field name and cannot be used as a search field",
        )
        return
    if defn.get("type", "string").endswith("-range"):
        # Range Type
        if "min_offset" in defn:
            yield from validate_eo3_sharefield_offset(
                field_name, mdt_name, defn["min_offset"]
            )
        else:
            yield ValidationMessage.error(
                "bad_range_nomin",
                f"No min_offset supplied for field {field_name} in metadata type {mdt_name}",
            )
        if "max_offset" in defn:
            yield from validate_eo3_sharefield_offset(
                field_name, mdt_name, defn["max_offset"]
            )
        else:
            yield ValidationMessage.error(
                "bad_range_nomax",
                f"No max_offset supplied for field {field_name} in metadata type {mdt_name}",
            )
    else:
        # Scalar Type
        if "offset" in defn:
            yield from validate_eo3_sharefield_offset(
                field_name, mdt_name, defn["offset"]
            )
        else:
            yield ValidationMessage.error(
                "bad_scalar",
                f"No offset supplied for field {field_name} in metadata type {mdt_name}",
            )


def validate_metadata_type(doc: dict[str, Any]) -> ValidationMessages:
    """
    Check for common metadata-type mistakes
    """
    # Must have a name and it's good for error reporting
    try:
        name = doc["name"]
    except KeyError:
        yield ValidationMessage.error("no_type_name", "Metadata type must have a name.")
        return
    # Validate it against ODC's schema (will be refused by ODC otherwise)
    for error in schema.METADATA_TYPE_SCHEMA.iter_errors(doc):
        displayable_path = ".".join(map(str, error.absolute_path))
        context = f"Error in {name}: ({displayable_path}) " if displayable_path else ""
        yield ValidationMessage.error("document_schema", f"{context}{error.message} ")

    # Validate system field offsets
    for k, v in doc["dataset"].items():
        if k == "search_fields":
            continue
        leg_fld = legacy_fields[k]
        yield from leg_fld.validate(v)

    # Validate all search field offsets are defined compliant with EO3/STAC assumptions
    for k, v in doc["dataset"]["search_fields"].items():
        yield from validate_eo3_sharefield_offsets(k, name, v)
