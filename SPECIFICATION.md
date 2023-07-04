## EO3 Dataset Documents

A dataset document contains the metadata for an ODC geo-data resource.

### Format

A dataset document is a YAML or JSON document that conforms to the EO3 Dataset JSON Schema at:

https://github.com/opendatacube/eo3/blob/develop/eo3/schema/dataset.schema.yaml

### Contents

The top level of an EO3 dataset document contains the following elements, discussed in detail
below:

- $schema (required)
- id (required)
- label (not required, but strongly recommended)
- product (required)
- location (optional)
- locations (optional)
- crs (required)
- geometry (??)
- grids (required)
- properties (required)
- measurements (required)
- accessories (optional)
- lineage (optional)

#### $schema

An EO3 dataset docment must contain a `$schema` element, which is a string that must
be exactly `https://schemas.opendatacube.org/dataset`.

#### id

An EO3 dataset must contain an `id` element, which is a string containing a valid UUID in standard
hexidecimal fomat (e.g. `550e8400-e29b-41d4-a716-446655440000`).  Id's should
be generated using an appropriate algorithm and should be globally unique.

#### label

Label is not currently required by the schema, but required by EO3 (see SPECIFICATION-odc-type.md).

The label is intended to contain a user-readable unique identifier for the dataset, however uniqueness
is not enforced.

Label can only contain alphanumeric characters, and underscores and dashes.

#### product

The product section is required and identifies the ODC product document associated with the dataset.

The product section must contain a name entry, and may contain a href entry, as decribed below.

##### name

Name is a string that identifies the product associated with the dataset document (as recorded in
the "name" field of the product document).  Name can only contain alphanumeric characters, underscores
and hyphens and is required in all dataset documents.

##### href

The product section may also contain a href entry, which is a valid URL pointing to a copy of the
product document.

Href is optional, but is recommended, particularly when working with multiple ODC indexes that may
contain slightly differing versions of a given product document.

#### location/locations

Location and/or locations are intended to store the root URI of the measurement datafile(s) in cases
where the root URI is not equal to the URI of the dataset metadata file (which is the default
assumption).

In datacube-1.8.x:

The dataset schema (in eodatasets) allowed for either a single string in the `location` field or an
array of strings in the `locations` field.  This avoids defining the the datatype for the location/loctaions
field(s) as a union, and theoretically allows the contents of an ODC database to be losslessly serialised to a
dataset metadata file. In the database, locations are stored in a separate table to datasets, and there
can be multiple locations per dataset. By default, the most recently added location is used, but it
is sometimes possible to specify a secondary location by giving the preferred URI schema,
e.g. s3:// vs https:// vs file:// (see `datacube.storage._base.BaseInfo`).

Datacube-core itself however, ignored the `locations` field and allowed the `location` field to be either
a string or an array of strings.  (If `location` is an array of strings, only the first string in
the array is actually read, the remainder are ignored.)  If set, the location field is stripped from
the metadata file before storing it in the ODC index - it is used only as part of the initial indexing
process.

From datacube-1.9.0:

The schema for the `locations` field will be updated to match the behaviour described above (i.e. a
union datatype).  The `location` field is no longer supported and will raise an error.

#### crs

The CRS for the georegistration of the spatial data is required. It maybe an EPSG code (e.g. "EPSG:4326")
or may be expressed in WKT format.

#### geometry

Geometry contains a 2D geometry (of Polygon or MultiPolygon type) such that all valid data points
in all the grids (described below) fall inside the geometry, and all data points in all the grids that
fall outside the geometry are invalid.

The geometry is used when performing dataset searches.  If there is valid data in the dataset outside
of the specified geometry, the dataset may not be returned when explicitly searching for that data.

The geometry may be approximate.  The geometry is optional.  If omitted, all data within the grids is assumed
to be valid.

The format expected is equivalent to a GeoJSON geometry primitive, e.g.:

```
    geometry:
        type: Polygon
        coordinates: [
            [
                [35.0, 10.0], [45.0, 45.0], [15.0, 40.0], [10.0, 20.0], [35.0, 10.0]
            ]
        ]
```

Coordinates are always in xy (lon, lat) order and are assumed to be expressed in the crs specified above.

#### grids

The grids section is required for EO3 datasets. It contains at least one grid definition named "default"
and may contain additional alternate grid definitions. Each grid definition is equivalent to an
`odc-geo` `GeoBox` for the entire dataset. Each measurement in the dataset must have a grid, but multiple
measurements can share the same grid.

