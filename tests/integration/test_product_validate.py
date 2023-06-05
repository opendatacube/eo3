from pathlib import Path
from typing import Dict

from eo3.product.validate import validate_product

from tests.common import MessageCatcher


def test_odc_product(product: Dict, eo3_product):
    """
    Test valid products pass
    """
    # A missing field will fail the schema check from ODC.
    # (these cannot be added to ODC so are a hard validation failure)
    msgs = MessageCatcher(validate_product(product))
    assert not msgs.errors()
    assert not msgs.warnings()
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_odc_product_schema(product: Dict):
    """
    If a product fails against ODC's schema, it's an error.
    """
    # A missing field will fail the schema check from ODC.
    # (these cannot be added to ODC so are a hard validation failure)
    del product["metadata"]
    msgs = MessageCatcher(validate_product(product))
    assert "document_schema" in msgs.error_text()


def test_embedded_metadata_deprecation(product: Dict, metadata_type: Dict):
    product["metadata_type"] = metadata_type
    msgs = MessageCatcher(validate_product(product))
    assert not msgs.errors()
    assert "embedded_metadata_type" in msgs.warning_text()


def test_managed_deprecation(product: Dict, metadata_type: Dict):
    product["managed"] = False
    msgs = MessageCatcher(validate_product(product))
    assert not msgs.errors()
    assert not msgs.warnings()
    product["managed"] = True
    msgs = MessageCatcher(validate_product(product))
    assert not msgs.errors()
    assert "ingested_product" in msgs.warning_text()


def test_warn_bad_product_license(l1_ls8_metadata_path: Path, product: Dict):
    # Missing license is a warning.
    del product["license"]
    msgs = MessageCatcher(validate_product(product))
    assert not msgs.errors()
    assert "no_license" in msgs.warning_text()

    # Invalid license string (not SPDX format), error. Is caught by ODC schema.
    product["license"] = "Sorta Creative Commons"
    msgs = MessageCatcher(validate_product(product))
    assert "document_schema" in msgs.error_text()


def test_warn_duplicate_measurement_name(eo3_product):
    """When a product is specified, it will validate that names are not repeated between measurements and aliases."""
    product = eo3_product
    orig_measurements = product["measurements"]
    # We have the "blue" measurement twice.
    product["measurements"] = orig_measurements + [
        dict(name="blue", dtype="uint8", units="1", nodata=255)
    ]

    msgs = MessageCatcher(validate_product(product))
    assert "duplicate_measurement_name" in msgs.error_text()
    assert "blue" in msgs.error_text()

    # An *alias* clashes with the *name* of a measurement.
    product["measurements"] = orig_measurements + [
        dict(
            name="azul",
            aliases=[
                "icecream",
                # Clashes with the *name* of a measurement.
                "blue",
            ],
            units="1",
            dtype="uint8",
            nodata=255,
        ),
    ]
    msgs = MessageCatcher(validate_product(product))
    assert "duplicate_measurement_name" in msgs.error_text()
    assert "blue" in msgs.error_text()

    # An alias is duplicated on the same measurement. Not an error, just a message!
    product["measurements"] = [
        dict(
            name="blue",
            aliases=[
                "icecream",
                "blue",
            ],
            dtype="uint8",
            units="1",
            nodata=255,
        ),
    ]
    msgs = MessageCatcher(validate_product(product))
    assert not msgs.errors()
    assert "duplicate_alias_name" in msgs.info_text()
    assert "blue" in msgs.info_text()


def test_no_measurements_deprecated(eo3_product):
    """
    Complain when product measurements are a dict.

    datasets have measurements as a dict, products have them as a List, so this is a common error.
    """

    eo3_product["measurements"] = []
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert "no_measurements" in msgs.warning_text()


def test_complains_about_measurement_lists(eo3_product):
    """
    Complain when product measurements are a dict.

    datasets have measurements as a dict, products have them as a List, so this is a common error.
    """

    eo3_product["measurements"] = {"a": {}}
    msgs = MessageCatcher(validate_product(eo3_product))
    assert "measurements_list" in msgs.error_text()


