from typing import Dict

import pytest
import toolz

from eo3 import validate
from eo3.model import DatasetMetadata
from eo3.validate import (
    InvalidDatasetError,
    validate_ds_to_metadata_type,
    validate_ds_to_product,
    validate_ds_to_schema,
)
from eo3.validation_msg import ValidationMessage

from tests.common import MessageCatcher


def test_val_msg_str():
    msg = ValidationMessage.info(
        "test_msg", "Spam, spam, spam, sausages and spam", hint="I don't like spam!"
    )
    msg_str = str(msg)
    assert "test_msg" in msg_str
    assert "sausages and spam" in msg_str
    assert "I don't like spam!" in msg_str


def test_valid_document_works(
    l1_ls8_folder_md_expected: Dict, eo3_product, metadata_type
):
    """All of our example metadata files should validate"""
    dataset = l1_ls8_folder_md_expected
    msgs = MessageCatcher(validate_ds_to_schema(dataset))
    assert not msgs.errors()

    msgs = MessageCatcher(validate_ds_to_metadata_type(dataset, metadata_type))
    assert not msgs.errors()

    msgs = MessageCatcher(validate_ds_to_product(dataset, eo3_product))
    assert not msgs.errors()


def test_missing_field(example_metadata: Dict):
    """when a required field (id) is missing, validation should fail"""
    del example_metadata["id"]
    msgs = MessageCatcher(validate_ds_to_schema(example_metadata))
    assert "'id' is a required property" in msgs.error_text()

    with pytest.raises(InvalidDatasetError, match="structure"):
        DatasetMetadata(example_metadata)


def test_invalid_eo3_schema(example_metadata: Dict):
    """When there's no eo3 $schema defined"""
    del example_metadata["$schema"]
    msgs = MessageCatcher(validate_ds_to_schema(example_metadata))
    assert "$schema" in msgs.error_text()

    example_metadata["$schema"] = "https://schemas.onepdapatube.org/dataset"
    msgs = MessageCatcher(validate_ds_to_schema(example_metadata))
    assert "($schema)" in msgs.error_text()


def test_dataset_maturity(example_metadata: Dict):
    """Dataset maturity is an optional but recommended field; schema validation
    should warn if it is absent and error if it is incorrect"""
    example_metadata["properties"]["dea:dataset_maturity"] = "blah"
    msgs = MessageCatcher(validate_ds_to_schema(example_metadata))
    assert msgs.errors()
    assert "dataset_maturity" in msgs.error_text()

    example_metadata["properties"]["dea:dataset_maturity"] = "INTERIM"
    msgs = MessageCatcher(validate_ds_to_schema(example_metadata))
    assert msgs.errors()
    assert "dataset_maturity" in msgs.error_text()

    del example_metadata["properties"]["dea:dataset_maturity"]
    msgs = MessageCatcher(validate_ds_to_schema(example_metadata))
    assert not msgs.errors()
    assert "recommended_field" in msgs.warning_text()


def test_grid_custom_crs(example_metadata: Dict):
    """Allow a grid to have its own crs, and error if crs is invalid"""
    example_metadata["grids"]["other_crs"] = {
        "crs": "epsg:32756",
        "shape": [2267, 1567],
        "transform": [50.0, 0.0, 257975.0, 0.0, -50.0, 6290325.0],
    }
    ds = DatasetMetadata(example_metadata)
    grid = ds.grids.get("other_crs")
    assert grid.crs == "epsg:32756"
    assert ds.crs.epsg != 32756

    example_metadata["grids"]["default"] = {
        "crs": "splunge:32756",
        "shape": [2267, 1567],
        "transform": [50.0, 0.0, 257975.0, 0.0, -50.0, 6290325.0],
    }
    with pytest.raises(InvalidDatasetError, match="invalid_crs"):
        DatasetMetadata(example_metadata)


def test_missing_grid_def(example_metadata: Dict):
    """A Measurement refers to a grid that doesn't exist"""
    a_measurement, *_ = list(example_metadata["measurements"])
    example_metadata["measurements"][a_measurement]["grid"] = "unknown_grid"
    with pytest.raises(InvalidDatasetError, match="invalid_grid_ref"):
        DatasetMetadata(example_metadata)


def test_absolute_path_in_measurement(example_metadata: Dict):
    """Warn if a measurement path is absolute"""
    a_measurement, *_ = list(example_metadata["measurements"])
    example_metadata["measurements"][a_measurement][
        "path"
    ] = "file:///this/is/an/utter/absolute/path.nc"
    with pytest.warns(UserWarning, match="absolute_path"):
        DatasetMetadata(example_metadata)


def test_path_with_part_in_measurement(example_metadata: Dict):
    """
    Measurement paths should not include parts; warn if they are present and error if they are invalid
    """
    a_measurement, *_ = list(example_metadata["measurements"])
    example_metadata["measurements"][a_measurement]["path"] += "#part=0"
    with pytest.warns(UserWarning, match="uri_part"):
        DatasetMetadata(example_metadata)

    example_metadata["measurements"][a_measurement]["path"] += "#part=nir"
    with pytest.raises(InvalidDatasetError, match="uri_invalid_part"):
        DatasetMetadata(example_metadata)

    example_metadata["measurements"][a_measurement]["path"] += "#part=-22"
    with pytest.raises(InvalidDatasetError, match="uri_invalid_part"):
        DatasetMetadata(example_metadata)


