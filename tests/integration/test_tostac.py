import json
import shutil
from pathlib import Path
from typing import Dict

import pytest

from eo3 import serialise
from eo3.scripts import tostac
from eo3.utils import read_file
from eo3.validate import InvalidDatasetError

from tests.common import assert_same, run_prepare_cli

TO_STAC_DATA: Path = Path(__file__).parent.joinpath("data/tostac")
ODC_METADATA_FILE: str = "ga_ls8c_ard_3-1-0_088080_2020-05-25_final.odc-metadata.yaml"
STAC_EXPECTED_FILE: str = (
    "ga_ls8c_ard_3-1-0_088080_2020-05-25_final.stac-item_expected.json"
)


@pytest.fixture
def odc_dataset_path(input_doc_folder: Path):
    d = input_doc_folder.joinpath(ODC_METADATA_FILE)
    assert d.exists()
    return d


@pytest.fixture
def expected_stac_doc(input_doc_folder: Path) -> Dict:
    d = input_doc_folder.joinpath(STAC_EXPECTED_FILE)
    assert d.exists()
    return json.load(d.open())


def test_tostac(odc_dataset_path: Path, expected_stac_doc: Dict):
    run_tostac(odc_dataset_path)

    expected_output_path = odc_dataset_path.with_name(
        odc_dataset_path.name.replace(".odc-metadata.yaml", ".stac-item.json")
    )

    assert expected_output_path.exists()

    output_doc = json.load(expected_output_path.open())

    assert expected_stac_doc["stac_extensions"][1] == output_doc["stac_extensions"][1]
    assert_same(expected_stac_doc, output_doc)


def remove_stac_properties(doc: Dict, remove_properties=()):
    """
    Remove the given fields from properties and assets.
    """

    def remove_proj(dict: Dict):
        for key in list(dict.keys()):
            if key in remove_properties:
                del dict[key]

    remove_proj(doc["properties"])
    for name, asset in doc["assets"].items():
        remove_proj(asset)


def test_add_property(input_doc_folder: Path):
    input_metadata_path = input_doc_folder.joinpath(ODC_METADATA_FILE)
    assert input_metadata_path.exists()

    input_doc = read_file(input_metadata_path)
    input_doc["properties"]["test"] = "testvalue"

    serialise.dump_yaml(input_metadata_path, input_doc)
    assert input_metadata_path.exists()

    run_tostac(input_metadata_path)

    name = input_metadata_path.stem.replace(".odc-metadata", "")
    actual_stac_path = input_metadata_path.with_name(f"{name}.stac-item.json")
    assert actual_stac_path.exists()

    actual_doc = json.load(actual_stac_path.open())
    assert actual_doc["properties"]["test"] == input_doc["properties"]["test"]


def test_no_crs(input_doc_folder: Path):
    input_metadata_path = input_doc_folder.joinpath(ODC_METADATA_FILE)
    assert input_metadata_path.exists()

    input_doc = read_file(input_metadata_path)
    del input_doc["crs"]

    serialise.dump_yaml(input_metadata_path, input_doc)
    assert input_metadata_path.exists()

    with pytest.raises(InvalidDatasetError, match="incomplete_geometry"):
        run_tostac(input_metadata_path)


def test_invalid_crs(input_doc_folder: Path):
    input_metadata_path = input_doc_folder.joinpath(ODC_METADATA_FILE)
    assert input_metadata_path.exists()

    input_doc = read_file(input_metadata_path)
    input_doc["crs"] = "I-CANT-BELIEVE-ITS-NOT-A-VALID-CRS:4236"

    serialise.dump_yaml(input_metadata_path, input_doc)
    assert input_metadata_path.exists()

    with pytest.raises(InvalidDatasetError, match="invalid_crs"):
        run_tostac(input_metadata_path)


def run_tostac(input_metadata_path: Path):
    run_prepare_cli(
        tostac.run,
        "-u",
        "http://dea-public-data-dev.s3-ap-southeast-2.amazonaws.com/"
        "analysis-ready-data/ga_ls8c_ard_3/088/080/2020/05/25/",
        "-e",
        "https://explorer.dev.dea.ga.gov.au/",
        "--validate",
        input_metadata_path,
    )


@pytest.fixture
def input_doc_folder(tmp_path: Path) -> Path:
    tmp_input_path = tmp_path / TO_STAC_DATA.name
    if TO_STAC_DATA.is_file():
        shutil.copy(TO_STAC_DATA, tmp_input_path)
    else:
        shutil.copytree(TO_STAC_DATA, tmp_input_path)
    return tmp_input_path
