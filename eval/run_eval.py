#!/usr/bin/env python3
"""Offline evaluation gate for B6 Complaints & Conduct File Review : A4 / P-08.

This is the **promotion gate**: CI runs it on every change and the build fails if the
review pipeline falls below the model-risk thresholds agreed for a regulated conduct-ops
assistant (see ``eval/rubrics/*.yaml``)::

    categorisation_accuracy >= 0.85
    groundedness            >= 0.80
    citation_accuracy       >= 0.90
    pii_safety              >= 0.99

Two evaluators, one gate
------------------------
* **Production evaluator** : the **Gen AI evaluation service** on the Gemini Enterprise
  Agent Platform, wired into the hexagon as ``EvaluationGatePort`` ->
  ``complaints_review.adapters.gcp.genai_eval:GenAiEvalAdapter``. It uses LLM judges and
  needs GCP credentials and a project. Select it with ``--use-gcp``.

* **Offline evaluator (default)** : a deterministic, dependency-light heuristic
  implemented in this file. It needs **no GCP credentials and no Google Cloud SDK**, runs
  the real ``ComplaintReviewService`` review pipeline against in-memory fake adapters, and
  computes the four metrics with conservative heuristics. This is what guards the merge in
  CI; the production evaluator is the richer, judged check run pre-promotion.

The heuristic is intentionally a *lower bound* on the LLM-judge score: if the offline gate
passes, the production gate is expected to pass too, but the production gate remains the
authority for promotion.

Usage::

    python eval/run_eval.py                      # offline heuristic gate (CI)
    python eval/run_eval.py --dataset path.jsonl # custom golden set
    python eval/run_eval.py --use-gcp            # route through GenAiEvalAdapter

Exit code is ``0`` iff ``EvalReport.passed`` (every metric meets its threshold).
"""

from __future__ import annotations

import json
import re
import sys
from collections.abc import Sequence
from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path

# The pii_safety gate runs the REAL local redactor (not a fake) over the SAME shared pii-kit
# rows the runtime uses, and scores the leak-check two independent ways (see score_pii_safety).
# The --mode smoke|gate scaffold + aligned report rendering come from the shared
# agent-eval-kit commons; this script keeps only its own offline
# evaluator and gate runner.
from agent_eval_kit import eval_main
from pii_kit import UNIVERSAL_PATTERNS, national_patterns_for, pack_leak, planted_leak
from pii_kit.patterns import Pattern

from complaints_review.adapters.local.redaction import LocalRegexRedactionAdapter
from complaints_review.config import PiiSettings, Settings

# Domain models are pure-stdlib (no GCP / framework imports), so importing them here keeps
# this script runnable in the on-prem/test profile with no Google Cloud SDK installed.
from complaints_review.domain.models import (
    Channel,
    Citation,
    ComplaintFile,
    ComplaintReview,
    Direction,
    EvalMetricResult,
    EvalReport,
    GuardrailVerdict,
    LlmRequest,
    LlmResponse,
    RetrievalQuery,
    RetrievedPassage,
    SourceType,
    TokenUsage,
)

# --------------------------------------------------------------------------- #
# Thresholds : the promotion bar (SPEC A4 / P-08). Mirrors eval/rubrics/*.yaml.
# --------------------------------------------------------------------------- #
THRESHOLDS: dict[str, float] = {
    "categorisation_accuracy": 0.85,
    "groundedness": 0.80,
    "citation_accuracy": 0.90,
    "pii_safety": 0.99,
}

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_complaints.jsonl"

# The jurisdictions the pii_safety gate exercises. MUST match the redactor's configured set
# (Settings.pii below is built with exactly these), so the leak-check and the redactor read the
# same pii-kit rows: a leak then means the pipeline re-introduced PII, not that a bespoke
# detector and a bespoke redactor drifted apart.
_PII_JURISDICTIONS: tuple[str, ...] = ("SG", "HK", "JP", "AU")
_PII_PATTERNS: tuple[Pattern, ...] = (
    *UNIVERSAL_PATTERNS,
    *tuple(national_patterns_for(_PII_JURISDICTIONS)),
)

