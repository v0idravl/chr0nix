"""Session context: the console's shared case state.

The session is the console's analogue of a metasploit workspace: the
set of paths and identity values every tool shares, so an investigator
points at a case once and then works — manifest, verify, log — without
re-typing paths on every command.

Every setter validates eagerly, at ``set`` time rather than at ``run``
time. That is a deliberate ergonomic and safety choice: an investigator
should learn immediately that a path is wrong or unsafe, not after
composing the rest of a command. The safety rules enforced here are the
same ones the module CLIs enforce at dispatch:

- ``evidence`` must be an existing directory.
- ``output`` and ``log`` must never resolve inside the evidence tree
  (the cardinal "read-only on evidence" rule).
- ``manifest`` must be an existing file when set explicitly.
- ``log`` must never be the same file as ``manifest``.
- ``workspace`` must be an existing directory that is either an
  initialized casework workspace or empty enough to ``init``, and like
  the other writable paths it must never resolve inside the evidence
  tree.

``set output`` also *proposes* ``manifest`` and ``log`` paths inside the
output directory when they are unset — the conventional layout the CLI
examples use. Proposals are plain assignments (the manifest may not
exist yet; the first ``run`` creates it), and an explicit ``set``
always overrides them.
"""

from dataclasses import dataclass
from pathlib import Path

from ..core import fields as _core_fields
from ..core.safety import is_within
from ..errors import SuiteError
from ..tiers import PendingAction

#: Session option names accepted by ``set`` / ``unset``, in the order
#: ``show options`` reports them.
OPTION_NAMES = ("evidence", "output", "manifest", "log", "actor", "workspace")

#: One-line description per option, for the ``show options`` table.
OPTION_DESCRIPTIONS: dict[str, str] = {
    "evidence": "the case's evidence tree (read-only; must exist)",
    "output": "where tools write; proposes manifest/log paths when set",
    "manifest": "the cust0dia manifest (proposed inside output)",
    "log": "the custody log (proposed inside output; never the manifest)",
    "actor": "the operator's name, recorded in custody/event/attestation logs",
    "workspace": "the casework workspace (casework's `init` creates the layout)",
}


def _check_free_text(value: str, what: str) -> str:
    """Reject control characters in a free-text session value.

    The actor name ends up in the custody log, where one event must
    always be one line; the same no-control-characters rule the log
    writer enforces is applied here so a bad actor name fails at
    ``set`` time, not mid-logging.
    """
    return _core_fields.clean_field(value, what, required=True, error=SuiteError)