def test_complains_about_impossible_nodata_vals(product: Dict):
    """Complain if a product nodata val cannot be represented in the dtype"""

    product["measurements"].append(
        dict(
            name="paradox",
            dtype="uint8",
            units="1",
            # Impossible for a uint6
            nodata=-999,
        )
    )
    msgs = MessageCatcher(validate_product(product))
    assert "unsuitable_nodata" in msgs.error_text()


def test_product_metadata_name(eo3_product):
    eo3_product["metadata"]["product"] = dict(name="spam")
    err_msgs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "product_name_mismatch" in err_msgs
    assert "spam" in err_msgs

    eo3_product["metadata"]["product"]["name"] = eo3_product["name"]
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert "product_name_metadata_deprecated" in msgs.warning_text()

    eo3_product["metadata"]["product"]["bacon"] = "eggs"
    err_msgs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "invalid_product_metadata" in err_msgs
    assert "bacon" in err_msgs


def test_invalid_metadatasection(eo3_product):
    eo3_product["metadata"]["spam"] = dict(eggs="bacon")
    msgs = MessageCatcher(validate_product(eo3_product))
    assert "invalid_metadata_key" in msgs.error_text()


def test_product_nested_metadata(eo3_product):
    eo3_product["metadata"]["properties"]["spam"] = dict(eggs="bacon")
    msgs = MessageCatcher(validate_product(eo3_product))
    assert "nested_metadata" in msgs.error_text()


def test_product_invalid_metadata_key(eo3_product):
    eo3_product["metadata"]["properties"]["spam, eggs, sausage and spam"] = "bacon"
    msgs = MessageCatcher(validate_product(eo3_product))
    assert "invalid_metadata_properties_key" in msgs.error_text()


def test_storage_and_load(eo3_product):
    eo3_product["storage"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "latitude": -0.001,
            "longitude": 0.001,
        },
    }
    eo3_product["load"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "latitude": -0.001,
            "longitude": 0.001,
        },
    }
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert "storage_and_load" in msgs.warning_text()


def test_storage_warnings(eo3_product):
    eo3_product["storage"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "latitude": -0.001,
            "longitude": 0.001,
        },
        "tile_size": {
            "latitude": 8000,
            "longitude": 8000,
        },
    }
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    warnings = msgs.warning_text()
    assert "storage_section" in warnings
    assert "storage_tilesize" in warnings


def test_load_align_dim(eo3_product):
    eo3_product["load"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "latitude": -0.001,
            "longitude": 0.001,
        },
        "align": {
            "x": 0,
            "y": 1,
        },
    }
    msg_errs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "invalid_align_dim" in msg_errs
    assert "latitude" in msg_errs
    assert "longitude" in msg_errs


def test_load_align_type(eo3_product):
    eo3_product["load"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "latitude": -0.001,
            "longitude": 0.001,
        },
        "align": {
            "longitude": "left",
            "latitude": "center",
        },
    }
    msg_errs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "invalid_align_type" in msg_errs
    assert "longitude" in msg_errs
    assert "latitude" in msg_errs


def test_load_align_val(eo3_product):
    eo3_product["load"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "latitude": -0.001,
            "longitude": 0.001,
        },
        "align": {
            "longitude": 0,
            "latitude": 1.6,
        },
    }
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    warnings = msgs.warning_text()
    assert "unexpected_align_val" in warnings
    assert "latitude" in warnings


def test_load_resolution_dim(eo3_product):
    eo3_product["load"] = {
        "crs": "EPSG:4326",
        "resolution": {
            "y": -0.001,
            "x": 0.001,
        },
        "align": {
            "longitude": 0,
            "latitude": 1,
        },
    }
    msg_errs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "invalid_resolution_dim" in msg_errs
    assert "latitude" in msg_errs
    assert "longitude" in msg_errs


def test_load_resolution_type(eo3_product):
    eo3_product["load"] = {
        "crs": "EPSG:4326",
        "resolution": {"latitude": "spam", "longitude": "eggs"},
        "align": {
            "longitude": 0,
            "latitude": 0.5,
        },
    }
    msg_errs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "invalid_resolution_type" in msg_errs
    assert "longitude" in msg_errs
    assert "latitude" in msg_errs
