import os
import pathlib
import re
import urllib.parse
from pathlib import Path
from typing import Optional, Union
from urllib.parse import parse_qsl, urljoin, urlparse
from urllib.request import url2pathname

# TODO: ideally this file would eventually be moved to a lower-level utils package

# CORE TODO: forked from datacube.utils.uris


URL_RE = re.compile(r"\A\s*[\w\d\+]+://")


def is_url(url_str: str) -> bool:
    """
    Check if url_str tastes like a url (starts with blah://)
    """
    try:
        return URL_RE.match(url_str) is not None
    except TypeError:
        return False


def is_vsipath(path: str) -> bool:
    """Check if string is a GDAL "/vsi.*" path"""
    path = path.lower()
    return path.startswith("/vsi")


def vsi_join(base: str, path: str) -> str:
    """Extend GDAL's vsi path

    Basically just base/path, but taking care of trailing `/` in base
    """
    return base.rstrip("/") + "/" + path


def default_base_dir() -> pathlib.Path:
    """Return absolute path to current directory. If PWD environment variable is
    set correctly return that, note that PWD might be set to "symlinked"
    path instead of "real" path.

    Only return PWD instead of cwd when:

    1. PWD exists (i.e. launched from interactive shell)
    2. Contains Absolute path (sanity check)
    3. Absolute ath in PWD resolves to the same directory as cwd (process didn't call chdir after starting)
    """
    cwd = pathlib.Path(".").resolve()

    _pwd = os.environ.get("PWD")
    if _pwd is None:
        return cwd

    pwd = pathlib.Path(_pwd)
    if not pwd.is_absolute():
        return cwd

    try:
        pwd_resolved = pwd.resolve()
    except OSError:
        return cwd

    if cwd != pwd_resolved:
        return cwd

    return pwd


def normalise_path(
    p: Union[str, pathlib.Path], base: Optional[Union[str, pathlib.Path]] = None
) -> pathlib.Path:
    """Turn path into absolute path resolving any `../` and `.`

    If path is relative pre-pend `base` path to it, `base` if set should be
    an absolute path. If not set, current working directory (as seen by the
    user launching the process, including any possible symlinks) will be
    used.
    """
    if not isinstance(p, (str, pathlib.Path)):
        raise ValueError(f"p is not a Path or str: {p}")
    if not isinstance(base, (str, pathlib.Path, type(None))):
        raise ValueError(f"base is not a Path, a str, or None: {p}")

    def norm(p):
        return pathlib.Path(os.path.normpath(str(p)))

    if isinstance(p, str):
        p = pathlib.Path(p)

    if isinstance(base, str):
        base = pathlib.Path(base)

    if p.is_absolute():
        return norm(p)

    if base is None:
        base = default_base_dir()
    elif not base.is_absolute():
        raise ValueError("Expect base to be an absolute path")

    return norm(base / p)


def uri_resolve(base: str, path: Optional[str] = None) -> str:
    """
    path                  -- if path is a uri or /vsi.* style path
    Path(path).as_uri()   -- if path is absolute filename
    base/path             -- in all other cases
    """
    if not path:
        return base

    if is_vsipath(path) or is_url(path):
        return path

    p = Path(path)
    if p.is_absolute():
        return p.as_uri()

    if is_vsipath(base):
        return vsi_join(base, path)
    else:
        return urljoin(base, path)


def uri_to_local_path(local_uri: Optional[str]) -> Optional[pathlib.Path]:
    """
    Transform a URI to a platform dependent Path.

    For example on Unix:
    'file:///tmp/something.txt' -> '/tmp/something.txt'

    On Windows:
    'file:///C:/tmp/something.txt' -> 'C:\\tmp\\test.tmp'

    .. note:
        Only supports file:// schema URIs
    """
    if not local_uri:
        return None

    components = urlparse(local_uri)
    if components.scheme != "file":
        raise ValueError(
            "Only file URIs currently supported. Tried {components.scheme}"
        )

    path = url2pathname(components.path)

    if components.netloc:
        if os.name == "nt":
            path = f"//{components.netloc}{path}"
        else:
            raise ValueError("Only know how to use `netloc` urls on Windows")

    return pathlib.Path(path)


def mk_part_uri(uri: str, idx: int) -> str:
    """Appends fragment part to the uri recording index of the part"""
    return f"{uri}#part={idx:d}"


def as_url(maybe_uri: str) -> str:
    if is_url(maybe_uri):
        return maybe_uri
    else:
        return pathlib.Path(maybe_uri).absolute().as_uri()


def is_absolute(url):
    """
    >>> is_absolute('LC08_L1TP_108078_20151203_20170401_01_T1.TIF')
    False
    >>> is_absolute('data/LC08_L1TP_108078_20151203_20170401_01_T1.TIF')
    False
    >>> is_absolute('/g/data/somewhere/LC08_L1TP_108078_20151203_20170401_01_T1.TIF')
    True
    >>> is_absolute('file:///g/data/v10/somewhere/LC08_L1TP_108078_20151203_20170401_01_T1.TIF')
    True
    >>> is_absolute('http://example.com/LC08_L1TP_108078_20151203_20170401_01_T1.TIF')
    True
    >>> is_absolute('tar:///g/data/v10/somewhere/dataset.tar#LC08_L1TP_108078_20151203_20170401_01_T1.TIF')
    True
    """
    location = urlparse(url)
    return bool(location.scheme or location.netloc) or os.path.isabs(location.path)


def get_part_from_uri(url):
    """
    >>> get_part_from_uri('path/to/file.tif')
    >>> get_part_from_uri('path/to/file.tif#page=2')
    >>> get_part_from_uri('path/to/file.tif#part=3')
    3
    >>> get_part_from_uri('path/to/file.tif#part=one')
    'one'
    """
    opts = dict(parse_qsl(urlparse(url).fragment))
    part = opts.get("part")
    if part is None:
        return None
    try:
        return int(part)
    except ValueError:
        return part


def register_scheme(*schemes):
    """
    Register additional uri schemes as supporting relative offsets (etc), so that band/measurement paths can be
    calculated relative to the base uri.
    """
    urllib.parse.uses_netloc.extend(schemes)
    urllib.parse.uses_relative.extend(schemes)
    urllib.parse.uses_params.extend(schemes)


# `urljoin`, that we use for relative path computation, needs to know which url
# schemes support relative offsets. By default only well known types are
# understood. So here we register more common blob store url protocols.
register_scheme(
    "s3",  # `s3://...`      -- AWS S3 Object Store
    "gs",  # `gs://...`      -- Google Cloud Storage
    "wasb",  # `wasb[s]://...` -- Windows Azure Storage Blob
    "wasbs",
    "az",
)
