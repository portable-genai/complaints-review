"""``complaints-review`` : the Typer CLI for the B6 service.

This is a thin presentation layer over the domain service. It owns no business logic:
every command builds the wiring from :func:`complaints_review.config.build_container` and
the factory functions in :mod:`complaints_review.api.deps`, invokes the review service,
and pretty-prints the cited result.

Design constraints honoured here:

* **Import-safe.** Importing this module (e.g. as the ``[project.scripts]`` entry point,
  or ``--help``) must never pull in FastAPI, uvicorn, the Google Cloud SDKs, or even the
  domain service. All of those are imported *lazily inside command bodies*, so the
  on-prem/test profile : which installs no Google Cloud SDK : can still load the CLI.
* **Profile-aware.** ``COMPLAINTS_PROFILE`` selects the adapter stack. The ``onprem``
  profile binds placeholder adapters that raise ``NotImplementedError``; the CLI maps that
  to a clean exit code 2 with a message that names the migration target.
* **Citations are first-class.** Every artifact is printed with provenance in
  ``source_id p.N : url`` form, because a conduct decision a reviewer cannot trace to a
  page is worthless.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import typer

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime top level
    from ..config import Container
    from ..domain.models import (
        Categorization,
        Citation,
        ComplaintFile,
        ComplaintReview,
        ComplaintSummary,
        ConductFlag,
        DraftResponse,
    )

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help=(
        "B6 Complaints & Conduct File Review : grounded, cited summary, categorisation, "
        "conduct flags and a draft regulator/customer response over a complaint file, on "
        "the Gemini Enterprise Agent Platform (region asia-southeast1)."
    ),
)

# Exit codes: 2 == the active profile cannot satisfy this command (e.g. on-prem stub);
# 1 == an unexpected adapter/runtime failure. 0 == success.
_PROFILE_EXIT = 2
_RUNTIME_EXIT = 1

_CLI_ACTOR = "cli:operator"


# --------------------------------------------------------------------------- #
# Wiring helpers (all imports lazy, so this module stays import-safe)
# --------------------------------------------------------------------------- #
def _container() -> Container:
    """Build the adapter container for the active ``COMPLAINTS_PROFILE``."""
    from ..config import build_container

    return build_container()


def _deps() -> Any:
    """Import the ``api.deps`` factory module lazily."""
    try:
        from ..api import deps  # type: ignore[attr-defined]
    except ImportError as exc:  # pragma: no cover - defensive wiring guard
        _fail(
            f"Service factories (complaints_review.api.deps) are unavailable: {exc}",
            code=_RUNTIME_EXIT,
        )
    return deps


def _fail(message: str, *, code: int = _RUNTIME_EXIT) -> Any:
    """Print a clean error to stderr and abort with ``code`` (no traceback)."""
    typer.secho(f"error: {message}", fg=typer.colors.RED, err=True)
    raise typer.Exit(code)


def _run(action: str, fn: Any) -> Any:
    """Execute ``fn`` and translate adapter failures into clean CLI errors.

    ``NotImplementedError`` (raised by every on-prem placeholder adapter) maps to a
    profile error that names the migration target; anything else surfaces as a runtime
    error. This is the single place the CLI turns exceptions into exit codes.
    """
    from ..config import Settings

    profile = Settings.load().profile
    try:
        return fn()
    except NotImplementedError as exc:
        detail = str(exc) or "method not implemented"
        _fail(
            f"'{action}' is not available under profile '{profile}'. "
            f"This profile uses placeholder adapters (on-prem migration target): {detail}",
            code=_PROFILE_EXIT,
        )
    except KeyError as exc:
        _fail(
            f"'{action}' has no adapter wired for profile '{profile}': {exc}",
            code=_PROFILE_EXIT,
        )
    except typer.Exit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary: no tracebacks to operators
        _fail(f"'{action}' failed: {type(exc).__name__}: {exc}", code=_RUNTIME_EXIT)


# --------------------------------------------------------------------------- #
# Pretty-printing
# --------------------------------------------------------------------------- #
def _fmt_citation(c: Citation) -> str:
    """Render one citation as ``[source_id, TYPE p.N] : url``."""
    page = f" p.{c.page}" if c.page is not None else ""
    src_type = c.source_type.value if hasattr(c.source_type, "value") else str(c.source_type)
    return f"[{c.source_id}, {src_type}{page}] : {c.url}"


def _echo_citations(citations: tuple[Citation, ...], indent: str = "  ") -> None:
    if not citations:
        typer.secho(f"{indent}(no citations)", fg=typer.colors.YELLOW)
        return
    typer.secho(f"{indent}Citations:", bold=True)
    for c in citations:
        typer.echo(f"{indent}  - {_fmt_citation(c)}")


def _echo_review_banner() -> None:
    typer.secho(
        "  [HUMAN REVIEW REQUIRED] maker-checker gate (P-06). The draft response is a "
        "DRAFT and is never sent by the system; a human reviews and sends it.",
        fg=typer.colors.YELLOW,
        bold=True,
    )


def _print_summary(summary: ComplaintSummary, indent: str = "") -> None:
    typer.secho(f"{indent}Summary", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"{indent}  issue: {summary.issue}")
    if summary.products:
        typer.echo(f"{indent}  products: {', '.join(summary.products)}")
    typer.echo(f"{indent}  channel: {summary.channel.value}")
    if summary.timeline:
        typer.secho(f"{indent}  timeline:", bold=True)
        for ev in summary.timeline:
            typer.echo(f"{indent}    {ev.date}: {ev.event}")
    if summary.parties:
        typer.echo(f"{indent}  parties: {', '.join(summary.parties)}")
    _echo_citations(summary.citations, indent=indent + "  ")


def _print_categorization(c: Categorization, indent: str = "") -> None:
    typer.secho(f"{indent}Categorisation", bold=True, fg=typer.colors.GREEN)
    typer.echo(f"{indent}  category: {c.category.value}  (severity: {c.severity.value})")
    systemic = "yes" if c.root_cause.systemic else "no"
    typer.echo(f"{indent}  root cause: {c.root_cause.description}  (systemic: {systemic})")
    if c.regulatory_relevance:
        typer.echo(f"{indent}  regulatory relevance: {', '.join(c.regulatory_relevance)}")
    _echo_citations(c.citations, indent=indent + "  ")


def _print_conduct_flags(flags: tuple[ConductFlag, ...], indent: str = "") -> None:
    typer.secho(f"{indent}Conduct flags ({len(flags)})", bold=True, fg=typer.colors.GREEN)
    if not flags:
        typer.secho(f"{indent}  (none)", fg=typer.colors.BRIGHT_BLACK)
        return
    for flag in flags:
        typer.secho(
            f"{indent}  [{flag.kind.value}] ({flag.severity.value}) {flag.detail}", bold=True
        )
        _echo_citations(flag.citations, indent=indent + "    ")


def _print_draft(draft: DraftResponse, indent: str = "") -> None:
    typer.secho(f"{indent}Draft response", bold=True, fg=typer.colors.GREEN)
    typer.secho(
        f"{indent}  tone: {draft.tone}  (is_draft: {str(draft.is_draft).lower()})", bold=True
    )
    typer.echo("")
    for line in draft.body.splitlines():
        typer.echo(f"{indent}  {line}")
    typer.echo("")
    _echo_citations(draft.citations, indent=indent + "  ")


def _print_review(review: ComplaintReview) -> None:
    typer.secho(f"Complaint review : {review.file_id}", bold=True, fg=typer.colors.CYAN)
    _echo_review_banner()
    typer.echo("")
    _print_summary(review.summary)
    typer.echo("")
    _print_categorization(review.categorization)
    typer.echo("")
    _print_conduct_flags(review.conduct_flags)
    if review.draft_response is not None:
        typer.echo("")
        _print_draft(review.draft_response)


# --------------------------------------------------------------------------- #
# Commands
# --------------------------------------------------------------------------- #
def _build_file(
    file_id: str,
    narrative: str,
    product: str,
    channel: str,
    received_date: str,
    customer_ref: str,
) -> ComplaintFile:
    from ..domain.models import Channel, ComplaintFile

    channel_enum = {c.value: c for c in Channel}.get(channel.lower(), Channel.OTHER)
    return ComplaintFile(
        id=file_id,
        customer_ref=customer_ref,
        product=product,
        channel=channel_enum,
        received_date=received_date,
        narrative=narrative,
    )


@app.command()
def review(
    file_id: str = typer.Argument(..., help="The complaint file identifier."),
    narrative: str = typer.Option(..., "--narrative", "-n", help="The complaint narrative."),
    product: str = typer.Option("", "--product", "-p", help="The product complained about."),
    channel: str = typer.Option(
        "other", "--channel", "-c", help="Channel the complaint arrived on."
    ),
    received_date: str = typer.Option(
        "", "--received", help="ISO date the complaint was received."
    ),
    customer_ref: str = typer.Option("", "--customer-ref", help="Pseudonymous customer reference."),
) -> None:
    """Produce a full cited complaint review (summary, categorisation, flags, draft)."""

    def _do() -> ComplaintReview:
        svc = _deps().build_review_service(_container())
        file = _build_file(file_id, narrative, product, channel, received_date, customer_ref)
        return svc.review(file, actor=_CLI_ACTOR)

    result = _run("review", _do)
    _print_review(result)


@app.command()
def summary(
    file_id: str = typer.Argument(..., help="The complaint file identifier."),
    narrative: str = typer.Option(..., "--narrative", "-n", help="The complaint narrative."),
    product: str = typer.Option("", "--product", "-p", help="The product complained about."),
    channel: str = typer.Option(
        "other", "--channel", "-c", help="Channel the complaint arrived on."
    ),
    received_date: str = typer.Option(
        "", "--received", help="ISO date the complaint was received."
    ),
    customer_ref: str = typer.Option("", "--customer-ref", help="Pseudonymous customer reference."),
) -> None:
    """Produce only the structured complaint-file summary."""

    def _do() -> ComplaintSummary:
        svc = _deps().build_review_service(_container())
        file = _build_file(file_id, narrative, product, channel, received_date, customer_ref)
        return svc.summarize(file, actor=_CLI_ACTOR)

    result = _run("summary", _do)
    _print_summary(result)


@app.command(name="draft-response")
def draft_response(
    file_id: str = typer.Argument(..., help="The complaint file identifier."),
    narrative: str = typer.Option(..., "--narrative", "-n", help="The complaint narrative."),
    product: str = typer.Option("", "--product", "-p", help="The product complained about."),
    channel: str = typer.Option(
        "other", "--channel", "-c", help="Channel the complaint arrived on."
    ),
    received_date: str = typer.Option(
        "", "--received", help="ISO date the complaint was received."
    ),
    customer_ref: str = typer.Option("", "--customer-ref", help="Pseudonymous customer reference."),
) -> None:
    """Produce only the draft regulator/customer response (a draft, never sent)."""

    def _do() -> DraftResponse:
        svc = _deps().build_review_service(_container())
        file = _build_file(file_id, narrative, product, channel, received_date, customer_ref)
        return svc.draft_response(file, actor=_CLI_ACTOR)

    result = _run("draft-response", _do)
    _echo_review_banner()
    _print_draft(result)


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address for the API server."),
    port: int = typer.Option(8095, help="TCP port for the API server."),
    reload: bool = typer.Option(False, "--reload", help="Auto-reload on code change (dev only)."),
) -> None:
    """Run the FastAPI app (A2A card, MCP, and REST endpoints) under uvicorn."""

    def _do() -> None:
        import uvicorn

        deps = _deps()
        if not hasattr(deps, "create_app"):
            _fail(
                "complaints_review.api.deps does not expose create_app(); cannot start the server.",
                code=_RUNTIME_EXIT,
            )
        typer.secho(
            f"serving complaints-review on http://{host}:{port} (profile={_profile_label()})",
            fg=typer.colors.GREEN,
        )
        uvicorn.run(
            "complaints_review.api.deps:create_app",
            factory=True,
            host=host,
            port=port,
            reload=reload,
        )

    _run("serve", _do)


@app.command()
def eval(  # noqa: A001 - "eval" is the documented command name in SPEC
    dataset: str | None = typer.Option(
        None,
        "--dataset",
        "-d",
        help="Path to the golden eval dataset (defaults to the gate's bundled set).",
    ),
) -> None:
    """Run the A4 promotion eval gate (categorisation / groundedness / citations / PII)."""

    def _do() -> int:
        import subprocess
        import sys
        from pathlib import Path

        repo_root = Path(__file__).resolve().parents[3]
        script = repo_root / "eval" / "run_eval.py"
        if not script.exists():
            _fail(f"eval gate script not found at {script}", code=_RUNTIME_EXIT)
        cmd = [sys.executable, str(script)]
        if dataset:
            cmd += ["--dataset", dataset]
        typer.secho(f"running eval gate: {script}", fg=typer.colors.CYAN)
        completed = subprocess.run(cmd, check=False)  # noqa: S603 - trusted local script
        return completed.returncode

    code = _run("eval", _do)
    if code == 0:
        typer.secho("eval gate: PASS", fg=typer.colors.GREEN, bold=True)
    else:
        typer.secho("eval gate: FAIL", fg=typer.colors.RED, bold=True)
    raise typer.Exit(int(code))


def _profile_label() -> str:
    from ..config import Settings

    return Settings.load().profile


if __name__ == "__main__":  # pragma: no cover
    app()
