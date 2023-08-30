from pathlib import Path

import jsonschema

from eo3.utils import read_file

# from typing import Dict


def _is_json_array(checker, instance) -> bool:
    """
    By default, jsonschema only allows a json array to be a Python list.
    Let's allow it to be a tuple too.
    """
    return isinstance(instance, (list, tuple))


def _load_schema_validator(p: Path) -> jsonschema.Draft6Validator:
    """
    Create a schema instance for the file.

    (Assumes they are trustworthy. Only local schemas!)
    """
    if not p.is_file():
        raise ValueError(f"Can only load local schemas. Could not find file {str(p)}")
    if p.suffix.lower() not in (".yaml", ".yml"):
        raise ValueError(f"Unexpected file type {p.suffix}. Expected yaml")
    schema = read_file(p)
    validator = jsonschema.validators.validator_for(schema)
    validator.check_schema(schema)

    # Allow schemas to reference other schemas relatively
    def doc_reference(path):
        path = p.parent.joinpath(path)
        if not path.exists():
            raise ValueError(f"Reference not found: {path}")
        referenced_schema = read_file(path)
        return referenced_schema

    ref_resolver = jsonschema.RefResolver.from_schema(
        schema, handlers={"": doc_reference}
    )
    custom_validator = jsonschema.validators.extend(
        validator, type_checker=validator.TYPE_CHECKER.redefine("array", _is_json_array)
    )
    return custom_validator(schema, resolver=ref_resolver)


SCHEMAS_PATH = Path(__file__).parent
DATASET_SCHEMA = _load_schema_validator(SCHEMAS_PATH / "dataset.schema.yaml")
PRODUCT_SCHEMA = _load_schema_validator(SCHEMAS_PATH / "product-schema.yaml")
METADATA_TYPE_SCHEMA = _load_schema_validator(
    SCHEMAS_PATH / "metadata-type-schema.yaml"
)
