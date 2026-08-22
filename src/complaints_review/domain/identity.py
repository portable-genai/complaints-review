"""Identity value objects for server-side, verified principals.

The service never trusts a client-asserted ``actor`` or ACL. A :class:`Principal` is
resolved server-side by an :class:`~complaints_review.ports.identity.IdentityPort` adapter
(local dev persona, GCP IAP-verified assertion, or an on-prem client IdP) from the inbound
transport context, and becomes the audit actor plus the entitlement principals fed into
governed retrieval. Pure stdlib: nothing here imports a web framework or a cloud SDK.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field


class IdentityError(Exception):
    """Raised when a verified principal cannot be resolved (maps to HTTP 401)."""


@dataclass(frozen=True, slots=True)
class RequestContext:
    """The inbound transport context an IdentityPort resolves a Principal from.

    ``headers`` keys are lower-cased; adapters read only what they need (a GCP IAP
    assertion header, or the local ``x-dev-persona`` selector) without depending on the
    web layer, so the domain stays framework-free.
    """

    headers: dict[str, str] = field(default_factory=dict)

    def header(self, name: str) -> str:
        return self.headers.get(name.lower(), "")


@dataclass(frozen=True, slots=True)
class Principal:
    """A verified end-user identity (never client-asserted)."""

    subject: str  # stable user id (email / sub); becomes the audit actor
    principals: tuple[str, ...] = ()  # entitlement principals/groups for governed ACL
    tenant: str = ""  # tenant / issuer partition (multi-tenant isolation)
    assurance: str = ""  # acr/amr auth-strength hint (optional, for step-up checks)
    source: str = ""  # which adapter resolved it (audit/debug)

    @property
    def actor(self) -> str:
        """The audit actor is the verified subject (non-repudiation, MAS TRM / CPS 234)."""
        return self.subject

    def entitlement_principals(self, requested: Iterable[str] = ()) -> tuple[str, ...]:
        """Effective entitlement principals for governed retrieval, fail-closed.

        The verified principal's own :attr:`principals` are the ceiling on what it may
        see. A caller-supplied ``requested`` list (e.g. a request-body ``acl_principals``)
        may only **narrow** to a subset of them: any requested id the principal does not
        actually hold is dropped, so a client can never widen its own visibility by
        asserting a privileged group id. An empty ``requested`` means "use my full
        entitlement".

        Examples:
            * own ``(group:complaints-analyst, group:conduct)``, requested ``()`` -> both.
            * own ``(group:complaints-analyst, group:conduct)``, requested
              ``(group:conduct,)`` -> ``(group:conduct,)`` (a legitimate scope-down).
            * own ``(group:complaints-analyst,)``, requested ``(group:audit,)`` -> ``()``
              (the foreign privileged id is dropped; the caller is never widened).
        """
        own = self.principals
        req = tuple(dict.fromkeys(r for r in requested if r))  # de-dup, drop empties
        if not req:
            return own
        allowed = set(own)
        return tuple(p for p in req if p in allowed)


# A safe non-identity used only where an adapter explicitly opts out; never the default
# in secure mode (the IdentityPort raises instead of returning this).
ANONYMOUS = Principal(subject="anonymous", source="none")