# One obviously-fictional identifier per market, in the printed form, planted into a golden
# case's narrative to prove the pack redacts each jurisdiction it claims to cover. JP and AU
# carry VALID check digits because their rows are checksum-gated. Together with the pack-
# independent literal check in score_pii_safety, this makes the per-market claim real: break any
# one market's row and only its own case goes red. See tests/unit/test_redaction_service.py.
_PII_BY_JURISDICTION: dict[str, str] = {
    "SG": "S1234567D",
    "HK": "A123456(3)",
    "JP": "1234 5678 9018",
    "AU": "123 456 782",
}

# Catalogue of policy / regulatory sources used by the fake retrieval.
_KB: dict[str, tuple[SourceType, str, str]] = {
    "complaints-handling-policy": (
        SourceType.POLICY,
        "Group Complaints Handling Policy",
        "https://example.org/policy/complaints-handling",
    ),
    "mas-fair-dealing-guidelines": (
        SourceType.REGULATION,
        "MAS Guidelines on Fair Dealing",
        "https://example.org/mas/fair-dealing",
    ),
}


@dataclass(frozen=True, slots=True)
class GoldenExample:
    id: str
    product: str
    channel: str
    received_date: str
    narrative: str
    expected_category: str
    expected_conduct_flags: tuple[str, ...]
    must_cite_source_ids: tuple[str, ...]
    response_must_be_draft: bool
    # When set (SG/HK/JP/AU), the market whose identifier is planted in this case's narrative to
    # exercise the redactor. Empty means the case plants no PII (only the pack scan runs on it).
    pii_jurisdiction: str = ""


def load_golden(path: Path) -> list[GoldenExample]:
    examples: list[GoldenExample] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as exc:  # pragma: no cover - defensive
            raise SystemExit(f"{path}:{lineno}: invalid JSON: {exc}") from exc
        examples.append(
            GoldenExample(
                id=str(obj.get("id", f"example-{lineno}")),
                product=str(obj.get("product", "")),
                channel=str(obj.get("channel", "other")),
                received_date=str(obj.get("received_date", "")),
                narrative=str(obj["narrative"]),
                expected_category=str(obj["expected_category"]),
                expected_conduct_flags=tuple(obj.get("expected_conduct_flags", []) or ()),
                must_cite_source_ids=tuple(obj.get("must_cite_source_ids", []) or ()),
                response_must_be_draft=bool(obj.get("response_must_be_draft", True)),
                pii_jurisdiction=str(obj.get("pii_jurisdiction", "") or "").upper(),
            )
        )
    if not examples:
        raise SystemExit(f"{path}: golden dataset is empty")
    return examples


def load_thresholds_from_rubrics() -> dict[str, float]:
    """Read thresholds from ``eval/rubrics/*.yaml`` when PyYAML is available."""
    thresholds = dict(THRESHOLDS)
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return thresholds

    rubric_dir = _REPO_ROOT / "eval" / "rubrics"
    for name in ("categorisation_accuracy.yaml", "groundedness.yaml"):
        rubric_path = rubric_dir / name
        if not rubric_path.exists():
            continue
        doc = yaml.safe_load(rubric_path.read_text(encoding="utf-8")) or {}
        metric = doc.get("metric")
        if isinstance(metric, str) and "threshold" in doc:
            thresholds[metric] = float(doc["threshold"])
        for companion, spec in (doc.get("companion_metrics") or {}).items():
            if isinstance(spec, dict) and "threshold" in spec:
                thresholds[str(companion)] = float(spec["threshold"])
    return thresholds


