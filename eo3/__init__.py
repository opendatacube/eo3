from ._version import get_versions
from .assemble import IncompleteDatasetError
from .images import GridSpec, ValidDataMethod
from .model import Eo3DatasetDocBase
from .properties import Eo3DictBase

REPO_URL = "https://github.com/GeoscienceAustralia/eo-datasets.git"

__version__ = get_versions()["version"]
del get_versions

__all__ = (
    "Eo3DatasetDocBase",
    "Eo3DictBase",
    "GridSpec",
    "IncompleteDatasetError",
    "REPO_URL",
    "ValidDataMethod",
    "__version__",
)
