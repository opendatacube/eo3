# This file is part of the Open Data Cube, see https://opendatacube.org for more information
#
# Copyright (c) 2015-2023 ODC Contributors
# SPDX-License-Identifier: Apache-2.0
import json
from unittest import mock

import botocore
import pytest
from botocore.credentials import ReadOnlyCredentials

from eo3.utils.aws import (
    _fetch_text,
    _s3_cache_key,
    auto_find_region,
    ec2_current_region,
    s3_client,
    s3_fmt_range,
    s3_url_parse,
)

AWS_ENV_VARS = (
    "AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY AWS_SESSION_TOKEN"
    "AWS_DEFAULT_REGION AWS_DEFAULT_OUTPUT AWS_PROFILE "
    "AWS_ROLE_SESSION_NAME AWS_CA_BUNDLE "
    "AWS_SHARED_CREDENTIALS_FILE AWS_CONFIG_FILE"
).split(" ")


@pytest.fixture
def without_aws_env(monkeypatch):
    for e in AWS_ENV_VARS:
        monkeypatch.delenv(e, raising=False)


def _json(**kw):
    return json.dumps(kw)


def mock_urlopen(text, code=200):
    m = mock.MagicMock()
    m.getcode.return_value = code
    m.read.return_value = text.encode("utf8")
    m.__enter__.return_value = m
    return m


def test_ec2_current_region():
    tests = [
        (None, None),
        (_json(region="TT"), "TT"),
        (_json(x=3), None),
        ("not valid json", None),
    ]

    for rv, expect in tests:
        with mock.patch("eo3.utils.aws._fetch_text", return_value=rv):
            assert ec2_current_region() == expect


@mock.patch("eo3.utils.aws.botocore_default_region", return_value=None)
def test_auto_find_region(*mocks):
    with mock.patch("eo3.utils.aws._fetch_text", return_value=None):
        with pytest.raises(ValueError):
            auto_find_region()

    with mock.patch("eo3.utils.aws._fetch_text", return_value=_json(region="TT")):
        assert auto_find_region() == "TT"


@mock.patch("eo3.utils.aws.botocore_default_region", return_value="tt-from-botocore")
def test_auto_find_region_2(*mocks):
    assert auto_find_region() == "tt-from-botocore"


def test_fetch_text():
    with mock.patch("eo3.utils.aws.urlopen", return_value=mock_urlopen("", 505)):
        assert _fetch_text("http://localhost:8817") is None

    with mock.patch("eo3.utils.aws.urlopen", return_value=mock_urlopen("text", 200)):
        assert _fetch_text("http://localhost:8817") == "text"

    def fake_urlopen(*args, **kw):
        raise OSError("Always broken")

    with mock.patch("eo3.utils.aws.urlopen", fake_urlopen):
        assert _fetch_text("http://localhost:8817") is None


def test_s3_basics(without_aws_env):
    from botocore.credentials import ReadOnlyCredentials
    from numpy import s_

    assert s3_url_parse("s3://bucket/key") == ("bucket", "key")
    assert s3_url_parse("s3://bucket/key/") == ("bucket", "key/")
    assert s3_url_parse("s3://bucket/k/k/key") == ("bucket", "k/k/key")

    with pytest.raises(ValueError):
        s3_url_parse("file://some/path")

    assert s3_fmt_range((0, 3)) == "bytes=0-2"
    assert s3_fmt_range(s_[4:10]) == "bytes=4-9"
    assert s3_fmt_range(s_[:10]) == "bytes=0-9"
    assert s3_fmt_range(None) is None

    for bad in (s_[10:], s_[-2:3], s_[:-3], (-1, 3), (3, -1), s_[1:100:3]):
        with pytest.raises(ValueError):
            s3_fmt_range(bad)

    creds = ReadOnlyCredentials("fake-key", "fake-secret", None)

    assert (
        str(s3_client(region_name="kk")._endpoint) == "s3(https://s3.kk.amazonaws.com)"
    )
    assert (
        str(s3_client(region_name="kk", use_ssl=False)._endpoint)
        == "s3(http://s3.kk.amazonaws.com)"
    )

    s3 = s3_client(region_name="us-west-2", creds=creds)
    assert s3 is not None


def test_s3_unsigned(monkeypatch, without_aws_env):
    s3 = s3_client(aws_unsigned=True)
    assert s3._request_signer.signature_version == botocore.UNSIGNED

    monkeypatch.setenv("AWS_UNSIGNED", "yes")
    s3 = s3_client()
    assert s3._request_signer.signature_version == botocore.UNSIGNED


@mock.patch("eo3.utils.aws.ec2_current_region", return_value="us-west-2")
def test_s3_client_cache(monkeypatch, without_aws_env):
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "fake-key-id")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "fake-secret")

    s3 = s3_client(cache=True)
    assert s3 is s3_client(cache=True)
    assert s3 is s3_client(cache="purge")
    assert s3_client(cache="purge") is None
    assert s3 is not s3_client(cache=True)

    opts = (
        dict(),
        dict(region_name="foo"),
        dict(region_name="bar"),
        dict(profile="foo"),
        dict(profile="foo", region_name="xxx"),
        dict(profile="bar"),
        dict(creds=ReadOnlyCredentials("fake1", "...", None)),
        dict(creds=ReadOnlyCredentials("fake1", "...", None), region_name="custom"),
        dict(creds=ReadOnlyCredentials("fake2", "...", None)),
    )

    keys = {_s3_cache_key(**o) for o in opts}
    assert len(keys) == len(opts)
