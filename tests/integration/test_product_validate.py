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


def test_storage_nocrs(eo3_product):
    eo3_product["storage"] = {
        "resolution": {
            "x": 15,
            "y": -15,
        },
    }
    err_msgs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "storage_nocrs" in err_msgs


def test_load_bad_crs(eo3_product):
    eo3_product["load"] = {
        "crs": "I-CAN'T-BELIEVE-IT'S-NOT-EPSG:4326",
        "resolution": {
            "longitude": 15,
            "latitude": -15,
        },
    }
    err_msgs = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "load_invalid_crs" in err_msgs


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


def test_valid_extra_dim(eo3_extradims_product):
    msgs = MessageCatcher(validate_product(eo3_extradims_product))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_duplicate_extradim(eo3_extradims_product):
    eo3_extradims_product["extra_dimensions"].append(
        {"name": "dim0", "dtype": "uint8", "values": [0, 50, 100, 150, 200, 250]}
    )
    msg_errs = MessageCatcher(validate_product(eo3_extradims_product)).error_text()
    assert "duplicate_extra_dimension" in msg_errs


def test_extradim_bad_coords(eo3_extradims_product):
    eo3_extradims_product["extra_dimensions"][0]["values"] = [0, 100, 200, 300, 400]
    msg_errs = MessageCatcher(validate_product(eo3_extradims_product)).error_text()
    assert "unsuitable_coords" in msg_errs


def test_bad_extradim_in_measurement(eo3_extradims_product):
    eo3_extradims_product["measurements"].append(
        {
            "name": "dim1_band",
            "aliases": ["band05", "other_dim_band"],
            "dtype": "uint8",
            "nodata": 255,
            "units": "1",
            "extra_dim": "dim1",
        }
    )
    msg_errs = MessageCatcher(validate_product(eo3_extradims_product)).error_text()
    assert "unknown_extra_dimension" in msg_errs
    assert "dim1" in msg_errs


def test_valid_spectral_def_simple(eo3_product):
    eo3_product["measurements"][0]["spectral_definition"] = {
        "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
        "response": [0.01, 0.12, 0.29, 0.89, 1.0, 0.92, 0.65, 0.23, 0.12, 0.07, 0.02],
    }
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_valid_spectral_def_extra(eo3_extradims_product):
    eo3_extradims_product["measurements"][-1]["spectral_definition"] = [
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                1.00,
                0.82,
                0.69,
                0.59,
                0.33,
                0.12,
                0.05,
                0.03,
                0.01,
                0.00,
                0.00,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.91,
                1.00,
                0.89,
                0.79,
                0.55,
                0.32,
                0.25,
                0.13,
                0.02,
                0.01,
                0.00,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.51,
                0.82,
                1.00,
                0.94,
                0.77,
                0.52,
                0.45,
                0.33,
                0.22,
                0.17,
                0.02,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.21,
                0.42,
                0.69,
                1.00,
                0.91,
                0.82,
                0.55,
                0.33,
                0.12,
                0.07,
                0.02,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.01,
                0.12,
                0.29,
                0.89,
                1.0,
                0.92,
                0.65,
                0.23,
                0.12,
                0.07,
                0.02,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.01,
                0.02,
                0.19,
                0.49,
                0.83,
                1.00,
                0.75,
                0.43,
                0.22,
                0.17,
                0.09,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.02,
                0.19,
                0.49,
                0.88,
                1.00,
                0.85,
                0.63,
                0.42,
                0.27,
                0.16,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.02,
                0.19,
                0.39,
                0.65,
                1.00,
                1.00,
                0.95,
                0.52,
                0.37,
                0.22,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.02,
                0.19,
                0.39,
                0.65,
                0.92,
                1.00,
                0.95,
                0.52,
                0.37,
                0.22,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.07,
                0.19,
                0.45,
                0.62,
                0.88,
                1.00,
                0.82,
                0.67,
                0.33,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.07,
                0.19,
                0.45,
                0.62,
                0.88,
                1.00,
                1.00,
                0.77,
                0.43,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.00,
                0.09,
                0.25,
                0.32,
                0.68,
                0.88,
                0.90,
                1.00,
                0.83,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.00,
                0.00,
                0.05,
                0.12,
                0.38,
                0.68,
                0.80,
                0.95,
                1.00,
            ],
        },
    ]
    msgs = MessageCatcher(validate_product(eo3_extradims_product))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_bad_length_spectral_def_extra(eo3_extradims_product):
    eo3_extradims_product["measurements"][-1]["spectral_definition"] = [
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.21,
                0.42,
                0.69,
                1.00,
                0.91,
                0.82,
                0.55,
                0.33,
                0.12,
                0.07,
                0.02,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.01,
                0.12,
                0.29,
                0.89,
                1.0,
                0.92,
                0.65,
                0.23,
                0.12,
                0.07,
                0.02,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.01,
                0.02,
                0.19,
                0.49,
                0.83,
                1.00,
                0.75,
                0.43,
                0.22,
                0.17,
                0.09,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.02,
                0.19,
                0.49,
                0.88,
                1.00,
                0.85,
                0.63,
                0.42,
                0.27,
                0.16,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.02,
                0.19,
                0.39,
                0.65,
                1.00,
                1.00,
                0.95,
                0.52,
                0.37,
                0.22,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.02,
                0.19,
                0.39,
                0.65,
                0.92,
                1.00,
                0.95,
                0.52,
                0.37,
                0.22,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.07,
                0.19,
                0.45,
                0.62,
                0.88,
                1.00,
                0.82,
                0.67,
                0.33,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.07,
                0.19,
                0.45,
                0.62,
                0.88,
                1.00,
                1.00,
                0.77,
                0.43,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.00,
                0.09,
                0.25,
                0.32,
                0.68,
                0.88,
                0.90,
                1.00,
                0.83,
            ],
        },
        {
            "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
            "response": [
                0.00,
                0.00,
                0.00,
                0.00,
                0.05,
                0.12,
                0.38,
                0.68,
                0.80,
                0.95,
                1.00,
            ],
        },
    ]
    errors = MessageCatcher(validate_product(eo3_extradims_product)).error_text()
    assert "bad_extradim_spectra" in errors


