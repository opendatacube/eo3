"""
Module
"""
import pytest
from affine import Affine
from odc.geo.geom import CRS, polygon
from ruamel.yaml import YAML

from eo3.eo3_core import (
    EO3Grid,
    add_eo3_parts,
    eo3_grid_spatial,
    is_doc_eo3,
    is_doc_geo,
    prep_eo3,
)

SAMPLE_DOC = """---
$schema: https://schemas.opendatacube.org/dataset
id: 7d41a4d0-2ab3-4da1-a010-ef48662ae8ef
crs: "EPSG:3857"
product:
    name: sample_product
properties:
    datetime: 2020-05-25 23:35:47.745731Z
    odc:processing_datetime: 2020-05-25 23:35:47.745731Z
grids:
    default:
       shape: [100, 200]
       transform: [10, 0, 100000, 0, -10, 200000, 0, 0, 1]
lineage:
  src_a: ['7cf53cb3-5da7-483f-9f12-6056e3290b4e']
  src_b:
    - 'f5b9f582-d5ff-43c0-a49b-ef175abe429c'
    - '7f8c6e8e-6f6b-4513-a11c-efe466405509'
  src_empty: []
...
"""

# Crosses lon=180 line in Pacific, taken from one the Landsat scenes
# https://landsat-pds.s3.amazonaws.com/c1/L8/074/071/LC08_L1TP_074071_20190622_20190704_01_T1/index.html
#
SAMPLE_DOC_180 = """---
$schema: https://schemas.opendatacube.org/dataset
id: f884df9b-4458-47fd-a9d2-1a52a2db8a1a
crs: "EPSG:32660"
product:
    name: sample_product
properties:
    datetime: 2020-05-25 23:35:47.745731Z
    odc:processing_datetime: 2020-05-25 23:35:47.745731Z
grids:
    default:
       shape: [7811, 7691]
       transform: [30, 0, 618285, 0, -30, -1642485, 0, 0, 1]
    pan:
       shape: [15621, 15381]
       transform: [15, 0, 618292.5, 0, -15, -1642492.5, 0, 0, 1]
lineage: {}
...
"""


@pytest.fixture
def basic_grid():
    return EO3Grid(dict(shape=(100, 100), transform=Affine(0, 100, 50, 100, 0, 50)))


@pytest.fixture
def sample_doc():
    return YAML(typ="safe").load(SAMPLE_DOC)


@pytest.fixture
def sample_doc_180():
    return YAML(typ="safe").load(SAMPLE_DOC_180)


def test_grid_ref_points(basic_grid):
    ref_pts = basic_grid.ref_points()
    assert ref_pts["ul"] == {"x": 50, "y": 50}
    assert ref_pts["lr"] == {"x": 10050, "y": 10050}
    assert ref_pts["ur"] == {"x": 50, "y": 10050}
    assert ref_pts["ll"] == {"x": 10050, "y": 50}


def test_polygon(basic_grid):
    poly = basic_grid.polygon()
    assert poly == polygon(
        [
            (50, 50),
            (50, 10050),
            (10050, 10050),
            (10050, 50),
            (50, 50),
        ],
        crs=None,
    )


def test_grid_crs(basic_grid):
    crs = CRS("EPSG:4326")
    poly = basic_grid.polygon(crs)
    assert poly == polygon(
        [
            (50, 50),
            (50, 10050),
            (10050, 10050),
            (10050, 50),
            (50, 50),
        ],
        crs=crs,
    )
    basic_grid.crs = crs
    poly = basic_grid.polygon()
    assert poly == polygon(
        [
            (50, 50),
            (50, 10050),
            (10050, 10050),
            (10050, 50),
            (50, 50),
        ],
        crs=crs,
    )


def test_grid_points():
    identity = list(Affine.translation(0, 0))
    grid = EO3Grid({"shape": (11, 22), "transform": identity})

    pts = grid.points()
    assert len(pts) == 4
    assert pts == [(0, 0), (22, 0), (22, 11), (0, 11)]
    pts_ = grid.points(ring=True)
    assert len(pts_) == 5
    assert pts == pts_[:4]
    assert pts_[0] == pts_[-1]

    grid = EO3Grid({"shape": (11, 22), "transform": tuple(Affine.translation(100, 0))})
    pts = grid.points()
    assert pts == [(100, 0), (122, 0), (122, 11), (100, 11)]

    for bad in [{}, dict(shape=(1, 1)), dict(transform=identity)]:
        with pytest.raises(ValueError):
            grid = EO3Grid(bad)


