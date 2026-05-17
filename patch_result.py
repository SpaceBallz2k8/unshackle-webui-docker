"""
patch_result.py

Fixes a bug in unshackle dev branch where download_manager.py calls
dl.result() without the `no_proxy_download` argument.

Patches the file directly by path — no module import needed.
"""
import sys
from pathlib import Path

# Unshackle is cloned to /unshackle during Docker build
DOWNLOAD_MANAGER = Path("/unshackle/unshackle/core/api/download_manager.py")


def patch_download_manager() -> bool:
    if not DOWNLOAD_MANAGER.exists():
        print(f"[patch] Not found: {DOWNLOAD_MANAGER}", file=sys.stderr)
        return False

    src = DOWNLOAD_MANAGER.read_text()

    if "no_proxy_download" in src:
        print(f"[patch] Already patched — no_proxy_download present in {DOWNLOAD_MANAGER}")
        return False

    old = '                no_proxy=params.get("no_proxy", False),\n                no_folder'
    new = '                no_proxy=params.get("no_proxy", False),\n                no_proxy_download=params.get("no_proxy_download", False),\n                no_folder'

    if old not in src:
        print(f"[patch] Insertion point not found in {DOWNLOAD_MANAGER}", file=sys.stderr)
        return False

    DOWNLOAD_MANAGER.write_text(src.replace(old, new))
    print(f"[patch] Applied no_proxy_download fix to {DOWNLOAD_MANAGER}")
    return True


if __name__ == "__main__":
    patch_download_manager()
