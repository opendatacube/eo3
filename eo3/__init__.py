from ._version import get_versions
from .model import DatasetMetadata

REPO_URL = "https://github.com/opendatacube/eo3.git"

__version__ = get_versions()["version"]
del get_versions

__all__ = (
    "DatasetMetadata",
    "REPO_URL",
    "__version__",
)
