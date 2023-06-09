from pathlib import Path
from textwrap import dedent
from typing import Dict, Union
from uuid import uuid4

import numpy as np
import rasterio
from rasterio.io import DatasetWriter

from eo3 import validate
from eo3.validate import (
    DocKind,
    ValidationExpectations,
    filename_doc_kind,
    guess_kind_from_contents,
    validate_dataset,
)
from eo3.validation_msg import ValidationMessage

from tests.common import MessageCatcher

Doc = Union[Dict, Path]


def test_val_msg_str():
    msg = ValidationMessage.info(
        "test_msg", "Spam, spam, spam, sausages and spam", hint="I don't like spam!"
    )
    msg_str = str(msg)
    assert "test_msg" in msg_str
    assert "sausages and spam" in msg_str
    assert "I don't like spam!" in msg_str


def test_dockind_legacy():
    assert not DocKind.dataset.is_legacy
    assert DocKind.legacy_dataset.is_legacy
    assert DocKind.ingestion_config.is_legacy


def test_valid_document_works(example_metadata: Dict):
    """All of our example metadata files should validate"""
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert not msgs.errors()


def test_bad_crs(example_metadata: Dict):
    example_metadata["crs"] = 4326
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "epsg codes should be prefixed" in msgs.error_text()


def test_missing_field(example_metadata: Dict):
    """when a required field (id) is missing, validation should fail"""
    del example_metadata["id"]
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "'id' is a required property" in msgs.error_text()


def test_invalid_eo3_schema(example_metadata: Dict):
    """When there's no eo3 $schema defined"""
    del example_metadata["$schema"]
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "no_schema:" in msgs.error_text()
    example_metadata["$schema"] = "https://schemas.onepdapatube.org/dataset"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "unknown_doc_type" in msgs.error_text()


def test_allow_optional_geo(example_metadata: Dict):
    """A doc can omit all geo fields and be valid if not requiring geometry."""
    del example_metadata["crs"]
    del example_metadata["geometry"]

    for m in example_metadata["measurements"].values():
        if "grid" in m:
            del m["grid"]

    example_metadata["grids"] = {}
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert msgs.errors()
    expect = ValidationExpectations(require_geometry=False)
    msgs = MessageCatcher(validate_dataset(example_metadata, expect=expect))
    assert "No geo information in dataset" in msgs.all_text()
    assert not msgs.errors()


def test_missing_geo_fields(example_metadata: Dict):
    """If you have one gis field, you should have all of them"""
    del example_metadata["crs"]
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "incomplete_crs" in msgs.error_text()
    expect = ValidationExpectations(require_geometry=False)
    msgs = MessageCatcher(validate_dataset(example_metadata, expect=expect))
    assert "incomplete_crs" in msgs.error_text()


def test_grid_custom_crs(example_metadata: Dict):
    """A Measurement refers to a grid that doesn't exist"""
    example_metadata["grids"]["other_crs"] = {
        "crs": "epsg:32756",
        "shape": [2267, 1567],
        "transform": [50.0, 0.0, 257975.0, 0.0, -50.0, 6290325.0],
    }
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert not msgs.error_text()
    assert not msgs.warning_text()


def test_grid_custom_bad_crs(example_metadata: Dict):
    """A Measurement refers to a grid that doesn't exist"""
    example_metadata["grids"]["other_crs"] = {
        "crs": "splunge:32756",
        "shape": [2267, 1567],
        "transform": [50.0, 0.0, 257975.0, 0.0, -50.0, 6290325.0],
    }
    msgs = MessageCatcher(validate_dataset(example_metadata))
    errs = msgs.error_text()
    assert "invalid_crs" in errs
    assert "other_crs" in errs


def test_missing_grid_def(example_metadata: Dict):
    """A Measurement refers to a grid that doesn't exist"""
    a_measurement, *_ = list(example_metadata["measurements"])
    example_metadata["measurements"][a_measurement]["grid"] = "unknown_grid"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "invalid_grid_ref" in msgs.error_text()


