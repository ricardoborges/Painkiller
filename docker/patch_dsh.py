import glob
import sys

def main():
    paths = glob.glob("/usr/local/lib/node_modules/**/dsh-win32-process/lib/index.js", recursive=True)
    if not paths:
        print("Warning: no dsh-win32-process files found to patch")
        return

    for p in paths:
        with open(p, "r", encoding="utf-8") as f:
            s = f.read()

        s = s.replace(
            'const STARTUPINFOW = koffi.struct("DSH_STARTUPINFOW",',
            'let STARTUPINFOW; try { STARTUPINFOW = koffi.struct("DSH_STARTUPINFOW",',
        )
        s = s.replace(
            'const PROCESS_INFORMATION = koffi.struct("DSH_PROCESS_INFORMATION",',
            '} catch { STARTUPINFOW = { size: 104 }; }\nlet PROCESS_INFORMATION; try { PROCESS_INFORMATION = koffi.struct("DSH_PROCESS_INFORMATION",',
        )
        s = s.replace(
            'if (PROCESS_INFORMATION.size !== 24)',
            '} catch { PROCESS_INFORMATION = { size: 24 }; }\nif (PROCESS_INFORMATION.size !== 24)',
        )

        with open(p, "w", encoding="utf-8") as f:
            f.write(s)
        print(f"Successfully patched {p}")

if __name__ == "__main__":
    main()
