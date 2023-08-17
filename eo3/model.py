from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union, Mapping
import warnings

import affine
import attr
from odc.geo import CoordList, Geometry, SomeCRS
from odc.geo.geom import polygon

from eo3 import validate
from eo3.validation_msg import (
    ContextualMessager,
    ValidationMessages,
)
from eo3.eo3_core import prep_eo3
from eo3.fields import get_search_fields, get_system_fields, Range
from eo3.utils import read_documents

import toolz

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

    def points(self, ring: bool = False) -> CoordList:
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


class DatasetMetadata(object):
    def __init__(self, raw_dict, mdt_definition: Mapping = None, normalisation_mapping = None, legacy_lineage = False):
        self.__dict__['_doc'] = prep_eo3(raw_dict, remap_lineage=legacy_lineage)

        if mdt_definition is None:
            # placeholder path
            mdt_definition = read_documents(Path(__file__).parent / "metadata" / "default-eo3-type.yaml")
        self.__dict__['_mdt_definition'] = mdt_definition

        # The user-configurable search fields for this dataset type.
        self.__dict__['_search_fields'] = {name: field
                                           for name, field in get_search_fields(mdt_definition).items()}
        # The field offsets that the datacube itself understands: id, format, sources etc.
        # (See the metadata-type-schema.yaml or the comments in default-metadata-types.yaml)
        self.__dict__['_system_offsets'] = {name: field
                                            for name, field in get_system_fields(mdt_definition).items()}
        
        self.__dict__['_normalisation_mapping'] = normalisation_mapping

        self.__dict__['_msg'] = ContextualMessager({"product": self._doc.get("product").get("name"),
                                                    "type": mdt_definition.get("name")})
        
        self.validate_base()

    def __getattr__(self, name):
        if name in self.fields.keys():
            return self.fields[name]
        else:
            raise AttributeError(
                'Unknown field %r. Expected one of %r' % (
                    name, list(self.fields.keys())
                )
            )
    
    def __setattr__(self, name, val):
        offset = self.all_offsets.get(name)
        if offset is None:
            raise AttributeError(
                'Unknown field offset %r. Expected one of %r' % (
                    name, list(self.all_offsets.keys())
                )
            )
        if self._normalisation_mapping:
            val = self.normalise(name, val)
        # handle if there are multiple offsets
        if isinstance(offset[0], list):
            is_range = isinstance(val, Range)
            # time can be a range or a single datetime
            if name == 'time':
                if is_range:
                    self._doc = toolz.assoc_in(self._doc, ["properties", "dtr:start_datetime"], val.begin)
                    self._doc = toolz.assoc_in(self._doc, ["properties", "dtr:end_datetime"], val.end)
                else:
                    self._doc = toolz.assoc_in(self._doc, ["properties", "datetime"], val)
            # for all other range fields, value must be range
            else:
                if not is_range:
                    raise TypeError('Field must be a range')
                # this assumes that offsets are in min, max order
                # and that there aren't multiple possible offsets for each
                self._doc = toolz.assoc_in(self._doc, offset[0], val.begin)
                self._doc = toolz.assoc_in(self._doc, offset[1], val.end)
        # otherwise it's a simple field
        else:
            self._doc = toolz.assoc_in(self._doc, offset, val)

    def __dir__(self):
        return list(self.fields)
    
    @property
    def doc(self):
        return self._doc

    @property
    def all_offsets(self):
        # all offset paths as defined by the metadata type
        all_fields = dict(**self._search_fields, **self._system_offsets)
        return {name: field.offset for name, field in all_fields.items()}

    @property
    def search_fields(self):
        return {name: field.extract(self.doc)
                for name, field in self._search_fields.items()}

    @property
    def system_fields(self):
        return {name: field.extract(self.doc)
                for name, field in self._system_offsets.items()}

    @property
    def fields(self):
        return dict(**self.system_fields, **self.search_fields)
    
    @property
    def locations(self):
        if self.doc.get("location"):
            warnings.warn("`location` is deprecated and will be removed in a future release. Use `locations` instead.")
            return [self.doc.get("location")]
        return self.doc.get("locations", None)

    @property
    def properties(self):
        return self.doc.get("properties")

    @property
    def product(self):
        return ProductDoc(**self.doc.get("product"))

    @property
    def geometry(self):
        from shapely.geometry import shape
        return shape(self.doc.get("geometry"))
    
    @property
    def grids(self):
        return {key: GridDoc(**doc) for key, doc in self.doc.get("grids")}

    @property
    def measurements(self):
        return {key: MeasurementDoc(**doc) for key, doc in self.doc.get("measurements")}
    
    @property
    def accessories(self):
        return {key: AccessoryDoc(**doc) for key, doc in self.doc.get("accessories")}

    def without_lineage(self):
        return toolz.assoc(self.doc, 'lineage', {})

    def normalise(self, key, value):
        if key not in self._normalisation_mapping:
            warnings.warn(f"Unknown Stac property {key!r}.")
        normaliser = self._normalisation_mapping.get(key)
        if normaliser and value is not None:
                return normaliser(value)
        
    def validate_to_product(self, product_definition: Mapping):
        self._msg.context["product"] = product_definition.get("name")
        yield from validate.validate_ds_to_product(self.doc, product_definition, self._msg)

    def validate_to_schema(self) -> ValidationMessages:
        # don't error if properties 'extent' or 'grid_spatial' are present
        doc = toolz.dissoc(self.doc, "extent", "grid_spatial")
        yield from validate.validate_ds_to_schema(doc, self._msg)

    def validate_to_mdtype(self) -> ValidationMessages:
        yield from validate.validate_ds_to_metadata_type(self.doc, self._mdt_definition, self._msg)

    def validate_base(self):
        if self._normalisation_mapping:
            for key, value in self.doc:
                self.normalise(key, value)
        validate.handle_validation_messages(self.validate_to_schema())
        validate.handle_validation_messages(self.validate_to_mdtype())
