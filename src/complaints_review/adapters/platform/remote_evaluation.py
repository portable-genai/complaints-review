"""Remote-platform evaluation adapter : thin HTTP client to Hrz4.

At promotion this vertical's quality is checked against the shared **Hrz4 AI Quality /
model-risk** service (``model-quality-gate``). This adapter implements
:class:`EvaluationGatePort` against Hrz4's hardened contract:

* ``evaluate`` -> ``POST /v1/evaluations {target, dataset_id, bundle}`` -> EvalReport.
* ``gate``     -> ``POST /v1/gate {target, dataset_id, bundle}`` -> ``{passed}``.

**Sourced from the shared ``agent-eval-kit`` commons.** The HTTP contract
is ``agent_eval_kit.gate_client.PromotionGateClient``; this adapter configures it (the
registered ``doc6-complaints-review`` bundle, the reasoning model, and this repo's S2S auth
headers) and re-raises its errors as :class:`RemoteEvaluationError`.

It returns the client's :class:`EvalReport` UNCHANGED. Rebuilding a locally declared report
from three of its fields would be a lossy identity function: it drops exactly the attested
evidence the client had just validated (the run id, the dataset version and digest, the
evaluator, the artifact refs, the attestation flag), so the port would hand back scores
nobody could re-derive a promotion decision from months later.
"""

from __future__ import annotations

from agent_eval_kit.gate_client import GateClientError, PromotionGateClient

from ...config import Settings
from ...domain.errors import ComplaintsError
from ...domain.models import EvalReport
from ...envread import setting_or_default
from . import _s2s

_DEFAULT_URL = "http://localhost:8084"

#: The registered Hrz4 metric bundle for this vertical (Hrz4 owns the metrics + bars).
_BUNDLE = "doc6-complaints-review"
#: Prompt/agent version tag; bump when the prompt corpus changes, or source it from a registry.
_PROMPT_VERSION = "v1"


class RemoteEvaluationError(ComplaintsError):
    """Raised when the Hrz4 quality service returns a non-2xx response."""


class RemoteEvaluationAdapter:
    """HTTP client for the Hrz4 ``model-quality-gate`` service (via PromotionGateClient)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = PromotionGateClient(
            setting_or_default("QUALITY_GATE_URL", _DEFAULT_URL),
            bundle=_BUNDLE,
            model=settings.models.reasoning,
            prompt_version=_PROMPT_VERSION,
            auth_headers=lambda: _s2s.headers(),
        )

    def evaluate(self, dataset_path: str) -> EvalReport:
        """Score ``dataset_path`` via Hrz4 and return the report Hrz4 attested, unchanged."""
        try:
            return self._client.evaluate(dataset_path)
        except GateClientError as exc:
            raise RemoteEvaluationError(str(exc)) from exc

    def gate(self, target: str) -> bool:
        """Promotion gate: True iff Hrz4 reports ``target`` passes."""
        try:
            return self._client.gate(target)
        except GateClientError as exc:
            raise RemoteEvaluationError(str(exc)) from exc
