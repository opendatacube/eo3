# Metadata Type Documents

Historically metadata type documents supported ...

For EO3 documents, their function is limited to ...

### Format

A metadata type document is a YAML or JSON document that conforms to the
EO3 Metadata Type JSON Schema at:

https://github.com/opendatacube/eo3/blob/develop/eo3/schema/metadata-type-schema.yaml

### Top Level

The top level of a Metadata Type Document consists of a name and description and a dataset
section.
```
name: eo3_minimal
description: Minimal EO3 compatible
dataset:
    ...
```

#### Name
`name` cannot contain whitespace or punctuation - alphanumeric characters (or underscores)
only.  Name is required and must be unique within a given index.

#### Description
`description` is a string. It is required but may have any value.

### Dataset (section)

As of datacube-1.8.x, most of the contents of `dataset` are no longer used by ODC, the only portion
still used is the `search_fields` section described below.  The remainder of this document is
required by the schema but mostly ignored by the ODC and/or assumed to have the following
canonical values:

```
dataset:
    id: [id]
    sources: [lineage, source_datasets]
    grid_spatial: [grid_spatial, projection]
    measurements: [measurements]
    creation_dt: [properties, 'odc:processing_datetime']
    label: [label]
    format: [properties, 'odc:file_format']
```

#### Fields that are nominally required in 1.8.x

`id`, and `sources`, are enforced to exist in the 1.8.x schema but are not used.  In 1.9 they
will become optional in the schema, then later deprecated, then dropped from the schema in 2.0.

`label` and `creation_dt` are enforced to exist in the 1.8.x schema but must match the above
values for EO3 compatibility. In 1.9 these values will become optional in the schema, defaulting
to the above values, then later deprecated, then dropped from the schema in 2.0.

#### Fields that are optional in 1.8.x

`format`, `grid_spatial`, and `measurements` are optional.

For an EO3-compliant geospatial metadata type these fields must all be present and have the values shown above.

In 1.9 these values will become optional in the schema, defaulting
to the above values, then later deprecated, then dropped from the schema in 2.0.

##### Proposed future extension - non-geospatial EO3 metadata

The legacy postgres ODC index driver in datacube 1.8 supports both EO3 and non-EO3 metadata types and also
supports both geospatial and non-geospatial metadata types, but "EO3-compatible" is largely assumed to
imply a geo-spatial metadata type.

With support for non-EO3-compatible metadata types being dropped in datacube-2.0, support for non-geospatial metadata
types will also be vanish.

New structures may be introduced at a later date to support EO3-compliant non-geospatial metadata types
(e.g. EO3 telemetry).

Note that EO3-compliant non-geospatial metadata types may not be supported by all index drivers.

#### Search Fields

The `search_fields` section contains a collection of search fields.  The index driver is responsible for ensuring that
efficient search queries can performed against all declared search fields.

The `search_fields` section is a dictionary (i.e. an associative array, or an "object" in json terminology) the keys
being the names of the search fields. Search field names can only contain alphanumeric characters and underscores.
The values of the `search_fields` dictionary are a section that may contain the following fields:

##### Description

An optional free-text description of the search field.  For informational purposes only.

##### Indexed

`indexed` is a an optional boolean field that defaults to True.  If False, the field is not indexed by the index
driver (i.e. a search field that cannot be searched.)

Indexed may be deprecated/required to be True in future releases.

##### Type

`type` is an optional string field that describes the data type of the search field.  If not specified, `type` defaults
to `"string"`.   The allowed values for type are:

**Scalar types:**
- string
- double
- integer
- numeric
- datetime

**Range types:**
- double-range
- integer-range
- numeric-range
- float-range
- datetime-range

`float-range` is a synonym for `numeric-range` and may be deprecated and removed in future releases.

Some index drivers may treat some combination of integer, double and numeric types as interchangable
for indexing purposes.

##### Offset (or min_offset and max_offset)

A search field with a scalar types must have an offset (and may not have a min_offset or max_offset).

A search field with a range types must have a min_offset and max_offset (and may not have an offset).

An offset is a sequence of strings and describes where the value for that search field can be found in
a Dataset document.  Range type search fields have two offsets: one for the lower limit of the range and
one for the upper limit of the range.

For EO3 compatibility the following restrictions apply to offsets:

1. The first offset element MUST be `"properties"`.
2. The offset can only be two elements long.
3. The second offset element must be a series of alphanumeric (plus underscore) only strings, separated
   by colons, e.g. "eo:instrument", "odc:file_format", etc.

I.e. all search offsets must be stored in dataset documents below "properties" with no nesting.

###### Special Case Search Fields

For historical reasons these restrictions are not enforced on some search fields:

**1. lat and lon**

For EO3 compatibility the "lat" and "lon" search fields MUST have the following values:

```
  search_fields:
    lon:
      description: Longitude range
      type: double-range
      min_offset:
        - [extent, lon, begin]
      max_offset:
        - [extent, lon, end]

    lat:
      description: Latitude range
      type: double-range
      min_offset:
        - [extent, lat, begin]
      max_offset:
        - [extent, lat, end]
```

"lat" and "lon" may be deprecated and removed in future releases.

**2. time**

"time" is STRONGLY recommended to have the following value:

```
  time:
      description: Acquisition time range
      type: datetime-range
      min_offset:
        - [properties, 'dtr:start_datetime']
        - [properties, datetime]
      max_offset:
        - [properties, 'dtr:end_datetime']
        - [properties, datetime]
```

These values may be enforced in future releases.  "time" may be deprecated and removed in future releases.

**3. crs_raw**

The raw EO3 native CRS (stored at `[crs]`) may be indexed as a search field called "crs_raw":

```
crs_raw:
  offset: [crs]
  indexed: False
  description: The raw CRS string as it appears in metadata
```
