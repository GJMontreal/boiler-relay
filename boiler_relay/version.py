import logging
from json import load
from pathlib import Path

log = logging.getLogger(__name__)

__version__ = "0.1.2"

BUILD_INFO = Path(__file__).resolve().parent.parent / "build_info.json"
UNKNOWN = "unknown"


def read_commit(path=BUILD_INFO):
    try:
        with open(path, "r") as file:
            commit = load(file)["commit"]
    except FileNotFoundError:
        return UNKNOWN
    except (OSError, ValueError, KeyError, TypeError) as error:
        log.warning("cannot read the commit from %s: %s", path, error)
        return UNKNOWN
    return commit if isinstance(commit, str) and commit else UNKNOWN


def describe(path=BUILD_INFO):
    return f"boiler_relay {__version__} ({read_commit(path)})"
