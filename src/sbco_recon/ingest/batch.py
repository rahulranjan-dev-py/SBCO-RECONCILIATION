"""Batch loader.

The legacy batch routine could lose a file without telling anyone: its own
saved Processing Summary reported 3 files selected, 2 processed and 0 failed.
The counters disagreed because the total came from UBound(FilePaths) in one
place and UBound(FilePaths) + 1 in another, and the single-file path rebuilt
the array 0-based so one file reported as zero.

Here every submitted path produces exactly one FileOutcome, and the runner
asserts that before returning. A file cannot vanish.
"""

from __future__ import annotations

from pathlib import Path

from ..errors import FileRejected, ReconError
from ..model import FileOutcome, Source
from ..store import Store, file_digest
from .detect import ReportKind, detect_kind
from .parse import parse_entries, parse_offices
from .reader import read_rows


def load_one(store: Store, path, *, allow_duplicate: bool = False) -> FileOutcome:
    """Load a single file. Never raises for data problems - returns an outcome."""
    p = Path(path)
    try:
        digest = file_digest(p) if p.exists() else ""
    except OSError as exc:
        return FileOutcome(str(p), "failed", "could not read file", str(exc))

    try:
        rows = read_rows(p)
        detection = detect_kind(rows)

        if detection.kind is ReportKind.OFFICE_MASTER:
            offices = parse_offices(rows, detection, p)
            # QA-10: this wipes the existing list. Say so plainly, and say what
            # changed - it used to report a bare "OK" indistinguishable from a
            # routine upload, with no way to undo it.
            previous = {o.office_id for o in store.offices()}
            incoming = {o.office_id for o in offices}
            store.replace_offices(offices)
            removed, added = previous - incoming, incoming - previous
            detail = f"{len(offices)} offices"
            if previous:
                detail += (f"; replaced the previous list of {len(previous)}"
                           f" ({len(added)} added, {len(removed)} removed)")
            return FileOutcome(str(p), "loaded", "office list", detail,
                               len(offices), None, digest)

        if not detection.ok:
            return FileOutcome(str(p), "rejected", "unrecognised report",
                               detection.reason, sha256=digest)

        if not allow_duplicate:
            existing = store.find_batch_by_digest(digest, detection.source)
            if existing:
                return FileOutcome(
                    str(p), "duplicate",
                    f"identical file already loaded as batch {existing['id']}",
                    f"on {existing['loaded_at']}", 0, existing["id"], digest)

        entries, warnings = parse_entries(rows, detection, p)

        # The legacy tool's date guard ('Duplicate Found: UPLOAD RESTRICTED'):
        # a day already held for this source is refused even when the bytes
        # differ - a re-downloaded Finacle report carries a fresh run stamp,
        # and loading it twice would double every figure. Accounting Details
        # files cover one account code over a range, so they key on (date, code).
        if not allow_duplicate:
            clash = _already_loaded(store, detection.source, entries)
            if clash:
                return FileOutcome(str(p), "duplicate", clash[0], clash[1],
                                   sha256=digest)

        try:
            batch_id = store.add_batch(detection.source, p, digest, entries)
        except Store.Duplicate as dup:
            return FileOutcome(str(p), "duplicate",
                               f"identical file already loaded as batch {dup.batch_id}",
                               f"on {dup.loaded_at}", 0, dup.batch_id, digest)
        return FileOutcome(str(p), "loaded", detection.kind.value,
                           "; ".join(warnings), len(entries), batch_id, digest)

    except FileRejected as exc:
        return FileOutcome(str(p), "rejected", exc.reason, exc.detail, sha256=digest)
    except ReconError as exc:
        return FileOutcome(str(p), "failed", "processing error", str(exc), sha256=digest)
    except Exception as exc:  # noqa: BLE001 - an unexpected fault is still an outcome
        return FileOutcome(str(p), "failed", "unexpected error",
                           f"{type(exc).__name__}: {exc}", sha256=digest)


def _already_loaded(store: Store, source: Source, entries) -> tuple:
    """('reason', 'detail') when the store already holds any of these
    (date, account code) pairs for this source, else ().

    The legacy tool refused a whole date ('Duplicate Found: UPLOAD
    RESTRICTED'). Keying on the account code as well keeps that protection
    for a re-downloaded report (same codes, fresh run stamp) while letting a
    second file that carries *other* codes for the same day load normally.
    """
    held = store.loaded_date_codes(
        source, {(e.txn_date, e.account_code) for e in entries})
    if not held:
        return ()
    days = sorted({d for d, _ in held})
    codes = sorted({c for _, c in held})
    batches = sorted(set(held.values()))
    span = f"{days[0]:%d-%m-%Y}" + (f" to {days[-1]:%d-%m-%Y}" if len(days) > 1 else "")
    if source is Source.APT_DETAILS or len(codes) <= 3:
        what = f"A/c {', '.join(codes)}"
    else:
        what = f"{len(codes)} account codes"
    return (f"{what} already loaded for {span}",
            f"upload #{', #'.join(str(b) for b in batches)} - undo it first "
            f"(Files screen) if this file should replace it")


def load_files(store: Store, paths, *, allow_duplicate: bool = False) -> list:
    """Load many files. Guarantees one outcome per submitted path."""
    submitted = [Path(p) for p in paths]
    outcomes = [load_one(store, p, allow_duplicate=allow_duplicate) for p in submitted]

    # The invariant the legacy tool lacked. A plain raise, not an assert:
    # `python -O` strips assertions, and this is the one guarantee that must
    # never be optimised away (QA-21).
    if len(outcomes) != len(submitted):
        raise RuntimeError(
            f"accounting error: {len(submitted)} files submitted but "
            f"{len(outcomes)} outcomes produced")
    return outcomes


def summarise(outcomes) -> dict:
    """Counts that always reconcile back to the number of files submitted."""
    counts = {"loaded": 0, "rejected": 0, "duplicate": 0, "failed": 0}
    rows = 0
    for outcome in outcomes:
        counts[outcome.status] = counts.get(outcome.status, 0) + 1
        rows += outcome.rows
    counts["submitted"] = len(outcomes)
    counts["rows"] = rows
    accounted = (counts["loaded"] + counts["rejected"]
                 + counts["duplicate"] + counts["failed"])
    if accounted != counts["submitted"]:
        raise RuntimeError(
            f"accounting error: {counts['submitted']} files submitted but "
            f"{accounted} accounted for")
    return counts
