""" Exceptions for pyintesishome """


class IHConnectionError(Exception):
    """Connection Error"""


class IHAuthenticationError(ConnectionError):
    """Authentication Error"""
