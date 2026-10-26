"""MeloKeep configuration with compatibility for MeloDock and musicdl deployments."""
import os


def apply_environment_aliases():
    # The legacy engine and existing integrations still read MUSICDL_* internally.
    # Explicit MELOKEEP_* values, including empty values, take precedence.
    for prefix in ('MELODOCK_', 'MELOKEEP_'):
        for name, value in list(os.environ.items()):
            if name.startswith(prefix):
                os.environ['MUSICDL_' + name[len(prefix):]] = value


def database_path(directory):
    for name in ('melokeep.db', 'melodock.db', 'musicdl.db'):
        path = directory / name
        if path.exists():
            return path
    return directory / 'melokeep.db'
