from datetime import datetime
from textwrap import dedent
from typing import Dict

import pytest
import toolz

from eo3.fields import Range
from eo3.model import DatasetMetadata
from eo3.utils import InvalidDocException, default_utc
from eo3.validate import InvalidDatasetError


def test_get_and_set(l1_ls8_folder_md_expected: Dict, metadata_type):
    """Test that we are able to access and set fields correctly"""
    ds = DatasetMetadata(
        raw_dict=l1_ls8_folder_md_expected, mdt_definition=metadata_type
    )
    # get
    with pytest.raises(AttributeError, match="Unknown field 'foobar'"):
        ds.foobar
    assert ds.id == "a780754e-a884-58a7-9ac0-df518a67f59d"
    assert ds.format == "GeoTIFF"
    # set
    with pytest.raises(AttributeError, match="Unknown field offset"):
        ds.foo = "bar"
    ds.format = "GeoTIFFF"
    assert ds.format == "GeoTIFFF"
    # set range
    with pytest.raises(TypeError, match="expects a Range value"):
        ds.lat = 0.0
    # time can be a range or a single value
    dt = datetime(2020, 1, 1, 23, 59, 59)
    ds.time = dt
    assert ds.time == Range(default_utc(dt), default_utc(dt))
    dt_end = datetime(2020, 1, 2, 23, 59, 59)
    ds.time = Range(dt, dt_end)
    assert ds.time == Range(default_utc(dt), default_utc(dt_end))


def test_update_metadata_type(l1_ls8_folder_md_expected: Dict, metadata_type):
    """
    Test that updating the metadata type definition gives us access to custom fields
    included in the new definition
    """
    ds = DatasetMetadata(
        raw_dict=l1_ls8_folder_md_expected, mdt_definition=metadata_type
    )
    with pytest.raises(AttributeError):
        ds.instrument
    new_metadata_type = toolz.assoc_in(
        metadata_type,
        ["dataset", "search_fields", "instrument"],
        {
            "offset": ["properties", "eo:instrument"],
            "description": "Instrument name",
        },
    )
    ds.metadata_type = new_metadata_type
    assert ds.instrument == "OLI_TIRS"

    # we shouldn't be able to update the md type definition if it's invalid
    bad_metadata_type = toolz.assoc_in(
        metadata_type,
        ["dataset", "creation_dt"],
        ["properties", "invalid_offset"],
    )
    with pytest.raises(InvalidDocException):
        ds.metadata_type = bad_metadata_type


def test_additional_metadata_access(l1_ls8_folder_md_expected: Dict, metadata_type):
    """Check that we are able to access metadata not defined in the metadata type"""
    ds = DatasetMetadata(
        raw_dict=l1_ls8_folder_md_expected, mdt_definition=metadata_type
    )
    assert ds.crs.epsg == 32655
    assert ds.product.name == "usgs_ls8c_level1_1"
    assert "coastal_aerosol" in ds.measurements
    assert "metadata:landsat_mtl" in ds.accessories
    assert ds.locations is None


def test_bad_crs(example_metadata: Dict):
    """CRS should be valid, and is preferred in epsg form if possible"""
    # Invalid crs
    example_metadata["crs"] = "123456"
    with pytest.raises(InvalidDatasetError, match="invalid_crs"):
        DatasetMetadata(example_metadata)
    # Missing crs
    del example_metadata["crs"]
    with pytest.raises(InvalidDatasetError, match="incomplete_geometry"):
        DatasetMetadata(example_metadata)

    # A CRS should be in epsg form if an EPSG exists, not WKT
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
    with pytest.warns(UserWarning, match="change CRS to 'epsg:32655'"):
        DatasetMetadata(example_metadata)


def test_extent(l1_ls8_folder_md_expected: Dict):
    # Core TODO: copied from tests.test_eo3
    """Check that extent is properly calculated"""
    ds = DatasetMetadata(l1_ls8_folder_md_expected)
    assert ds.extent is not None
    assert ds.extent.crs.epsg == 32655

    del l1_ls8_folder_md_expected["geometry"]
    doc = dict(**l1_ls8_folder_md_expected, geometry=ds.extent.buffer(-1).json)

    ds2 = DatasetMetadata(doc)
    assert ds.extent.contains(ds2.extent)


def test_warn_location_deprecated(
    l1_ls8_folder_md_expected: Dict,
):
    """Warn if dataset includes deprecated 'location' field"""
    l1_ls8_folder_md_expected["location"] = "file:///path/to"
    ds = DatasetMetadata(l1_ls8_folder_md_expected)
    with pytest.warns(UserWarning, match="`location` is deprecated"):
        assert ds.locations == ["file:///path/to"]


def test_embedded_lineage(l1_ls8_folder_md_expected: Dict):
    """Error if dataset contains embedded lineage,
    and that it's not lumped under 'incomplete_geometry'"""
    l1_ls8_folder_md_expected["lineage"] = {
        "source_datasets": {"ds": {"id": "abcd", "label": "00000"}}
    }
    with pytest.raises(InvalidDatasetError, match="invalid_lineage"):
        DatasetMetadata(l1_ls8_folder_md_expected)
