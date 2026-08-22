"""Contract test: the platform eval adapter speaks A4 (Hrz4)'s hardened wire contract.

The ``platform`` profile delegates the promotion gate to the shared A4
``model-quality-gate`` service. This pins the request/response shape the adapter
sends and parses (SPEC §6, A4 contract), using ``respx`` to intercept the httpx calls:

* ``POST /v1/evaluations`` carries a structured ``target`` object, a top-level
  ``dataset_id`` that MUST equal ``target.dataset_id``, and ``bundle`` selecting the
  registered metric suite : never raw metric names (A4 422s on unknown metrics).
* the response's ``results[]`` list is parsed into a domain :class:`EvalReport`, and the
  evidence around it (how many examples, which run, which dataset digest, which evaluator,
  which artifacts, attested or not) has to be there for the parse to happen at all.
* ``gate`` POSTs (not GETs) ``/v1/gate`` and returns a verdict RE-DERIVED from a complete
  GateDecision, never the server's naked aggregate boolean.

The fixtures below model the full evidence because the hardened ``agent-eval-kit`` client
re-derives every verdict instead of trusting a flag: a metric row whose ``passed`` does not
equal ``score >= threshold``, a red-team aggregate that disagrees with its rows, or a
top-level verdict that disagrees with the assurance evidence all RAISE rather than parse.
That strictness is the point, so the refusal tests at the bottom are as much the contract as
the happy path: a promotion certified by ``{"passed": true}`` and nothing else is a
promotion certified by nothing.

Like the other offline tests this needs no Google Cloud SDK: the adapter is a thin httpx
client and respx mocks the transport.
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from complaints_review.adapters.platform.remote_evaluation import (
    RemoteEvaluationAdapter,
    RemoteEvaluationError,
)
from complaints_review.config import ModelSettings, Settings
from complaints_review.domain.models import EvalReport

_BASE = "https://hrz-quality.test"
_DATASET_PATH = "eval/datasets/golden_complaints.jsonl"
_DATASET_ID = "golden_complaints"  # basename without the .jsonl suffix
_MODEL = "gemini-3.5-flash"  # the pinned reasoning model

# The four A4 metric names the fixed adapter must NEVER put on the wire (selection is by
# bundle now; A4 422s on unregistered metric names).
_METRIC_NAMES = (
    "categorisation_accuracy",
    "groundedness",
    "citation_accuracy",
    "pii_safety",
)

#: Obviously fictional durable identifiers. Every one of these is REQUIRED: without them the
#: evidence names no run, no dataset state and no evaluator, so nobody could ever re-derive
#: the verdict from it later, which is the whole reason a promotion record exists.
_DIGEST = "sha256:feedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedfacefeedface"
_EVALUATOR = "hrz4-ai-quality (FICTIONAL)"
_DATASET_VERSION = "golden_complaints@2026-08-01"


def _eval_body(*, run_id: str, results: list[dict], attested: bool = True) -> dict:
    """A complete evaluation response in the hardened shape.

    ``passed`` is deliberately NOT sent: the client derives it from the rows, and sending a
    value that disagrees with them is a hard error rather than an override.
    """
    return {
        "results": results,
        "n_examples": 24,
        "run_id": run_id,
        "dataset_version": _DATASET_VERSION,
        "dataset_digest": _DIGEST,
        "evaluator": _EVALUATOR,
        "schema_version": "v1",
        "artifact_refs": [f"gs://fictional-hrz4-evidence/{run_id}/report.json"],
        "attested": attested,
    }


#: Every row is internally CONSISTENT (``passed`` equals ``score >= threshold``), because the
#: client re-derives each verdict and raises on contradiction rather than trusting the flag.
_PASSING_ROWS = [
    {"metric": "categorisation_accuracy", "score": 0.91, "threshold": 0.85, "passed": True},
    {"metric": "groundedness", "score": 0.95, "threshold": 0.80, "passed": True},
    {"metric": "citation_accuracy", "score": 0.93, "threshold": 0.90, "passed": True},
    {"metric": "pii_safety", "score": 1.0, "threshold": 0.99, "passed": True},
]

#: The same suite with one genuine miss. A gate that must return False has to reach False
#: through evidence like this, never through a body that merely claims it.
_FAILING_ROWS = [
    {"metric": "categorisation_accuracy", "score": 0.71, "threshold": 0.85, "passed": False},
    {"metric": "groundedness", "score": 0.95, "threshold": 0.80, "passed": True},
    {"metric": "citation_accuracy", "score": 0.93, "threshold": 0.90, "passed": True},
    {"metric": "pii_safety", "score": 1.0, "threshold": 0.99, "passed": True},
]

#: Red-team rows: ``passed`` and ``blocked`` must AGREE (an attack that was not blocked did
#: not pass), and the aggregate must equal the AND of the rows.
_REDTEAM_PASSING = {
    "passed": True,
    "results": [
        {"case": "prompt-injection-01", "passed": True, "blocked": True},
        {"case": "pii-exfil-01", "passed": True, "blocked": True},
    ],
}

_MODEL_CARD_REF = "gs://fictional-hrz4-evidence/model-cards/doc6-complaints-review.md"
_MRM_REF = "gs://fictional-hrz4-evidence/mrm/doc6-complaints-review-2026-08.json"


def _gate_body(*, passed: bool, rows: list[dict], attested: bool = True) -> dict:
    """The complete GateDecision the promotion gate demands, at every layer.

    The top-level ``passed`` must EQUAL (eval passed AND attested AND red team passed); the
    client recomputes it, so a body may not assert a verdict its own evidence contradicts.
    """
    return {
        "passed": passed,
        "eval_report": _eval_body(run_id="run-fictional-0001", results=rows, attested=attested),
        "redteam_report": _REDTEAM_PASSING,
        "model_card_ref": _MODEL_CARD_REF,
        "mrm_evidence_ref": _MRM_REF,
    }


def _adapter(monkeypatch: pytest.MonkeyPatch) -> RemoteEvaluationAdapter:
    monkeypatch.setenv("HRZ_QUALITY_URL", _BASE)
    settings = Settings(profile="platform", models=ModelSettings(reasoning=_MODEL))
    return RemoteEvaluationAdapter(settings)


def _sent_body(route: respx.Route) -> dict:
    assert route.called, "adapter never called the A4 endpoint"
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_evaluate_sends_structured_contract_and_parses_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(
            200,
            json=_eval_body(run_id="run-fictional-0002", results=_PASSING_ROWS[:2]),
        )
    )

    report = _adapter(monkeypatch).evaluate(_DATASET_PATH)
    body = _sent_body(route)

    # Only the three hardened keys are sent : no metric list of any kind.
    assert set(body) == {"target", "dataset_id", "bundle"}

    # Structured target with the pinned model + prompt version.
    target = body["target"]
    assert isinstance(target, dict)
    assert set(target) == {"model", "prompt_version", "dataset_id", "system"}
    assert target["model"] == _MODEL
    assert target["prompt_version"] == "v1"
    assert target["system"] == ""

    # Top-level dataset_id equals target.dataset_id, both = basename without .jsonl.
    assert body["dataset_id"] == _DATASET_ID
    assert body["dataset_id"] == target["dataset_id"]

    # Metric selection is by the registered bundle; no raw metric names on the wire.
    assert body["bundle"] == "doc6-complaints-review"
    serialised = json.dumps(body)
    for name in _METRIC_NAMES:
        assert name not in serialised, f"unregistered metric name {name!r} leaked into the request"

    # results[] parsed into a domain EvalReport, thresholds passed through unchanged.
    assert isinstance(report, EvalReport)
    assert report.dataset == _DATASET_PATH
    assert [r.metric for r in report.results] == ["categorisation_accuracy", "groundedness"]
    assert [r.score for r in report.results] == [0.91, 0.95]
    assert [r.threshold for r in report.results] == [0.85, 0.80]
    assert report.n_examples == 24
    assert report.passed is True

    # The attested evidence SURVIVES the adapter. This is the half a re-built report loses: a
    # mapper that copies dataset/results/n_examples onto a locally declared type silently drops
    # the run, the dataset state, the evaluator and the artifacts the client just validated, so
    # nobody could re-derive the verdict months later from what the port actually returned.
    assert report.run_id == "run-fictional-0002"
    assert report.dataset_version == _DATASET_VERSION
    assert report.dataset_digest == _DIGEST
    assert report.evaluator == _EVALUATOR
    assert report.schema_version == "v1"
    assert report.artifact_refs == ("gs://fictional-hrz4-evidence/run-fictional-0002/report.json",)
    assert report.attested is True


@respx.mock
def test_evaluate_REFUSES_scores_with_no_durable_run_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Passing metrics that name no run, digest or evaluator are not promotion evidence.

    The client enforces the durable identifiers on the plain evaluations path too, not
    only inside ``gate()``: a score nobody can trace back to a dataset state and an evaluator
    cannot be re-derived, so it cannot support a promotion decision months later.
    """
    thin = {"results": _PASSING_ROWS, "n_examples": 24}
    respx.post(f"{_BASE}/v1/evaluations").mock(return_value=httpx.Response(200, json=thin))
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).evaluate(_DATASET_PATH)


