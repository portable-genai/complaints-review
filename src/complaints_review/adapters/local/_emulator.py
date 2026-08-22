"""Optional Google emulator detection for the ``local`` profile (opt-in, never required).

For the stores that have an official Google emulator, the local adapters can route to
it for higher-fidelity local development WHEN the standard emulator env var is set AND
the matching client library (from the ``[gcp]`` extra) imports. Otherwise the adapters
use their SDK-free SQLite / in-process path, which is the default.

This module only *detects* the opt-in; it deliberately performs **no google-cloud
import at module top level**. Each adapter that supports an emulator imports the google
client lazily, inside the method, and only on the emulator branch, so the default local
path and the offline test suite never import a google-cloud package.

There is no emulator for Agent Search, Gemini, Model Armor, DLP or Document AI, so those
adapters stay on the SDK-free workaround unconditionally. In B6 the registry is the only
store with an opt-in Firestore-emulator branch.
"""

from __future__ import annotations

from ...envread import read_env_setting

#: Standard emulator host env vars, by logical backend.
FIRESTORE_EMULATOR_ENV = "FIRESTORE_EMULATOR_HOST"
PUBSUB_EMULATOR_ENV = "PUBSUB_EMULATOR_HOST"
STORAGE_EMULATOR_ENV = "STORAGE_EMULATOR_HOST"


def _emulator_host(name: str) -> str | None:
    """The emulator host named by ``name``, or ``None`` when no emulator was named.

    Deliberate collapse: UNSET and SET-AND-EMPTY both return ``None``. The closed direction
    is the same for both, because the emulator branch is an OPT-IN relaxation of the default
    SDK-free path: "nobody asked for an emulator" and "an emulator was asked for and named
    nothing" both mean the opt-in does not fire. These variables have no documented default
    (there is no host that could stand in for one), so there is nothing an emptied value
    could wrongly inherit.
    """
    return read_env_setting(name).value or None


def firestore_emulator_host() -> str | None:
    """Return the Firestore emulator host if ``FIRESTORE_EMULATOR_HOST`` names one, else None."""
    return _emulator_host(FIRESTORE_EMULATOR_ENV)


def pubsub_emulator_host() -> str | None:
    """Return the Pub/Sub emulator host if ``PUBSUB_EMULATOR_HOST`` names one, else None."""
    return _emulator_host(PUBSUB_EMULATOR_ENV)


def storage_emulator_host() -> str | None:
    """Return the Cloud Storage emulator host if ``STORAGE_EMULATOR_HOST`` names one, else None."""
    return _emulator_host(STORAGE_EMULATOR_ENV)


def firestore_client_available() -> bool:
    """Whether ``google-cloud-firestore`` is importable (the ``[gcp]`` extra is installed).

    The import is attempted lazily here (not at module top level) so that the default
    SDK-free local path never imports a google-cloud package.
    """
    try:
        import google.cloud.firestore  # noqa: F401  (lazy availability probe only)
    except Exception:  # noqa: BLE001 - any import failure means the emulator path is off
        return False
    return True


def firestore_emulator_active() -> bool:
    """True only when both the emulator env var is set AND the client lib imports."""
    return firestore_emulator_host() is not None and firestore_client_available()
