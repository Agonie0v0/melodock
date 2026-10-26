"""MeloDock configuration with compatibility for existing musicdl deployments."""
import os


def apply_environment_aliases():
    # The legacy engine and existing integrations still read MUSICDL_* internally.
    # Explicit MELODOCK_* values, including empty values, take precedence.
    for name, value in list(os.environ.items()):
        if name.startswith('MELODOCK_'):
            os.environ['MUSICDL_' + name[len('MELODOCK_'):]] = value


def database_path(directory):
    current, previous = directory / 'melodock.db', directory / 'musicdl.db'
    return previous if previous.exists() and not current.exists() else current