def test_product_name_mismatch(l1_ls8_folder_md_expected: Dict, eo3_product):
    """Dataset product name doesn't match product name of given product"""
    eo3_product["name"] = "wrong_product_name"
    msgs = MessageCatcher(
        validate_ds_to_product(l1_ls8_folder_md_expected, eo3_product)
    )
    assert "product_mismatch" in msgs.error_text()


def test_measurements_match_product(l1_ls8_folder_md_expected: Dict, eo3_product):
    """Validate that the dataset measurements match the product"""
    measurements = l1_ls8_folder_md_expected["measurements"]
    # add extra measurement not defined in product
    measurements = toolz.assoc(
        measurements, "new_measurement", {"path": "measurement_path"}
    )
    # remove measurement expected by product
    measurements = toolz.dissoc(measurements, "blue")
    l1_ls8_folder_md_expected["measurements"] = measurements

    msgs = MessageCatcher(
        validate_ds_to_product(l1_ls8_folder_md_expected, eo3_product)
    )
    assert "missing_measurement" in msgs.error_text()
    assert "extra_measurements" in msgs.warning_text()
    assert "new_measurement" in msgs.warning_text()


def test_product_metadata_mismatch(
    l1_ls8_folder_md_expected: Dict,
    eo3_product,
):
    """
    Complains when a dataset doesn't contain all metadata properties given by the product
    """
    # A metadata field that's not in the dataset.
    eo3_product["metadata"]["properties"]["favourite_sandwich"] = "spam"

    msgs = MessageCatcher(
        validate_ds_to_product(
            l1_ls8_folder_md_expected, product_definition=eo3_product
        )
    )
    assert "metadata_mismatch" in msgs.error_text()


def test_has_offset():
    """_has_offset helper function for checking missing offsets"""
    doc = dict(spam="spam", bacon="eggs", atmosphere=dict(interruptions="vikings"))
    from eo3.validate import _has_offset

    assert _has_offset(doc, ["spam"])
    assert _has_offset(doc, ["atmosphere", "interruptions"])
    assert not _has_offset(doc, ["eggs"])


def test_get_field_offsets(metadata_type: Dict):
    """
    Test the get_field_offsets function, should return all field offsets defined by the metadata type
    """
    assert list(validate._get_field_offsets(metadata_type)) == [
        ("id", [["id"]]),
        ("sources", [["lineage", "source_datasets"]]),
        ("grid_spatial", [["grid_spatial", "projection"]]),
        ("measurements", [["measurements"]]),
        ("creation_dt", [["properties", "odc:processing_datetime"]]),
        ("label", [["label"]]),
        ("format", [["properties", "odc:file_format"]]),
        (
            "time",
            [
                ["properties", "dtr:start_datetime"],
                ["properties", "datetime"],
                ["properties", "dtr:end_datetime"],
                ["properties", "datetime"],
            ],
        ),
        (
            "lat",
            [
                ["extent", "lat", "begin"],
                ["extent", "lat", "end"],
            ],
        ),
        (
            "lon",
            [
                ["extent", "lon", "begin"],
                ["extent", "lon", "end"],
            ],
        ),
    ]


def test_validate_ds_to_metadata_type(
    metadata_type,
    l1_ls8_folder_md_expected: Dict,
):
    """
    Validator should allow a document that doesn't include all the metadata type fields,
    but should warn about these missing fields
    """
    metadata_type["dataset"]["search_fields"]["foobar"] = {
        "description": "A required property that is missing",
        "type": "string",
        "offset": ["properties", "eo3:foobar"],
    }
    msgs = MessageCatcher(
        validate_ds_to_metadata_type(
            l1_ls8_folder_md_expected,
            metadata_type_definition=metadata_type,
        )
    )
    assert not msgs.error_text()
    warns = msgs.warning_text()
    assert "missing_field" in warns
    assert "foobar" in warns


def test_supports_measurementless_products(
    l1_ls8_folder_md_expected: Dict,
    eo3_product,
):
    """
    Validator should support products without any measurements in the document.

    These are valid for products which can't be dc.load()'ed but are
    referred to for provenance, such as DEA's telemetry data or DEA's collection-2
    Level 1 products.
    """
    eo3_product["measurements"] = []
    msgs = MessageCatcher(
        validate_ds_to_product(l1_ls8_folder_md_expected, eo3_product)
    )
    assert not msgs.errors()


def test_product_no_href(
    l1_ls8_folder_md_expected: Dict,
):
    """
    Validator should support products without any measurements in the document.

    These are valid for products which can't be dc.load()'ed but are
    referred to for provenance, such as DEA's telemetry data or DEA's collection-2
    Level 1 products.
    """
    del l1_ls8_folder_md_expected["product"]["href"]
    with pytest.warns(UserWarning, match="product->href"):
        DatasetMetadata(l1_ls8_folder_md_expected)
