"""The portable-Windows-package builder.

The parts that decide whether the bundle works on the clerk's PC - the ._pth
rewrite that makes vendored packages visible, the launcher wiring, and the
completeness check - are tested here without any network. The full assembly
(pip vendoring + zip) runs in the Windows CI job, which then smoke-tests the
bundled runtime itself.
"""

from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "make_portable",
    Path(__file__).resolve().parents[1] / "packaging" / "make_portable.py")
mp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mp)


# ─────────────────────────────────────────────────────────── ._pth rewrite

def write_pth(tmp_path, text, name="python312._pth"):
    runtime = tmp_path / "runtime"
    runtime.mkdir(exist_ok=True)
    (runtime / name).write_text(text, encoding="utf-8")
    return runtime


def test_pth_gains_site_packages_and_import_site(tmp_path):
    # verbatim content of the real embeddable build's ._pth
    runtime = write_pth(tmp_path,
                        "python312.zip\n.\n\n"
                        "# Uncomment to run site.main() automatically\n"
                        "#import site\n")
    pth = mp.rewrite_pth(runtime)
    lines = pth.read_text(encoding="utf-8").splitlines()
    assert lines == ["python312.zip", ".", r"Lib\site-packages", "import site"]


def test_pth_rewrite_is_idempotent(tmp_path):
    runtime = write_pth(tmp_path, "python312.zip\n.\n#import site\n")
    mp.rewrite_pth(runtime)
    first = (runtime / "python312._pth").read_text(encoding="utf-8")
    mp.rewrite_pth(runtime)
    assert (runtime / "python312._pth").read_text(encoding="utf-8") == first


def test_pth_missing_or_ambiguous_fails(tmp_path):
    empty = tmp_path / "runtime"
    empty.mkdir()
    with pytest.raises(SystemExit, match="_pth"):
        mp.rewrite_pth(empty)
    write_pth(tmp_path, "x\n")
    write_pth(tmp_path, "x\n", name="python313._pth")
    with pytest.raises(SystemExit, match="_pth"):
        mp.rewrite_pth(tmp_path / "runtime")


# ─────────────────────────────────────────────────── launchers and runtime

def test_launchers_use_the_bundled_runtime_only():
    # %~dp0 anchors both launchers to the bundle folder: whatever Python is or
    # is not installed on the PC must never be consulted.
    for launcher in (mp.LAUNCHER_GUI, mp.LAUNCHER_CLI):
        assert r"%~dp0runtime\python.exe" in launcher
        assert "py -3" not in launcher and "where " not in launcher
    assert "-m sbco_recon.cli gui" in mp.LAUNCHER_GUI
    assert "doctor" in mp.LAUNCHER_GUI          # failure path self-diagnoses
    assert "%*" in mp.LAUNCHER_CLI              # CLI form passes arguments on


def test_bundle_readme_is_plain_ascii():
    text = mp.BUNDLE_README.format(version="9.9.9")
    text.encode("ascii")                        # Notepad-safe on any Windows
    assert "double-click" in text.lower()
    assert "not in this folder" in text.lower() # where the data lives


def test_runtime_zip_verification_rejects_wrong_hash(tmp_path, monkeypatch):
    payload = tmp_path / "runtime.zip"
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("python.exe", b"MZ")
    monkeypatch.setattr(mp, "EXPECTED_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="hash mismatch"):
        mp.verify_runtime_zip(payload)


# ───────────────────────────────────────────────────── completeness check

def make_fake_bundle(tmp_path) -> Path:
    bundle = tmp_path / "bundle"
    site = bundle / "runtime" / "Lib" / "site-packages"
    for rel in ("sbco_recon/cli.py", "sbco_recon/refdata/account_codes.json",
                "sbco_recon/webapp/static/index.html", "openpyxl/__init__.py",
                "xlrd/__init__.py", "pyxlsb/__init__.py"):
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
    (bundle / "runtime" / "python.exe").write_bytes(b"MZ")
    (bundle / "runtime" / "python312._pth").write_text(
        "python312.zip\n.\nLib\\site-packages\nimport site\n")
    (bundle / "SBCO Reconciliation.bat").write_text(mp.LAUNCHER_GUI)
    (bundle / "sbco.bat").write_text(mp.LAUNCHER_CLI)
    (bundle / "README.txt").write_text("x")
    (bundle / "LICENSE.txt").write_text("MIT License")
    return bundle


def test_check_bundle_accepts_a_complete_bundle(tmp_path):
    mp.check_bundle(make_fake_bundle(tmp_path))


def test_check_bundle_names_whats_missing(tmp_path):
    bundle = make_fake_bundle(tmp_path)
    (bundle / "runtime" / "Lib" / "site-packages" / "sbco_recon"
     / "refdata" / "account_codes.json").unlink()
    with pytest.raises(SystemExit, match="account_codes.json"):
        mp.check_bundle(bundle)


def test_zip_bundle_writes_checksums(tmp_path):
    bundle = make_fake_bundle(tmp_path)
    out = tmp_path / "dist"
    target = mp.zip_bundle(bundle, out, "9.9.9")
    assert target.name == "SBCO-Reconciliation-9.9.9-windows-x64.zip"
    sums = (out / "SHA256SUMS.txt").read_text()
    assert target.name in sums
    assert sums.split()[0] == mp.sha256(target)
    with zipfile.ZipFile(target) as zf:
        names = zf.namelist()
        # everything sits under one versioned top folder, ready to extract
        assert all(n.startswith("SBCO-Reconciliation-9.9.9-windows-x64/")
                   for n in names)
        assert ("SBCO-Reconciliation-9.9.9-windows-x64/"
                "SBCO Reconciliation.bat") in names