@dataclass
class SessionContext:
    """Shared case state for one console session.

    Mutable by design: a session is a working context that evolves as
    the investigator moves through a case, not a record of fact like
    :class:`cust0dia.manifest.ManifestEntry`. All mutations go through
    :meth:`set_option` and :meth:`unset_option` so validation is never
    bypassed.
    """

    evidence_dir: Path | None = None
    output_dir: Path | None = None
    manifest_path: Path | None = None
    custody_log: Path | None = None
    actor: str | None = None
    active_tool: str | None = None
    workspace: Path | None = None
    #: The casework tool's default case. A plain attribute, not an
    #: option: it changes far too often for `set`, and the casework
    #: commands validate it themselves when they use it.
    active_case: str | None = None
    #: The one YELLOW action awaiting `ack`, set by the challenge and
    #: cleared by `ack` or by any other command. A plain attribute:
    #: only the command layer's challenge/ack flow mutates it.
    pending_action: PendingAction | None = None
    #: The active guided form (subject/vehicle profile editing), a
    #: chr0nix.console.forms.GuidedForm. While set, every typed line is
    #: form input, not a command. A plain attribute: only the command
    #: layer's form flow mutates it. Typed as object to keep session
    #: importable without the forms module.
    form: object | None = None

    def set_option(self, name: str, value: str) -> str:
        """Validate and store one option; return a confirmation message.

        Unknown option names and invalid values raise
        :class:`SuiteError` — the command layer lets it propagate to
        the UI, which renders it as a clean one-line error.
        """
        handler = {
            "evidence": self._set_evidence,
            "output": self._set_output,
            "manifest": self._set_manifest,
            "log": self._set_log,
            "actor": self._set_actor,
            "workspace": self._set_workspace,
        }.get(name)
        if handler is None:
            raise SuiteError(
                f"unknown option {name!r}; expected one of: {', '.join(OPTION_NAMES)}"
            )
        return handler(value)

    def unset_option(self, name: str) -> str:
        """Clear one option (``actor`` included); return a confirmation."""
        attribute = {
            "evidence": "evidence_dir",
            "output": "output_dir",
            "manifest": "manifest_path",
            "log": "custody_log",
            "actor": "actor",
            "workspace": "workspace",
        }.get(name)
        if attribute is None:
            raise SuiteError(
                f"unknown option {name!r}; expected one of: {', '.join(OPTION_NAMES)}"
            )
        setattr(self, attribute, None)
        return f"{name} unset"

    def describe_options(self) -> list[tuple[str, str]]:
        """``(name, value-or-placeholder)`` pairs for ``show options``."""
        pairs: list[tuple[str, str]] = []
        for name in OPTION_NAMES:
            value = {
                "evidence": self.evidence_dir,
                "output": self.output_dir,
                "manifest": self.manifest_path,
                "log": self.custody_log,
                "actor": self.actor,
                "workspace": self.workspace,
            }[name]
            pairs.append((name, str(value) if value is not None else "(unset)"))
        return pairs

    def _set_evidence(self, value: str) -> str:
        path = Path(value).expanduser()
        if not path.exists():
            raise SuiteError(f"evidence directory does not exist: {value}")
        if not path.is_dir():
            raise SuiteError(f"evidence directory is not a directory: {value}")
        resolved = path.resolve()
        # Pointing at a new evidence tree must not silently legitimize
        # outputs that would now land inside it.
        for label, existing in (
            ("output", self.output_dir),
            ("log", self.custody_log),
            ("workspace", self.workspace),
        ):
            if existing is not None and is_within(existing, resolved):
                raise SuiteError(
                    f"refusing: the current {label} path {existing} would be inside "
                    f"the evidence directory {resolved}; unset it first"
                )
        self.evidence_dir = resolved
        return f"evidence -> {resolved}"

    def _set_output(self, value: str) -> str:
        resolved = Path(value).expanduser().resolve()
        if self.evidence_dir is not None and is_within(resolved, self.evidence_dir):
            raise SuiteError(
                f"refusing to write into the evidence directory: {resolved} "
                f"is inside {self.evidence_dir}"
            )
        self.output_dir = resolved
        lines = [f"output -> {resolved}"]
        # Propose the conventional layout for unset follow-on paths.
        # These are proposals, not validations: the manifest may not
        # exist until the first ``run`` creates it.
        if self.manifest_path is None:
            self.manifest_path = resolved / "manifest.json"
            lines.append(f"manifest -> {self.manifest_path} (proposed)")
        if self.custody_log is None:
            self.custody_log = resolved / "custody-log.csv"
            lines.append(f"log -> {self.custody_log} (proposed)")
        return "\n".join(lines)

    def _set_manifest(self, value: str) -> str:
        path = Path(value).expanduser()
        if not path.exists():
            raise SuiteError(f"manifest does not exist: {value}")
        if not path.is_file():
            raise SuiteError(f"manifest is not a regular file: {value}")
        resolved = path.resolve()
        if resolved == self.custody_log:
            raise SuiteError("the custody log and the manifest must be different files")
        self.manifest_path = resolved
        return f"manifest -> {resolved}"

    def _set_log(self, value: str) -> str:
        resolved = Path(value).expanduser().resolve()
        if resolved == self.manifest_path:
            raise SuiteError("the custody log and the manifest must be different files")
        if self.evidence_dir is not None and is_within(resolved, self.evidence_dir):
            raise SuiteError(
                f"refusing to write into the evidence directory: {resolved} "
                f"is inside {self.evidence_dir}"
            )
        self.custody_log = resolved
        return f"log -> {resolved}"

    def _set_actor(self, value: str) -> str:
        self.actor = _check_free_text(value, "actor")
        return f"actor -> {self.actor}"

    def _set_workspace(self, value: str) -> str:
        """Point the session at a casework workspace directory.

        The directory must exist and be either an initialized workspace
        (it contains ``config/``) or empty — the state in which
        casework's ``init`` can create the layout without adopting a
        directory full of unrelated content. Like every other writable
        path in the session, it must never resolve inside the evidence
        tree: a workspace is case work product, and work product is
        written.
        """
        path = Path(value).expanduser()
        if not path.exists():
            raise SuiteError(f"workspace directory does not exist: {value}")
        if not path.is_dir():
            raise SuiteError(f"workspace is not a directory: {value}")
        resolved = path.resolve()
        if self.evidence_dir is not None and is_within(resolved, self.evidence_dir):
            raise SuiteError(
                f"refusing to write into the evidence directory: {resolved} "
                f"is inside {self.evidence_dir}"
            )
        if not (resolved / "config").is_dir() and any(resolved.iterdir()):
            raise SuiteError(
                f"refusing {resolved} as a workspace: it is not empty and has no "
                "config/ directory — point at an initialized workspace, or at an "
                "empty directory and run casework's `init`"
            )
        self.workspace = resolved
        return f"workspace -> {resolved}"
