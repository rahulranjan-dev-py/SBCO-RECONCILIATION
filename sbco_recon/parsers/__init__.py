from . import apt_details, cashbook, glwise
from .base import ParsedReport, ParseError, read_grid

#: Registry used by the import service to auto-detect a file's report type.
#: Order matters: glwise has a distinctive title; cashbook before apt_details
#: because both carry Office/Date columns and cashbook's check is stricter.
PARSERS = {
    glwise.REPORT_TYPE: glwise,
    cashbook.REPORT_TYPE: cashbook,
    apt_details.REPORT_TYPE: apt_details,
}

__all__ = [
    "PARSERS",
    "ParsedReport",
    "ParseError",
    "read_grid",
    "glwise",
    "cashbook",
    "apt_details",
]
