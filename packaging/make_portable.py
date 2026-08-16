"""Build the portable Windows package.

Produces a folder a clerk can extract anywhere and double-click - no
installer, no admin rights, no Python on the PC, nothing added to PATH.
The runtime inside is python.org's official *embeddable* build of CPython,
unmodified; every dependency is pure Python, so the bundle assembles
deterministically on any OS (the usual place is the Windows CI job, but a
Linux or macOS machine builds an identical zip).

Why a portable folder and not a single .exe: freezers like PyInstaller
self-extract at launch and are routinely quarantined by the antivirus policy
on departmental PCs; a plain folder of files with Microsoft-signed python.exe
inside is not. Upgrading is replacing the folder - the database lives in the
user profile (%LOCALAPPDATA%\\SBCO), which is also why re-extracting cannot
touch anyone's data.

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

# SHA-256 of python-{PYTHON_VERSION}-embed-{ARCH}.zip. Set from a build log's
# "computed sha256" line (or python.org's published hashes) after the first
# trusted download; once set, any different download aborts the build.
EXPECTED_SHA256 = ""

ROOT = Path(__file__).resolve().parents[1]

LAUNCHER_GUI = """\
@echo off
setlocal
title SBCO Reconciliation Tool
echo.
echo   Starting the SBCO Reconciliation Tool...
echo   Your browser will open in a moment.
echo.
echo   Keep this window open while you work. Close it when you are finished.
echo   Your data is kept in your user folder, not in this program folder,
echo   so replacing this folder to upgrade will not touch it.
echo.
"%~dp0runtime\\python.exe" -m sbco_recon.cli gui
if errorlevel 1 (
  echo.
  echo   The tool stopped with an error. Running a check to find out why...
  echo.
  "%~dp0runtime\\python.exe" -m sbco_recon.cli doctor
  pause
)
endlocal
"""

LAUNCHER_CLI = """\
@"%~dp0runtime\\python.exe" -m sbco_recon.cli %*
"""

BUNDLE_README = """\
SBCO Reconciliation Tool {version}  -  portable Windows package
================================================================

To start:  double-click "SBCO Reconciliation.bat".
           The tool opens in your web browser. Keep the black window
           open while you work; close it when you are finished.

Nothing is installed. This folder is the whole program - you can keep it
on the Desktop, in Documents, or on a shared drive, and you do not need
administrator rights.

Your data (loaded reports, the discrepancy register, your settings) is
kept in your Windows user profile, NOT in this folder. Deleting or
replacing this folder does not touch your data.

To upgrade:  delete this folder and extract the new one. Your data stays.

Command line:  "sbco.bat" runs the same tool from a command prompt,
e.g.   sbco.bat doctor
       sbco.bat reconcile --month Jul-2026

This package carries its own Python runtime (the official embeddable
build from python.org) in the "runtime" folder. It does not use, change,
or require any Python installed on the PC.
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


def extract_runtime(runtime_zip: Path, runtime_dir: Path) -> None:
    runtime_dir.mkdir(parents=True)
    with zipfile.ZipFile(runtime_zip) as zf:
        zf.extractall(runtime_dir)


def rewrite_pth(runtime_dir: Path) -> Path:
    """Point the embeddable runtime at Lib\\site-packages.

    The embeddable build ships pythonXY._pth with 'import site' commented out
    and no site-packages entry, so a vendored package would be invisible.
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
    site = bundle / "runtime" / "Lib" / "site-packages"
    required = [
        bundle / "SBCO Reconciliation.bat",
        bundle / "sbco.bat",
        bundle / "README.txt",
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

    runtime = bundle / "runtime"
    if not (runtime / "python.exe").exists():
        raise SystemExit("bundle is incomplete: runtime/python.exe missing")
    pth = list(runtime.glob("python*._pth"))
    if not pth or r"Lib\site-packages" not in pth[0].read_text(encoding="utf-8"):
        raise SystemExit("runtime ._pth does not reference Lib\\site-packages")


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
    extract_runtime(runtime_zip, staging / "runtime")
    rewrite_pth(staging / "runtime")
    vendor_packages(staging / "runtime" / "Lib" / "site-packages")

    (staging / "SBCO Reconciliation.bat").write_text(LAUNCHER_GUI, encoding="ascii")
    (staging / "sbco.bat").write_text(LAUNCHER_CLI, encoding="ascii")
    (staging / "README.txt").write_text(
        BUNDLE_README.format(version=version), encoding="ascii")

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