def test_absolute_path_in_measurement(example_metadata: Dict):
    """A Measurement refers to a grid that doesn't exist"""
    a_measurement, *_ = list(example_metadata["measurements"])
    example_metadata["measurements"][a_measurement][
        "path"
    ] = "file:///this/is/an/utter/absolute/path.nc"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    warns = msgs.warning_text()
    assert "absolute_path" in warns
    assert a_measurement in warns


def test_path_with_part_in_measurement(example_metadata: Dict):
    """A Measurement refers to a grid that doesn't exist"""
    a_measurement, *_ = list(example_metadata["measurements"])
    example_metadata["measurements"][a_measurement]["path"] += "#part=0"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "uri_part" in msgs.warning_text()

    example_metadata["measurements"][a_measurement]["path"] += "#part=nir"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "uri_part" in msgs.warning_text()
    errs = msgs.error_text()
    assert "uri_invalid_part" in errs
    assert "nir" in errs

    example_metadata["measurements"][a_measurement]["path"] += "#part=-22"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "uri_part" in msgs.warning_text()
    errs = msgs.error_text()
    assert "uri_invalid_part" in errs
    assert "-22" in errs


def test_absolute_path_in_accessory(example_metadata: Dict):
    an_accessory, *_ = list(example_metadata["accessories"])
    example_metadata["accessories"][an_accessory][
        "path"
    ] = "file:///this/is/an/utter/absolute/path.nc"
    msgs = MessageCatcher(validate_dataset(example_metadata))
    warns = msgs.warning_text()
    assert "absolute_path" in warns
    assert an_accessory in warns


def test_invalid_shape(example_metadata: Dict):
    """the geometry must be a valid shape"""

    # Points are in an invalid order.
    example_metadata["geometry"] = {
        "coordinates": (
            (
                (770_115.0, -2_768_985.0),
                (525_285.0, -2_981_715.0),
                (770_115.0, -2_981_715.0),
                (525_285.0, -2_768_985.0),
                (770_115.0, -2_768_985.0),
            ),
        ),
        "type": "Polygon",
    }
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert "invalid_geometry" in msgs.error_text()


def test_crs_as_wkt(example_metadata: Dict):
    """A CRS should be in epsg form if an EPSG exists, not WKT"""
    example_metadata["crs"] = dedent(
        """PROJCS["WGS 84 / UTM zone 55N",
    GEOGCS["WGS 84",
        DATUM["WGS_1984",
            SPHEROID["WGS 84",6378137,298.257223563,
                AUTHORITY["EPSG","7030"]],
            AUTHORITY["EPSG","6326"]],
        PRIMEM["Greenwich",0,
            AUTHORITY["EPSG","8901"]],
        UNIT["degree",0.01745329251994328,
            AUTHORITY["EPSG","9122"]],
        AUTHORITY["EPSG","4326"]],
    UNIT["metre",1,
        AUTHORITY["EPSG","9001"]],
    PROJECTION["Transverse_Mercator"],
    PARAMETER["latitude_of_origin",0],
    PARAMETER["central_meridian",147],
    PARAMETER["scale_factor",0.9996],
    PARAMETER["false_easting",500000],
    PARAMETER["false_northing",0],
    AUTHORITY["EPSG","32655"],
    AXIS["Easting",EAST],
    AXIS["Northing",NORTH]]
    """
    )
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert not msgs.errors()
    assert "non_epsg" in msgs.warning_text()
    assert "change CRS to 'epsg:32655'" in msgs.warning_text()


def test_flat_lineage(example_metadata: Dict):
    example_metadata["lineage"] = {
        "spam": [str(uuid4())],
        "bacon": [str(uuid4())],
        "eggs": [str(uuid4())],
    }
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert not msgs.error_text()
    assert not msgs.warning_text()
    assert "nonflat_lineage" not in msgs.info_text()


