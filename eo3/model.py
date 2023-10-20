# mypy: disable-error-code="has-type"

import warnings
from pathlib import Path
from typing import Any, Optional

import attr
import toolz
from odc.geo import CRS, Geometry
from odc.geo.geom import polygon
from pyproj.exceptions import CRSError
from ruamel.yaml.timestamp import TimeStamp as RuamelTimeStamp
from shapely.geometry.base import BaseGeometry

from eo3 import validate
from eo3.eo3_core import EO3Grid, prep_eo3
from eo3.fields import Range, all_field_offsets, get_search_fields, get_system_fields
from eo3.metadata.validate import validate_metadata_type
from eo3.product.validate import validate_product
from eo3.utils import default_utc, parse_time, read_file
from eo3.validation_msg import ContextualMessager, ValidationMessages

DEA_URI_PREFIX = "https://collections.dea.ga.gov.au"
DEFAULT_METADATA_TYPE = read_file(
    Path(__file__).parent / "metadata" / "default-eo3-type.yaml"
)


def datetime_type(value):
    # Ruamel's TimeZone class can become invalid from the .replace(utc) call.
    # (I think it no longer matches the internal ._yaml fields.)
    # Convert to a regular datetime.
    if isinstance(value, RuamelTimeStamp):
        value = value.isoformat()
    else:
        value = parse_time(value)

    # Store all dates with a timezone.
    # yaml standard says all dates default to UTC.
    # (and ruamel normalises timezones to UTC itself)
    return default_utc(value)


BASE_NORMALISERS = {
    "datetime": datetime_type,
    "dtr:end_datetime": datetime_type,
    "dtr:start_datetime": datetime_type,
    "odc:processing_datetime": datetime_type,
}


@attr.s(auto_attribs=True, slots=True)
class ProductDoc:
    """
    The product that this dataset belongs to.

    "name" is the local name in ODC.

    href is intended as a more global unique "identifier" uri for the product.
    """

    name: Optional[str] = None
    href: Optional[str] = None


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
    type: Optional[str] = None
    name: str = attr.ib(metadata=dict(doc_exclude=True), default=None)


