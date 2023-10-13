from datetime import datetime
from enum import Enum
from pathlib import Path, PurePath
from typing import Mapping
from uuid import UUID

import numpy
from ruamel.yaml import YAML, Representer
from ruamel.yaml.comments import CommentedMap, CommentedSeq

from eo3.model import DatasetMetadata


class FileFormat(Enum):
    GeoTIFF = 1
    NetCDF = 2
    Zarr = 3
    JPEG2000 = 4


def _format_representer(dumper, data: FileFormat):
    return dumper.represent_scalar("tag:yaml.org,2002:str", f"{data.name}")


def _uuid_representer(dumper, data):
    """
    :type dumper: yaml.representer.BaseRepresenter
    :type data: uuid.UUID
    :rtype: yaml.nodes.Node
    """
    return dumper.represent_scalar("tag:yaml.org,2002:str", f"{data}")


def _represent_datetime(self, data: datetime):
    """
    The default Ruamel representer strips 'Z' suffixes for UTC.

    But we like to be explicit.
    """
    # If there's a non-utc timezone, use it.
    if data.tzinfo is not None and (data.utcoffset().total_seconds() > 0):
        value = data.isoformat(" ")
    else:
        # Otherwise it's UTC (including when tz==null).
        value = data.replace(tzinfo=None).isoformat(" ") + "Z"
    return self.represent_scalar("tag:yaml.org,2002:timestamp", value)


def _represent_numpy_datetime(self, data: numpy.datetime64):
    return _represent_datetime(self, data.astype("M8[ms]").tolist())


def _represent_paths(self, data: PurePath):
    return Representer.represent_str(self, data.as_posix())


def _represent_float(self, data: float):
    float_text = numpy.format_float_scientific(data)
    return self.represent_scalar("tag:yaml.org,2002:float", float_text)


def _init_yaml() -> YAML:
    yaml = YAML()

    yaml.representer.add_representer(FileFormat, _format_representer)
    yaml.representer.add_multi_representer(UUID, _uuid_representer)
    yaml.representer.add_representer(datetime, _represent_datetime)
    yaml.representer.add_multi_representer(PurePath, _represent_paths)

    # WAGL spits out many numpy primitives in docs.
    yaml.representer.add_representer(numpy.int8, Representer.represent_int)
    yaml.representer.add_representer(numpy.uint8, Representer.represent_int)
    yaml.representer.add_representer(numpy.int16, Representer.represent_int)
    yaml.representer.add_representer(numpy.uint16, Representer.represent_int)
    yaml.representer.add_representer(numpy.int32, Representer.represent_int)
    yaml.representer.add_representer(numpy.uint32, Representer.represent_int)
    yaml.representer.add_representer(numpy.int64, Representer.represent_int)
    yaml.representer.add_representer(numpy.uint64, Representer.represent_int)
    yaml.representer.add_representer(numpy.float32, Representer.represent_float)
    yaml.representer.add_representer(numpy.float64, Representer.represent_float)

    yaml.representer.add_representer(numpy.ndarray, Representer.represent_list)
    yaml.representer.add_representer(numpy.datetime64, _represent_numpy_datetime)

    # Match yamllint default expectations. (Explicit start/end are recommended to tell if a file is cut off)
    yaml.width = 80
    yaml.explicit_start = True
    yaml.explicit_end = True

    return yaml


def dump_yaml(output_yaml: Path, *docs: Mapping) -> None:
    if not output_yaml.name.lower().endswith(".yaml"):
        raise ValueError(
            f"YAML filename doesn't end in *.yaml (?). Received {output_yaml!r}"
        )

    yaml = _init_yaml()
    with output_yaml.open("w") as stream:
        yaml.dump_all(docs, stream)


def dumps_yaml(stream, *docs: Mapping) -> None:
    """Dump yaml through a stream, using the default serialisation settings."""
    yml = _init_yaml()
    yml.representer.add_representer(float, _represent_float)
    return yml.dump_all(docs, stream=stream)


def to_formatted_doc(d: DatasetMetadata) -> CommentedMap:
    """Serialise to a yaml-serialisation-ready dict"""
    doc = prepare_formatting(d.doc)
    # Add user-readable names for measurements as a comment if present.
    if d.measurements:
        for band_name, band_doc in d.measurements.items():
            if band_doc.alias and band_name.lower() != band_doc.alias.lower():
                doc["measurements"].yaml_add_eol_comment(band_doc.alias, band_name)

    return doc


def to_path(path: Path, *ds: DatasetMetadata) -> None:
    """
    Output dataset(s) as a formatted YAML to a local path

    (multiple datasets will result in a multi-document yaml file)
    """
    dump_yaml(path, *(to_formatted_doc(d) for d in ds))


def to_stream(stream, *ds: DatasetMetadata) -> None:
    """
    Output dataset(s) as a formatted YAML to an output stream

    (multiple datasets will result in a multi-document yaml file)
    """
    dumps_yaml(stream, *(to_formatted_doc(d) for d in ds))


def _stac_key_order(key: str):
    """All keys in alphabetical order, but unprefixed keys first."""
    if ":" in key:
        # Tilde comes after all alphanumerics.
        return f"~{key}"
    else:
        return key


def _eo3_key_order(keyval: str):
    """
    Order keys in an an EO3 document.

    Suitable for sorted() func usage.
    """
    key, val = keyval
    try:
        i = _EO3_PROPERTY_ORDER.index(key)
        if i == -1:
            return 999
        return i
    except ValueError:
        return 999


# A logical, readable order for properties to be in a dataset document.
_EO3_PROPERTY_ORDER = [
    "$schema",
    # Products / Types
    "name",
    "license",
    "metadata_type",
    "description",
    "metadata",
    # EO3 Datasets
    "id",
    "label",
    "product",
    "location",
    "locations",
    "crs",
    "geometry",
    "grids",
    "properties",
    "measurements",
    "accessories",
    "lineage",
]


def prepare_formatting(d: Mapping) -> CommentedMap:
    """
    Format an eo3 dataset dict for human-readable yaml serialisation.

    This will order fields, add whitespace, comments, etc.

    Output is intended for ruamel.yaml.
    """
    # Sort properties for readability.
    doc = CommentedMap(sorted(d.items(), key=_eo3_key_order))
    doc["properties"] = CommentedMap(
        sorted(doc["properties"].items(), key=_stac_key_order)
    )

    # Whitespace
    doc.yaml_set_comment_before_after_key("$schema", before="Dataset")
    if "geometry" in doc:
        # Set some numeric fields to be compact yaml format.
        _use_compact_format(doc["geometry"], "coordinates")
    if "grids" in doc:
        for grid in doc["grids"].values():
            _use_compact_format(grid, "shape", "transform")

    _add_space_before(
        doc,
        "label" if "label" in doc else "id",
        "crs",
        "properties",
        "measurements",
        "accessories",
        "lineage",
        "location",
        "locations",
    )

    p: CommentedMap = doc["properties"]
    p.yaml_add_eol_comment("# Ground sample distance (m)", "eo:gsd")

    return doc


def _use_compact_format(d: dict, *keys):
    """Change the given sequence to compact YAML form"""
    for key in keys:
        if key in d:
            d[key] = CommentedSeq(d[key])
            d[key].fa.set_flow_style()


def _add_space_before(d: CommentedMap, *keys):
    """Add an empty line to the document before a section (key)"""
    for key in keys:
        d.yaml_set_comment_before_after_key(key, before="\n")