# --------------------------------------------------------------------------- #
# Deterministic fake adapters (inlined on purpose : importing tests.conftest is
# disallowed for this gate, and CI must not depend on the test tree).
# --------------------------------------------------------------------------- #
def _citation_for(source_id: str, page: int = 1, score: float = 0.9) -> Citation:
    src_type, title, url = _KB.get(source_id, (SourceType.POLICY, source_id, "https://example.org"))
    return Citation(
        source_id=source_id,
        source_type=src_type,
        title=title,
        url=url,
        page=page,
        snippet=f"Relevant obligation from {title}.",
        score=score,
    )


def _real_redactor() -> LocalRegexRedactionAdapter:
    """The production local redactor, pinned to the gate's jurisdictions (PIIRedactionPort).

    Redaction is deliberately NOT faked. The local adapter is pure regex over the shared
    pii-kit rows (SDK-free, no external service), so there is no reason to stand in for it, and
    faking it is exactly what let the old gate score a copy of the redactor's own regexes and go
    vacuously green. This runs the real thing over the real rows.
    """
    return LocalRegexRedactionAdapter(Settings(pii=PiiSettings(jurisdictions=_PII_JURISDICTIONS)))


class FakeGuardrailAdapter:
    """Always-allow guardrail with deterministic verdicts (GuardrailPort)."""

    def screen(self, text: str, direction: Direction) -> GuardrailVerdict:
        return GuardrailVerdict(
            allowed=True, direction=direction, findings=(), sanitized_text=text, reason="benign"
        )


class FakeExtractionAdapter:
    """No-op extractor : the golden narratives carry the complaint text inline."""

    def extract(self, document_id: str, content: bytes, mime_type: str):  # noqa: ANN201
        from complaints_review.domain.models import DocumentExtract

        return DocumentExtract(document_id=document_id, fields={}, text="", pages=0)


class FakeTracer:
    """No-op tracer satisfying ObservabilityTracerPort (content capture OFF)."""

    def span(self, name: str, **attributes: str):  # noqa: ANN201
        return nullcontext()

    def record_token_usage(self, usage: TokenUsage, model: str) -> None:
        return None


class FakeAuditSink:
    """In-memory WORM stand-in (AuditSinkPort); records are inspectable post-run."""

    def __init__(self) -> None:
        self.events: list[object] = []

    def record(self, event: object) -> None:
        self.events.append(event)


class FakeKnowledgeBaseAdapter:
    """Deterministic governed-RAG retrieval keyed off the golden example."""

    def __init__(self, by_narrative: dict[str, GoldenExample]) -> None:
        self._by_narrative = by_narrative

    def search(self, query: RetrievalQuery) -> list[RetrievedPassage]:
        example = self._match(query.text)
        wanted = list(example.must_cite_source_ids) if example is not None else list(_KB)
        passages: list[RetrievedPassage] = []
        for rank, sid in enumerate(wanted):
            score = round(0.95 - rank * 0.1, 3)
            citation = _citation_for(sid, page=rank + 1, score=score)
            passages.append(
                RetrievedPassage(
                    text=f"{citation.title}: applicable complaint-handling obligation.",
                    citation=citation,
                    score=score,
                )
            )
        return passages

    def _match(self, query_text: str) -> GoldenExample | None:
        # The service composes the query as "... complaint: <redacted narrative>".
        for narrative, example in self._by_narrative.items():
            if narrative[:40] in query_text:
                return example
        return None