def test_invalid_spectral_def_simple(eo3_product):
    eo3_product["measurements"][0]["spectral_definition"] = {
        "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
    }
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "invalid_spectral_definition" in errors


def test_mismatched_spectral_def_simple(eo3_product):
    eo3_product["measurements"][0]["spectral_definition"] = {
        "wavelength": [440, 480, 520, 570, 610, 650, 720, 790, 800, 850, 920],
        "response": [
            0.01,
            0.12,
            0.29,
            0.89,
            1.0,
            0.92,
            0.65,
            0.23,
            0.12,
            0.07,
            0.02,
            0.01,
            0.00,
        ],
    }
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "mismatched_spectral_definition" in errors


def test_valid_bit_flags_definition(eo3_product):
    eo3_product["measurements"].append(
        {
            "name": "qa_band",
            "aliases": ["qa", "bitmask"],
            "dtype": "uint8",
            "nodata": 0,
            "units": "none",
            "flags_definition": {
                "nodata": {
                    "bits": 0,
                    "values": {0: False, 1: True},
                    "description": "No data flag",
                },
                "spam": {
                    "bits": 2,
                    "values": {0: False, 1: True},
                    "description": "Pixel contains spam",
                },
                "sausage": {
                    "bits": 3,
                    "values": {0: False, 1: True},
                    "description": "Pixel contains sausage",
                },
                "egg": {
                    "bits": 6,
                    "values": {0: False, 1: True},
                    "description": "Pixel contains egg",
                },
                "eggless": {
                    "bits": 6,
                    "values": {0: True, 1: False},
                    "description": "Pixel does not contain egg",
                },
            },
        }
    )
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_valid_categorical_flags_definition(eo3_product):
    eo3_product["measurements"].append(
        {
            "name": "qa_band",
            "aliases": ["qa", "bitmask"],
            "dtype": "uint8",
            "nodata": 0,
            "units": "none",
            "flags_definition": {
                "a_mapping": {
                    "bits": [0, 1, 2, 3, 4, 5, 6, 7],
                    "values": {
                        0: "nodata",
                        1: "spam",
                        2: "eggs",
                        3: "sausage",
                        4: "more spam",
                        5: "bacon",
                    },
                    "description": "But I don't like spam!",
                },
            },
        }
    )
    msgs = MessageCatcher(validate_product(eo3_product))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_nonint_bits_flags_definition(eo3_product):
    eo3_product["measurements"].append(
        {
            "name": "qa_band",
            "aliases": ["qa", "bitmask"],
            "dtype": "uint8",
            "nodata": 0,
            "units": "none",
            "flags_definition": {
                "a_mapping": {
                    "bits": 2.5,
                    "values": {
                        0: "nodata",
                        1: "spam",
                        2: "eggs",
                        3: "sausage",
                        4: "more spam",
                        5: "bacon",
                    },
                    "description": "But I don't like spam!",
                },
            },
        }
    )
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "non_integer_bits" in errors

    eo3_product["measurements"][-1]["flags_definition"]["a_mapping"]["bits"] = -3
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "non_integer_bits" in errors

    eo3_product["measurements"][-1]["flags_definition"]["a_mapping"]["bits"] = [
        0,
        1,
        2,
        2.3,
    ]
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "non_integer_bits" in errors

    eo3_product["measurements"][-1]["flags_definition"]["a_mapping"]["bits"] = [
        0,
        1,
        2,
        -3,
    ]
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "non_integer_bits" in errors


def test_invalid_values_flags_definition(eo3_product):
    eo3_product["measurements"].append(
        {
            "name": "qa_band",
            "aliases": ["qa", "bitmask"],
            "dtype": "uint8",
            "nodata": 0,
            "units": "none",
            "flags_definition": {
                "a_mapping": {
                    "bits": [0, 1, 2, 2, 3, 4, 5, 6, 7],
                    "values": {
                        0: "nodata",
                        1: "spam",
                        2: "eggs",
                        3: "sausage",
                        4: "more spam",
                        5: "bacon",
                    },
                    "description": "But I don't like spam!",
                },
                "spam": {
                    "bits": 2,
                    "values": {0: False, 1: True, 5: "woah!"},
                    "description": "Pixel contains spam",
                },
            },
        }
    )

    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "bad_bit_value_repr" in errors

    del eo3_product["measurements"][-1]["flags_definition"]["spam"]["values"][5]
    eo3_product["measurements"][-1]["flags_definition"]["a_mapping"]["values"][
        -4
    ] = "cornflakes"
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "bad_bits_value_repr" in errors

    del eo3_product["measurements"][-1]["flags_definition"]["a_mapping"]["values"][-4]
    eo3_product["measurements"][-1]["flags_definition"]["a_mapping"]["values"][6] = 400
    errors = MessageCatcher(validate_product(eo3_product)).error_text()
    assert "bad_flag_value" in errors