@respx.mock
def test_evaluate_REFUSES_a_row_whose_verdict_contradicts_its_score(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A row claiming PASS below its own bar is the failure mode a flag can always hide."""
    rows = [{"metric": "groundedness", "score": 0.41, "threshold": 0.80, "passed": True}]
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(200, json=_eval_body(run_id="run-fictional-0003", results=rows))
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).evaluate(_DATASET_PATH)


@respx.mock
def test_gate_posts_and_returns_true_only_on_a_full_consistent_decision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    route = respx.post(f"{_BASE}/v1/gate").mock(
        return_value=httpx.Response(200, json=_gate_body(passed=True, rows=_PASSING_ROWS))
    )

    assert _adapter(monkeypatch).gate(_DATASET_PATH) is True

    # It is a POST (not GET) to /v1/gate with the same hardened body.
    assert route.calls.last.request.method == "POST"
    body = _sent_body(route)
    assert set(body) == {"target", "dataset_id", "bundle"}
    assert body["bundle"] == "doc6-complaints-review"
    assert body["dataset_id"] == body["target"]["dataset_id"] == _DATASET_ID


@respx.mock
def test_gate_returns_false_when_a4_fails_the_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """A FAIL is reached through consistent evidence: one metric genuinely missed its bar."""
    respx.post(f"{_BASE}/v1/gate").mock(
        return_value=httpx.Response(200, json=_gate_body(passed=False, rows=_FAILING_ROWS))
    )
    assert _adapter(monkeypatch).gate(_DATASET_PATH) is False


@respx.mock
def test_gate_REFUSES_a_naked_boolean_with_no_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    """The unhardened response shape.

    Accepting it is how a promotion gets certified by nothing: an upstream that returns
    ``{"passed": true}`` for every target is indistinguishable from one that evaluated
    anything at all. The refusal IS the contract, not an inconvenience.
    """
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json={"passed": True}))
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET_PATH)


@respx.mock
def test_gate_REFUSES_an_unattested_report_even_when_every_metric_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unattested scores are a draft, not evidence, however good the numbers look."""
    respx.post(f"{_BASE}/v1/gate").mock(
        return_value=httpx.Response(
            200, json=_gate_body(passed=True, rows=_PASSING_ROWS, attested=False)
        )
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET_PATH)


@respx.mock
def test_gate_REFUSES_a_redteam_aggregate_that_contradicts_its_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A red-team summary saying PASS over a row that was not blocked is a rubber stamp."""
    body = _gate_body(passed=True, rows=_PASSING_ROWS)
    body["redteam_report"] = {
        "passed": True,
        "results": [
            {"case": "prompt-injection-01", "passed": True, "blocked": True},
            {"case": "pii-exfil-01", "passed": False, "blocked": False},
        ],
    }
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET_PATH)


@respx.mock
def test_gate_REFUSES_a_decision_with_no_model_card_or_mrm_reference(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model-risk sign-off has to point at something durable, or it points at nothing."""
    body = _gate_body(passed=True, rows=_PASSING_ROWS)
    body["mrm_evidence_ref"] = ""
    respx.post(f"{_BASE}/v1/gate").mock(return_value=httpx.Response(200, json=body))
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).gate(_DATASET_PATH)


@respx.mock
def test_non_2xx_raises_remote_evaluation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    # A4 rejects a divergent/invalid request with 422; the adapter surfaces its error type.
    respx.post(f"{_BASE}/v1/evaluations").mock(
        return_value=httpx.Response(422, text="dataset_id mismatch")
    )
    with pytest.raises(RemoteEvaluationError):
        _adapter(monkeypatch).evaluate(_DATASET_PATH)
