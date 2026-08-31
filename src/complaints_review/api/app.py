"""FastAPI application for the B6 Complaints & Conduct File Review service.

Exposes the review artifacts (full review, summary, draft response) plus health and
governance endpoints, and publishes the A2A AgentCard at
``/.well-known/agent-card.json``. The React/Next.js UI and the CLI consume this surface.

Design constraints:

* **Import-safe.** Building the :class:`~complaints_review.config.Container` is deferred to
  request time via the ``deps`` factories, so importing this module (or ``app``) never
  touches Google Cloud. The on-prem/test profile imports it with no GCP SDK installed.
* **Guardrail blocks are not 500s.** A :class:`GuardrailBlockedError` from the service is
  translated to an HTTP 200 carrying a *blocked* envelope flagged for human review.
* **Server-verified identity.** Every artifact route resolves a verified :class:`Principal`
  (``CurrentPrincipal``); the request body carries no ``actor``. The verified subject is the
  audit actor and the verified entitlement principals scope governed retrieval.
* **Region pinned** to ``asia-southeast1`` (Singapore) for data residency (SPEC §2).

Run locally with ``python -m complaints_review.api.app`` (uvicorn on :8095).
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from hex_service_kit import cors_allowlist, resolve_bind_host
from hex_service_kit.web import add_loopback_exposure_guard

from ..config import end_user_auth_kind
from ..domain import entitlements
from ..domain.errors import AccessDeniedError, GuardrailBlockedError, RetrievalEmptyError
from ..domain.services import ComplaintReviewService
from ..envread import read_env_setting, setting_or_default
from ..ports.identity import VERIFIED
from . import deps
from .schemas import (
    AgentCardModel,
    ComplaintReviewModel,
    ComplaintSummaryModel,
    DraftResponseModel,
    HealthResponse,
    ReviewRequest,
)
from .security import CurrentPrincipal

# Local Next.js dev origins the browser UI is served from during development.
_DEV_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Embedding-surface controls. In secure/embedded mode the service is served same-origin via
# the parent app's reverse-proxy (no CORS needed); for the cross-origin / standalone dev
# case, COMPLAINTS_CORS_ORIGINS is an explicit per-tenant allowlist (never "*").
# COMPLAINTS_FRAME_ANCESTORS is the CSP frame-ancestors allowlist of parent origins
# permitted to iframe the UI.
_CORS_ORIGINS_ENV = "COMPLAINTS_CORS_ORIGINS"
_FRAME_ANCESTORS_ENV = "COMPLAINTS_FRAME_ANCESTORS"


#: Entries that are a wildcard by BEHAVIOUR rather than by spelling, so the asterisk test below
#: cannot see them. ``null`` is the one that matters: a sandboxed iframe presents a null origin,
#: so ``frame-ancestors null`` admits framing from a document whose own origin the browser has
#: already decided not to trust, and a null CORS origin trusts the same document WITH
#: credentials. ``'*'`` is the quoted form CSP also honours and ``*.*`` is the subdomain
#: wildcard; both carry an asterisk, and both are named here so the set reads as the complete
#: refusal rather than as a list of leftovers. Matching is exact, so ``https://nullify.example``
#: remains a perfectly good origin. The same four are refused in ``ui/lib/csp.mjs``.
_WILDCARD_TOKENS = frozenset({"*", "'*'", "null", "*.*"})


def _refuse_wildcard(origins: list[str] | tuple[str, ...], setting: str) -> None:
    """An origin policy naming everybody is not an allowlist, so refuse to boot with one.

    "never ``*``" was written in the comment above and enforced nowhere, which is the same
    as unenforced. ``*`` in the CORS allowlist trusts every origin WITH credentials, and in
    frame-ancestors it lets any page on the internet frame the console and drive it as the
    signed-in user. The rule catches a wildcard hiding inside an origin too
    (``https://*.example``): a legitimate origin has no ``*`` anywhere in it, so this
    refuses no configuration a deployment could correctly hold.

    The asterisk test alone was not the whole rule. ``null`` carries no asterisk, so it passed
    both allowlists and reached ``CORSMiddleware`` and the CSP directive verbatim: see
    :data:`_WILDCARD_TOKENS`. The two halves are a UNION, and the union is what
    ``ui/lib/csp.mjs`` already enforced for the document a browser actually frames, so until
    now the two surfaces disagreed about what an origin policy may hold.
    """
    offending = [origin for origin in origins if "*" in origin or origin in _WILDCARD_TOKENS]
    if offending:
        raise ValueError(
            f"{setting} origin policy must never contain a wildcard, got {offending}. "
            "Name each permitted origin in full."
        )


def _frame_ancestors(raw: str | None) -> str:
    """Three-state read of ``COMPLAINTS_FRAME_ANCESTORS``; an emptied value REFUSES framing.

    Unset keeps the shipped ``'self'``. A value naming no origin would emit the
    header ``Content-Security-Policy: frame-ancestors`` with an empty directive, which is a
    CSP parse error, so browsers dropped the directive and the clickjacking restriction went
    with it. An operator who empties the allowlist means "nobody may frame this", which is
    spelled ``'none'``, so that is what the emptied state now produces.

    A wildcard is the fourth state, and it refuses: see ``_refuse_wildcard``.
    """
    if raw is None:
        return "'self'"
    ancestors = raw.split()
    _refuse_wildcard(ancestors, _FRAME_ANCESTORS_ENV)
    return " ".join(ancestors) or "'none'"


_FRAME_ANCESTORS = _frame_ancestors(read_env_setting(_FRAME_ANCESTORS_ENV).raw)


def _cors_origins() -> list[str]:
    """Explicit allowlist, never "*", and a configured EMPTY allowlist refuses.

    Three-state, because "configured and empty" and "never configured" are different
    answers. Unset delegates to the shared hex-service-kit rule, whose localhost dev
    fallback is a RELAXATION and therefore keys off ``exposure_profile``: a run that named
    no profile gets no cross-origin trust. Set to a value naming no origin refuses every
    cross-origin request instead of falling back to the dev origins the operator was trying
    to remove.
    """
    raw = read_env_setting(_CORS_ORIGINS_ENV).raw
    if raw is not None:
        configured = [origin.strip() for origin in raw.split(",") if origin.strip()]
        _refuse_wildcard(configured, _CORS_ORIGINS_ENV)
        return configured
    resolved = cors_allowlist(
        deps.get_settings().exposure_profile,
        origins_env=_CORS_ORIGINS_ENV,
        dev_origins=tuple(_DEV_ORIGINS),
    )
    _refuse_wildcard(resolved, _CORS_ORIGINS_ENV)
    return resolved


app = FastAPI(
    title="B6 Complaints & Conduct File Review",
    version="0.1.0",
    description=(
        "Conduct-ops assistant for APAC banking Complaints/Conduct teams. From a complaint "
        "file it produces a cited summary, categorisation with conduct flags, and a draft "
        "regulator/customer response (always human-reviewed, never auto-sent), on the "
        "Gemini Enterprise Agent Platform."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Dev-Persona"],
)


def _frame_options(frame_ancestors: str) -> str:
    """The X-Frame-Options equivalent of ``frame_ancestors``, or "" where none exists.

    X-Frame-Options is the pre-CSP header, and browsers that understand frame-ancestors
    ignore it, so it is only a backstop for the ones that do not. It can express exactly two
    of the three states: ``'self'`` is SAMEORIGIN and ``'none'`` is DENY. It cannot express an
    allowlist (ALLOW-FROM was never widely implemented and is gone), so a named parent origin
    gets no backstop rather than a DENY that would break the embed it was configured for.

    The emptied state must not fall through here with no header at all, on top of a CSP
    directive the browser had already discarded as a parse error, which left the operator who
    asked for the STRICTEST posture with no clickjacking control whatsoever.
    """
    if frame_ancestors == "'self'":
        return "SAMEORIGIN"
    if frame_ancestors == "'none'":
        return "DENY"
    return ""


@app.middleware("http")
async def _security_headers(request: Request, call_next: Any) -> Any:
    """Emit embedding-surface headers: CSP frame-ancestors (who may iframe the UI)."""
    response = await call_next(request)
    response.headers["Content-Security-Policy"] = f"frame-ancestors {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if deps.get_settings().profile in {"gcp", "platform"}:
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    frame_options = _frame_options(_FRAME_ANCESTORS)
    if frame_options:
        response.headers["X-Frame-Options"] = frame_options
    return response


# A request arrives with nothing authenticating the END USER unless BOTH of these hold, and
# the guard bounds every case where either fails:
#
#   1. a profile was chosen. Absent that, nobody selected an identity scheme, the seeded
#      persona adapter refuses to construct, and every end-user route answers 401; but
#      /healthz and the agent card would still answer a stranger, and a deployment in that
#      state has no business being reachable at all. It is also the one case where a settings
#      file that bound a verifying adapter must NOT buy the relaxation: unset is not consent,
#      whatever the binding says;
#   2. the identity adapter the active binding names DECLARES that it verifies the end user.
#      Seeded personas arrive on a header the caller wrote (client-asserted) and the
#      on-premises placeholder resolves nobody at all (unimplemented); neither authenticates
#      anyone, so neither may switch this off.
#
# Note what is NOT in this expression: COMPLAINTS_S2S_TOKEN. A service credential is evidence
# about a calling SERVICE and says nothing about the end-user routes, so setting one must not,
# and cannot, disable their bound. S2S routes are bounded by their own dependency, which is
# where a service credential belongs.
_END_USER_AUTHENTICATED = deps.get_settings().profile_explicit and end_user_auth_kind() == VERIFIED

# The RESTRICTION's profile string. `bind_profile` already reads an unconsented run as
# `local`; this widens the same rule to every posture that cannot authenticate an end user, so
# the start-up bound in `main()` and the request-time guard agree instead of one binding every
# interface while the other refuses every caller on it.
_BIND_PROFILE = deps.get_settings().bind_profile if _END_USER_AUTHENTICATED else "local"

# Registered LAST, so it is the OUTERMOST middleware: an off-loopback caller is refused before
# CORS, before the header baseline and before any route or dependency runs. Bound to the APP
# OBJECT, not to `main()`: the Dockerfile CMD is
# `uvicorn complaints_review.api.app:app --host 0.0.0.0`, so a guard reachable only from
# `main()` never runs in a shipped process and the seeded personas would be served to the LAN.
add_loopback_exposure_guard(
    app,
    unauthenticated=not _END_USER_AUTHENTICATED,
    insecure_demo_env="COMPLAINTS_ALLOW_INSECURE_DEMO",
    # The EXPOSURE profile, so a run nobody configured names itself 'unconfigured' in the
    # refusal rather than borrowing the name of a profile an operator never chose.
    posture=deps.get_settings().exposure_profile,
)


def _blocked_response(file_id: str, reason: str) -> JSONResponse:
    """A 200 JSON body for a guardrail-blocked or ungrounded request.

    The review pipeline raises rather than return a partial artifact, so there is no
    domain object to project. We answer 200 with an explicit blocked envelope (flagged for
    human review) so the UI/CLI can render the block without treating it as a 5xx.
    """
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content={
            "file_id": file_id,
            "blocked": True,
            "requires_human_review": True,
            "detail": "This request was blocked or could not be grounded; routed for human review.",
            "reason": reason or "blocked",
        },
    )


def _denied_response(exc: AccessDeniedError) -> JSONResponse:
    """403 for a failed server-side complaint entitlement check (never a data leak).

    The verified principal is not entitled to the named complaint file, so we refuse
    rather than run a review the caller may not see; the body carries only the reason.
    """
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"detail": str(exc)},
    )


# --------------------------------------------------------------------------- #
# Artifact endpoints
# --------------------------------------------------------------------------- #
@app.post("/v1/review", response_model=ComplaintReviewModel, tags=["artifacts"])
def review(
    request: ReviewRequest,
    principal: CurrentPrincipal,
    service: Annotated[ComplaintReviewService, Depends(deps.get_review_service)],
) -> JSONResponse | ComplaintReviewModel:
    """Produce a full cited complaint review (summary, categorisation, flags, draft)."""
    # Object-level authorization: entitlement to the named complaint is decided server-side
    # from the VERIFIED principal (role/grant check), never from the request body. The
    # verified tenant is then threaded into retrieval so evidence is tenant-partitioned.
    try:
        entitlements.complaint_scope(principal, request.file.id)
    except AccessDeniedError as exc:
        return _denied_response(exc)
    try:
        result = service.review(
            request.file.to_domain(),
            actor=principal.actor,
            principals=principal.entitlement_principals(),
            tenant=principal.tenant,
        )
    except (GuardrailBlockedError, RetrievalEmptyError) as exc:
        return _blocked_response(request.file.id, str(exc))
    return ComplaintReviewModel.from_domain(result)


@app.post("/v1/summary", response_model=ComplaintSummaryModel, tags=["artifacts"])
def summary(
    request: ReviewRequest,
    principal: CurrentPrincipal,
    service: Annotated[ComplaintReviewService, Depends(deps.get_review_service)],
) -> JSONResponse | ComplaintSummaryModel:
    """Produce only the structured complaint-file summary."""
    try:
        entitlements.complaint_scope(principal, request.file.id)
    except AccessDeniedError as exc:
        return _denied_response(exc)
    try:
        result = service.summarize(
            request.file.to_domain(),
            actor=principal.actor,
            principals=principal.entitlement_principals(),
            tenant=principal.tenant,
        )
    except (GuardrailBlockedError, RetrievalEmptyError) as exc:
        return _blocked_response(request.file.id, str(exc))
    return ComplaintSummaryModel.from_domain(result)


@app.post("/v1/draft-response", response_model=DraftResponseModel, tags=["artifacts"])
def draft_response(
    request: ReviewRequest,
    principal: CurrentPrincipal,
    service: Annotated[ComplaintReviewService, Depends(deps.get_review_service)],
) -> JSONResponse | DraftResponseModel:
    """Produce only the draft regulator/customer response (a draft, never sent)."""
    try:
        entitlements.complaint_scope(principal, request.file.id)
    except AccessDeniedError as exc:
        return _denied_response(exc)
    try:
        result = service.draft_response(
            request.file.to_domain(),
            actor=principal.actor,
            principals=principal.entitlement_principals(),
            tenant=principal.tenant,
        )
    except (GuardrailBlockedError, RetrievalEmptyError) as exc:
        return _blocked_response(request.file.id, str(exc))
    return DraftResponseModel.from_domain(result)


# --------------------------------------------------------------------------- #
# Health & governance
# --------------------------------------------------------------------------- #
@app.get("/healthz", response_model=HealthResponse, tags=["ops"])
def healthz() -> HealthResponse:
    """Liveness/readiness probe. Reports the active profile and pinned region."""
    settings = deps.get_settings()
    return HealthResponse(
        status="ok",
        profile=settings.profile,
        region=settings.region,
        runtime=settings.runtime,
        generator_model=settings.generator_model,
    )


@app.get("/v1/personas", tags=["ops"])
def personas() -> list[dict[str, str]]:
    """List seeded dev personas for the local persona picker (empty outside local profile).

    Local mode runs with no IdP; the UI uses this to let a demo/test pick an identity
    (and thus exercise per-user authorization) via the ``X-Dev-Persona`` header. Secure
    profiles resolve identity from the IAP assertion, so this returns an empty list.
    """
    # A relaxation (it publishes unauthenticated identities), so a run that chose no profile
    # lists nothing rather than constructing the persona adapter, which refuses under exactly
    # this condition. Every chosen profile keeps its previous answer.
    if not deps.get_settings().profile_explicit:
        return []
    identity = deps.get_container().identity
    lister = getattr(identity, "personas", None)
    if lister is None:
        return []
    return [dict(p) for p in lister()]


@app.get("/.well-known/agent-card.json", response_model=AgentCardModel, tags=["governance"])
def agent_card() -> AgentCardModel:
    """Publish this service's A2A AgentCard for discovery (A3 Registry / interop)."""
    from ..agent.agent_card import build_agent_card

    settings = deps.get_settings()
    card = build_agent_card(settings)
    return AgentCardModel.from_domain(card)


def main() -> None:
    """Run the API locally with uvicorn (Cloud Run / Agent Runtime use this app object)."""

    import uvicorn

    uvicorn.run(
        "complaints_review.api.app:app",
        # Fail-closed bind (shared hex-service-kit rule): the no-auth local
        # profile binds loopback unless COMPLAINTS_ALLOW_INSECURE_DEMO=1; secure profiles
        # keep 0.0.0.0 (container-local; ingress is fronted by the platform). This is a
        # RESTRICTION, so it reads _BIND_PROFILE: a run that named no profile, and any run
        # whose identity binding cannot verify an end user, must look local here and stay
        # confined. That is the same value the request-time guard was built with, so the
        # two cannot disagree.
        host=resolve_bind_host(
            _BIND_PROFILE,
            host_env="COMPLAINTS_API_HOST",
            insecure_demo_env="COMPLAINTS_ALLOW_INSECURE_DEMO",
        ),
        # PORT has a documented default, so it takes the shape-1 read: unset takes 8095, and
        # an emptied PORT refuses rather than silently inheriting it.
        port=int(setting_or_default("PORT", "8095")),
        # Deliberate collapse: unset and emptied both leave the reloader OFF. The reloader is
        # a development convenience that watches and re-executes the source tree, so "off" is
        # the closed direction for both states, and only an explicit affirmative turns it on.
        reload=read_env_setting("COMPLAINTS_API_RELOAD").value.lower()
        in {"1", "true", "yes", "on"},
    )


if __name__ == "__main__":
    main()
