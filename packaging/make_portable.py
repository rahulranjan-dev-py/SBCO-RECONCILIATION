"""Build the portable Windows package.

Produces a folder a clerk can extract anywhere and double-click - no
installer, no admin rights, no Python on the PC, nothing added to PATH.
The runtime inside is python.org's official *embeddable* build of CPython,
unmodified; every dependency is pure Python, so the bundle assembles
deterministically on any OS (the usual place is the Windows CI job, but a
Linux or macOS machine builds an identical zip).

The entry point is the (renamed) Python interpreter itself - "SBCO
Reconciliation.exe" - not a .bat script. This matters on managed Windows:

- Smart App Control (default-on for new Windows 11 machines) blocks
  internet-downloaded .bat/.cmd scripts outright, with no "run anyway"
  option. It allows reputably signed executables - and python.exe carries
  the Python Software Foundation's Authenticode signature, which survives
  renaming (the signature covers content, not the file name).
- Single-file freezers (PyInstaller and friends) self-extract at launch and
  are routinely quarantined by departmental antivirus policy; a folder of
  plain files around a signed interpreter is not.

Double-clicking the exe starts the GUI through a guarded sitecustomize hook:
the embeddable runtime's ._pth runs `import site`, site imports
sitecustomize, and the hook launches the application only for a bare
interactive start (sys.argv == ['']) of an exe named sbco* - verified
signatures for a double-click and nothing else. Every scripted invocation
(-m, -c, a script path) passes through untouched, and SBCO_NO_AUTOSTART=1
is the escape hatch.

Why the runtime files sit at the bundle root: the interpreter looks for its
python3xx.dll and ._pth beside itself, so the renamed exe must live among
them. Upgrading is replacing the folder - the database lives in the user
profile (%LOCALAPPDATA%\\SBCO), which is also why re-extracting cannot touch
anyone's data.

Usage:
    python packaging/make_portable.py                    # download + build
    python packaging/make_portable.py --runtime-zip P    # use a local copy
    python packaging/make_portable.py --out dist

The embeddable runtime is pinned by version and SHA-256. If the pin below is
empty the builder still verifies the download is a well-formed zip, prints the
hash it computed, and tells you to pin it.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

PYTHON_VERSION = "3.12.8"
ARCH = "amd64"
DOWNLOAD_URL = ("https://www.python.org/ftp/python/{v}/python-{v}-embed-{a}.zip")

# SHA-256 of python-{PYTHON_VERSION}-embed-{ARCH}.zip, as computed from the
# first trusted download (CI run #1 fetching directly from python.org over
# TLS). Any different download aborts the build. Re-pin when PYTHON_VERSION
# changes.
EXPECTED_SHA256 = "8d3f33be9eb810f23c102f08475af2854e50484b8e4e06275e937be61ce3d2fb"

APP_EXE = "SBCO Reconciliation.exe"

ROOT = Path(__file__).resolve().parents[1]

LAUNCHER_CLI = """\
@"%~dp0SBCO Reconciliation.exe" -m sbco_recon.cli %*
"""

SITECUSTOMIZE = '''\
"""Bundle-only startup hook (this file ships inside the portable Windows
package, never in the installed library).

The embeddable runtime's ._pth runs `import site`, which imports this
module on every interpreter start. When - and only when - the start is a
bare double-click of the bundle's own executable, it launches the
application instead of dropping the clerk into a Python prompt.

The double-click signature is exact: sys.argv == [''] happens for an
interactive start with no arguments and for nothing else (-m, -c and
script runs all differ), and the executable-name check keeps the hook
inert if this file is ever copied near a normally-named python.exe.
Set SBCO_NO_AUTOSTART=1 to disable the hook entirely.
"""

import os
import sys


def _autostart():
    if os.environ.get("SBCO_NO_AUTOSTART"):
        return
    if getattr(sys, "argv", None) not in ([], [""]):
        return
    exe = os.path.basename(getattr(sys, "executable", "") or "").lower()
    if not exe.startswith("sbco"):
        return
    if os.environ.get("SBCO_AUTOSTART_CHECK"):
        # CI proves the double-click path is wired without starting a server.
        print("SBCO-AUTOSTART-OK")
        raise SystemExit(0)
    from sbco_recon.cli import main

    raise SystemExit(main(["gui"]))


_autostart()
'''

BUNDLE_README = """\
SBCO Reconciliation Tool {version}  -  portable Windows package
================================================================

To start:  double-click "SBCO Reconciliation" (the application file).
           The tool opens in your web browser. Keep the black window
           open while you work; close it when you are finished.

Nothing is installed. This folder is the whole program - you can keep it
on the Desktop, in Documents, or on a shared drive, and you do not need
administrator rights.

