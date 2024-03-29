#!/usr/bin/env python

import pathlib
from itertools import chain

from setuptools import find_packages, setup

import versioneer

HERE = pathlib.Path(__file__).parent.resolve()

README = (HERE / "README.md").read_text(encoding="utf-8")


tests_require = [
    "deepdiff",
    "gdal",
    "mock",
    "pep8-naming",
    "pytest",
    "pytest-cov",
    "pytest-httpserver",
    "rio_cogeo",
    "sphinx-autodoc-typehints",
    "sphinx_rtd_theme",
    "moto",
]

EXTRAS_REQUIRE = {
    "test": tests_require,
    # If packaging ard/wagl.
    "wagl": ["h5py"],
    # The (legacy) prepare scripts
    "ancillary": ["checksumdir", "netCDF4"],
    # Optional valid-data poly handling methods
    "algorithms": ["scikit-image"],
    # Match the expected environment of our docker image
    "docker": ["gdal==3.6.3"],
}
EXTRAS_REQUIRE["all"] = list(chain(EXTRAS_REQUIRE.values()))
# Tests need all those optionals too.

EXTRAS_REQUIRE["test"] = EXTRAS_REQUIRE["all"]
# Prod deployment just adds the optional wagl depenencies.
EXTRAS_REQUIRE["deployment"] = EXTRAS_REQUIRE["wagl"]

setup(
    name="eo3",
    description="Formal specification of, and extensible library for manipulating OpenDataCube EO3 datasets",
    long_description=README,
    long_description_content_type="text/markdown",
    author="Open Data Cube",
    version=versioneer.get_version(),
    cmdclass=versioneer.get_cmdclass(),
    packages=find_packages(exclude=("tests", "tests.*")),
    package_data={
        "": ["*.json", "*.yaml", "*.db"],
        "eo3": ["eo3/py.typed"],
    },
    license="Apache Software License 2.0",
    python_requires=">=3.8",
    classifiers=[
        "License :: OSI Approved :: Apache Software License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.6",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Operating System :: OS Independent",
    ],
    url="https://github.com/opendatacube/eo3",
    install_requires=[
        "affine",
        "attrs>=18.1",  # 18.1 adds 'factory' syntactic sugar
        "boltons",
        "botocore",  # missing from datacube
        "boto3",
        "cattrs",
        "ciso8601",
        "click",
        "defusedxml",
        "h5py",
        "jsonschema>=4.18",
        "referencing",
        "numpy>=1.15.4",
        "odc-geo",
        "pyproj",
        "rasterio",
        "ruamel.yaml",
        "scipy",
        "shapely",
        "structlog",
        "xarray",
        "toolz",
        "python-rapidjson",
        "pystac>=1.8.4",  # 1.8.4 fixes RefResolver issue
    ],
    tests_require=tests_require,
    extras_require=EXTRAS_REQUIRE,
    entry_points="""
        [console_scripts]
        eo3-validate=eo3.validate:run
        eo3-prepare=eo3.scripts.prepare:run
        eo3-recompress-tar=eo3.scripts.recompress:main
        eo3-package-wagl=eo3.scripts.packagewagl:run
        eo3-to-stac=eo3.scripts.tostac:run
    """,
    project_urls={
        "Bug Reports": "https://github.com/opendatacube/eo3/issues",
        "Source": "https://github.com/opendatacube/eo3",
    },
)
