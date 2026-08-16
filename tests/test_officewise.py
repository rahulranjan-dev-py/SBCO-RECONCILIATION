from __future__ import annotations

import datetime as dt

from sbco_recon.db.models import Office
from sbco_recon.parsers import apt_details, glwise, read_grid
from sbco_recon.services import import_service, officewise_service

from .fixtures import make_apt_details_file, make_glwise_setid_file

DATE = dt.date(2026, 7, 31)
CODE = "8001000100"


def _seed_offices(session):
    session.add_all(
        [
            Office(name="MODEL OFFICE HO", office_id="12345600", sol_or_bo_code="58345610", sol_group="58345610"),
            Office(name="MODEL OFFICE 1 SO", office_id="12345601", sol_or_bo_code="58345611", sol_group="58345611"),
            Office(name="MODEL OFFICE 1.1 BO", office_id="12345602", sol_or_bo_code="A1234", sol_group="58345611"),
        ]
    )
    session.commit()


def test_glwise_setid_multi_section_parsing(tmp_path):
    f = make_glwise_setid_file(
        tmp_path / "gl_set.xlsx",
        DATE,
        [
            ("58345610", [(CODE, "POSB -Receipts", 1000.0, 0)]),
            ("58345611", [(CODE, "POSB -Receipts", 600.0, 0), ("8001000200", "POSB -Payments", 0, 250.0)]),
        ],
    )
    grid = read_grid(f)
    assert glwise.fingerprint(grid)
    parsed = glwise.extract(grid)

    # consolidated rows aggregate across sections
    by_code = {r["account_code"]: r["amount"] for r in parsed.rows}
    assert by_code[CODE] == 1600.0
    assert by_code["8001000200"] == 250.0

    # sol rows keep the per-SOL breakdown
    sol_amounts = {(r["sol_id"], r["account_code"]): r["amount"] for r in parsed.sol_rows}
    assert sol_amounts[("58345610", CODE)] == 1000.0
    assert sol_amounts[("58345611", CODE)] == 600.0
    assert sol_amounts[("58345611", "8001000200")] == 250.0


def test_apt_details_parser(tmp_path):
    f = make_apt_details_file(
        tmp_path / "apt.xlsx",
        CODE,
        [
            (DATE, "12345600", "MODEL OFFICE HO", 1000.0),
            (DATE, "12345601", "MODEL OFFICE 1 SO", 400.0),
            (DATE, "12345602", "MODEL OFFICE 1.1 BO", 200.0),
        ],
    )
    grid = read_grid(f)
    assert apt_details.fingerprint(grid)
    parsed = apt_details.extract(grid)
    assert len(parsed.rows) == 3
    # code came from the "A/c Code :" header cell
    assert all(r["account_code"] == CODE for r in parsed.rows)
    assert parsed.rows[0]["office_id"] == "12345600"


def test_apt_details_not_confused_with_cashbook(tmp_path):
    from .fixtures import make_cashbook_file
    from sbco_recon.parsers import cashbook

    cb = make_cashbook_file(tmp_path / "cb.xlsx", DATE, [(CODE, "POSB", "Receipts", 10.0, 0, 0)])
    grid = read_grid(cb)
    assert cashbook.fingerprint(grid)
    assert not apt_details.fingerprint(grid)


def test_officewise_compare(session, tmp_path):
    _seed_offices(session)
    gl = make_glwise_setid_file(
        tmp_path / "gl_set.xlsx",
        DATE,
        [
            ("58345610", [(CODE, "POSB -Receipts", 1000.0, 0)]),
            ("58345611", [(CODE, "POSB -Receipts", 600.0, 0)]),
        ],
    )
    apt = make_apt_details_file(
        tmp_path / "apt.xlsx",
        CODE,
        [
            (DATE, "12345600", "MODEL OFFICE HO", 1000.0),
            (DATE, "12345601", "MODEL OFFICE 1 SO", 400.0),
            (DATE, "12345602", "MODEL OFFICE 1.1 BO", 150.0),
        ],
    )
    results = import_service.import_files(session, [gl, apt])
    assert [r.status for r in results] == ["PROCESSED", "PROCESSED"]
    assert results[1].report_type == apt_details.REPORT_TYPE

    df = officewise_service.compare(session, CODE, DATE, DATE)
    groups = df[df["Office / SOL group"].str.startswith("SOL")]
    g610 = groups[groups["Code"] == "58345610"].iloc[0]
    g611 = groups[groups["Code"] == "58345611"].iloc[0]
    # HO group matches exactly
    assert g610["Finacle"] == 1000.0 and g610["APT"] == 1000.0 and g610["Difference"] == 0.0
    # SO group: Finacle 600 vs APT 400+150 (SO + its BO) -> 50 short
    assert g611["Finacle"] == 600.0
    assert g611["APT"] == 550.0
    assert g611["Difference"] == 50.0
    # BO member row shows its own APT amount
    bo_row = df[df["Code"] == "A1234"].iloc[0]
    assert bo_row["APT"] == 150.0


def test_apt_details_duplicate_guard_is_per_code(session, tmp_path):
    _seed_offices(session)
    f1 = make_apt_details_file(tmp_path / "a1.xlsx", CODE, [(DATE, "12345600", "HO", 100.0)])
    assert import_service.import_file(session, f1).status == "PROCESSED"

    # same code + date again -> refused
    f2 = make_apt_details_file(tmp_path / "a2.xlsx", CODE, [(DATE, "12345600", "HO", 999.0)])
    assert import_service.import_file(session, f2).status == "DUPLICATE"

    # different code, same date -> fine
    f3 = make_apt_details_file(tmp_path / "a3.xlsx", "8001000200", [(DATE, "12345600", "HO", 50.0)])
    assert import_service.import_file(session, f3).status == "PROCESSED"
