from . import cashbook, glwise
from .base import ParsedReport, ParseError, read_grid

#: Registry used by the import service to auto-detect a file's report type.
PARSERS = {
    glwise.REPORT_TYPE: glwise,
    cashbook.REPORT_TYPE: cashbook,
}

__all__ = ["PARSERS", "ParsedReport", "ParseError", "read_grid", "glwise", "cashbook"]
