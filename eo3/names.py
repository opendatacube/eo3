from pathlib import Path
from urllib.parse import unquote, urlparse

from eo3.model import Location
from eo3.uris import is_url, is_vsipath, normalise_path, register_scheme

# Needed when packaging zip or tar files.
register_scheme("zip", "tar")


def _strip_major_version(version: str) -> str:
    """
    >>> _strip_major_version('1.2.3')
    '2.3'
    >>> _strip_major_version('01.02.03')
    '02.03'
    >>> _strip_major_version('30.40')
    '40'
    >>> _strip_major_version('40')
    ''
    """
    return ".".join(version.split(".")[1:])


class MissingRequiredFields(ValueError):
    ...


def resolve_location(path: Location) -> str:
    """
    Make sure a dataset location is a URL, suitable to be
    the dataset_location in datacube indexing.

    Users may specify a pathlib.Path(), and we'll convert it as needed.
    """
    if isinstance(path, str):
        if not is_url(path) and not is_vsipath(path):
            raise ValueError(
                "A string location is expected to be a URL or VSI path. "
                "Perhaps you want to give it as a local pathlib.Path()?"
            )
        return path

    path = normalise_path(path)
    if ".tar" in path.suffixes:
        return f"tar:{path}!/"
    elif ".zip" in path.suffixes:
        return f"zip:{path}!/"
    else:
        uri = unquote(path.as_uri())
        # Base paths specified as directories must end in a slash,
        # so they will be url joined as subfolders. (pathlib strips them)
        if path.is_dir():
            return f"{uri}/"
        return uri


def _as_path(url: str) -> Path:
    """Try to convert the given URL to a local Path"""
    parts = urlparse(url)
    if not parts.scheme == "file":
        raise ValueError(f"Expected a filesystem path, got a URL! {url!r}")

    return Path(parts.path)
