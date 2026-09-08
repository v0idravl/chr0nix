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

``set output`` also *proposes* ``manifest`` and ``log`` paths inside the
output directory when they are unset — the conventional layout the CLI
examples use. Proposals are plain assignments (the manifest may not
exist yet; the first ``run`` creates it), and an explicit ``set``
always overrides them.
"""

from dataclasses import dataclass
from pathlib import Path

from cust0dia.paths import is_within

from ..errors import SuiteError

#: Session option names accepted by ``set`` / ``unset``, in the order
#: ``show options`` reports them.
OPTION_NAMES = ("evidence", "output", "manifest", "log", "actor")


def _check_free_text(value: str, what: str) -> str:
    """Reject control characters in a free-text session value.

    The actor name ends up in the custody log, where one event must
    always be one line; the same no-control-characters rule the log
    writer enforces is applied here so a bad actor name fails at
    ``set`` time, not mid-logging.
    """
    cleaned = value.strip()
    if any(ord(char) < 32 or ord(char) == 127 for char in cleaned):
        raise SuiteError(f"{what} must not contain control characters")
    if not cleaned:
        raise SuiteError(f"{what} must not be empty")
    return cleaned


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
        for label, existing in (("output", self.output_dir), ("log", self.custody_log)):
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