def test_bad_grids():
    identity = list(Affine.translation(0, 0))
    bad_grids = [
        # No Shape
        {
            "transform": identity,
        },
        # Non 2-d Shape (NB: geospatial dimensions only.  Other dimensions are handled elsewhere.)
        {
            "shape": (1024,),
            "transform": identity,
        },
        {
            "shape": (1024, 564, 256),
            "transform": identity,
        },
        # No Transform
        {
            "shape": (1024, 256),
        },
        # Formally invalid affine transform (must be 6 or 9 elements)
        {
            "shape": (1024, 256),
            "transform": [343.3],
        },
        {
            "shape": (1024, 256),
            "transform": [343, 23345, 234, 9, -65.3],
        },
        {
            "shape": (1024, 256),
            "transform": [343, 23345, 234, 9, -65.3, 1, 0],
        },
        {
            "shape": (1024, 256),
            "transform": [
                343,
                23345,
                234,
                9,
                -65.3,
                1,
                0,
                7435.24563,
                0.0001234,
                888.888,
                3,
                3,
                2,
            ],
        },
        # Formally invalid affine transform (all elements must be numbers)
        {"shape": (1024, 256), "transform": [343, 23345, 234, 9, -65.3, "six"]},
        # Formally invalid affine transform (in 9 element form, last 3 numbers must be 0,0,1)
        {
            "shape": (1024, 256),
            "transform": [343, 23345, 234, 9, -65.3, 1, 3, 3, 2],
        },
    ]
    for bad_grid in bad_grids:
        with pytest.raises(ValueError):
            EO3Grid(bad_grid)


def test_eo3_grid_spatial_nogrids():
    with pytest.raises(ValueError, match="grids.foo"):
        eo3_grid_spatial(
            {
                "crs": "EPSG:4326",
                "grids": {
                    "default": {
                        "shape": (1024, 256),
                        "transform": [343, 23345, 234, 9, -65.3, 1],
                    }
                },
            },
            grid_name="foo",
        )


def test_is_eo3(sample_doc, sample_doc_180):
    assert is_doc_eo3(sample_doc) is True
    assert is_doc_eo3(sample_doc_180) is True

    # If there's no schema field at all, it's treated as legacy eo.
    assert is_doc_eo3({}) is False
    assert is_doc_eo3({"crs": "EPSG:4326"}) is False
    assert is_doc_eo3({"crs": "EPSG:4326", "grids": {}}) is False

    with pytest.raises(ValueError, match="Unsupported dataset schema.*"):
        is_doc_eo3({"$schema": "https://schemas.opendatacube.org/eo4"})


def test_is_geo(sample_doc, sample_doc_180):
    assert is_doc_geo(sample_doc) is True
    assert is_doc_geo(sample_doc_180) is True

    assert is_doc_geo({}) is False
    assert is_doc_geo({"crs": "EPSG:4326"}) is False
    assert is_doc_geo({"crs": "EPSG:4326", "extent": "dummy_extent"}) is True


def test_add_gs_info(sample_doc, sample_doc_180):
    doc = dict(**sample_doc)
    doc.pop("crs")
    with pytest.raises(ValueError):
        add_eo3_parts(doc)

    doc = dict(**sample_doc)
    doc.pop("grids")
    with pytest.raises(ValueError):
        add_eo3_parts(doc)

    doc = add_eo3_parts(sample_doc)
    assert doc is not sample_doc
    assert doc.get("crs") == "EPSG:3857"
    assert doc.get("extent") is not None
    assert doc.get("grid_spatial") is not None
    assert doc["extent"]["lat"]["begin"] < doc["extent"]["lat"]["end"]
    assert doc["extent"]["lon"]["begin"] < doc["extent"]["lon"]["end"]

    assert doc == add_eo3_parts(doc)

    doc = add_eo3_parts(sample_doc_180)
    assert doc is not sample_doc_180
    assert doc["extent"]["lon"]["begin"] < 180 < doc["extent"]["lon"]["end"]


def test_prep_eo3(sample_doc, sample_doc_180):
    doc = prep_eo3(sample_doc)

    assert "src_a" in doc["lineage"]["source_datasets"]
    assert "src_b1" in doc["lineage"]["source_datasets"]
    assert "src_b2" in doc["lineage"]["source_datasets"]
    assert "src_empty" not in doc["lineage"]["source_datasets"]

    doc = prep_eo3(sample_doc_180)
    assert doc["lineage"]["source_datasets"] == {}

    assert prep_eo3(None) is None
    with pytest.raises(ValueError):
        prep_eo3({})