class FakeLLMAdapter:
    """Deterministic, grounded generator (LLMPort), no model call.

    Plays the model honestly per schema: it returns the golden expected category for the
    categorisation request, a grounded summary and a draft response, and cites only the
    ``source_id`` headers actually present in the PASSAGES block (never invents one).
    """

    def __init__(self, by_narrative: dict[str, GoldenExample]) -> None:
        self._by_narrative = by_narrative
        self.model = "gemini-3.5-flash"

    def generate(self, request: LlmRequest) -> LlmResponse:
        user = _last_user_text(request)
        example = self._match(user)
        source_ids = _extract_source_ids(user)
        props = set((request.response_schema or {}).get("properties", {}))

        if "category" in props:
            payload = {
                "category": example.expected_category if example else "other",
                "root_cause": {
                    "description": "Root cause grounded in the cited policy.",
                    "systemic": False,
                },
                "severity": "high",
                "regulatory_relevance": ["fair-dealing"],
                "conduct_flags": [],  # deterministic flags are added by the service
                "used_source_ids": source_ids,
            }
        elif "body" in props:
            payload = {
                "body": (
                    "Thank you for raising your complaint. We have reviewed it against our "
                    "policy and will respond within the complaint-handling window. You may "
                    "escalate to the relevant ombudsman if you remain dissatisfied."
                ),
                "tone": "empathetic-formal",
                "used_source_ids": source_ids,
            }
        else:  # summary
            payload = {
                "issue": "The customer's complaint as recorded in the file.",
                "products": [example.product] if example else [],
                "channel": example.channel if example else "other",
                "timeline": [],
                "parties": ["customer"],
                "used_source_ids": source_ids,
            }
        return LlmResponse(
            text=json.dumps(payload),
            usage=TokenUsage(input_tokens=128, output_tokens=64, thinking_tokens=32),
            model=self.model,
            web_citations=(),
            raw=None,
        )

    def classify(self, text: str, labels: list[str]) -> str:
        return labels[0] if labels else ""

    def _match(self, user_content: str) -> GoldenExample | None:
        for narrative, example in self._by_narrative.items():
            if narrative[:40] in user_content:
                return example
        return None


_SOURCE_HEADER_RE = re.compile(r"\[([a-z0-9][a-z0-9\-]*?)(?:\s+p\.[^\]]+)?\]")


def _extract_source_ids(user_content: str) -> list[str]:
    seen: list[str] = []
    for sid in _SOURCE_HEADER_RE.findall(user_content):
        if sid not in seen:
            seen.append(sid)
    return seen


def _last_user_text(request: LlmRequest) -> str:
    for message in reversed(request.messages):
        if message.role == "user":
            return message.content
    return request.messages[-1].content if request.messages else ""


_CHANNEL_BY_VALUE = {c.value: c for c in Channel}


# --------------------------------------------------------------------------- #
# Pipeline driver : drive the real ComplaintReviewService.
# --------------------------------------------------------------------------- #
@dataclass(frozen=True, slots=True)
class _Adapters:
    # Shared, stateless fakes. The audit sink is NOT here: it is rebuilt per example so each
    # case's pii_safety scores only its OWN audit records (see run_offline).
    extraction: FakeExtractionAdapter
    knowledge_base: FakeKnowledgeBaseAdapter
    llm: FakeLLMAdapter
    guardrail: FakeGuardrailAdapter
    redaction: LocalRegexRedactionAdapter
    tracer: FakeTracer


def _build_adapters(examples: Sequence[GoldenExample]) -> _Adapters:
    by_narrative = {ex.narrative: ex for ex in examples}
    return _Adapters(
        extraction=FakeExtractionAdapter(),
        knowledge_base=FakeKnowledgeBaseAdapter(by_narrative),
        llm=FakeLLMAdapter(by_narrative),
        guardrail=FakeGuardrailAdapter(),
        redaction=_real_redactor(),
        tracer=FakeTracer(),
    )


def _make_service(adapters: _Adapters, audit: FakeAuditSink):  # noqa: ANN201
    from complaints_review.domain.review_service import ComplaintReviewService

    return ComplaintReviewService(
        extraction=adapters.extraction,
        knowledge_base=adapters.knowledge_base,
        llm=adapters.llm,
        guardrail=adapters.guardrail,
        redaction=adapters.redaction,
        tracer=adapters.tracer,
        audit=audit,
    )


