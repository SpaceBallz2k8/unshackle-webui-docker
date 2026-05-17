"""
strip_vaults.py — sanitises unshackle.yaml before the app reads it.
1. Removes key_vaults section (vault plugins don't load in this install)
2. Rewrites all relative directory paths to absolute /config/* paths
   so unshackle doesn't scatter files all over /app
"""
import sys
import re


def fix_directories(text: str) -> str:
    """
    Replace relative directory values with absolute /config/* paths.
    Also ensure downloads points to /downloads.
    """
    # Map of yaml key (lowercase) -> absolute path inside container
    DIR_MAP = {
        "cache":     "/config/Cache",
        "cookies":   "/config/Cookies",
        "dcsl":      "/config/DCSL",
        "logs":      "/config/Logs",
        "temp":      "/config/Temp",
        "wvds":      "/config/WVDs",
        "prds":      "/config/PRDs",
        "vaults":    "/config/vaults",
        "downloads": "/downloads",
    }

    lines = text.splitlines(keepends=True)
    out = []
    in_directories = False

    for line in lines:
        # Detect entering/leaving the directories: block
        if re.match(r'^directories\s*:', line):
            in_directories = True
            out.append(line)
            continue
        if in_directories:
            # Leave block when we hit another top-level key
            if line and not line[0].isspace() and not line.startswith('#'):
                in_directories = False
                out.append(line)
                continue
            # Match "  key: value" lines inside the block
            m = re.match(r'^(\s+)(\w+)\s*:\s*(.+)$', line)
            if m:
                indent, key, val = m.group(1), m.group(2).lower(), m.group(3).strip()
                # Skip services list entries and already-absolute paths
                if key in DIR_MAP and not val.startswith('/'):
                    out.append(f"{indent}{m.group(2)}: {DIR_MAP[key]}\n")
                    continue
                elif key in DIR_MAP and val.startswith('/') and key == 'downloads':
                    # Always force downloads to /downloads
                    out.append(f"{indent}{m.group(2)}: /downloads\n")
                    continue
            out.append(line)
            continue
        out.append(line)

    return "".join(out)


def strip_key_vaults(text: str) -> str:
    """Remove the key_vaults: block entirely."""
    lines = text.splitlines(keepends=True)
    out = []
    skipping = False
    for line in lines:
        if re.match(r'^key_vaults\s*:', line):
            skipping = True
            out.append("# key_vaults removed — vault plugins unavailable in container\n")
            continue
        if skipping:
            if line and not line[0].isspace() and not line.startswith('#') and not line.startswith('-'):
                skipping = False
            else:
                continue
        out.append(line)
    return "".join(out)


if __name__ == "__main__":
    path = sys.argv[1]
    with open(path, "r") as f:
        content = f.read()

    content = strip_key_vaults(content)
    content = fix_directories(content)

    with open(path, "w") as f:
        f.write(content)

    print(f"[strip_vaults] Sanitised: {path}")
