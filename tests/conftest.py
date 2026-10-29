"""Expose the repository root as the package `custom_components.shopping_sync`.

The integration lives in the repository root (HACS `content_in_root`), so tests
register the root directory under the import name Home Assistant would use.
The root `__init__.py` is not executed: the pure core needs no Home Assistant.
"""

import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

namespace = types.ModuleType("custom_components")
namespace.__path__ = []
package = types.ModuleType("custom_components.shopping_sync")
package.__path__ = [str(ROOT)]
namespace.shopping_sync = package
sys.modules.setdefault("custom_components", namespace)
sys.modules.setdefault("custom_components.shopping_sync", package)