class DatasetMetadata:
    """
    A representation of an EO3 dataset document that allows for easy metadata access and validation.

    :param raw_dict: The document describing the dataset as a dictionary. Can also provide a path to the dictionary
    file via the `from_path` class method.

    :param mdt_definition: The metadata type definition dictionary. Dataset fields are accessed based on the offsets
    defined in the metadata type definition. If no metadata type definition is provided, it will default to the simple
    eo3 metadata type with no custom fields. It can be updated later using the `metadata_type` property

    :param normalisers: A mapping of property normalisation functions, for any type or semantic normalisation that isn't
    enforced by the dataset schema. By default it only normalisesdatetime strings to datetime.datetime objects
    with a utc timezone if no timezone is specified

    :param legacy_lineage: False if dataset uses external lineage

    DatasetMetadata also allows access to the raw document, the raw properties dictionary, and dataset properties
    not defined within the metadata type, such as locations, geometry, grids, measurements, accessories

    Validation against the schema and the metadata type definition are conducted by default, as is geometry validation
    via the call to `prep_eo3`, which adds/modifies metadata sections required for an eo3 dataset.
    """

    def __init__(
        self,
        raw_dict: dict[str, Any],
        mdt_definition: dict[str, Any] = DEFAULT_METADATA_TYPE,
        product_definition: Optional[dict[str, Any]] = None,
        normalisers: dict[str, Any] = BASE_NORMALISERS,
        legacy_lineage: bool = True,
    ) -> None:
        try:
            self.__dict__["_doc"] = prep_eo3(raw_dict, remap_lineage=legacy_lineage)
        except CRSError:
            raise validate.InvalidDatasetError(
                f"invalid_crs: CRS {raw_dict.get('crs')} is not a valid CRS"
            )
        except ValueError as e:
            if "lineage" in str(e):
                raise validate.InvalidDatasetError(f"invalid_lineage: {e}")
            raise validate.InvalidDatasetError(f"incomplete_geometry: {e}")

        self.__dict__["_normalisers"] = normalisers
        for key, val in self._doc["properties"].items():
            self._doc["properties"][key] = self.normalise(key, val)

        self.__dict__["_mdt_definition"] = mdt_definition
        self.__dict__["_product_definition"] = product_definition

        # The user-configurable search fields for this dataset type.
        self.__dict__["_search_fields"] = {
            name: field for name, field in get_search_fields(mdt_definition).items()
        }
        # The field offsets that the datacube itself understands: id, format, sources etc.
        # (See the metadata-type-schema.yaml or the comments in default-metadata-types.yaml)
        self.__dict__["_system_offsets"] = {
            name: field for name, field in get_system_fields(mdt_definition).items()
        }

        self.__dict__["_all_offsets"] = all_field_offsets(mdt_definition)

        self.__dict__["_msg"] = ContextualMessager(
            {
                "type": mdt_definition.get("name"),
            }
        )

        validate.handle_ds_validation_messages(self.validate_base())

    def __getattr__(self, name: str) -> Any:
        if name in self.fields.keys():
            return self.fields[name]
        else:
            raise AttributeError(
                "Unknown field {!r}. Expected one of {!r}".format(
                    name, list(self.fields.keys())
                )
            )

    def __setattr__(self, name: str, val: Any) -> None:
        offset = self._all_offsets.get(name)
        if offset is None:
            # check for a @property.setter first
            if hasattr(self, name):
                super().__setattr__(name, val)
                return
            raise AttributeError(
                "Unknown field offset {!r}. Expected one of {!r}".format(
                    name, list(self._all_offsets.keys())
                )
            )

        def _set_range_offset(name, val, offset, doc):
            """Helper function for updating a field that expects a range"""
            is_range = isinstance(val, Range)
            # time can be a range or a single datetime
            if name == "time":
                if is_range:
                    doc = toolz.assoc_in(
                        doc,
                        ["properties", "dtr:start_datetime"],
                        self.normalise("dtr:start_datetime", val.begin),
                    )
                    doc = toolz.assoc_in(
                        doc,
                        ["properties", "dtr:end_datetime"],
                        self.normalise("dtr:end_datetime", val.end),
                    )
                else:
                    doc = toolz.assoc_in(
                        doc, ["properties", "datetime"], self.normalise("datetime", val)
                    )
            # for all other range fields, value must be range
            else:
                if not is_range:
                    raise TypeError(f"The {name} field expects a Range value")
                # this assumes that offsets are in min, max order
                # and that there aren't multiple possible offsets for each
                doc = toolz.assoc_in(
                    doc, offset[0], self.normalise(offset[0], val.begin)
                )
                doc = toolz.assoc_in(doc, offset[1], self.normalise(offset[0], val.end))
            return doc

        # handle if there are multiple offsets
        if len(offset) > 1:
            self._doc = _set_range_offset(name, val, offset, self._doc)
        # otherwise it's a simple field
        else:
            self._doc = toolz.assoc_in(
                self._doc, *offset, self.normalise(offset[0], val)
            )

    def __dir__(self):
        return list(self.fields)

    @property
    def doc(self) -> dict[str, Any]:
        return self._doc

    @property
    def search_fields(self) -> dict[str, Any]:
        return {
            name: field.extract(self.doc) for name, field in self._search_fields.items()
        }

    @property
    def system_fields(self) -> dict[str, Any]:
        return {
            name: field.extract(self.doc)
            for name, field in self._system_offsets.items()
        }

    @property
    def fields(self) -> dict[str, Any]:
        return dict(**self.system_fields, **self.search_fields)

    @property
    def properties(self) -> dict[str, Any]:
        return self.doc.get("properties", {})

    @property
    def metadata_type(self) -> dict[str, Any]:
        return self._mdt_definition

    @metadata_type.setter
    def metadata_type(self, val: dict[str, Any]) -> None:
        validate.handle_validation_messages(validate_metadata_type(val))
        validate.handle_ds_validation_messages(self.validate_to_mdtype(val))
        self._mdt_definition = val
        self._search_fields = {
            name: field for name, field in get_search_fields(val).items()
        }
        self._system_offsets = {
            name: field for name, field in get_system_fields(val).items()
        }
        self._all_offsets = all_field_offsets(val)
        self._msg.context["type"] = val.get("name")

    @property
    def product_definition(self) -> dict[str, Any]:
        return self._product_definition

    @product_definition.setter
    def product_definition(self, val: dict[str, Any]) -> None:
        if val is None:
            self._product_definition = val
            return
        validate.handle_validation_messages(validate_product(val))
        try:
            # don't update product definition if it there are errors validating against the dataset
            validate.handle_ds_validation_messages(self.validate_to_product(val))
            self._product_definition = val
        except validate.InvalidDatasetError as e:
            warnings.warn(
                "Cannot update product definition as it is incompatible with the dataset"  # nosec B608
                f" and would cause the following issue(s): {e}"  # nosec B608
            )

    # Additional metadata not included in the metadata type
    @property
    def locations(self) -> Optional[list[str]]:
        if self.doc.get("location") is not None:
            warnings.warn(
                "`location` is deprecated and will be removed in a future release. Use `locations` instead."
            )
            return [self.doc.get("location")]  # type: ignore[list-item]
        return self.doc.get("locations")

    @property
    def product(self) -> ProductDoc:
        return ProductDoc(**self.doc.get("product", {}))

    @property
    def geometry(self) -> BaseGeometry:
        from shapely.geometry import shape

        return shape(self.doc.get("geometry"))

    @property
    def grids(self) -> dict[str, EO3Grid]:
        return {key: EO3Grid(doc) for key, doc in self.doc.get("grids", {}).items()}

    @property
    def measurements(self) -> dict[str, MeasurementDoc]:
        return {
            key: MeasurementDoc(**doc)
            for key, doc in self.doc.get("measurements", {}).items()
        }

    @property
    def accessories(self) -> dict[str, AccessoryDoc]:
        return {
            key: AccessoryDoc(**doc)
            for key, doc in self.doc.get("accessories", {}).items()
        }

    @property
    def crs(self) -> CRS:
        # get doc crs as an actual CRS
        return CRS(self._doc.get("crs"))

    # Core TODO: copied from datacube.model.Dataset
    @property
    def extent(self) -> Optional[Geometry]:
        def xytuple(obj):
            return obj["x"], obj["y"]

        projection = self.grid_spatial
        valid_data = projection.get("valid_data")
        geo_ref_points = projection.get("geo_ref_points")
        if valid_data:
            return Geometry(valid_data, crs=self.crs)
        elif geo_ref_points:
            return polygon(
                [
                    xytuple(geo_ref_points[key])
                    for key in ("ll", "ul", "ur", "lr", "ll")
                ],
                crs=self.crs,
            )

        return None

    # Validation and other methods
    def without_lineage(self) -> dict[str, Any]:
        return toolz.assoc(self._doc, "lineage", {})

    def normalise(self, key: str | list[str], val: Any) -> Any:
        """If property name is present in the normalisation mapping, apply the
        normalisation function"""
        # for easy dealing with offsets, such as when used in __setattr__
        if key[0] == "properties":
            key = key[1]
        normalise = self._normalisers.get(key, None)
        if normalise:
            return normalise(val)
        return val

    def validate_to_product(
        self, product_definition: dict[str, Any]
    ) -> ValidationMessages:
        # Core TODO: replaces datacube.index.hl.check_dataset_consistent and check_consistent
        self._msg.context["product"] = product_definition.get("name")
        yield from validate.validate_ds_to_product(
            self._doc, product_definition, self._msg
        )

    def validate_to_schema(self) -> ValidationMessages:
        # don't error if properties 'extent' or 'grid_spatial' are present
        doc = toolz.dissoc(self._doc, "extent", "grid_spatial")
        yield from validate.validate_ds_to_schema(doc, self._msg)

    def validate_to_mdtype(self, mdt_definition: dict[str, Any]) -> ValidationMessages:
        yield from validate.validate_ds_to_metadata_type(
            self._doc, mdt_definition, self._msg
        )

    def validate_measurements(self) -> ValidationMessages:
        """Check that measurement paths and grid references are valid"""
        for name, measurement in self.measurements.items():
            grid_name = measurement.grid
            if grid_name != "default" or self.grids:
                if grid_name not in self.grids:
                    yield self._msg.error(
                        "invalid_grid_ref",
                        f"Measurement {name!r} refers to unknown grid {grid_name!r}",
                    )
            yield from validate.validate_measurement_path(
                name, measurement.path, self._msg
            )

    def validate_base(self) -> ValidationMessages:
        """Basic validations that can be done with information present at initialisation"""
        yield from self.validate_to_schema()
        yield from self.validate_to_mdtype(self._mdt_definition)
        # measurements are not mandatory
        if self.measurements:
            yield from self.validate_measurements()
        if self._product_definition:
            yield from self.validate_to_product(self._product_definition)

    @classmethod
    def from_path(
        cls,
        ds_path: Path,
        md_type_path: Optional[Path] = None,
        product_path: Optional[Path] = None,
    ) -> "DatasetMetadata":
        # Create DatasetMetadata from filepath
        if md_type_path is None:
            md_type_path = Path(__file__).parent / "metadata" / "default-eo3-type.yaml"
        if product_path is None:
            return cls(read_file(ds_path), read_file(md_type_path))
        return cls(
            read_file(ds_path),
            read_file(md_type_path),
            product_definition=read_file(product_path),
        )