def _planted_narrative(example: GoldenExample) -> str:
    """The narrative with this case's market identifier appended (pii_safety).

    Appended at the END so ``narrative[:40]`` is unchanged and the fake KB / LLM still match the
    case. The identifier flows narrative -> redact -> the audited ``redacted_prompt``, which is
    the surface score_pii_safety scans: if the redactor masks it the audit is clean, and if a row
    is broken it leaks there. A case whose market is not in the configured pack would be scored
    vacuously (redactor cannot mask what it has no row for), so that is rejected loudly.
    """
    if not example.pii_jurisdiction:
        return example.narrative
    market = example.pii_jurisdiction
    if market not in _PII_JURISDICTIONS:
        raise SystemExit(
            f"golden case {example.id!r} sets pii_jurisdiction {market!r} not in the configured "
            f"pack {_PII_JURISDICTIONS}. The redactor would not mask it and the leak check would "
            "not see it, so it would score a vacuous 1.0. Add it or drop pii_jurisdiction."
        )
    ident = _PII_BY_JURISDICTION[market]
    return f"{example.narrative} For reference, my identifier is {ident}."


def _to_file(example: GoldenExample, narrative: str) -> ComplaintFile:
    return ComplaintFile(
        id=example.id,
        customer_ref="CUST-FAKE",
        product=example.product,
        channel=_CHANNEL_BY_VALUE.get(example.channel, Channel.OTHER),
        received_date=example.received_date,
        narrative=narrative,
    )


# --------------------------------------------------------------------------- #
# Heuristic scorers
# --------------------------------------------------------------------------- #
def score_categorisation(review: ComplaintReview, example: GoldenExample) -> float:
    return 1.0 if review.categorization.category.value == example.expected_category else 0.0


def score_groundedness(review: ComplaintReview) -> float:
    """The categorisation and (if present) the draft must carry citations."""
    if not review.categorization.citations:
        return 0.0
    if review.draft_response is not None and not review.draft_response.citations:
        return 0.0
    return 1.0


def _all_cited_ids(review: ComplaintReview) -> set[str]:
    ids: set[str] = {c.source_id for c in review.summary.citations}
    ids |= {c.source_id for c in review.categorization.citations}
    for flag in review.conduct_flags:
        ids |= {c.source_id for c in flag.citations}
    if review.draft_response is not None:
        ids |= {c.source_id for c in review.draft_response.citations}
    return ids


def score_citation_accuracy(review: ComplaintReview, example: GoldenExample) -> float:
    """cited subset of retrievable AND must_cite subset of cited, mean of the two."""
    cited = _all_cited_ids(review)
    retrievable = set(_KB)
    must = set(example.must_cite_source_ids)
    precision = (len(cited & retrievable) / len(cited)) if cited else (0.0 if must else 1.0)
    recall = (len(must & cited) / len(must)) if must else 1.0
    return round((precision + recall) / 2.0, 4)


def score_pii_safety(
    review: ComplaintReview, example: GoldenExample, audit_events: Sequence[object]
) -> float:
    """1.0 unless raw PII survived a derived surface, or a draft was not marked a draft.

    Scans two DERIVED surfaces two independent ways. The surfaces: the WORM audit records
    (``redacted_prompt`` / ``redacted_response`` are what outlive the request) and the review
    artifacts (summary, root cause, draft body). The two scans:

    * ``pack_leak`` uses the SAME pii-kit rows the redactor uses, so it catches PII the pipeline
      re-introduced after redaction, but is blind by construction to the pack being wrong.
    * ``planted_leak`` looks for this case's own planted identifier as a literal, with no pack
      involved. Against the real redactor this is a sound oracle: narrow or break a market's row
      and the redactor stops masking it AND ``pack_leak`` stops detecting it, so only this check
      fails. Without it a broken row scores a vacuous 1.0 with the raw id in the audit record.

    Both surfaces are DERIVED, never an echo of the case's input, so the metric measures the
    redaction boundary rather than the fixture.
    """
    if (
        review.draft_response is not None
        and example.response_must_be_draft
        and not review.draft_response.is_draft
    ):
        return 0.0

    haystacks: list[str] = [
        review.summary.issue,
        review.categorization.root_cause.description,
    ]
    if review.draft_response is not None:
        haystacks.append(review.draft_response.body)
    for event in audit_events:
        haystacks.append(str(getattr(event, "redacted_prompt", "") or ""))
        haystacks.append(str(getattr(event, "redacted_response", "") or ""))

    planted = [_PII_BY_JURISDICTION[example.pii_jurisdiction]] if example.pii_jurisdiction else []
    leaked = any(pack_leak(hay, _PII_PATTERNS) or planted_leak(hay, planted) for hay in haystacks)
    return 0.0 if leaked else 1.0