Each grid definition has a `shape` and a `transform` and represents the native geobox for the whole
dataset for at least one measurement belonging to the dataset.  `shape` is an array of two integers,
and represents the width and height of the grid in pixels.  `transform` is an array of either 6 or
9 floating point numbers and represents an affine transform for converting pixel coordinates to
coordinates in the `crs` specified above.  If the 9-number form is used, the last three numbers must
be [0, 0, 1].

E.g.
```
  grids:
    default:
      # "default" grid for most measurement bands is 7941x7901 pixels
      shape: [7941, 7901]
      # 9 number form - note that last three elements are [0, 0, 1]
      transform: [30.0, 0.0, 557385.0, 0.0, -30.0, -4030485.0, 0.0, 0.0, 1.0]
    panchromatic:
      # "panchromatic" grid for the panchromatic measurement band
      # This grid has higher resolution over the same area than default: 15881x15801 pixels
      shape: [15881, 15801]
      # 6 number form - final [0, 0, 1] elements are automatically appended.
      transform: [15.0, 0.0, 557392.5, 0.0, -15.0, -4030492.5]
```

#### properties

The properties section contains arbitrary user-specified metadata.

Previously this data could be nested arbitrarily, but in EO3 it is required to be flat
with colon separated namespaces for virtual nesting, as described in the odc-type specification
document.

Please refer to the default eo3 metadata type definition for common field locations. Compatibility
with STAC metadata is recommended, and may be more strongly enforced in future.

In particular the acquisition time (or coverage time for derived products) should be stored
as either a range defined by `dtr:start_datetime` and `dtr:end_datetime`, or as single time value
at `datetime`.

#### measurements

The measurements section describes the measurments (or bands) associated with the dataset.

The measurements section is required for EO3 compatibility.  The measurements map canonical measurement
names to measurement definitions.  All measurements defined by the dataset's product must be included.
Additional measurements not defined in the product have historically been supported, but this may be
deprecated or removed in a future release.

Measurement names can contain alphanumeric characters and underscores only. Measurement definitions
can contain the following elements:

##### path

Path is the only element of a measurement definition that is always required. It contains the
path to the datafile, evaluated relative to the location of the dataset.
```
measurements:
  red:
    path: data/red.tif
  green:
    path: data/green.tif
```

##### path with part

Previously, if a NetCDF datafile contained multiple time-slices or measurements,
the part number can be specified as part of the `path`. This is a zero-based index (in contrast to
the 1-based convention used by rasterio) E.g.:

```
measurements:
   red:
      path: data/file.nc#part=0
```

This usage is considered ambiguous and potentially confusing and will be deprecated and
removed in future releases.  Instead, use the `band` and `layer` entries discussed below.


##### band and layer

To specify multiple bands/time-slices in a single file, the optional band and layer entries can
be used.

Band is a band or part number using a rasterio-style 1-based index.

Layer is a (string type) band or layer name.

Band and layer can be used together or separately. The normal use cases are a band number for a GeoTIFF
and either or both for a NetCDF, depending on the structure of the file.  E.g.

```
// Time slice from NetCDF file - first time-slice in file, number 1 and two named layers as measurments
measurements:
  red:
    path: data/file.nc
    band: 1
    layer: red
  green:
    path: data/file.nc
    band: 1
    layer: green
```

```
// Bands in a GeoTIFF file
measurements:
  red:
    path: data/file.tif
    band: 1
  green:
    path: data/file.tif
    band: 2
```
##### grid

The `grid` element identifies the grid (from the `grids` section described above) to use
for this measurement band.  It is optional and defaults to `"default"`.

#### accessories

Accessories is an optional section for describing accessory and ancillary files packaged with
the data and metadata (e.g. thumbnail images, checksums, metadata in alternate formats, etc).

Accessories is a object mapping accessory file names to a relative file path and an optional
type.  Accessory names consist of alphanumeric (plus underscores) characters, with colons
to allow for a nested hierarchy of colon-separated namespaces.

path contains a path to the accessory file, relative to the location of the dataset.  The
interpretation of the optional type field is not specified.  E.g.

```
accessories:
   metadata:stac:
      path: this-dataset.stac-info.json
      type: STAC v1.0.0(proj,view)
   checksum:sha1:
      path: checksums/this-dataset.sha1
```


#### lineage

