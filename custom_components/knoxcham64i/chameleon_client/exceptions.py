"""Exceptions for Knox Chameleon64i client."""


class ChameleonError(Exception):
    """Base exception for Chameleon client."""


class ChameleonConnectionError(ChameleonError):
    """Connection to device failed."""


class ChameleonTimeoutError(ChameleonError):
    """Command timed out."""


class ChameleonCommandError(ChameleonError):
    """Command execution failed."""


class ChameleonProtocolError(ChameleonError):
    """Protocol parsing or validation error."""
