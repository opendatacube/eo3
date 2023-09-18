"""
Module
"""

from enum import Enum

import pytest

from eo3.properties import FileFormat, degrees_type, of_enum_type, percent_type


class LowerEnum(Enum):
    spam = 1
    bacon = 2
    eggs = 3
    beans = 4


class UpperEnum(Enum):
    SPAM = 1
    BACON = 2
    EGGS = 3
    BEANS = 4


def test_of_enum_type():
    ff = of_enum_type(FileFormat)
    assert ff("GeoTIFF") == "GeoTIFF"
    assert ff(FileFormat.GeoTIFF) == "GeoTIFF"
    with pytest.raises(ValueError):
        assert ff("GeoTUFF") == "GeoTIFF"
    ff = of_enum_type(FileFormat, strict=False)
    assert ff("GeoTUFF") == "GeoTUFF"

    low = of_enum_type(LowerEnum, lower=True)
    assert low("spam") == "spam"
    assert low("BACON") == "bacon"

    upp = of_enum_type(UpperEnum, upper=True)
    assert upp("spam") == "SPAM"
    assert upp("BACON") == "BACON"


def test_percent_type():
    assert percent_type("2.22") == pytest.approx(2.22)
    with pytest.raises(ValueError):
        percent_type("-2.2")
    with pytest.raises(ValueError):
        percent_type("104.6666")


def test_degrees_type():
    assert degrees_type("355.3") == pytest.approx(355.3)
    with pytest.raises(ValueError):
        percent_type("-2.2")
    with pytest.raises(ValueError):
        percent_type("404.6666")
