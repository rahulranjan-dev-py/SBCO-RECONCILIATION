"""The portable-Windows-package builder.

The parts that decide whether the bundle works on the clerk's PC - the ._pth
rewrite that makes vendored packages visible, the renamed-interpreter entry
point with its double-click hook, and the completeness check - are tested
here without any network. The full assembly (pip vendoring + zip) runs in
the Windows CI job, which then smoke-tests the bundled runtime itself,
including the double-click autostart path.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
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


# ──────────────────────────────────────────── the double-click entry point

def test_cli_launcher_targets_the_renamed_exe():
    # %~dp0 anchors the launcher to the bundle folder: whatever Python is or
    # is not installed on the PC must never be consulted.
    assert r'"%~dp0SBCO Reconciliation.exe"' in mp.LAUNCHER_CLI
    assert "-m sbco_recon.cli" in mp.LAUNCHER_CLI
    assert "%*" in mp.LAUNCHER_CLI              # passes arguments on


def _clean_env(extra=None):
    """The host may carry SBCO_* variables; the hook must see only ours."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("SBCO_")}
    env.update(extra or {})
    return env


def _run_sitecustomize_probe(tmp_path, *, argv, exe_name, env=None):
    """Import the bundle's sitecustomize under controlled sys state.

    Exercises the hook's *gating* logic. The hook ends fire-paths with
    os._exit (a hard requirement inside `import site`), so the probe records
    the GUI call in a file and treats a post-import survival marker as proof
    the hook declined to fire. The genuine init-time path is exercised by
    the interpreter-copy tests below.
    """
    site = tmp_path / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize_probe.py").write_text(
        mp.SITECUSTOMIZE, encoding="ascii")
    gui_marker = tmp_path / "gui-called.txt"
    probe = tmp_path / "probe.py"
    probe.write_text(f"""
import sys, types
sys.argv = {argv!r}
sys.executable = {exe_name!r}
fake_cli = types.ModuleType("sbco_recon.cli")
def fake_main(args):
    open({str(gui_marker)!r}, "w").write(repr(args))
    return 0
fake_cli.main = fake_main
fake_pkg = types.ModuleType("sbco_recon")
fake_pkg.cli = fake_cli
sys.modules["sbco_recon"] = fake_pkg
sys.modules["sbco_recon.cli"] = fake_cli
sys.path.insert(0, {str(site)!r})
import sitecustomize_probe
print("SURVIVED-IMPORT")
""", encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-I", str(probe)], capture_output=True, text=True,
        env=_clean_env(env), timeout=30)
    assert result.returncode == 0, result.stderr
    return result.stdout, gui_marker.exists()


def test_hook_fires_only_on_a_bare_start_of_the_bundle_exe(tmp_path):
    out, gui = _run_sitecustomize_probe(
        tmp_path, argv=[""], exe_name="C:/x/SBCO Reconciliation.exe")
    assert gui                            # the GUI entry point was invoked
    assert "SURVIVED-IMPORT" not in out   # and the hook ended the process


@pytest.mark.parametrize("argv", [["-m", "sbco_recon.cli"], ["-c"], ["script.py"]])
def test_hook_ignores_scripted_invocations(tmp_path, argv):
    out, gui = _run_sitecustomize_probe(
        tmp_path, argv=argv, exe_name="C:/x/SBCO Reconciliation.exe")
    assert not gui and "SURVIVED-IMPORT" in out


def test_hook_ignores_a_normally_named_interpreter(tmp_path):
    out, gui = _run_sitecustomize_probe(
        tmp_path, argv=[""], exe_name="C:/x/python.exe")
    assert not gui and "SURVIVED-IMPORT" in out


def test_hook_escape_hatch(tmp_path):
    out, gui = _run_sitecustomize_probe(
        tmp_path, argv=[""], exe_name="C:/x/SBCO Reconciliation.exe",
        env={"SBCO_NO_AUTOSTART": "1"})
    assert not gui and "SURVIVED-IMPORT" in out


def test_hook_check_mode_prints_marker_instead_of_launching(tmp_path):
    out, gui = _run_sitecustomize_probe(
        tmp_path, argv=[""], exe_name="C:/x/SBCO Reconciliation.exe",
        env={"SBCO_AUTOSTART_CHECK": "1"})
    assert "SBCO-AUTOSTART-OK" in out
    assert not gui                        # marker path exits before launching


# ─────────────────────────── the hook on the REAL interpreter-init path
#
# These launch an actual interpreter, bare (no arguments), with sitecustomize
# imported by `import site` during startup - the exact context of a
# double-click. A raise of SystemExit from the hook is a *fatal* Python error
# in this context (site catches only Exception), which is precisely the class
# of defect the in-script probes above cannot see.

def _sbco_named_interpreter(tmp_path) -> Path:
    source = Path(sys.executable).resolve()
    target = tmp_path / f"sbco-probe{source.suffix}"
    shutil.copy2(source, target)
    return target


def _init_path_env(tmp_path, fake_main_body, extra=None):
    site = tmp_path / "site"
    pkg = site / "sbco_recon"
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("")
    (pkg / "cli.py").write_text(fake_main_body, encoding="utf-8")
    (site / "sitecustomize.py").write_text(mp.SITECUSTOMIZE, encoding="ascii")
    return _clean_env({"PYTHONPATH": str(site), **(extra or {})})


def test_init_path_check_mode_exits_cleanly(tmp_path):
    exe = _sbco_named_interpreter(tmp_path)
    env = _init_path_env(tmp_path, "def main(args): return 0\n",
                         {"SBCO_AUTOSTART_CHECK": "1"})
    result = subprocess.run(
        [str(exe)], capture_output=True, text=True, env=env,
        stdin=subprocess.DEVNULL, timeout=60)
    assert result.returncode == 0, result.stderr
    assert "SBCO-AUTOSTART-OK" in result.stdout
    assert "Fatal Python error" not in result.stderr
    assert "Error in sitecustomize" not in result.stderr