def test_nonflat_lineage(example_metadata: Dict):
    example_metadata["lineage"] = {
        "spam": [str(uuid4()), str(uuid4()), str(uuid4())],
    }
    msgs = MessageCatcher(validate_dataset(example_metadata))
    assert not msgs.error_text()
    assert not msgs.warning_text()
    assert "nonflat_lineage" in msgs.info_text()


def test_non_uuids_in_lineage(example_metadata: Dict):
    example_metadata["lineage"] = {
        "spam": [str(uuid4())],
        "eggs": [str(uuid4()), "scrambled"],
        "beans": [str(uuid4()), str(uuid4()), str(uuid4())],
    }
    msgs = MessageCatcher(validate_dataset(example_metadata))
    errs = msgs.error_text()
    assert "invalid_source_id" in errs
    assert "scrambled" in errs
    assert "eggs" in errs


def test_valid_with_product_doc(l1_ls8_folder_md_expected: Dict, product: Dict) -> Path:
    """When a product is specified, it will validate that the measurements match the product"""
    product["name"] = l1_ls8_folder_md_expected["product"]["name"]
    # Document is valid on its own.
    msgs = MessageCatcher(validate_dataset(l1_ls8_folder_md_expected))
    assert not msgs.errors()
    # It contains all measurements in the product, so will be valid when not thorough.
    msgs = MessageCatcher(
        validate_dataset(l1_ls8_folder_md_expected, product_definition=product)
    )
    assert not msgs.errors()

    # Remove some expected measurements from product - should get warnings now
    product["default_allowances"]["allow_extra_measurements"] = [
        "cirrus",
        "coastal_aerosol",
        "red",
        "green",
        "blue",
        "nir",
        "swir_1",
        "swir_2",
        "panchromatic",
    ]
    msgs = MessageCatcher(
        validate_dataset(l1_ls8_folder_md_expected, product_definition=product)
    )
    assert "extra_measurements" in msgs.warning_text()
    assert "quality" in msgs.warning_text()
    assert "lwir_1" in msgs.warning_text()
    assert not msgs.errors()

    expect = ValidationExpectations(
        allow_extra_measurements=[
            "lwir_1",
            "lwir_2",
            "quality",
        ]
    )
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected, product_definition=product, expect=expect
        )
    )
    assert not msgs.errors()


# @pytest.mark.skip("This check is outside the current callpath.")
def test_complains_about_product_not_matching(
    l1_ls8_folder_md_expected: Dict,
    eo3_product,
):
    """
    Complains when we're given products but they don't match the dataset
    """

    # A metadata field that's not in the dataset.
    eo3_product["metadata"]["properties"]["favourite_sandwich"] = "spam"

    msgs = MessageCatcher(
        validate_dataset(l1_ls8_folder_md_expected, product_definition=eo3_product)
    )
    assert "metadata_mismatch" in msgs.error_text()


def test_complains_when_no_product(
    l1_ls8_folder_md_expected: Dict,
):
    """When a product is specified, it will validate that the measurements match the product"""
    # Thorough checking should fail when there's no product provided
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected, thorough=True, product_definition=None
        )
    )
    assert "no_product" in msgs.error_text()


def test_is_product():
    """Product documents should be correctly identified as products"""
    product = dict(
        name="minimal_product", metadata_type="eo3", measurements=[dict(name="blue")]
    )
    assert guess_kind_from_contents(product) == DocKind.product


def test_is_ingestion():
    """Product documents should be correctly identified as products"""
    product = dict(
        name="minimal_product", metadata_type="eo3", measurements=[dict(name="blue")]
    )
    assert guess_kind_from_contents(product) == DocKind.product


def test_is_metadata_type():
    """Product documents should be correctly identified as products"""
    mdt = dict(name="minimal_mdt", dataset=dict(search_fields=dict()))
    assert guess_kind_from_contents(mdt) == DocKind.metadata_type


def test_is_legacy_dataset():
    """Product documents should be correctly identified as products"""
    ds = dict(id="spam", lineage=["sources"], platform="boots")
    assert guess_kind_from_contents(ds) == DocKind.legacy_dataset


