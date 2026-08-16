# Windows packaging

`make_portable.py` builds the thing end users actually receive: a zip that
extracts to a folder and runs by double-click, with no installer, no admin
rights, and no Python on the PC.

```
SBCO-Reconciliation-<version>-windows-x64/
  SBCO Reconciliation.exe     <- double-click this: python.org's interpreter,
                                 renamed, PSF Authenticode signature intact
  python312.dll, *.pyd, ...   <- the embeddable runtime, beside its exe
  python312._pth              <- adds Lib\site-packages, runs `import site`
  Lib/site-packages/          <- sbco_recon + openpyxl + xlrd + pyxlsb,
                                 plus the sitecustomize double-click hook
  sbco.bat                    <- command-line form (see the SAC note below)
  README.txt                  <- plain-language notes for the clerk
  LICENSE.txt                 <- this software (MIT)
  PYTHON-LICENSE.txt          <- the runtime's own licence (PSF)
```

## Why this shape

- **Smart App Control.** Field testing on a new Windows 11 laptop showed SAC
  hard-blocks internet-downloaded `.bat` files — no "run anyway" offered. It
  allows reputably signed executables, and the PSF-signed interpreter stays
  validly signed after renaming (Authenticode covers content, not the file
  name). So the signed interpreter *is* the entry point: a guarded
  `sitecustomize` hook starts the GUI only on a bare double-click
  (`sys.argv == ['']` of an sbco-named exe). `-m`/`-c`/script invocations
  pass through untouched; `SBCO_NO_AUTOSTART=1` disables the hook.
- **No antivirus quarantine.** Single-file freezers (PyInstaller and
  friends) self-extract at launch and are routinely flagged by endpoint
  policies. This bundle is plain files around a signed `python.exe`.
- **No admin rights.** Departmental PCs rarely grant them. Extracting a
  folder needs none.
- **Upgrades cannot destroy data.** The database lives in
  `%LOCALAPPDATA%\SBCO`, never in the program folder, so "delete the folder,
  extract the new one" is the whole upgrade procedure.
- **Deterministic.** Every dependency is pure Python (`py3-none-any`
  wheels), so the same bundle assembles on a Windows, Linux or macOS
  builder. The runtime files sit at the bundle root because the interpreter
  resolves its DLL and `._pth` beside its own executable.

## Building

```bash
python packaging/make_portable.py            # downloads the pinned runtime
python packaging/make_portable.py --runtime-zip path/to/python-3.12.8-embed-amd64.zip
```

Output lands in `dist/`: the zip plus `SHA256SUMS.txt`. Pass `--keep-folder`
to also keep the unzipped bundle for inspection.

The embeddable runtime is pinned by version (`PYTHON_VERSION`) and SHA-256
(`EXPECTED_SHA256`) in `make_portable.py`; a download that does not match the
pin aborts the build. Re-pin when the version changes.

## CI

`.github/workflows/windows.yml` runs the test suite on `windows-latest`
(normal and `-O`), builds the package, and then smoke-tests the **bundled**
runtime — verifies the renamed exe's Authenticode signature is still valid,
exercises the double-click autostart path (`SBCO_AUTOSTART_CHECK=1`), and
runs doctor, a file load, a reconciliation, a register entry and a Table-3
export through `SBCO Reconciliation.exe` itself, never the runner's Python.
The zip is uploaded as a build artifact on every push, and attached to the
GitHub release when a `v*` tag is pushed or the workflow is dispatched with
a `release_tag`.
