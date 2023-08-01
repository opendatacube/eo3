from ._version import get_versions
from .images import GridSpec, ValidDataMethod
from .model import DatasetDocBase
from .properties import Eo3DictBase

REPO_URL = "https://github.com/GeoscienceAustralia/eo-datasets.git"

__version__ = get_versions()["version"]
del get_versions

__all__ = (
    "DatasetDocBase",
    "Eo3DictBase",
    "GridSpec",
    "REPO_URL",
    "ValidDataMethod",
    "__version__",
)
