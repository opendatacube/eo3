"""
Test utility functions
(tests copied from datacube-core/tests/test_utils_docs.py and test_utils_generic.py)
"""
from collections import OrderedDict
from pathlib import Path
from typing import Iterable, Tuple

import numpy as np
import pytest

from eo3.utils import (
    as_url,
    jsonify_document,
    netcdf_extract_string,
    read_documents,
    thread_local_cache,
)
from eo3.utils.utils import _open_from_s3, map_with_lookahead, transform_object_tree


@pytest.fixture
def sample_document_files():
    files = [
        ("multi_doc.yml", 3),
        ("multi_doc.yml.gz", 3),
        ("multi_doc.nc", 3),
        ("single_doc.yaml", 1),
        ("sample.json", 1),
    ]

    files = [
        (str(Path(__file__).parent / "data" / f), num_docs) for f, num_docs in files
    ]

    return files


def test_read_docs_from_local_path(sample_document_files):
    _test_read_docs_impl(sample_document_files)


def test_read_docs_from_file_uris(sample_document_files):
    uris = [("file://" + doc, ndocs) for doc, ndocs in sample_document_files]
    _test_read_docs_impl(uris)


def test_read_docs_from_s3(sample_document_files, monkeypatch):
    """
    Use a mocked S3 bucket to test reading documents from S3
    """
    boto3 = pytest.importorskip("boto3")
    moto = pytest.importorskip("moto")

    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake")

    with moto.mock_s3():
        s3 = boto3.resource("s3", region_name="us-east-1")
        bucket = s3.create_bucket(Bucket="mybucket")

        mocked_s3_objs = []
        for abs_fname, ndocs in sample_document_files:
            if abs_fname.endswith("gz") or abs_fname.endswith("nc"):
                continue

            fname = Path(abs_fname).name
            bucket.upload_file(abs_fname, fname)

            mocked_s3_objs.append(("s3://mybucket/" + fname, ndocs))

        _test_read_docs_impl(mocked_s3_objs)

    with pytest.raises(RuntimeError):
        with _open_from_s3("https://not-s3.ga/file.txt"):
            pass


def test_read_docs_from_http(sample_document_files, httpserver):
    http_docs = []
    for abs_fname, ndocs in sample_document_files:
        if abs_fname.endswith("gz") or abs_fname.endswith("nc"):
            continue
        path = "/" + Path(abs_fname).name

        httpserver.expect_request(path).respond_with_data(open(abs_fname).read())
        http_docs.append((httpserver.url_for(path), ndocs))

    _test_read_docs_impl(http_docs)


def _test_read_docs_impl(sample_documents: Iterable[Tuple[str, int]]):
    # Test case for returning URIs pointing to documents
    for doc_url, num_docs in sample_documents:
        all_docs = list(read_documents(doc_url, uri=True))
        assert len(all_docs) == num_docs

        for uri, doc in all_docs:
            assert isinstance(doc, dict)
            assert isinstance(uri, str)

        url = as_url(doc_url)
        if num_docs > 1:
            expect_uris = [as_url(url) + f"#part={i}" for i in range(num_docs)]
        else:
            expect_uris = [as_url(url)]

        assert [f for f, _ in all_docs] == expect_uris


def test_netcdf_strings():
    assert netcdf_extract_string(np.asarray([b"a", b"b"])) == "ab"
    txt = "some string"
    assert netcdf_extract_string(txt) is txt


def test_jsonify():
    from datetime import datetime
    from decimal import Decimal
    from uuid import UUID

    assert sorted(
        jsonify_document(
            {
                "a": (1.0, 2.0, 3.0),
                "b": float("inf"),
                "c": datetime(2016, 3, 11),
                "d": np.dtype("int16"),
            }
        ).items()
    ) == [
        ("a", (1.0, 2.0, 3.0)),
        ("b", "Infinity"),
        ("c", "2016-03-11T00:00:00"),
        ("d", "int16"),
    ]

    # Converts keys to strings:
    assert sorted(jsonify_document({1: "a", "2": Decimal("2")}).items()) == [
        ("1", "a"),
        ("2", "2"),
    ]

    assert jsonify_document({"k": UUID("1f231570-e777-11e6-820f-185e0f80a5c0")}) == {
        "k": "1f231570-e777-11e6-820f-185e0f80a5c0"
    }


def test_transform_object_tree():
    def add_one(a):
        return a + 1

    assert transform_object_tree(add_one, [1, 2, 3]) == [2, 3, 4]
    assert transform_object_tree(add_one, {"a": 1, "b": 2, "c": 3}) == {
        "a": 2,
        "b": 3,
        "c": 4,
    }
    assert transform_object_tree(add_one, {"a": 1, "b": (2, 3), "c": [4, 5]}) == {
        "a": 2,
        "b": (3, 4),
        "c": [5, 6],
    }
    assert transform_object_tree(
        add_one, {1: 1, "2": 2, 3.0: 3}, key_transform=float
    ) == {1.0: 2, 2.0: 3, 3.0: 4}
    # Order must be maintained
    assert transform_object_tree(
        add_one, OrderedDict([("z", 1), ("w", 2), ("y", 3), ("s", 7)])
    ) == OrderedDict([("z", 2), ("w", 3), ("y", 4), ("s", 8)])


def test_map_with_lookahead():
    def if_one(x):
        return "one" + str(x)

    def if_many(x):
        return "many" + str(x)

    assert list(map_with_lookahead(iter([]), if_one, if_many)) == []
    assert list(map_with_lookahead(iter([1]), if_one, if_many)) == [if_one(1)]
    assert list(map_with_lookahead(range(5), if_one, if_many)) == list(
        map(if_many, range(5))
    )
    assert list(map_with_lookahead(range(10), if_one=if_one)) == list(range(10))
    assert list(map_with_lookahead(iter([1]), if_many=if_many)) == [1]


def test_thread_local_cache():
    name = "test_0123394"
    v = {}

    assert thread_local_cache(name, v) is v
    assert thread_local_cache(name) is v
    assert thread_local_cache(name, purge=True) is v
    assert thread_local_cache(name, 33) == 33
    assert thread_local_cache(name, purge=True) == 33

    assert thread_local_cache("no_such_key", purge=True) is None
    assert thread_local_cache("no_such_key", 111, purge=True) == 111
