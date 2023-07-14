"""
Module
"""


from affine import Affine
import pytest
from odc.geo.geom import polygon, CRS
from eo3.model import GridDoc


@pytest.fixture
def basic_grid():
    return GridDoc(
        shape=(100, 100),
        transform=Affine(0, 100, 50, 100, 0, 50)
    )


def test_grid_ref_points(basic_grid):
    ref_pts = basic_grid.ref_points()
    assert ref_pts["ul"] == {"x": 50, "y": 50}
    assert ref_pts["lr"] == {"x": 10050, "y": 10050}
    assert ref_pts["ur"] == {"x": 50, "y": 10050}
    assert ref_pts["ll"] == {"x": 10050, "y": 50}


def test_grid_points(basic_grid):
    pts = basic_grid.points(ring=True)
    assert pts == [
        (50, 50),
        (50, 10050),
        (10050, 10050),
        (10050, 50),
        (50, 50),
    ]


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
        crs=None
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
        crs=crs
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
        crs=crs
    )