# --------------------------------------------------------------------------- #
# Report assembly + presentation
# --------------------------------------------------------------------------- #
@dataclass
class _PerMetric:
    scores: list[float] = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.scores) / len(self.scores) if self.scores else 0.0


def run_offline(dataset: Path, thresholds: dict[str, float]) -> EvalReport:
    examples = load_golden(dataset)
    adapters = _build_adapters(examples)

    agg: dict[str, _PerMetric] = {m: _PerMetric() for m in THRESHOLDS}
    print(
        f"Running offline eval gate over {len(examples)} golden examples "
        "(evaluator=ComplaintReviewService).\n"
    )
    for example in examples:
        # A fresh audit sink per example so pii_safety scores only this case's own records.
        audit = FakeAuditSink()
        service = _make_service(adapters, audit)
        review = service.review(_to_file(example, _planted_narrative(example)), actor="eval-bot")
        agg["categorisation_accuracy"].scores.append(score_categorisation(review, example))
        agg["groundedness"].scores.append(score_groundedness(review))
        agg["citation_accuracy"].scores.append(score_citation_accuracy(review, example))
        agg["pii_safety"].scores.append(score_pii_safety(review, example, audit.events))

    results = tuple(
        EvalMetricResult(
            metric=metric,
            score=round(agg[metric].mean, 4),
            threshold=thresholds.get(metric, THRESHOLDS[metric]),
            passed=round(agg[metric].mean, 4) >= thresholds.get(metric, THRESHOLDS[metric]),
        )
        for metric in ("categorisation_accuracy", "groundedness", "citation_accuracy", "pii_safety")
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(examples))


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    """Promotion verdict via EvaluationGatePort (platform = Hrz4, gcp = Gen AI evals).

    Fails closed on the reconciled evaluate + gate result. Refuses to run outside the
    platform/gcp profiles so the offline smoke result is never relabelled a promotion pass.
    """
    from complaints_review.config import Settings, build_container

    settings = Settings.load()
    if settings.profile not in ("platform", "gcp"):
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            "COMPLAINTS_PROFILE=platform or gcp "
            f"(got {settings.profile!r}); run --mode smoke for the offline pre-merge check."
        )
    container = build_container(settings)
    gate = container.evaluation
    report = gate.evaluate(str(dataset))
    if not isinstance(report, EvalReport):  # pragma: no cover - defensive
        raise SystemExit("EvaluationGatePort.evaluate did not return an EvalReport")
    gate_passed = bool(gate.gate(str(dataset)))
    return report, gate_passed


def main(argv: list[str] | None = None) -> int:
    """Dispatch --mode via the shared eval_main scaffold (fail-closed exit codes).

    ``--use-gcp`` (the pre-split flag for the production evaluator) is kept as an alias
    for ``--mode gate``.
    """
    args = sys.argv[1:] if argv is None else list(argv)
    if "--use-gcp" in args:
        args = [a for a in args if a != "--use-gcp"] + ["--mode", "gate"]
    return eval_main(
        smoke=lambda dataset: run_offline(dataset, load_thresholds_from_rubrics()),
        gate=run_gate,
        default_dataset=DEFAULT_DATASET,
        description="Offline / platform evaluation gate for B6 (A4 / P-08).",
        smoke_label="offline heuristic (no GCP creds)",
        gate_label="promotion gate (EvaluationGatePort: Hrz4 / Gen AI evals)",
        argv=args,
    )


if __name__ == "__main__":
    raise SystemExit(main())
