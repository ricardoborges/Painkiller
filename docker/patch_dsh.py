"""Work around the duplicate koffi struct types in dsh-win32-process on Linux.

The three replacements open and close two try/catch blocks between them, so
they only make sense together: applying a subset leaves broken JavaScript.
Each file is patched all-or-nothing, and the output says what really happened.
"""

import glob
import sys

REPLACEMENTS = [
    (
        'const STARTUPINFOW = koffi.struct("DSH_STARTUPINFOW",',
        'let STARTUPINFOW; try { STARTUPINFOW = koffi.struct("DSH_STARTUPINFOW",',
    ),
    (
        'const PROCESS_INFORMATION = koffi.struct("DSH_PROCESS_INFORMATION",',
        '} catch { STARTUPINFOW = { size: 104 }; }\n'
        'let PROCESS_INFORMATION; try { PROCESS_INFORMATION = koffi.struct("DSH_PROCESS_INFORMATION",',
    ),
    (
        'if (PROCESS_INFORMATION.size !== 24)',
        '} catch { PROCESS_INFORMATION = { size: 24 }; }\nif (PROCESS_INFORMATION.size !== 24)',
    ),
]


def patch_file(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()

    if REPLACEMENTS[0][1] in source:
        return "already patched"
    found = [old in source for old, _ in REPLACEMENTS]
    if not any(found):
        return "pattern not found (upstream changed?), left untouched"
    if not all(found):
        missing = [old for (old, _), ok in zip(REPLACEMENTS, found) if not ok]
        raise SystemExit(f"{path}: only part of the patch matches, missing {missing}; aborting")

    for old, new in REPLACEMENTS:
        source = source.replace(old, new, 1)
    with open(path, "w", encoding="utf-8") as f:
        f.write(source)
    return "patched"


def main() -> None:
    paths = glob.glob("/usr/local/lib/node_modules/**/dsh-win32-process/lib/index.js", recursive=True)
    if not paths:
        print("Warning: no dsh-win32-process files found to patch")
        return
    for path in paths:
        print(f"{path}: {patch_file(path)}")


if __name__ == "__main__":
    main()
    sys.exit(0)
