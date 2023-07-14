from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union
from uuid import UUID

import affine
import attr
from odc.geo import CoordList, SomeCRS, Geometry
from odc.geo.geom import polygon
from ruamel.yaml.comments import CommentedMap
from shapely.geometry.base import BaseGeometry

from eo3.properties import Eo3DictBase, Eo3InterfaceBase

DEA_URI_PREFIX = "https://collections.dea.ga.gov.au"
ODC_DATASET_SCHEMA_URL = "https://schemas.opendatacube.org/dataset"

# Either a local filesystem path or a string URI.
# (the URI can use any scheme supported by rasterio, such as tar:// or https:// or ...)
Location = Union[Path, str]


@attr.s(auto_attribs=True, slots=True)
class ProductDoc:
    """
    The product that this dataset belongs to.

    "name" is the local name in ODC.

    href is intended as a more global unique "identifier" uri for the product.
    """

    name: str = None
    href: str = None


@attr.s(auto_attribs=True, slots=True, hash=True)
class GridDoc:
    """The grid describing a measurement/band's pixels"""

    shape: Tuple[int, int]
    transform: affine.Affine
    crs: Optional[str] = None

    def points(self, ring: bool=False) -> CoordList:
        ny, nx = (float(dim) for dim in self.shape)
        pts = [(0.0, 0.0), (nx, 0.0), (nx, ny), (0.0, ny)]
        if ring:
            pts += pts[:1]
        return [self.transform * pt for pt in pts]

    def ref_points(self) -> Dict[str, Dict[str, float]]:
        nn = ["ul", "ur", "lr", "ll"]
        return {n: dict(x=x, y=y) for n, (x, y) in zip(nn, self.points())}

    def polygon(self, crs: Optional[SomeCRS] = None) -> Geometry:
        if not crs:
            crs = self.crs
        return polygon(self.points(ring=True), crs=crs)



@attr.s(auto_attribs=True, slots=True)
class MeasurementDoc:
    """
    A Dataset's reference to a measurement file.
    """

    path: str
    band: Optional[int] = 1
    layer: Optional[str] = None
    grid: str = "default"

    name: str = attr.ib(metadata=dict(doc_exclude=True), default=None)
    alias: str = attr.ib(metadata=dict(doc_exclude=True), default=None)


@attr.s(auto_attribs=True, slots=True)
class AccessoryDoc:
    """
    An accessory is an extra file included in the dataset that is not
    a measurement/band.

    For example: thumbnails, alternative metadata documents, or checksum files.
    """

    path: str
    type: str = None
    name: str = attr.ib(metadata=dict(doc_exclude=True), default=None)


@attr.s(auto_attribs=True, slots=True)
class Eo3DatasetDocBase(Eo3InterfaceBase):
    """
    A minimally-validated EO3 dataset document

    Includes :class:`.Eo3InterfaceBase` methods for metadata access::

        >>> p = Eo3DatasetDocBase()
        >>> p.processed = '2018-04-03'
        >>> p.properties['odc:processing_datetime']
        datetime.datetime(2018, 4, 3, 0, 0, tzinfo=datetime.timezone.utc)

    """

    #: Dataset UUID
    id: UUID = None
    #: Human-readable identifier for the dataset
    label: str = None
    #: The product name (local) and/or url (global)
    product: ProductDoc = None
    #: Location(s) where this dataset is stored.
    #:
    #: (ODC supports multiple locations when the same dataset is stored in multiple places)
    #:
    #: They are fully qualified URIs (``file://...`, ``https://...``, ``s3://...``)
    #:
    #: All other paths in the document (measurements, accessories) are relative to the
    #: chosen location.
    #:
    #: If not supplied, the directory from which the metadata was read is treated as the root for the data.
    locations: List[str] = None

    #: CRS string. Eg. ``epsg:3577``
    crs: str = None
    #: Shapely geometry of the valid data coverage
    #:
    #: (it must contain all non-empty pixels of the image)
    geometry: BaseGeometry = None
    #: Grid specifications for measurements
    grids: Dict[str, GridDoc] = None
    #: Raw properties
    properties: Eo3DictBase = attr.ib(factory=Eo3DictBase)
    #: Loadable measurements of the dataset
    measurements: Dict[str, MeasurementDoc] = None
    #: References to accessory files
    #:
    #: Such as thumbnails, checksums, other kinds of metadata files.
    #:
    #: (any files included in the dataset that are not measurements)
    accessories: Dict[str, AccessoryDoc] = attr.ib(factory=CommentedMap)
    #: Links to source dataset uuids
    lineage: Dict[str, List[UUID]] = attr.ib(factory=CommentedMap)
