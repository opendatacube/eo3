from ._version import get_versions
from .fields import Range
from .model import DatasetMetadata

REPO_URL = "https://github.com/opendatacube/eo3.git"

__version__ = get_versions()["version"]
del get_versions

__all__ = (
    "DatasetMetadata",
    "Range",
    "REPO_URL",
    "__version__",
)
