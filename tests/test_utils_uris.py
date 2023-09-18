"""
Test utility uri functions
(tests copied from datacube-core/tests/test_utils_other.py)
"""
import os
from pathlib import Path

import pytest

from eo3.utils import (
    as_url,
    get_part_from_uri,
    is_url,
    is_vsipath,
    mk_part_uri,
    normalise_path,
    uri_resolve,
    uri_to_local_path,
)
from eo3.utils.uris import default_base_dir


def test_uri_to_local_path():
    if os.name == "nt":
        assert "C:\\tmp\\test.tmp" == str(uri_to_local_path("file:///C:/tmp/test.tmp"))
        assert "\\\\remote\\path\\file.txt" == str(
            uri_to_local_path("file://remote/path/file.txt")
        )

    else:
        assert "/tmp/something.txt" == str(
            uri_to_local_path("file:///tmp/something.txt")
        )

        with pytest.raises(ValueError):
            uri_to_local_path("file://remote/path/file.txt")

    assert uri_to_local_path(None) is None

    with pytest.raises(ValueError):
        uri_to_local_path("ftp://example.com/tmp/something.txt")


def test_part_uri():
    base = "file:///foo.txt"

    for i in range(10):
        assert get_part_from_uri(mk_part_uri(base, i)) == i

    assert get_part_from_uri("file:///f.txt") is None
    assert get_part_from_uri("file:///f.txt#something_else") is None
    assert get_part_from_uri("file:///f.txt#part=aa") == "aa"
    assert get_part_from_uri("file:///f.txt#part=111") == 111


@pytest.mark.parametrize(
    "test_input,expected",
    [
        ("/foo/bar/file.txt", False),
        ("file:///foo/bar/file.txt", True),
        ("test.bar", False),
        ("s3://mybucket/objname.tiff", True),
        ("gs://mybucket/objname.tiff", True),
        ("wasb://mybucket/objname.tiff", True),
        ("wasbs://mybucket/objname.tiff", True),
        ("ftp://host.name/filename.txt", True),
        ("https://host.name.com/path/file.txt", True),
        ("http://host.name.com/path/file.txt", True),
        ("sftp://user:pass@host.name.com/path/file.txt", True),
        ("file+gzip://host.name.com/path/file.txt", True),
        ("bongo:host.name.com/path/file.txt", False),
    ],
)
def test_is_url(test_input, expected):
    assert is_url(test_input) == expected
    if expected:
        assert as_url(test_input) is test_input


@pytest.mark.parametrize(
    "base",
    [
        "s3://foo",
        "gs://foo",
        "wasb://foo",
        "wasbs://foo",
        "/vsizip//vsicurl/https://host.tld/some/path",
    ],
)
def test_uri_resolve(base):
    abs_path = "/abs/path/to/something"
    some_uri = "http://example.com/file.txt"

    assert uri_resolve(base, abs_path) == "file://" + abs_path
    assert uri_resolve(base, some_uri) is some_uri
    assert uri_resolve(base, None) is base
    assert uri_resolve(base, "") is base
    assert uri_resolve(base, "relative/path") == base + "/relative/path"
    assert uri_resolve(base + "/", "relative/path") == base + "/relative/path"
    assert (
        uri_resolve(base + "/some/dir/", "relative/path")
        == base + "/some/dir/relative/path"
    )

    if not is_vsipath(base):
        assert (
            uri_resolve(base + "/some/dir/file.txt", "relative/path")
            == base + "/some/dir/relative/path"
        )


def test_normalise_path():
    cwd = Path(".").resolve()
    assert normalise_path(".").resolve() == cwd

    p = Path("/a/b/c/d.txt")
    assert normalise_path(p) == Path(p)
    assert normalise_path(str(p)) == Path(p)

    base = Path("/a/b/")
    p = Path("c/d.txt")
    assert normalise_path(p, base) == (base / p)
    assert normalise_path(str(p), str(base)) == (base / p)
    assert normalise_path(p) == (cwd / p)

    with pytest.raises(ValueError):
        normalise_path(p, "not/absolute/path")


def test_default_base_dir(monkeypatch):
    def set_pwd(p):
        if p is None:
            monkeypatch.delenv("PWD")
        else:
            monkeypatch.setenv("PWD", str(p))

    cwd = Path(".").resolve()

    # Default base dir (once resolved) will never be different from cwd
    assert default_base_dir().resolve() == cwd

    # should work when PWD is not set
    set_pwd(None)
    assert "PWD" not in os.environ
    assert default_base_dir() == cwd

    # should work when PWD is not absolute path
    set_pwd("this/is/not/a/valid/path")
    assert default_base_dir() == cwd

    # should be cwd when PWD points to some other dir
    set_pwd(cwd / "deeper")
    assert default_base_dir() == cwd

    set_pwd(cwd.parent)
    assert default_base_dir() == cwd

    # PWD == cwd
    set_pwd(cwd)
    assert default_base_dir() == cwd

    # TODO:
    # - create symlink to current directory in temp
    # - set PWD to that link
    # - make sure that returned path is the same as symlink and different from cwd