def test_is_legacy_ingestion_cfg():
    """Product documents should be correctly identified as products"""
    ds = dict(metadata_type="foo", source_type="bar")
    assert guess_kind_from_contents(ds) == DocKind.ingestion_config


def test_is_stac():
    """Product documents should be correctly identified as products"""
    ds = dict(id="spam", properties=dict(datetime="today, right now"))
    assert guess_kind_from_contents(ds) == DocKind.stac_item


def test_not_a_dockind():
    """Product documents should be correctly identified as products"""
    product = dict(spam="spam", bacon="eggs", interruptions="vikings")
    assert guess_kind_from_contents(product) is None


def test_has_offset():
    doc = dict(spam="spam", bacon="eggs", atmosphere=dict(interruptions="vikings"))
    from eo3.validate import _has_offset

    assert _has_offset(doc, ["spam"])
    assert _has_offset(doc, ["atmosphere", "interruptions"])
    assert not _has_offset(doc, ["eggs"])


def test_dataset_is_not_a_product(example_metadata: Dict):
    """
    Datasets should not be identified as products

    (checks all example metadata files)
    """
    assert guess_kind_from_contents(example_metadata) == DocKind.dataset
    assert filename_doc_kind(Path("asdf.odc-metadata.yaml")) == DocKind.dataset


