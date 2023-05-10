"""
API for easily writing an ODC Dataset
"""
import shutil
import tempfile
import uuid
import warnings
from copy import deepcopy
from enum import Enum, auto
from pathlib import Path, PosixPath, PurePath
from textwrap import dedent
from typing import Any, Dict, Generator, Iterable, List, Optional, Tuple, Union
from urllib.parse import urlsplit

import numpy
import rasterio
import xarray
from rasterio import DatasetReader
from rasterio.crs import CRS
from rasterio.enums import Resampling
from ruamel.yaml.comments import CommentedMap
from shapely.geometry.base import BaseGeometry

import eo3
from eo3 import documents, images, serialise, validate
from eo3.documents import find_and_read_documents
from eo3.images import FileWrite, GridSpec, MeasurementBundler, ValidDataMethod
from eo3.model import AccessoryDoc, Eo3DatasetDocBase, Location, ProductDoc
from eo3.names import resolve_location
from eo3.properties import Eo3DictBase, Eo3InterfaceBase
from eo3.uris import is_url, uri_resolve
from eo3.validate import Level, ValidationExpectations, ValidationMessage
from eo3.verify import PackageChecksum


class AssemblyError(Exception):
    pass


class IncompleteDatasetError(Exception):
    """
    Raised when a dataset is missing essential things and so cannot be written.

    (such as mandatory metadata)
    """

    def __init__(self, validation: ValidationMessage) -> None:
        self.validation = validation


class IncompleteDatasetWarning(UserWarning):
    """A non-critical warning for invalid or incomplete metadata"""

    def __init__(self, validation: ValidationMessage) -> None:
        self.validation = validation

    def __str__(self) -> str:
        return str(self.validation)


def _validate_property_name(name: str):
    """
    >>> _validate_property_name('eo:gsd')
    >>> _validate_property_name('thumbnail:full_resolution')
    >>> _validate_property_name('full resolution')
    Traceback (most recent call last):
       ...
    ValueError: Not a valid property name 'full resolution' (must be alphanumeric with colons or underscores)
    >>> _validate_property_name('Mr Sprinkles')
    Traceback (most recent call last):
      ...
    ValueError: Not a valid property name 'Mr Sprinkles' (must be alphanumeric with colons or underscores)
    """
    if not name.replace(":", "").isidentifier():
        raise ValueError(
            f"Not a valid property name {name!r} "
            "(must be alphanumeric with colons or underscores)"
        )


def _default_metadata_path(dataset_url: str):
    """
    The default metadata path for a given dataset location url.

    By default, we put a sibling file with extension 'odc-metadata.yaml':
    >>> _default_metadata_path('file:///tmp/ls7_nbar_20120403_c1/esri-scene.stac-item.json')
    'file:///tmp/ls7_nbar_20120403_c1/esri-scene.odc-metadata.yaml'
    >>> _default_metadata_path('s3://deafrica-data/jaxa/alos_palsar_mosaic/2017/N05E040/N05E040_2017.tif')
    's3://deafrica-data/jaxa/alos_palsar_mosaic/2017/N05E040/N05E040_2017.odc-metadata.yaml'
    >>> _default_metadata_path('file:///tmp/ls7_nbar_20120403_c1/my-dataset.tar.gz')
    'file:///tmp/ls7_nbar_20120403_c1/my-dataset.odc-metadata.yaml'

    Or, if a directory, we place one inside:
    >>> _default_metadata_path('file:///tmp/ls7_nbar_20120403_c1/')
    'file:///tmp/ls7_nbar_20120403_c1/odc-metadata.yaml'

    If a tar/zip file, place it alongside.
    >>> _default_metadata_path('tar:///g/data/v10/somewhere/my-dataset.tar!/')
    'file:///g/data/v10/somewhere/my-dataset.odc-metadata.yaml'
    >>> _default_metadata_path('zip:///g/data/v10/landsat-dataset.zip!')
    'file:///g/data/v10/landsat-dataset.odc-metadata.yaml'

    Unless it's already a metadata path:
    >>> _default_metadata_path('file:///tmp/ls7_nbar_20120403_c1/odc-metadata.yaml')
    'file:///tmp/ls7_nbar_20120403_c1/odc-metadata.yaml'
    """
    # Already a metadata url?
    if dataset_url.endswith("odc-metadata.yaml"):
        return dataset_url

    # If a tar URL, convert to file before proceding.
    u = urlsplit(dataset_url)
    path = PosixPath(u.path)
    if u.scheme in ("tar", "zip"):
        dataset_url = f"file://{path.as_posix()}"

    # A directory, place a default name inside.
    if dataset_url.endswith("/"):
        return f"{dataset_url}odc-metadata.yaml"

    # Otherwise a sibling file to the dataset file.
    base_url, file_name = dataset_url.rsplit("/", maxsplit=1)
    file_stem = file_name.split(".")[0]
    return uri_resolve(dataset_url, f"{base_url}/{file_stem}.odc-metadata.yaml")


def relative_url(base: str, offset: str, allow_absolute=False):
    """
    >>> relative_url('file:///tmp/dataset/odc-metadata.yaml', 'file:///tmp/dataset/my-image.tif')
    'my-image.tif'
    >>> relative_url('file:///tmp/dataset/odc-metadata.yaml', 'file:///tmp/dataset/images/my-image.tif')
    'images/my-image.tif'
    >>> relative_url(
    ...    'https://example.test/dataset/odc-metadata.yaml',
    ...    'https://example.test/dataset/images/my-image.tif'
    ... )
    'images/my-image.tif'
    >>> # Outside the base directory
    >>> relative_url('https://example.test/dataset/odc-metadata.yaml', 'https://example.test/my-image.tif')
    Traceback (most recent call last):
    ...
    ValueError: Absolute paths are not allowed, and file 'https://example.test/my-image.tif' is outside location \
'https://example.test/dataset/odc-metadata.yaml'
    >>> # Matching paths, different hosts.
    >>> relative_url('https://example.test/odc-metadata.yaml', 'https://example2.test/my-image.tif')
    Traceback (most recent call last):
      ...
    ValueError: Absolute paths are not allowed, and file 'https://example2.test/my-image.tif' is outside location \
'https://example.test/odc-metadata.yaml'
    """
    base_parts = urlsplit(base)
    offset_parts = urlsplit(offset)
    if not allow_absolute:
        if (base_parts.hostname, base_parts.scheme) != (
            offset_parts.hostname,
            offset_parts.scheme,
        ):
            raise ValueError(
                f"Absolute paths are not allowed, and file {offset!r} is outside location {base!r}"
            )

    base_dir, _ = base_parts.path.rsplit("/", 1)
    try:
        return PosixPath(offset_parts.path).relative_to(base_dir).as_posix()
    except ValueError:
        if not allow_absolute:
            raise ValueError(
                f"Absolute paths are not allowed, and file {offset!r} is outside location {base!r}"
            )
        # We can't make it relative, return the absolute.
        return offset
