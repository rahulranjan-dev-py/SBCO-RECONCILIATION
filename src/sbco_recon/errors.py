"""Exception hierarchy. Every failure carries a reason the user can act on."""


class ReconError(Exception):
    """Base class for all engine errors."""


class FileRejected(ReconError):
    """An input file failed validation.

    Unlike the legacy tool's single-cell check, every rejection names the
    specific reason so the user knows what to fix.
    """

    def __init__(self, path, reason, detail=""):
        self.path = str(path)
        self.reason = reason
        self.detail = detail
        super().__init__(f"{self.path}: {reason}" + (f" ({detail})" if detail else ""))


class ParseError(ReconError):
    """A file matched its expected shape but a value could not be read."""


class ConfigError(ReconError):
    """Office master or period configuration is invalid."""
