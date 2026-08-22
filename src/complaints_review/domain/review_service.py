"""ComplaintReviewService — the B6 complaint-review orchestration (SPEC §5).

Owns the full review pipeline and calls only ports. Because a complaint file carries
customer PII, the full R1 safety pipeline runs (redact then guardrail on input and
output). The pipeline, in order:

    tracer.span("complaint.review"):
      redact(complaint text)
      -> guardrail.screen(INPUT)        [blocked -> audit BLOCKED + raise]
      -> extract attached documents (+ redact each extract)
      -> A2 retrieve policy/regulatory guidance  [empty -> audit + raise]
      -> llm summarise
      -> categorise (category + root cause + conduct flags; deterministic + LLM)
      -> llm draft response (grounded, always a draft, never sent)
      -> assemble ComplaintReview (requires_human_review=True)
      -> guardrail.screen(OUTPUT)       [blocked -> audit BLOCKED + raise]
      -> review policy (always) + escalation
      -> audit.record(redacted prompt + response)

Defensive throughout: empty retrieval and a guardrail block raise rather than emit a
partial, ungrounded or unsafe conduct decision; the draft response is never sent by the
system (R1 / P-06: a human sends it).

Pure domain code: no Google Cloud / ADK / FastAPI imports.
"""

from __future__ import annotations

from contextlib import nullcontext, suppress
from typing import Any

from . import _grounded as g
from .categorization_service import CategorizationService
from .errors import GuardrailBlockedError, RetrievalEmptyError
from .models import (
    AuditEvent,
    Channel,
    Citation,
    ComplaintFile,
    ComplaintReview,
    ComplaintSummary,
    Decision,
    Direction,
    DocumentExtract,
    DraftResponse,
    GuardrailVerdict,
    RedactionResult,
    RetrievedPassage,
    TimelineEvent,
)
from .policy import ComplaintPolicy
from .prompts import _CITATION_RULES, SUMMARY_SYSTEM, SUMMARY_USER
from .response_drafting_service import ResponseDraftingService
from .review_policy import ComplaintReviewPolicy
from .serialization import to_jsonable

_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "issue": {"type": "string"},
        "products": {"type": "array", "items": {"type": "string"}},
        "channel": {"type": "string"},
        "timeline": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "event": {"type": "string"},
                },
                "required": ["date", "event"],
            },
        },
        "parties": {"type": "array", "items": {"type": "string"}},
        "used_source_ids": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["issue"],
}

_CHANNEL_BY_VALUE: dict[str, Channel] = {c.value: c for c in Channel}