def test_get_field_offsets(metadata_type: Dict):
    """
    Test the get_field_offsets function.
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
    ]


def test_validate_ds_with_metadata_doc(
    l1_ls8_metadata_path: str,
    metadata_type,
    l1_ls8_folder_md_expected: Dict,
):
    # When thorough, the dtype and nodata are wrong
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            metadata_type_definition=metadata_type,
            readable_location=l1_ls8_metadata_path,
        )
    )
    assert not msgs.error_text()
    assert not msgs.warning_text()


def test_validate_ds_with_metadata_doc_warnings(
    l1_ls8_metadata_path: str,
    metadata_type,
    l1_ls8_folder_md_expected: Dict,
):
    metadata_type["dataset"]["search_fields"]["foobar"] = {
        "description": "A required property that is missing",
        "type": "string",
        "offset": ["properties", "eo3:foobar"],
    }
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            metadata_type_definition=metadata_type,
            readable_location=l1_ls8_metadata_path,
        )
    )
    assert not msgs.error_text()
    warns = msgs.warning_text()
    assert "missing_field" in warns
    assert "foobar" in warns
    l1_ls8_folder_md_expected["properties"]["eo3:foobar"] = None
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            metadata_type_definition=metadata_type,
            readable_location=l1_ls8_metadata_path,
        )
    )
    assert not msgs.error_text()
    assert not msgs.warning_text()
    infos = msgs.info_text()
    assert "null_field" in infos
    assert "foobar" in infos


def test_validate_location_deprec(
    l1_ls8_folder_md_expected: Dict,
):
    l1_ls8_folder_md_expected["location"] = "file:///path/to"
    # When thorough, the dtype and nodata are wrong
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
        )
    )
    assert "dataset_location" in msgs.warning_text()


def test_dtype_compare_with_product_doc(
    l1_ls8_metadata_path: str,
    eo3_product,
    l1_ls8_folder_md_expected: Dict,
):
    """'thorough' validation should check the dtype of measurements against the product"""

    eo3_product["measurements"] = [
        dict(name="blue", dtype="uint8", units="1", nodata=255)
    ]

    # When thorough, the dtype and nodata are wrong
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            product_definition=eo3_product,
            readable_location=l1_ls8_metadata_path,
            thorough=True,
        )
    )
    err_text = msgs.error_text()
    assert "different_dtype" in err_text
    assert "blue" in err_text
    assert "uint8" in err_text


def test_nodata_compare_with_product_doc(
    l1_ls8_metadata_path: str,
    eo3_product,
    l1_ls8_folder_md_expected: Dict,
):
    """'thorough' validation should check the nodata of measurements against the product"""

    # Remake the tiff with a 'nodata' set.
    blue_tif = (
        l1_ls8_metadata_path.parent
        / l1_ls8_folder_md_expected["measurements"]["blue"]["path"]
    )
    _create_dummy_tif(
        blue_tif,
        dtype="uint16",
        nodata=65535,
    )
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            product_definition=eo3_product,
            readable_location=l1_ls8_metadata_path,
            thorough=True,
        )
    )
    assert not msgs.errors()
    assert not msgs.warnings()
    assert not msgs.infos()

    # Override blue definition with invalid nodata value.
    _measurement(eo3_product, "blue")["nodata"] = 255
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            product_definition=eo3_product,
            readable_location=l1_ls8_metadata_path,
            thorough=True,
        )
    )
    assert "different_nodata" in msgs.error_text()


def test_measurements_compare_with_nans(
    l1_ls8_metadata_path: str,
    eo3_product,
    l1_ls8_folder_md_expected: Dict,
):
    """When dataset and product have NaN nodata values, it should handle them correctly"""
    product = eo3_product
    blue_tif = (
        l1_ls8_metadata_path.parent
        / l1_ls8_folder_md_expected["measurements"]["blue"]["path"]
    )

    # When both are NaN, it should be valid
    blue = _measurement(product, "blue")
    blue["nodata"] = float("NaN")
    blue["dtype"] = "float32"
    _create_dummy_tif(blue_tif, nodata=float("NaN"))

    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            product_definition=eo3_product,
            readable_location=l1_ls8_metadata_path,
            thorough=True,
        )
    )
    assert not msgs.errors()
    assert not msgs.warnings()
    assert not msgs.infos()

    # ODC can also represent NaNs as strings due to json's lack of NaN
    blue["nodata"] = "NaN"
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            product_definition=eo3_product,
            readable_location=l1_ls8_metadata_path,
            thorough=True,
        )
    )
    assert not msgs.errors()
    assert not msgs.warnings()
    assert not msgs.infos()

    # When product is set, dataset is NaN, they no longer match.
    blue["nodata"] = 0
    msgs = MessageCatcher(
        validate_dataset(
            l1_ls8_folder_md_expected,
            product_definition=eo3_product,
            readable_location=l1_ls8_metadata_path,
            thorough=True,
        )
    )
    errtxt = msgs.error_text()
    assert "different_nodata" in errtxt
    assert "blue" in errtxt
    assert "dataset nan" in errtxt
    assert "product 0" in errtxt


def test_missing_measurement_from_product(
    l1_ls8_folder_md_expected: Dict,
    eo3_product,
):
    """Validator should notice a missing measurement from the product def"""
    product = eo3_product
    product["name"] = "test_with_extra_measurement"
    product["measurements"] = [
        dict(name="razzmatazz", dtype="int32", units="1", nodata=-999)
    ]
    msgs = MessageCatcher(
        validate_dataset(l1_ls8_folder_md_expected, product_definition=eo3_product)
    )
    errtxt = msgs.error_text()
    assert "missing_measurement" in errtxt
    assert "razzmatazz" in errtxt


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
        validate_dataset(l1_ls8_folder_md_expected, product_definition=eo3_product)
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
    msgs = MessageCatcher(validate_dataset(l1_ls8_folder_md_expected))
    assert not msgs.errors()
    assert "product_href" in msgs.info_text()


def _measurement(product: Dict, name: str):
    """Get a measurement by name"""
    for m in product["measurements"]:
        if m["name"] == name:
            return m
    raise ValueError(f"Measurement {name} not found?")


def _create_dummy_tif(blue_tif, nodata=None, dtype="float32", **opts):
    with rasterio.open(
        blue_tif,
        "w",
        width=10,
        height=10,
        count=1,
        dtype=dtype,
        driver="GTiff",
        nodata=nodata,
        **opts,
    ) as ds:
        ds: DatasetWriter
        ds.write(np.ones((10, 10), dtype=dtype), 1)