Lineage is an optional section for listing other datasets that were used in the calculation of
this dataset.   Older ODC metadata formats supported embedding of complete metadata documents of
parent datasets, however this is now deprecated in favour of just including the ids of ancestor
datasets.

The lineage section maps labels describing types of classes of source datasets to lists of source
dataset ids.

The legacy postgres index driver rewrote lineage sections to flatten the dependency list prior
to storage. E.g. a dataset with a lineage section specifying 4 source dataset ids of type 'ard'
would be rewritten to have four source types ('ard1', 'ard2', 'ard3' and 'ard4'), each with
a single source dataset id.  This flattening is not performed by the new postgis index driver.

E.g.
```
lineage:
  ard:
  - c90f820b-7aa5-492d-a12b-ba8d47a16a90
  - 90267ce3-41e0-480c-8cc1-4418a1ebc314
  - 07c0a669-b2de-4437-aa90-43a86da9525e
  - d5c99c8e-7ce1-4627-bb4d-4a1abbfebc1a
```

The new postgis index driver stores this lineage information exactly as provided.  The legacy
postgres index driver will rewrite this section for storage as follows:

```
lineage:
  ard1:
  - c90f820b-7aa5-492d-a12b-ba8d47a16a90
  ard2:
  - 90267ce3-41e0-480c-8cc1-4418a1ebc314
  ard3:
  - 07c0a669-b2de-4437-aa90-43a86da9525e
  ard4:
  - d5c99c8e-7ce1-4627-bb4d-4a1abbfebc1a
```

### Elements derived and inserted on indexing

The following elements are traditionally not included in dataset metadata documents external
to the datacube (i.e. transmitted over a network protocol or stored on a network or local file
system.)  Instead, they are generated by the Open Data Cube on indexing and injected into dataset
metadata documents for internal storage in the ODC index, and internal use within the ODC.  They
are generated by the `prep_eo3` method defined in `datacube.index.eo3`.

These elements are not documented in the schema, and so will fail validation.


#### extent

In the "postgres" index driver (the default index driver in datacube-1.8), the extent section
was not expected to be in the source dataset metadata document, but was generated from the grids
section at index time and injected into the dataset document before being stored in the database.
It was never included in the dataset document schema in the eodatasets repository.

The extent section contains the maximum and minimum latitude and longitude values for the
dataset in the EPSG:4326 CRS in the following format:

```
extent:
  lat:
    begin: -21.789474556891378
    end: -20.788940834502526
  lon:
    begin: 133.0656386483482
    end: 134.13328670106225
```

The extent section was historically used by the "postgres" driver to perform spatial search queries -
leading to inefficient and/or broken search behaviour for datasets that lie around the poles
and the anti-meridian, even if the dataset has a native CRS that performs well in those regions.

It is not used by the new "postgis" index driver (which uses instead the grids and geometry sections described
above).

#### grid_spatial

`grid_spatial` is calculated from the "default" grid in the `grids` section described above.

`grid_spatial` contains a `projection` section, which in turn contains the following elements:

##### spatial_reference

`spatial_reference` is a CRS expressed in a supported format (EPSG code or WKT) it is simply copied from
the `crs` entry described above.

`geo_ref_points` contains the coordinates of the four corners of the GeoBox defined by the default
grid spec.  These are stored as "x" and "y" coordinate values for the upper-left (ul), lower-right (lr),
etc. points.  Note that "x" and "y" are used even if the CRS defines alternative names for
its axes (e.g. does not become "latitude" and "longitude" when `spatial_reference` is EPSG:4326).

`valid data` is geoJSON geometry primitive (with coordinates in the CRS from `spatial_reference`). If
the `geometry` section (described above) is provided, it is a copy of that.  If no `geometry` section was
provided, a four sided polygon is generated from the `geo_ref_points`.

E.g.

```
grid_spatial:
  projection
    spatial_reference: epsg:32753
    geo_ref_points:
       ll:
         x: 300000.0
         y: 7590220.0
       lr:
         x: 409800.0
         y: 7590220.0
       ul:
         x: 300000.0
         y: 7700020.0
       ur:
         x: 409800.0
         y: 7700020.0
    valid_data:
      type: Polygon
      coordinates: [
         [
           [300000.0, 7700020.0],
           [409800.0, 7700020.0],
           [409800.0, 7590220.0],
           [300000.0, 7590220.0],
           [300000.0, 7700020.0]
         ]
      ]
```