class ComplaintReviewService:
    """Review a complaint file end to end. Constructor fixed by SPEC §5."""

    def __init__(
        self,
        extraction: Any,
        knowledge_base: Any,
        llm: Any,
        guardrail: Any,
        redaction: Any,
        tracer: Any,
        audit: Any,
        review_policy: ComplaintReviewPolicy | None = None,
        review_router: Any = None,
        complaint_policy: ComplaintPolicy | None = None,
    ) -> None:
        self._extraction = extraction
        self._knowledge_base = knowledge_base
        self._llm = llm
        self._guardrail = guardrail
        self._redaction = redaction
        self._tracer = tracer
        self._audit = audit
        policy = complaint_policy or ComplaintPolicy()
        self._review = review_policy or ComplaintReviewPolicy(policy=policy)
        # Rule R8: when the review requires human review it is routed to Hrz7 (the maker-checker
        # console), not left as a boolean. Optional so unit tests and the CLI can omit it; when
        # unset the escalation still audits ESCALATED, it just is not forwarded to a console.
        self._review_router = review_router
        self._categorizer = CategorizationService(llm, knowledge_base, policy=policy)
        self._drafter = ResponseDraftingService(llm)

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def review(
        self,
        file: ComplaintFile,
        actor: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> ComplaintReview:
        """Produce a full ComplaintReview for ``file`` via the SPEC §5 pipeline.

        ``actor``, ``principals`` and ``tenant`` are the VERIFIED end-user identity
        resolved server-side by the IdentityPort (never client-asserted). ``actor`` is the
        audit subject; ``principals`` are the user's entitlement principals; ``tenant``
        (when set) is stamped as a ``tenant:<t>`` ACL principal into governed A2 retrieval
        so the data path is partitioned to the caller's tenant, not just their groups. All
        three default to empty so existing callers/tests are unaffected.
        """
        span = self._tracer.span("complaint.review", action="review", actor=actor)
        with span if span is not None else nullcontext():
            return self._review_inner(file, actor, principals, tenant)

    def summarize(
        self,
        file: ComplaintFile,
        actor: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> ComplaintSummary:
        """Produce only the structured summary (still R1-safe and audited)."""
        span = self._tracer.span("complaint.summary", action="summary", actor=actor)
        with span if span is not None else nullcontext():
            complaint_text, passages, redacted = self._prepare(
                file, actor, "summary", principals, tenant
            )
            summary = self._summarize(file, complaint_text, passages)
            self._write_audit(
                actor, redacted, summary.issue, Decision.ESCALATED, "summary", summary.citations
            )
            return summary

    def draft_response(
        self,
        file: ComplaintFile,
        actor: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> DraftResponse:
        """Produce only the draft response (grounded; always a draft, never sent)."""
        span = self._tracer.span("complaint.draft_response", action="draft_response", actor=actor)
        with span if span is not None else nullcontext():
            complaint_text, passages, redacted = self._prepare(
                file, actor, "draft_response", principals, tenant
            )
            categorization, _flags = self._categorizer.categorize(
                file, complaint_text, passages, tracer=self._tracer
            )
            draft = self._drafter.draft(
                complaint_text, categorization, passages, tracer=self._tracer
            )
            draft = self._screen_draft(file, redacted, actor, draft)
            self._write_audit(
                actor, redacted, draft.body, Decision.ESCALATED, "draft_response", draft.citations
            )
            return draft

    # ------------------------------------------------------------------ #
    # Pipeline
    # ------------------------------------------------------------------ #
    def _review_inner(
        self,
        file: ComplaintFile,
        actor: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> ComplaintReview:
        complaint_text, passages, redacted = self._prepare(
            file, actor, "review", principals, tenant
        )

        # Summarise, categorise (deterministic + LLM flags), then draft a response.
        summary = self._summarize(file, complaint_text, passages)
        categorization, conduct_flags = self._categorizer.categorize(
            file, complaint_text, passages, tracer=self._tracer
        )
        draft = self._drafter.draft(complaint_text, categorization, passages, tracer=self._tracer)

        # Output guardrail over the assembled, model-authored draft body.
        draft = self._screen_draft(file, redacted, actor, draft)

        review = ComplaintReview(
            file_id=file.id,
            summary=summary,
            categorization=categorization,
            conduct_flags=conduct_flags,
            draft_response=draft,
            requires_human_review=self._review.requires_review(),
        )

        # A review is always routed to a human checker (P-06); a high-stakes flag or
        # severity escalates it to a *senior* checker, recorded in the audit metadata.
        escalated = self._review.escalates(conduct_flags, categorization.severity)
        self._write_audit(
            actor,
            redacted,
            summary.issue,
            Decision.ESCALATED,
            "review",
            self._all_citations(review),
            metadata={
                "category": categorization.category.value,
                "severity": categorization.severity.value,
                "n_conduct_flags": str(len(conduct_flags)),
                "senior_escalation": str(escalated).lower(),
                "draft_sent": str(self._review.draft_is_sendable()).lower(),
            },
        )

        # Route the escalation to Hrz7 (rule R8). A complaint review always requires human review,
        # so it is handed to the maker-checker console rather than terminating in a boolean; the
        # adapter redacts before the wire. Best-effort: a console outage must not fail an already-
        # assembled, already-audited review (the audit ESCALATED record is the durable escalation
        # of record, and the outbox path retries).
        if self._review_router is not None and review.requires_human_review:
            with suppress(Exception):
                self._review_router.route(review, maker=actor, tenant=tenant)
        return review

    # ------------------------------------------------------------------ #
    # Shared preparation: redact -> guardrail(INPUT) -> extract -> retrieve.
    # ------------------------------------------------------------------ #
    def _prepare(
        self,
        file: ComplaintFile,
        actor: str,
        action: str,
        principals: tuple[str, ...] = (),
        tenant: str = "",
    ) -> tuple[str, list[RetrievedPassage], str]:
        # 1) Redact the complaint narrative (P-04) before model / KB / audit.
        redaction: RedactionResult = self._redaction.redact(file.narrative)
        redacted_narrative = redaction.text

        # 2) Guardrail screen (INPUT). Blocked -> audit BLOCKED + raise.
        in_verdict: GuardrailVerdict = self._guardrail.screen(redacted_narrative, Direction.INPUT)
        if not in_verdict.allowed:
            self._write_audit(actor, redacted_narrative, "", Decision.BLOCKED, action)
            raise GuardrailBlockedError(
                in_verdict.reason or "complaint file blocked by input guardrail"
            )
        screened = in_verdict.sanitized_text or redacted_narrative

        # 3) Extract attached documents, redacting each extract before use.
        extract_texts = self._extract_documents(file)

        complaint_text = self._compose_complaint_text(file, screened, extract_texts)

        # 4) Governed A2 retrieval of policy + regulatory guidance. Empty -> raise.
        # The verified user's entitlement principals scope the retrieval ACL alongside the
        # request actor (per-user authZ); the SERVER-VERIFIED tenant is stamped as a
        # ``tenant:<t>`` principal (never derived from the request body) so a tenant-tagged
        # passage is partitioned to the caller's tenant. Untagged (public policy) passages
        # stay visible to everyone, so grounding is never starved.
        query = (
            f"complaint handling policy and regulatory guidance for a {file.product} "
            f"complaint: {screened}"
        )
        tenant_principals = (f"tenant:{tenant}",) if tenant else ()
        passages = g.retrieve_passages(
            self._knowledge_base, query, acl_principals=(actor, *principals, *tenant_principals)
        )
        if not passages:
            self._write_audit(actor, redacted_narrative, "", Decision.ESCALATED, action)
            raise RetrievalEmptyError(
                f"no policy/regulatory passages retrieved for complaint {file.id!r}"
            )
        return complaint_text, passages, redacted_narrative

    def _extract_documents(self, file: ComplaintFile) -> list[str]:
        """Extract and redact each attached document; tolerant of a stub extractor."""
        texts: list[str] = []
        for doc_id in file.documents:
            try:
                extract: DocumentExtract = self._extraction.extract(doc_id, b"", "application/pdf")
            except NotImplementedError:
                # On-prem stub or no extractor wired: the narrative still drives review.
                continue
            except Exception:  # noqa: BLE001 - a bad doc must not crash the review
                continue
            redacted = self._redaction.redact(extract.text or "").text
            if redacted.strip():
                texts.append(redacted)
        return texts

    @staticmethod
    def _compose_complaint_text(
        file: ComplaintFile, narrative: str, extract_texts: list[str]
    ) -> str:
        parts = [
            f"product: {file.product}",
            f"channel: {file.channel.value}",
            f"received_date: {file.received_date}",
            f"narrative: {narrative}",
        ]
        for i, text in enumerate(extract_texts, start=1):
            parts.append(f"document_{i}: {text}")
        return "\n".join(parts)

    # ------------------------------------------------------------------ #
    # Summary
    # ------------------------------------------------------------------ #
    def _summarize(
        self, file: ComplaintFile, complaint_text: str, passages: list[RetrievedPassage]
    ) -> ComplaintSummary:
        passage_block = g.render_passages(passages)
        system = SUMMARY_SYSTEM.format(citation_rules=_CITATION_RULES)
        user = SUMMARY_USER.format(complaint=complaint_text, passages=passage_block)
        request = g.build_llm_request(
            system_instruction=system,
            user_content=user,
            model=None,
            response_schema=_SUMMARY_SCHEMA,
        )
        response = self._llm.generate(request)
        g.maybe_record_usage(self._tracer, response)
        parsed = g.parse_structured(response)

        timeline = tuple(
            TimelineEvent(
                date=str(item.get("date") or "").strip(),
                event=str(item.get("event") or "").strip(),
            )
            for item in (parsed.get("timeline") or [])
            if isinstance(item, dict) and str(item.get("event") or "").strip()
        )
        channel = _CHANNEL_BY_VALUE.get(
            str(parsed.get("channel") or "").strip().lower(), file.channel
        )
        return ComplaintSummary(
            issue=str(parsed.get("issue") or "").strip() or "(no issue extracted)",
            products=tuple(g.as_str_list(parsed.get("products"))) or (file.product,),
            channel=channel,
            timeline=timeline,
            parties=tuple(g.as_str_list(parsed.get("parties"))),
            citations=g.citations_for_source_ids(
                g.as_str_list(parsed.get("used_source_ids")), passages
            ),
        )

    # ------------------------------------------------------------------ #
    # Output guardrail on the draft body
    # ------------------------------------------------------------------ #
    def _screen_draft(
        self, file: ComplaintFile, redacted: str, actor: str, draft: DraftResponse
    ) -> DraftResponse:
        out_verdict: GuardrailVerdict = self._guardrail.screen(draft.body, Direction.OUTPUT)
        if not out_verdict.allowed:
            self._write_audit(actor, redacted, "", Decision.BLOCKED, "draft_response")
            raise GuardrailBlockedError(
                out_verdict.reason or "draft response blocked by output guardrail"
            )
        if out_verdict.sanitized_text and out_verdict.sanitized_text != draft.body:
            return DraftResponse(
                body=out_verdict.sanitized_text,
                tone=draft.tone,
                citations=draft.citations,
                requires_human_review=True,
                is_draft=True,
            )
        return draft

    # ------------------------------------------------------------------ #
    # Helpers / audit
    # ------------------------------------------------------------------ #
    @staticmethod
    def _all_citations(review: ComplaintReview) -> tuple[Citation, ...]:
        out: list[Citation] = list(review.summary.citations)
        out.extend(review.categorization.citations)
        for flag in review.conduct_flags:
            out.extend(flag.citations)
        if review.draft_response is not None:
            out.extend(review.draft_response.citations)
        return tuple(out)

    def _write_audit(
        self,
        actor: str,
        redacted_prompt: str,
        redacted_response: str,
        decision: Decision,
        action: str,
        citations: tuple[Citation, ...] = (),
        metadata: dict[str, str] | None = None,
    ) -> None:
        event = AuditEvent(
            action=action,
            actor=actor,
            decision=decision,
            redacted_prompt=redacted_prompt,
            redacted_response=redacted_response,
            citations=citations,
            metadata=metadata or {},
        )
        try:
            self._audit.record(event)
        except Exception:  # noqa: BLE001 - audit failure must not crash the request
            # The event is best-effort; serialization is validated to be jsonable.
            to_jsonable(event)
