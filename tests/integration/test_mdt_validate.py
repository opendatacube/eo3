from typing import Dict

from eo3.metadata.validate import legacy_fields, validate_metadata_type

from tests.common import MessageCatcher


def test_legacy_fields():
    # Missing but required
    error_msgs = MessageCatcher(legacy_fields["id"].validate(None)).error_text()
    assert "missing_system_field" in error_msgs
    assert "id" in error_msgs

    # Missing but optional
    msgs = MessageCatcher(legacy_fields["sources"].validate(None))
    assert not msgs.all_text()


def test_validate_metadata_type(metadata_type: Dict):
    msgs = MessageCatcher(validate_metadata_type(metadata_type))
    assert not msgs.errors()
    assert not msgs.warnings()


def test_metadata_no_name(metadata_type: Dict):
    del metadata_type["name"]
    msgs = MessageCatcher(validate_metadata_type(metadata_type))
    assert "no_type_name" in msgs.error_text()


def test_metadata_schema(metadata_type: Dict):
    metadata_type["eggs"] = "spam"
    msgs = MessageCatcher(validate_metadata_type(metadata_type))
    assert "document_schema" in msgs.error_text()


def test_metadata_bad_system_field(metadata_type: Dict):
    metadata_type["dataset"]["id"] = ["i", "am"]
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "bad_system_field" in err_msgs
    assert "id" in err_msgs

    metadata_type["dataset"]["measurements"] = ["bands"]
    metadata_type["dataset"]["label"] = ["id", "label"]
    metadata_type["dataset"]["creation_dt"] = ["genesis_dt"]
    metadata_type["dataset"]["format"] = ["ugly_hack", "dos", "file_extension"]
    metadata_type["dataset"]["sources"] = ["sources", "lineage"]
    metadata_type["dataset"]["grid_spatial"] = ["spam", "spam", "spam", "spam", "spam"]
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "id" in err_msgs
    assert "measurements" in err_msgs
    assert "label" in err_msgs
    assert "creation_dt" in err_msgs
    assert "format" in err_msgs
    assert "sources" in err_msgs
    assert "grid_spatial" not in err_msgs


def test_metadata_eo3_sys_in_share(metadata_type: Dict):
    metadata_type["dataset"]["search_fields"]["grid_spatial"] = [
        "properties",
        "odc:spatial_grid",
    ]
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "system_field_in_search_fields" in err_msgs
    assert "grid_spatial" in err_msgs


def test_metadata_eo3_sys_in_search(metadata_type: Dict):
    metadata_type["dataset"]["search_fields"]["grid_spatial"] = {
        "description": "Spam, spam, eggs, bacon and spam",
        "type": "string",
        "offset": ["properties", "odc:spatial_grid"],
    }
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "system_field_in_search_fields" in err_msgs
    assert "grid_spatial" in err_msgs


def test_metadata_eo3_search_bad_scalar(metadata_type: Dict):
    metadata_type["dataset"]["search_fields"]["spam"] = {
        "description": "Spam, sausage, and bacon",
        "type": "string",
        "min-offset": ["properties", "odc:spatial_grid"],
    }
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "bad_scalar" in err_msgs
    assert "spam" in err_msgs


def test_metadata_eo3_search_no_minmax(metadata_type: Dict):
    metadata_type["dataset"]["search_fields"]["spam"] = {
        "description": "Spam, sausage, and bacon",
        "type": "integer-range",
        "min-offset": ["properties", "odc:spatial_grid"],
    }
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "bad_range_nomin" in err_msgs
    assert "bad_range_nomax" in err_msgs


def test_metadata_eo3_search(metadata_type: Dict):
    metadata_type["dataset"]["search_fields"]["spam"] = {
        "description": "Spam, sausage, and bacon",
        "type": "integer",
        "offset": ["eggs", "odc:sausage_bacon"],
    }
    err_msgs = MessageCatcher(validate_metadata_type(metadata_type)).error_text()
    assert "bad_offset" in err_msgs
    assert "spam" in err_msgs


def test_metadata_eo3_search_legacy_special(metadata_type: Dict):
    metadata_type["dataset"]["search_fields"]["crs_raw"] = {
        "description": "CRS of record",
        "offset": ["crs"],
    }
    msgs = MessageCatcher(validate_metadata_type(metadata_type))
    assert not msgs.errors()
