"""The grounded request must not sample by default.

The organization front page claims, for every repository here, that the consequential math is
deterministic and replayable and that the model "never produces the number". That sentence was
measured in exactly one tree, `cdd-sow-research`, because it is the only one with a paired
demonstration to measure it against, and there it was FALSE. On 2026-08-26 two runs of one
identical case against the deployment, minutes apart, returned `score` 0.5 then 0.0,
`confidence` 0.4 then 1.0, and four scorecard factors then none. The cause was not in any one
service: the shared request builder defaulted to `temperature=0.2`, so every grounded call
sampled.

This file is that finding applied here rather than left as one repository's history. The default
belongs on the grounded builder, because every grounded call site goes through it and one that
omits `temperature` inherits whatever the default is.

Since 2026-09-23 sampling is decided per call: the request TYPE defaults to `None`, which every
adapter turns into NO temperature (some models reject the parameter, so free is absent, never
`1.0`). The builder still pins, so freeing a grounded call is an explicit act at its call site;
only the drafted response does it (`tests/unit/test_answer_provenance.py`).

**Temperature 0 is not a promise of determinism, and nothing here asserts one.** A hosted model
can still vary across batching and model revisions. It is the strongest thing a caller controls,
and it is what makes a comparison between two profiles a measurement rather than a sample.
"""

from __future__ import annotations

import inspect

from complaints_review.domain import _grounded as _b0
from complaints_review.domain.kernel import LlmRequest


def test_the_request_type_leaves_sampling_to_the_call() -> None:
    """``None`` on the type means "send no temperature"; the builder below carries the pin."""
    assert LlmRequest.__dataclass_fields__["temperature"].default is None


def test_the_builder_in__grounded_0_does_not_sample_by_default() -> None:
    signature = inspect.signature(_b0.build_llm_request)

    assert signature.parameters["temperature"].default == 0.0