Your data (loaded reports, the discrepancy register, your settings) is
kept in your Windows user profile, NOT in this folder. Deleting or
replacing this folder does not touch your data.

To upgrade:  delete this folder and extract the new one. Your data stays.

If Windows blocks something
---------------------------
Windows marks every file downloaded from the internet, and its Smart App
Control / SmartScreen features block unknown *scripts* such as .bat files.
That is why the tool starts from "SBCO Reconciliation" (a signed program),
which Windows allows. If Windows still shows a warning when you start it,
choose "More info" and then "Run anyway" - or clear the download mark
first: right-click the downloaded .zip file -> Properties -> tick
"Unblock" -> OK, and extract it again.

sbco.bat runs the same tool from a command prompt (for example:
sbco.bat doctor). Being a .bat script, it may be blocked on PCs with
Smart App Control; there, use the application file's own command form:

    "SBCO Reconciliation.exe" -m sbco_recon.cli doctor

About this package
------------------
It carries its own Python runtime - the official embeddable build from
python.org, renamed but otherwise unmodified, with its digital signature
intact. It does not use, change, or require any Python installed on the
PC. PYTHON-LICENSE.txt is the runtime's own licence; LICENSE.txt covers
this software (MIT).
"""


def app_version() -> str:
    text = (ROOT / "src" / "sbco_recon" / "__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("could not read __version__ from src/sbco_recon/__init__.py")
    return match.group(1)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 17), b""):
            digest.update(chunk)
    return digest.hexdigest()


def obtain_runtime_zip(cache: Path, local: Path | None) -> Path:
    """Download the pinned embeddable runtime, or take a local copy."""
    if local:
        if not local.is_file():
            raise SystemExit(f"--runtime-zip: {local} does not exist")
        return local

    cache.mkdir(parents=True, exist_ok=True)
    name = f"python-{PYTHON_VERSION}-embed-{ARCH}.zip"
    target = cache / name
    if not target.exists():
        url = DOWNLOAD_URL.format(v=PYTHON_VERSION, a=ARCH)
        print(f"  downloading {url}")
        import urllib.request

        with urllib.request.urlopen(url, timeout=120) as response:
            target.write_bytes(response.read())
    return target


def verify_runtime_zip(path: Path) -> None:
    digest = sha256(path)
    print(f"  runtime zip: {path.name}")
    print(f"  computed sha256: {digest}")
    if EXPECTED_SHA256:
        if digest != EXPECTED_SHA256.lower():
            raise SystemExit(
                f"runtime hash mismatch!\n  expected {EXPECTED_SHA256}\n"
                f"  got      {digest}\n  The download is not the pinned file - "
                f"do not ship it.")
        print("  matches the pinned hash")
    else:
        print("  NOTE: no hash pinned in make_portable.py - pin the value above "
              "(EXPECTED_SHA256) after confirming it against python.org")
    if not zipfile.is_zipfile(path):
        raise SystemExit(f"{path} is not a zip file")


def install_runtime(runtime_zip: Path, bundle: Path) -> None:
    """Unpack the embeddable runtime into the bundle root and rename its
    interpreter to the application name (the Authenticode signature covers
    content, not the file name, so it stays valid)."""
    bundle.mkdir(parents=True)
    with zipfile.ZipFile(runtime_zip) as zf:
        zf.extractall(bundle)

    exe = bundle / "python.exe"
    if not exe.exists():
        raise SystemExit("runtime zip did not contain python.exe")
    exe.rename(bundle / APP_EXE)

    # The runtime ships its own LICENSE.txt (the PSF licence). Keep it under
    # a distinct name so this project's LICENSE.txt does not overwrite it.
    psf_licence = bundle / "LICENSE.txt"
    if psf_licence.exists():
        psf_licence.rename(bundle / "PYTHON-LICENSE.txt")


def rewrite_pth(runtime_dir: Path) -> Path:
    """Point the embeddable runtime at Lib\\site-packages.

    The embeddable build ships pythonXY._pth with 'import site' commented out
    and no site-packages entry, so a vendored package would be invisible -
    and the sitecustomize hook depends on 'import site' running.
    """
    candidates = list(runtime_dir.glob("python*._pth"))
    if len(candidates) != 1:
        raise SystemExit(
            f"expected exactly one python*._pth in {runtime_dir}, "
            f"found {[c.name for c in candidates]}")
    pth = candidates[0]
    lines = [line.strip() for line in pth.read_text(encoding="utf-8").splitlines()]
    kept = [line for line in lines
            if line and not line.startswith("#") and line != "import site"]
    if r"Lib\site-packages" not in kept:
        kept.append(r"Lib\site-packages")
    kept.append("import site")
    pth.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return pth


def vendor_packages(site_packages: Path) -> None:
    """Install the application and its dependencies into the bundle.

    Everything is pure Python (py3-none-any wheels), which is what lets a
    Linux CI runner assemble a Windows bundle byte-for-byte.
    """
    site_packages.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable, "-m", "pip", "install",
        "--target", str(site_packages),
        "--no-compile",              # .pyc are interpreter-version-specific
        "--no-warn-script-location",
        str(ROOT),                   # sbco-recon itself (brings openpyxl)
        "xlrd>=2.0",                 # legacy BIFF .xls downloads
        "pyxlsb",                    # .xlsb workbooks
    ]
    print("  vendoring: sbco-recon, openpyxl, xlrd, pyxlsb")
    subprocess.run(command, check=True)

    # pip --target leaves scripts/metadata folders we do not ship
    for junk in ("bin", "Scripts", "__pycache__"):
        target = site_packages / junk
        if target.exists():
            shutil.rmtree(target)


def check_bundle(bundle: Path) -> None:
    """Fail the build if the assembled folder is missing anything vital."""
    site = bundle / "Lib" / "site-packages"
    required = [
        bundle / APP_EXE,
        bundle / "sbco.bat",
        bundle / "README.txt",
        bundle / "LICENSE.txt",
        site / "sitecustomize.py",
        site / "sbco_recon" / "cli.py",
        site / "sbco_recon" / "refdata" / "account_codes.json",
        site / "sbco_recon" / "webapp" / "static" / "index.html",
        site / "openpyxl" / "__init__.py",
        site / "xlrd" / "__init__.py",
        site / "pyxlsb" / "__init__.py",
    ]
    missing = [str(p.relative_to(bundle)) for p in required if not p.exists()]
    if missing:
        raise SystemExit("bundle is incomplete, missing:\n  " + "\n  ".join(missing))

    if not list(bundle.glob("python3*.dll")):
        raise SystemExit("bundle is incomplete: python3*.dll missing beside the exe")
    if (bundle / "python.exe").exists():
        raise SystemExit("bundle still contains python.exe - the rename did not happen")
    pth = list(bundle.glob("python*._pth"))
    if not pth or r"Lib\site-packages" not in pth[0].read_text(encoding="utf-8"):
        raise SystemExit("runtime ._pth does not reference Lib\\site-packages")
    if "import site" not in pth[0].read_text(encoding="utf-8"):
        raise SystemExit("runtime ._pth does not run 'import site' - "
                         "the double-click hook would never load")


def zip_bundle(bundle: Path, out_dir: Path, version: str) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    name = f"SBCO-Reconciliation-{version}-windows-x64"
    target = out_dir / f"{name}.zip"
    if target.exists():
        target.unlink()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(bundle.rglob("*")):
            if path.is_file():
                zf.write(path, Path(name) / path.relative_to(bundle))
    (out_dir / "SHA256SUMS.txt").write_text(
        f"{sha256(target)}  {target.name}\n", encoding="utf-8")
    return target


def build(out_dir: Path, runtime_zip_arg: Path | None, keep_folder: bool) -> Path:
    version = app_version()
    print(f"  building SBCO Reconciliation {version} portable package")

    staging = out_dir / "_bundle"
    if staging.exists():
        shutil.rmtree(staging)

    runtime_zip = obtain_runtime_zip(out_dir / "_cache", runtime_zip_arg)
    verify_runtime_zip(runtime_zip)
    install_runtime(runtime_zip, staging)
    rewrite_pth(staging)
    site_packages = staging / "Lib" / "site-packages"
    vendor_packages(site_packages)
    (site_packages / "sitecustomize.py").write_text(SITECUSTOMIZE, encoding="ascii")

    (staging / "sbco.bat").write_text(LAUNCHER_CLI, encoding="ascii")
    (staging / "README.txt").write_text(
        BUNDLE_README.format(version=version), encoding="ascii")
    shutil.copy2(ROOT / "LICENSE", staging / "LICENSE.txt")

    check_bundle(staging)
    target = zip_bundle(staging, out_dir, version)
    print(f"  written: {target}")
    print(f"  sha256:  {sha256(target)}")
    if not keep_folder:
        shutil.rmtree(staging)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=ROOT / "dist",
                        help="output directory (default: dist)")
    parser.add_argument("--runtime-zip", type=Path, default=None,
                        help="use this local embeddable-python zip instead of "
                             "downloading")
    parser.add_argument("--keep-folder", action="store_true",
                        help="leave the unzipped bundle folder next to the zip")
    args = parser.parse_args(argv)
    build(args.out, args.runtime_zip, args.keep_folder)
    return 0


if __name__ == "__main__":
    sys.exit(main())
