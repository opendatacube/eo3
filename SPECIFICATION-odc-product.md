## Product Documents

Product documents were originally known as "Dataset Type" documents.  The preferred terminology is now
"products".

In the ODC, all datasets must belong to a product. The products can be represented by product
documents.

### Format

A product document is a YAML or JSON document that conforms to the
EO3 Product JSON Schema at:

https://github.com/opendatacube/eo3/blob/develop/eo3/schema/product-schema.yaml

### Top Level

The top level of an EO3 compatible product document contains (or may contain) the following elements:

#### Name
`name` cannot contain whitespace or punctuation - alphanumeric characters (or underscores)
only.  Name is required and must be unique within a given ODC index.

#### Description
`description` is a string. It is required but may have any value.

#### Metadata Type
`metadata_type` is required. It must a string that is the name of a metadata type document stored in the target
ODC index.

The JSON schema also allows for a full metadata_type document to be embedded in this position, but this is deprecated
in 1.9 and will be dropped in 2.0.

#### License

`license` is an optional (but strongly recommended) string that describes the usage license that the product is
published under.

The schema limits the contents of the `license` field to alphanumeric, plus underscores, dashes, periods, and the
plus sign (`[A-Za-z0-9_\-.+]`).

License is recommended to be either 'various', 'proprietary' or and SPDX license identifier.  This is not
currently validated, but may be in future.

#### Metadata

The `metadata` section contains metadata that all datasets belonging to product are required to match exactly
with values in datasets' properties section.

In 1.8, product metadata may explicitly include the product name, e.g.:

```
name: this_product
....
metadata:
    product:
        name: this_product
```

If this is included, the specified product name must match the name of the product.  If it is not included,
it is assumed. 

In 1.9 explicitly specifying the product name in the metadata like this is deprecated, and it will be forbidden in 2.0

For EO3 compatible products, the metadata section should un-nested key-value pairs with EO3-compatible
key values: alphanumeric plus underscores, with a colon-separated namespace hierarchy.
E.g. "eo:instrument", "odc:file_format", etc.

#### Extra Dimensions

The `extra_dimensions` section was added in datacube-1.8 to support some simple multi-dimensional data loading
scenarios, as described in https://github.com/opendatacube/datacube-core/blob/develop/docs/ops/load_3d_dataset.rst

Datacube-2.0 is planned to support more general multi-dimension data-loading scenarios, so changes in this area
are expected.

As of 1.8, the extra_dimensions section is an optional array of extra dimensions to be loaded between t and (y,x).

Each extra dimension consists of:

##### name

The name of the extra dimension in loaded xarrays and as referenced from the measurement section
of the product document.


##### dtype

A string representing a numpy numeric datatype. One of:

 - float16
 - float32
 - float64
 - int8
 - int16
 - int32
 - int64
 - uint8
 - uint16
 - uint32
 - uint64
 - complex64
 - complex128

##### values

An array of coordinate values for the extra dimension. All values must be compatible with the provided
dtype.


#### Storage and Load

Storage and load were originally historic methods for providing load hints.

In 1.8, load and storage are equivalent, with load taking precedence over storage if both are provided - unless
the storage section contains "tile_size", in which case it is ignored.

Storage will be deprecated in 1.9 and removed in 2.0.

The remaining effect of the load (or storage) section is:

##### crs

crs is required and must represent a resolvable CRS (EPSG code or WKT)

It is returned by `prod.load_hints()["output_crs"]` and `prod.default_crs`, and is used to construct
the output geobox.

It also used to determine the coordinate labels for resolution and align, as discussed below.

##### resolution and align

Resolution and align are optional and should represent a numeric vector in the coordinates of the
CRS.  They are returned as prod.default resolution and prod.default.align and used to construct
the output geobox.

Resolution specifies the native/default resolution (in CRS coordinate units) and align specifies
the default pixel alignment.

Pixel alignment are measured between 0 and 1, with (0,0) being top-left alignment and (1,1)
being bottom-right alignment

E.g.:

```
load:
   crs: EPSG:4326
   // EPSG:4326 coordinate names are "latitude" and "longitude"
   resolution:
      // Measured in units of the CRS (degrees in this case)
      longitude: 0.0001
      // Y/vertical/lat resolution is usually negative
      latitude: -0.0001
   align:
      // bottom left
      longitude: 0
      latitude: 1
```

In 1.8 other entries (i.e. not crs, resolution or align) in load are ignored.  In 1.9 they will produce warnings,
and in 2.0 errors.

#### Measurements

The `measurements` section describes the measurements (or bands) that datasets within the product are expected to have.

The measurements section is required for EO3 compatible products and consists of an array of measurement definitions.

Each measurement definition contains:

##### Required fields: name, dtype, nodata, units

`name` is a string that provides a canonical name for the measurement.

`dtype` is a string numpy numeric datatype (see list of allowed values above).

`nodata` is the value representing no data. It must be compatible with the dtype.  If dtype is a
floating point type, no data may be a string with the value 'Inf', '-Inf' or 'NaN'.

`units` is a string describing the unit of the measurement band.

The remaining fields are optional:

##### aliases

A list of recognised aliases for the measurement. All aliases must be unique within the product.

##### extra_dim

Associates the measurement with named extra dimension.  Every pixel value for the measurement
in the source data should be in the values list in the `extra_dimensions` section.

##### spectral_definition

A representation of the spectral response of the measurement.

For normal measurements, contains `wavelength` and `response`, both of which are arrays of equal length of
numerical values.

For extra dimension measurements, a list of spectral definitions is provided, one per coordinate value
in the extra dimension.

##### scale_factor and add_offset

Define a mapping to some "real" space like so:

```
real_value = pixel_value * scale_factor + add_offset
```

##### flags_definition

Provides metadata for categorical and bitflag measurements.

Bitflag example:
```
flags_definition:
   nodata:
     // Bit 1 = 1(0x1)
     bits: 0
     values:
       0: False
       1: True
     description: No data flags_definition:
   spam:
     // Bit 2 = 2(0x2)
     bits: 2
     values:
       0: False
       1: True
     description: Pixel contains spam
   sausage:
     // Bit 3 = 4(0x4)
     bits: 3
     values:
       0: False
       1: True
     description: Pixel contains sausage
   eggs:
     // Bit 6 = 32(0x12)
     bits: 6
     values:
       0: False
       1: True
     description: Pixel contains eggs
```

Categorical data example:

```
 flags_definition:
    // Multiple value mappings may be provided
    a_mapping:
        // this is a categorical mapping, so include all bits
        bits: [
            0
            1
            2
            3
            4
            5
            6
            7
        ]
        values:
            0: nodata
            1: valid
            2: cloud
            3: shadow
            4: snow
            5: water
        description: An example categorical value mapping
```


### Managed

`managed` is an optional boolean field that defaults to false.  It should be true only if the product was created
with the datacube ingestion API.  Note that the ingestion API is deprecated in v1.9 and will be removed in 2.0,
after which the managed field will no longer be supported.