def test_init_path_gui_launch_exits_with_mains_code(tmp_path):
    marker = tmp_path / "gui-called.txt"
    exe = _sbco_named_interpreter(tmp_path)
    env = _init_path_env(
        tmp_path,
        f"def main(args):\n"
        f"    open({str(marker)!r}, 'w').write(repr(args))\n"
        f"    return 0\n")
    result = subprocess.run(
        [str(exe)], capture_output=True, text=True, env=env,
        stdin=subprocess.DEVNULL, timeout=60)
    assert result.returncode == 0, result.stderr
    assert marker.read_text() == "['gui']"
    assert "Fatal Python error" not in result.stderr
    assert ">>>" not in result.stdout     # never fell through to the REPL


def test_init_path_gui_failure_reports_and_exits_nonzero(tmp_path):
    exe = _sbco_named_interpreter(tmp_path)
    env = _init_path_env(
        tmp_path,
        "def main(args):\n"
        "    raise OSError('port 8765 unavailable')\n")
    result = subprocess.run(
        [str(exe)], capture_output=True, text=True, env=env,
        stdin=subprocess.DEVNULL, timeout=60)
    assert result.returncode == 1
    assert "could not start" in result.stderr
    assert "port 8765 unavailable" in result.stderr
    # never the swallowed-by-site one-liner, never a REPL
    assert "Error in sitecustomize" not in result.stderr
    assert ">>>" not in result.stdout


def test_bundle_readme_is_plain_ascii():
    text = mp.BUNDLE_README.format(version="9.9.9")
    text.encode("ascii")                        # Notepad-safe on any Windows
    assert "double-click" in text.lower()
    assert "not in this folder" in text.lower() # where the data lives
    assert "Unblock" in text                    # the mark-of-the-web recovery


def test_runtime_zip_verification_rejects_wrong_hash(tmp_path, monkeypatch):
    payload = tmp_path / "runtime.zip"
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("python.exe", b"MZ")
    monkeypatch.setattr(mp, "EXPECTED_SHA256", "0" * 64)
    with pytest.raises(SystemExit, match="hash mismatch"):
        mp.verify_runtime_zip(payload)


def test_install_runtime_renames_exe_and_preserves_psf_licence(tmp_path):
    payload = tmp_path / "runtime.zip"
    with zipfile.ZipFile(payload, "w") as zf:
        zf.writestr("python.exe", b"MZ")
        zf.writestr("python312.dll", b"MZ")
        zf.writestr("python312._pth", "python312.zip\n.\n#import site\n")
        zf.writestr("LICENSE.txt", "PSF LICENSE")
    bundle = tmp_path / "bundle"
    mp.install_runtime(payload, bundle)
    assert (bundle / mp.APP_EXE).read_bytes() == b"MZ"
    assert not (bundle / "python.exe").exists()
    assert (bundle / "PYTHON-LICENSE.txt").read_text() == "PSF LICENSE"
    assert not (bundle / "LICENSE.txt").exists()   # ours is written later


# ───────────────────────────────────────────────────── completeness check

def make_fake_bundle(tmp_path) -> Path:
    bundle = tmp_path / "bundle"
    site = bundle / "Lib" / "site-packages"
    for rel in ("sbco_recon/cli.py", "sbco_recon/refdata/account_codes.json",
                "sbco_recon/webapp/static/index.html", "openpyxl/__init__.py",
                "xlrd/__init__.py", "pyxlsb/__init__.py"):
        target = site / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("x")
    (site / "sitecustomize.py").write_text(mp.SITECUSTOMIZE)
    (bundle / mp.APP_EXE).write_bytes(b"MZ")
    (bundle / "python312.dll").write_bytes(b"MZ")
    (bundle / "python312._pth").write_text(
        "python312.zip\n.\nLib\\site-packages\nimport site\n")
    (bundle / "sbco.bat").write_text(mp.LAUNCHER_CLI)
    (bundle / "README.txt").write_text("x")
    (bundle / "LICENSE.txt").write_text("MIT License")
    (bundle / "PYTHON-LICENSE.txt").write_text("PSF License")
    return bundle


def test_check_bundle_accepts_a_complete_bundle(tmp_path):
    mp.check_bundle(make_fake_bundle(tmp_path))


def test_check_bundle_names_whats_missing(tmp_path):
    bundle = make_fake_bundle(tmp_path)
    (bundle / "Lib" / "site-packages" / "sbco_recon"
     / "refdata" / "account_codes.json").unlink()
    with pytest.raises(SystemExit, match="account_codes.json"):
        mp.check_bundle(bundle)


def test_check_bundle_rejects_a_leftover_python_exe(tmp_path):
    bundle = make_fake_bundle(tmp_path)
    (bundle / "python.exe").write_bytes(b"MZ")
    with pytest.raises(SystemExit, match="rename"):
        mp.check_bundle(bundle)


def test_check_bundle_requires_the_hook_and_import_site(tmp_path):
    bundle = make_fake_bundle(tmp_path)
    (bundle / "Lib" / "site-packages" / "sitecustomize.py").unlink()
    with pytest.raises(SystemExit, match="sitecustomize"):
        mp.check_bundle(bundle)

    bundle2 = make_fake_bundle(tmp_path / "b2")
    (bundle2 / "python312._pth").write_text("python312.zip\n.\nLib\\site-packages\n")
    with pytest.raises(SystemExit, match="import site"):
        mp.check_bundle(bundle2)


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
                "SBCO Reconciliation.exe") in names
