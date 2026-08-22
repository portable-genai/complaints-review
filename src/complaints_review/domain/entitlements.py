"""Server-side complaint entitlements: who may review a complaint file, decided here.

The retrieval ACL for a complaint review is NEVER derived from a client-supplied
identifier alone. A request names a complaint file (its ``file.id``), but the
``complaint:<id>`` retrieval principal and the ``tenant:<t>`` partition are granted only
after :func:`may_access_complaint` passes against the VERIFIED
:class:`~complaints_review.domain.identity.Principal` (resolved by the IdentityPort,
never client-asserted). Combined with tenant tagging at retrieval and the subset ACL
match in the knowledge-base adapters, this closes the object-level authorization gap: an
authenticated analyst in one tenant cannot read another tenant's tagged evidence by
naming a complaint id.

Access model (deliberately simple, override per deployment):

* an explicit ``complaint:<id>`` entitlement on the principal always grants access
  (fine-grained grants provisioned by the IdP / entitlement system); otherwise
* membership of one of the ``complaint_access_roles`` grants access, and tenant
  isolation is still enforced by the ``tenant:<tenant>`` tag at retrieval time.

Pure stdlib; raising :class:`AccessDeniedError` maps to HTTP 403 at the API layer.
"""

from __future__ import annotations

from .errors import AccessDeniedError
from .identity import Principal

#: Roles whose members may review complaint files (within their own tenant). Deployments
#: with finer-grained needs provision explicit ``complaint:<id>`` entitlements instead.
DEFAULT_COMPLAINT_ACCESS_ROLES: frozenset[str] = frozenset(
    {
        "group:complaints-analyst",
        "group:complaints-approver",
        "group:conduct",
        "group:audit",
    }
)


def complaint_acl(file_id: str, tenant: str = "") -> tuple[str, ...]:
    """The ACL tags a complaint's tenant-scoped evidence carries.

    Always ``complaint:<id>``; plus ``tenant:<t>`` when the file belongs to a tenant. The
    store's subset match then requires a reader to hold every tag, so a complaint id
    alone never crosses a tenant boundary (object-level authorization).
    """
    if tenant:
        return (f"complaint:{file_id}", f"tenant:{tenant}")
    return (f"complaint:{file_id}",)


def complaint_acl_ok(file_id: str, tenant: str, principals: tuple[str, ...]) -> bool:
    """Subset, fail-closed: the caller must hold every one of the complaint's ACL tags."""
    return set(complaint_acl(file_id, tenant)) <= set(principals)


def may_access_complaint(
    principal: Principal,
    file_id: str,
    roles: frozenset[str] = DEFAULT_COMPLAINT_ACCESS_ROLES,
) -> bool:
    """True when the verified principal is entitled to review the complaint file."""
    if f"complaint:{file_id}" in principal.principals:
        return True
    return any(p in roles for p in principal.principals)


def complaint_scope(
    principal: Principal,
    file_id: str,
    roles: frozenset[str] = DEFAULT_COMPLAINT_ACCESS_ROLES,
) -> tuple[str, ...]:
    """The retrieval ACL principals for ``file_id``, derived entirely server-side.

    Returns the principal's own entitlements plus ``tenant:<tenant>`` (when the principal
    carries a tenant) plus ``complaint:<file_id>``; raises :class:`AccessDeniedError` when
    the principal is not entitled. The knowledge-base ACL match is subset-based, so a
    passage tagged with another tenant stays invisible even though the ``complaint:<id>``
    principal is present: the tenant tag is what isolates a shared governed corpus.
    """
    if not may_access_complaint(principal, file_id, roles):
        raise AccessDeniedError(
            f"{principal.actor} is not entitled to complaint {file_id!r} "
            "(no explicit complaint grant and no complaint-access role)"
        )
    scope: list[str] = list(principal.entitlement_principals())
    if principal.tenant:
        scope.append(f"tenant:{principal.tenant}")
    scope.append(f"complaint:{file_id}")
    return tuple(scope)
