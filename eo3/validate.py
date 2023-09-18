"""
Validate ODC dataset documents
"""
import enum
from datetime import datetime
from pathlib import Path
from textwrap import indent
from typing import (
    Dict,
    Generator,
    Iterable,
    List,
    Mapping,
    MutableMapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
from urllib.parse import urlparse
from uuid import UUID

import attr
import cattr
import ciso8601
import rasterio
import toolz
from attr import Factory, define, field, frozen
from cattrs import ClassValidationError
from click import echo
from rasterio import DatasetReader
from rasterio.crs import CRS
from rasterio.errors import CRSError
from shapely.validation import explain_validity

from eo3 import model, serialise, utils
from eo3.eo3_core import prep_eo3
from eo3.metadata.validate import validate_metadata_type
from eo3.model import AccessoryDoc, Eo3DatasetDocBase
from eo3.product.validate import validate_product
from eo3.ui import get_part, is_absolute, uri_resolve
from eo3.uris import is_url
from eo3.utils import (
    EO3_SCHEMA,
    InvalidDocException,
    _is_nan,
    contains,
    default_utc,
    load_documents,
    read_documents,
)
from eo3.validation_msg import (
    ContextualMessager,
    Level,
    ValidationMessage,
    ValidationMessages,
)

DEFAULT_NULLABLE_FIELDS = ("label",)
DEFAULT_OPTIONAL_FIELDS = (
    # Older product do not have this field at all, and when not specified it is considered stable.
    "dataset_maturity",
)


class DocKind(enum.Enum):
    # EO3 datacube dataset.
    dataset = 1
    # Datacube product
    product = 2
    # Datacube Metadata Type
    metadata_type = 3
    # Stac Item
    stac_item = 4
    # Legacy datacube ("eo1") dataset
    legacy_dataset = 5
    # Legacy product config for ingester
    ingestion_config = 6

    @property
    def is_legacy(self):
        return self in (self.legacy_dataset, self.ingestion_config)


# What kind of document each suffix represents.
# (full suffix will also have a doc type: .yaml, .json, .yaml.gz etc)
# Example:  "my-test-dataset.odc-metadata.yaml"
SUFFIX_KINDS = {
    ".odc-metadata": DocKind.dataset,
    ".odc-product": DocKind.product,
    ".odc-type": DocKind.metadata_type,
}
# Inverse of above
DOC_TYPE_SUFFIXES = {v: k for k, v in SUFFIX_KINDS.items()}


def filename_doc_kind(path: Union[str, Path]) -> Optional["DocKind"]:
    """
    Get the expected file type for the given filename.

    Returns None if it does not follow any naming conventions.

    >>> filename_doc_kind('LC8_2014.odc-metadata.yaml').name
    'dataset'
    >>> filename_doc_kind('/tmp/something/water_bodies.odc-metadata.yaml.gz').name
    'dataset'
    >>> filename_doc_kind(Path('/tmp/something/ls8_fc.odc-product.yaml')).name
    'product'
    >>> filename_doc_kind(Path('/tmp/something/ls8_wo.odc-product.json.gz')).name
    'product'
    >>> filename_doc_kind(Path('/tmp/something/eo3_gqa.odc-type.yaml')).name
    'metadata_type'
    >>> filename_doc_kind(Path('/tmp/something/some_other_file.yaml'))
    """

    for suffix in reversed(Path(path).suffixes):
        suffix = suffix.lower()
        if suffix in SUFFIX_KINDS:
            return SUFFIX_KINDS[suffix]

    return None


def guess_kind_from_contents(doc: Dict):
    """
    What sort of document do the contents look like?
    """
    if "$schema" in doc and doc["$schema"] == EO3_SCHEMA:
        return DocKind.dataset
    if "metadata_type" in doc:
        if "source_type" in doc:
            return DocKind.ingestion_config
        return DocKind.product
    if ("dataset" in doc) and ("search_fields" in doc["dataset"]):
        return DocKind.metadata_type
    if "id" in doc:
        if ("lineage" in doc) and ("platform" in doc):
            return DocKind.legacy_dataset

        if ("properties" in doc) and ("datetime" in doc["properties"]):
            return DocKind.stac_item

    return None


@frozen(init=True)
class ValidationExpectations:
    """
    What expectations do we have when validating this dataset?
    """

    #: Allow these extra measurement names to be included in the dataset.
    #: (ODC allows unlisted measurement names, but it's usually a mistake)
    allow_extra_measurements: Sequence[str] = ()

    #: Do we expect full geometry information in every dataset?
    #: (It's optional in ODC, but often a mistake to miss it)
    require_geometry: bool = True

    #: Are any of the configured fields nullable?
    allow_nullable_fields: Sequence[str] = field(
        default=Factory(lambda: DEFAULT_NULLABLE_FIELDS)
    )
    #: Can any of the fields be completely omitted from the document?
    allow_missing_fields: Sequence[str] = field(
        default=Factory(lambda: DEFAULT_OPTIONAL_FIELDS)
    )

    def with_document_overrides(self, doc: Dict):
        """
        Return an instance with any overrides from the given document.

        (TODO: Overrides are passed in in "default_allowances" section of product or metadata
        document but are not part of the schema, so using them renders the document
        invalid. Bad API design, IMO.)
        """
        if "default_allowances" not in doc:
            return self

        overridden_values = {**attr.asdict(self), **doc["default_allowances"]}
        # Merge, don't replace, these lists.
        overridden_values["allow_nullable_fields"] = list(
            {*overridden_values["allow_nullable_fields"], *self.allow_nullable_fields}
        )
        overridden_values["allow_missing_fields"] = list(
            {*overridden_values["allow_missing_fields"], *self.allow_missing_fields}
        )
        overridden_values["allow_extra_measurements"] = list(
            {
                *overridden_values["allow_extra_measurements"],
                *self.allow_extra_measurements,
            }
        )
        return cattr.structure(overridden_values, self.__class__)


def validate_dataset(
    doc: Dict,
    product_definition: Optional[Dict] = None,
    product_definitions: Optional[Dict] = None,
    metadata_type_definition: Optional[Mapping[str, Dict]] = None,
    thorough: bool = False,
    readable_location: Union[str, Path] = None,
    expect: ValidationExpectations = None,
) -> ValidationMessages:
    """
    Validate a dataset document, optionally against the given product.

    By default this will only look at the metadata, run with thorough=True to
    open the data files too.

    :param product_definition: Optionally check that the dataset matches this product definition.
    :param thorough: Open the imagery too, to check that data types etc match.
    :param readable_location: Dataset location to use, if not the metadata path.
    :param expect: Where can we be lenient in validation?
    """
    # Prepare validation context and contextual message builder
    expect = expect or ValidationExpectations()
    validation_context = {}
    if metadata_type_definition is not None:
        expect = expect.with_document_overrides(metadata_type_definition)
        validation_context["type"] = metadata_type_definition["name"]
    if product_definition is not None:
        expect = expect.with_document_overrides(product_definition)
        validation_context["product"] = product_definition["name"]
    elif product_definitions is not None:
        product_name = doc.get("product", {}).get("name")
        if product_name and product_name in product_definitions:
            product_definition = product_definitions[product_name]
            expect = expect.with_document_overrides(product_definition)
            validation_context["product"] = product_name

    msg = ContextualMessager(validation_context)

    if expect.allow_extra_measurements:
        yield msg.warning("extra_measurements", "Extra measurements are deprecated")

    if thorough and not product_definition:
        yield msg.error(
            "no_product", "Must supply product definition for thorough validation"
        )

    # Validate against schema and deserialise to a (base eo3) dataset doc
    yield from _validate_ds_to_schema(doc, msg)
    if msg.errors:
        return

    # Validate Lineage before serialisation for clearer error reporting. (Get incomprehensible error messages
    #   for invalid UUIDs)
    yield from _validate_lineage(doc.get("lineage", {}), msg)
    if msg.errors:
        return

    # TODO: How to make this step more extensible?
    try:
        dataset = serialise.from_doc(doc, skip_validation=True)
    except ClassValidationError as e:

        def expand(err: ClassValidationError) -> str:
            expanded = err.message
            try:
                for sub_err in err.exceptions:
                    expanded += expand(sub_err)
            except AttributeError:
                pass
            return expanded

        yield msg.error("serialisation_failure", f"Serialisation failed: {expand(e)}")
        return

    # non-schema basic validation
    if not dataset.product.href:
        yield msg.info("product_href", "A url (href) is recommended for products")

    if doc.get("location"):
        yield msg.warning(
            "dataset_location",
            "Location is deprecated and will be removed in a future release. Use 'locations' instead.",
        )

    # Validate geometry
    yield from _validate_geo(dataset, msg, expect_geometry=expect.require_geometry)
    if msg.errors:
        return

    # Previously a dataset could have no measurements (eg. telemetry data).
    if expect.require_geometry:
        if dataset.measurements:
            yield from _validate_measurements(dataset, msg)
            if msg.errors:
                return

    # Base properties
    # Validation is implemented in Eo3DictBase so it can be extended
    yield from dataset.properties.validate_eo3_properties(msg)

    # Accessories
    for acc_name, accessory in dataset.accessories.items():
        yield from _validate_accessory(acc_name, accessory, msg)

    required_measurements: Dict[str, ExpectedMeasurement] = {}

    # Validate dataset against product and metadata type definitions
    if product_definition is not None:
        yield from _validate_ds_to_product(
            dataset,
            required_measurements,
            product_definition,
            allow_extra_measurements=expect.allow_extra_measurements,
            msg=msg,
        )
        if msg.errors:
            return

    if metadata_type_definition:
        yield from _validate_ds_to_metadata_type(
            doc, metadata_type_definition, expect, msg
        )

    if thorough:
        # Validate contents of actual data against measurement metadata
        yield from _validate_ds_against_data(
            dataset, readable_location, required_measurements, msg
        )


def _validate_ds_to_schema(doc: Dict, msg: ContextualMessager) -> ValidationMessages:
    """
    Validate against eo3 schema
    """
    schema = doc.get("$schema")
    if schema is None:
        yield msg.error(
            "no_schema",
            f"No $schema field. "
            f"You probably want an ODC dataset schema {model.ODC_DATASET_SCHEMA_URL!r}",
        )
        return
    if schema != model.ODC_DATASET_SCHEMA_URL:
        yield msg.error(
            "unknown_doc_type",
            f"Unknown doc schema {schema!r}. Only ODC datasets are supported ({model.ODC_DATASET_SCHEMA_URL!r})",
        )
        return

    for error in serialise.DATASET_SCHEMA.iter_errors(doc):
        displayable_path = ".".join(error.absolute_path)

        hint = None
        if displayable_path == "crs" and "not of type" in error.message:
            hint = "epsg codes should be prefixed with 'epsg', e.g. 'epsg:1234'"

        context = f"({displayable_path}) " if displayable_path else ""
        yield msg.error("structure", f"{context}{error.message} ", hint=hint)


def _validate_measurements(dataset: Eo3DatasetDocBase, msg: ContextualMessager):
    for name, measurement in dataset.measurements.items():
        grid_name = measurement.grid
        if grid_name != "default" or dataset.grids:
            if grid_name not in dataset.grids:
                yield msg.error(
                    "invalid_grid_ref",
                    f"Measurement {name!r} refers to unknown grid {grid_name!r}",
                )

        if is_absolute(measurement.path):
            yield msg.warning(
                "absolute_path",
                f"measurement {name!r} has an absolute path: {measurement.path!r}",
            )

        part = get_part(measurement.path)
        if part is not None:
            yield msg.warning(
                "uri_part",
                f"measurement {name!r} has a part in the path. (Use band and/or layer instead)",
            )
        if isinstance(part, int):
            if part < 0:
                yield msg.error(
                    "uri_invalid_part",
                    f"measurement {name!r} has an invalid part (less than zero) in the path ({part})",
                )
        elif isinstance(part, str):
            yield msg.error(
                "uri_invalid_part",
                f"measurement {name!r} has an invalid part (non-integer) in the path ({part})",
            )


def _validate_accessory(name: str, accessory: AccessoryDoc, msg: ContextualMessager):
    accessory.name = name
    if is_absolute(accessory.path):
        yield msg.warning(
            "absolute_path",
            f"Accessory {accessory.name!r} has an absolute path: {accessory.path!r}",
        )


def _validate_lineage(lineage, msg):
    for label, parent_ids in lineage.items():
        if len(parent_ids) > 1:
            yield msg.info(
                "nonflat_lineage",
                f"Lineage label {label} has multiple sources and may get flattened on indexing "
                "depending on the index driver",
            )
        for parent_id in parent_ids:
            try:
                UUID(parent_id)
            except ValueError:
                yield msg.error(
                    "invalid_source_id",
                    f"Lineage id in {label} is not a valid UUID {parent_id}",
                )


def _validate_ds_to_product(
    dataset: Eo3DatasetDocBase,
    required_measurements: MutableMapping[str, "ExpectedMeasurement"],
    product_definition: Mapping,
    allow_extra_measurements: Sequence[str],
    msg: ContextualMessager,
):
    required_measurements.update(
        {
            m.name: m
            for m in map(
                ExpectedMeasurement.from_definition,
                product_definition.get("measurements") or (),
            )
        }
    )
    product_name = product_definition.get("name")
    if product_name and product_name != dataset.product.name:
        yield msg.error(
            "product_mismatch",
            f"Dataset product name {dataset.product.name!r} "
            f"does not match the given product ({product_name!r}",
        )

    ds_props = dict(dataset.properties)
    prod_props = product_definition["metadata"].get("properties", {})
    if not contains(ds_props, prod_props):
        diffs = tuple(_get_printable_differences(ds_props, prod_props))
        difference_hint = _differences_as_hint(diffs)
        yield msg.error(
            "metadata_mismatch",
            "Dataset template does not match product document template.",
            hint=difference_hint,
        )

    for name in required_measurements:
        if name not in dataset.measurements.keys():
            yield msg.error(
                "missing_measurement",
                f"Product {product_name} expects a measurement {name!r})",
            )
    measurements_not_in_product = set(dataset.measurements.keys()).difference(
        {m["name"] for m in product_definition.get("measurements") or ()}
    )
    # Remove the measurements that are allowed to be extra.
    measurements_not_in_product.difference_update(allow_extra_measurements or set())

    if measurements_not_in_product:
        things = ", ".join(sorted(measurements_not_in_product))
        yield msg.warning(
            "extra_measurements",
            f"Dataset has measurements not present in product definition for {product_name!r}: {things}",
            hint="This may be valid, as it's allowed by ODC. Set `expect_extra_measurements` to mute this.",
        )


def _validate_ds_to_metadata_type(
    doc: Dict,
    metadata_type_definition: Dict,
    expect: ValidationExpectations,
    msg: ContextualMessager,
):
    # Datacube does certain transforms on an eo3 doc before storage.
    # We need to do the same, as the fields will be read from the storage.
    prepared_doc = prep_eo3(doc)

    all_nullable_fields = tuple(expect.allow_nullable_fields) + tuple(
        expect.allow_missing_fields
    )
    for field_name, offsets in _get_field_offsets(
        metadata_type=metadata_type_definition
    ):
        if (
            # If a field is required...
            (field_name not in expect.allow_missing_fields)
            and
            # ... and none of its offsets are in the document
            not any(_has_offset(prepared_doc, offset) for offset in offsets)
        ):
            # ... warn them.
            readable_offsets = " or ".join("->".join(offset) for offset in offsets)
            yield msg.warning(
                "missing_field",
                f"Dataset is missing field {field_name!r} "
                f"for type {metadata_type_definition['name']!r}",
                hint=f"Expected at {readable_offsets}",
            )
            continue

        if field_name not in all_nullable_fields:
            value = None
            for offset in offsets:
                value = toolz.get_in(offset, prepared_doc)
            if value is None:
                yield msg.info(
                    "null_field",
                    f"Value is null for configured field {field_name!r}",
                )


def _validate_ds_against_data(
    dataset: Eo3DatasetDocBase,
    readable_location: str,
    required_measurements: Dict[str, "ExpectedMeasurement"],
    msg: ContextualMessager,
):
    # For each measurement, try to load it.
    # If loadable, validate measurements exist and match expectations.
    dataset_location = dataset.locations[0] if dataset.locations else readable_location
    for name, measurement in dataset.measurements.items():
        full_path = uri_resolve(dataset_location, measurement.path)
        expected_measurement = required_measurements.get(name)

        band = measurement.band or 1
        with rasterio.open(full_path) as ds:
            ds: DatasetReader

            if band not in ds.indexes:
                yield msg.error(
                    "incorrect_band",
                    f"Measurement {name!r} file contains no rio index {band!r}.",
                    hint=f"contains indexes {ds.indexes!r}",
                )
                continue

            if not expected_measurement:
                # The measurement is not in the product definition
                #
                # This is only informational because a product doesn't have to define all
                # measurements that the datasets contain.
                #
                # This is historically because dataset documents reflect the measurements that
                # are stored on disk, which can differ. But products define the set of measurments
                # that are mandatory in every dataset.
                #
                # (datasets differ when, for example, sensors go offline, or when there's on-disk
                #  measurements like panchromatic that GA doesn't want in their product definitions)
                if required_measurements:
                    yield msg.info(
                        "unspecified_measurement",
                        f"Measurement {name} is not in the product",
                    )
            else:
                expected_dtype = expected_measurement.dtype
                band_dtype = ds.dtypes[band - 1]
                if expected_dtype != band_dtype:
                    yield ValidationMessage.error(
                        "different_dtype",
                        f"{name} dtype: "
                        f"product {expected_dtype!r} != dataset {band_dtype!r}",
                    )

                ds_nodata = ds.nodatavals[band - 1]

                # If the dataset is missing 'nodata', we can allow anything in product 'nodata'.
                # (In ODC, nodata might be a fill value for loading data.)
                if ds_nodata is None:
                    continue

                # Otherwise check that nodata matches.
                expected_nodata = expected_measurement.nodata
                if expected_nodata != ds_nodata and not (
                    _is_nan(expected_nodata) and _is_nan(ds_nodata)
                ):
                    yield msg.error(
                        "different_nodata",
                        f"{name} nodata: "
                        f"product {expected_nodata !r} != dataset {ds_nodata !r}",
                    )


def _has_offset(doc: Dict, offset: List[str]) -> bool:
    """
    Is the given offset present in the document?
    """
    for key in offset:
        if key not in doc:
            return False
        doc = doc[key]
    return True


@define
class ExpectedMeasurement:
    name: str
    dtype: str
    nodata: int

    @classmethod
    def from_definition(cls, doc: Dict):
        return ExpectedMeasurement(doc["name"], doc.get("dtype"), doc.get("nodata"))


# Name of a field and its possible offsets in the document.
FieldNameOffsetS = Tuple[str, Set[List[str]]]


def validate_paths(
    paths: List[str],
    thorough: bool = False,
    product_definitions: Dict[str, Dict] = None,
    metadata_type_definitions: Dict[str, Dict] = None,
    expect: ValidationExpectations = None,
) -> Generator[Tuple[str, List[ValidationMessage]], None, None]:
    """Validate the list of paths. Product documents can be specified before their datasets."""

    products = dict(product_definitions or {})
    metadata_types = dict(metadata_type_definitions or {})

    for url, doc, was_specified_by_user in read_paths(paths):
        messages = []
        kind = filename_doc_kind(url)
        if kind is None:
            kind = guess_kind_from_contents(doc)
            if kind and (kind in DOC_TYPE_SUFFIXES):
                # It looks like an ODC doc but doesn't have the standard suffix.
                messages.append(
                    ValidationMessage.warning(
                        "missing_suffix",
                        f"Document looks like a {kind.name} but does not have "
                        f'filename extension "{DOC_TYPE_SUFFIXES[kind]}{_readable_doc_extension(url)}"',
                    )
                )

        if kind == DocKind.product:
            messages.extend(validate_product(doc))
            if "name" in doc:
                products[doc["name"]] = doc
        elif kind == DocKind.dataset:
            messages.extend(
                validate_eo3_doc(
                    doc,
                    url,
                    products,
                    metadata_types,
                    thorough,
                    expect=expect,
                )
            )
        elif kind == DocKind.metadata_type:
            messages.extend(validate_metadata_type(doc))
            if "name" in doc:
                metadata_types[doc["name"]] = doc

        # Otherwise it's a file we don't support.
        # If the user gave us the path explicitly, it seems to be an error.
        # (if they didn't -- it was found via scanning directories -- we don't care.)
        elif was_specified_by_user:
            if kind is None:
                raise ValueError(f"Unknown document type for {url}")
            else:
                raise NotImplementedError(
                    f"Cannot currently validate {kind.name} files"
                )
        else:
            # Not a doc type we recognise, and the user didn't specify it. Skip it.
            continue

        yield url, messages


def _get_field_offsets(metadata_type: Dict) -> Iterable[FieldNameOffsetS]:
    """
    Yield all fields and their possible document-offsets that are expected for this metadata type.

    Eg, if the metadata type has a region_code field expected properties->region_code, this
    will yield ('region_code', {['properties', 'region_code']})

    (Properties can have multiple offsets, where ODC will choose the first non-null one, hence the
    return of multiple offsets for each field.)
    """
    dataset_section = metadata_type["dataset"]
    search_fields = dataset_section["search_fields"]

    # The fixed fields of ODC. 'id', 'label', etc.
    for field_ in dataset_section:
        if field_ == "search_fields":
            continue

        offset = dataset_section[field_]
        if offset is not None:
            yield field_, [offset]

    # The configurable search fields.
    for field_, spec in search_fields.items():
        offsets = []
        if "offset" in spec:
            offsets.append(spec["offset"])
        offsets.extend(spec.get("min_offset", []))
        offsets.extend(spec.get("max_offset", []))

        yield field_, offsets


def _readable_doc_extension(uri: str):
    """
    >>> _readable_doc_extension('something.json.gz')
    '.json.gz'
    >>> _readable_doc_extension('something.yaml')
    '.yaml'
    >>> _readable_doc_extension('apple.odc-metadata.yaml.gz')
    '.yaml.gz'
    >>> _readable_doc_extension('products/tmad/tmad_product.yaml#part=1')
    '.yaml'
    >>> _readable_doc_extension('/tmp/human.06.tall.yml')
    '.yml'
    >>> # Not a doc, even though it's compressed.
    >>> _readable_doc_extension('db_dump.gz')
    >>> _readable_doc_extension('/tmp/nothing')
    """
    path = urlparse(uri).path
    compression_formats = (".gz",)
    doc_formats = (
        ".yaml",
        ".yml",
        ".json",
    )
    suffix = "".join(
        s.lower()
        for s in Path(path).suffixes
        if s.lower() in doc_formats + compression_formats
    )
    # If it's only compression, no doc format, it's not valid.
    if suffix in compression_formats:
        return None
    return suffix or None


def read_paths(
    input_paths: Iterable[str],
) -> Generator[Tuple[str, Union[Dict, str], bool], None, None]:
    """
    Read the given input paths, returning a URL, document, and whether
    it was explicitly given by the user.

    When a local directory is specified, inner readable docs are returned, but will
    be marked as not explicitly specified.
    """
    for input_ in input_paths:
        for uri, was_specified in expand_paths_as_uris([input_]):
            try:
                for full_uri, doc in read_documents(uri, uri=True):
                    yield full_uri, doc, was_specified
            except InvalidDocException as e:
                if was_specified:
                    raise
                else:
                    echo(e, err=True)


def expand_paths_as_uris(
    input_paths: Iterable[str],
) -> Generator[Tuple[Path, bool], None, None]:
    """
    For any paths that are directories, find inner documents that are known.

    Returns Tuples: path as a URL, and whether it was specified explicitly by user.
    """
    for input_ in input_paths:
        if is_url(input_):
            yield input_, True
        else:
            path = Path(input_).resolve()
            if path.is_dir():
                for found_path in path.rglob("*"):
                    if _readable_doc_extension(found_path.as_uri()) is not None:
                        yield found_path.as_uri(), False
            else:
                yield path.as_uri(), True


def validate_eo3_doc(
    doc: Dict,
    location: Union[str, Path],
    products: Dict[str, Dict],
    metadata_types: Dict[str, Dict],
    thorough: bool = False,
    expect: ValidationExpectations = None,
) -> List[ValidationMessage]:
    messages = []

    matched_product = None

    metadata_type = None
    if metadata_types and matched_product:
        metadata_type = matched_product["metadata_type"]
        if metadata_type not in metadata_types:
            messages.append(
                ValidationMessage(
                    Level.error if thorough else Level.info,
                    "no_metadata_type",
                    f"Metadata type not provided {metadata_type}: not validating fields",
                )
            )

    messages.extend(
        validate_dataset(
            doc,
            product_definitions=products,
            readable_location=location,
            thorough=thorough,
            metadata_type_definition=metadata_types.get(metadata_type),
            expect=expect,
        )
    )
    return messages


def _get_printable_differences(dict1: Dict, dict2: Dict):
    """
    Get a series of lines to print that show the reason that dict1 is not a superset of dict2
    """
    dict1 = dict(utils.flatten_dict(dict1))
    dict2 = dict(utils.flatten_dict(dict2))

    for path in dict2.keys():
        v1, v2 = dict1.get(path), dict2.get(path)
        if v1 != v2:
            yield f"{path}: {v1!r} != {v2!r}"


def _get_product_mismatch_reasons(dataset_doc: Dict, product_definition: Dict):
    """
    Which fields don't match the given dataset doc to a product definition?

    Gives human-readable lines of text.
    """
    yield from _get_printable_differences(dataset_doc, product_definition["metadata"])


def _differences_as_hint(product_diffs):
    return indent("\n".join(product_diffs), prefix="\t")


def _validate_eo3_properties(dataset: Eo3DatasetDocBase, msg: ContextualMessager):
    for name, value in dataset.properties.items():
        if name in dataset.properties.KNOWN_PROPERTIES:
            normaliser = dataset.properties.KNOWN_PROPERTIES.get(name)
            if normaliser and value is not None:
                try:
                    normalised_value = normaliser(value)
                    # A normaliser can return two values, the latter adding extra extracted fields.
                    if isinstance(normalised_value, tuple):
                        normalised_value = normalised_value[0]

                    # It's okay for datetimes to be strings
                    # .. since ODC's own loader does that.
                    if isinstance(normalised_value, datetime) and isinstance(
                        value, str
                    ):
                        value = ciso8601.parse_datetime(value)

                    # Special case for dates, as "no timezone" and "utc timezone" are treated identical.
                    if isinstance(value, datetime):
                        value = default_utc(value)

                    if not isinstance(value, type(normalised_value)):
                        yield msg.warning(
                            "property_type",
                            f"Value {value} expected to be "
                            f"{type(normalised_value).__name__!r} (got {type(value).__name__!r})",
                        )
                    elif normalised_value != value:
                        if _is_nan(normalised_value) and _is_nan(value):
                            # Both are NaNs, ignore.
                            pass
                        else:
                            yield ValidationMessage.warning(
                                "property_formatting",
                                f"Property {value!r} expected to be {normalised_value!r}",
                            )
                except ValueError as e:
                    yield msg.error("invalid_property", f"{name!r}: {e.args[0]}")
        # else: warning for unknown property?
    if "odc:producer" in dataset.properties:
        producer = dataset.properties["odc:producer"]
        # We use domain name to avoid arguing about naming conventions ('ga' vs 'geoscience-australia' vs ...)
        if "." not in producer:
            yield msg.warning(
                "producer_domain",
                "Property 'odc:producer' should be the organisation's domain name. Eg. 'ga.gov.au'",
            )

    # This field is a little odd, but is expected by the current version of ODC.
    # (from discussion with Kirill)
    if not dataset.properties.get("odc:file_format"):
        yield msg.warning(
            "global_file_format",
            "Property 'odc:file_format' is empty",
            hint="Usually 'GeoTIFF'",
        )


def _validate_geo(
    dataset: Eo3DatasetDocBase, msg: ContextualMessager, expect_geometry: bool = True
):
    # If we're not expecting geometry, and there's no geometry, then there's nothing to see here.
    if not expect_geometry and (
        dataset.geometry is None and not dataset.grids and not dataset.crs
    ):
        yield msg.info("non_geo", "No geo information in dataset")
        return

    # Geometry is recommended but not required
    if dataset.geometry is None:
        if expect_geometry:
            yield msg.info(
                "incomplete_geo", "Dataset has some geo fields but no geometry"
            )
    elif not dataset.geometry.is_valid:
        yield msg.error(
            "invalid_geometry",
            f"Geometry is not a valid shape: {explain_validity(dataset.geometry)!r}",
        )
        return

    # CRS required
    if not dataset.crs:
        yield msg.error("incomplete_crs", "Dataset has some geo fields but no crs")
    else:
        # We only officially support epsg code (recommended) or wkt.
        # TODO Anything supported by odc-geo
        yield from _validate_crs(dataset.crs, msg)

    # Grids is validated by schema - but is required
    if not dataset.grids:
        yield msg.error("incomplete_grids", "Dataset has some geo fields but no grids")
    else:
        yield from _validate_grids(dataset.grids, dataset.crs, msg)

    return


def _validate_crs(crs, msg):
    if crs.lower().startswith("epsg:"):
        try:
            CRS.from_string(crs)
        except CRSError as e:
            yield msg.error("invalid_crs_epsg", e.args[0])

        if crs.lower() != crs:
            yield msg.warning("mixed_crs_case", "Recommend lowercase 'epsg:' prefix")
    else:
        wkt_crs = None
        try:
            wkt_crs = CRS.from_wkt(crs)
        except CRSError as e:
            yield msg.error(
                "invalid_crs",
                f"Expect either an epsg code or a WKT string: {e.args[0]}",
            )

        if wkt_crs and wkt_crs.is_epsg_code:
            yield msg.warning(
                "non_epsg",
                f"Prefer an EPSG code to a WKT when possible. (Can change CRS to 'epsg:{wkt_crs.to_epsg()}')",
            )


def _validate_grids(grids, default_crs, msg):
    for grid_name, grid_def in grids.items():
        sub_msg = msg.sub_msg(grid=grid_name)
        if not grid_def.crs:
            grid_def.crs = default_crs
        else:
            yield from _validate_crs(grid_def.crs, sub_msg)


def _has_some_geo(dataset: Eo3DatasetDocBase) -> bool:
    return dataset.geometry is not None or dataset.grids or dataset.crs


def _load_doc(url):
    return list(load_documents(url))
