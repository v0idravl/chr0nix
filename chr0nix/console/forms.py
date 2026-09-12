"""Guided field-by-field forms: the console's "fill in the boxes" flow.

``subject add`` / ``vehicle add`` (and their ``edit`` counterparts)
walk a fixed list of profile fields, one prompt per typed line: a
self-explanatory label, a format hint, and the current value in
brackets when editing. Enter keeps the current value (or skips an empty
one); ``done`` saves immediately; ``cancel`` aborts without touching
the registry. Multi-value fields accept comma-separated input; a
long-form field (notes) offers ``:edit`` to compose in ``$EDITOR``
instead of typing inline.

Like every other console decision, this module is curses-free: a form
is a small state machine fed one line at a time, returning display
text. When a field wants the terminal editor the machine raises
:class:`EditorHandoff`, which the UI (or a test) answers by calling its
``resume`` callback with the edited text. Committing — the only write —
is a callback the command layer supplies, so the form itself never
touches the filesystem.
"""

from collections.abc import Callable

from ..casework.entities import ProfileField
from ..core.fields import clean_field
from ..errors import SuiteError

#: Sentinel a typed line (or a field value) can carry to ask for the
#: terminal editor instead of inline text — one convention across the
#: profile forms, `statement`, and `event`.
EDIT_SENTINEL = ":edit"


class EditorHandoff(Exception):
    """A command or form wants the terminal editor; the UI runs it.

    Raised out of :func:`chr0nix.console.commands.dispatch` exactly like
    ``ConsoleExit``/``ConsoleClear``: the curses UI catches it, suspends
    curses, runs :func:`chr0nix.core.editor.edit_text`, and calls
    ``resume(text)`` with the result (``None`` when the editor was
    aborted). ``resume`` returns ``(display_text, finished)`` —
    ``finished`` ends the active form (always True for one-shot
    handoffs outside a form). Tests drive the same path in-process:
    catch the handoff, call ``resume`` with stub text.
    """

    def __init__(
        self,
        *,
        label: str,
        initial_text: str = "",
        instructions: tuple[str, ...] = (),
        resume: Callable[[str | None], tuple[str, bool]],
    ) -> None:
        super().__init__(label)
        self.label = label
        self.initial_text = initial_text
        self.instructions = instructions
        self.resume = resume


def flatten_long_text(text: str) -> str:
    """The one-line form of editor-composed text, for single-line CSV fields.

    Registry and event-log fields are one line each (the append-only
    CSVs reject control characters), so a multi-line composition is
    flattened to ``"; "``-joined lines before storage.
    """
    return "; ".join(line.strip() for line in text.splitlines() if line.strip())


class GuidedForm:
    """A field-by-field prompt session over a fixed list of fields.

    ``fields`` are :class:`chr0nix.casework.entities.ProfileField`
    specs; ``values`` maps field name -> current stored string
    (``;``-joined for multi fields), prefilled when editing. ``commit``
    receives the final values mapping and returns the confirmation
    text; it is where — and only where — the profile is written.
    ``validators`` may hold per-field checks (e.g. slug rules and
    duplicate-id rejection for the id prompt) that run at entry time.
    """

    def __init__(
        self,
        *,
        title: str,
        fields: tuple[ProfileField, ...],
        values: dict[str, str] | None = None,
        commit: Callable[[dict[str, str]], str],
        validators: dict[str, Callable[[str], None]] | None = None,
    ) -> None:
        self.title = title
        self.fields = list(fields)
        self.values = dict(values or {})
        self.commit = commit
        self.validators = dict(validators or {})
        self.index = 0

    def start(self) -> str:
        """The intro text plus the first prompt."""
        lines = [
            self.title,
            "Enter keeps [current] / skips; `done` saves now; `cancel` aborts.",
            self._prompt(),
        ]
        return "\n".join(lines)

    def feed(self, line: str) -> tuple[str, bool]:
        """Feed one typed line; return (display text, form finished)."""
        text = line.strip()
        if text == "cancel":
            return "cancelled — no changes saved", True
        field = self.fields[self.index]
        if text == "done":
            return self._commit(), True
        if text == EDIT_SENTINEL:
            if not field.long:
                return (
                    f"{EDIT_SENTINEL} is only offered on long-form fields "
                    f"(this one is typed inline)\n{self._prompt()}",
                    False,
                )
            raise self._editor_handoff(field)
        if text:
            try:
                self._accept(field, text)
            except SuiteError as exc:
                # A bad entry re-prompts the same field — a typo costs
                # nothing, it must never lose the values already given.
                return f"error: {exc}\n{self._prompt()}", False
        return self._advance()

    # -- internals --------------------------------------------------------

    def _prompt(self) -> str:
        field = self.fields[self.index]
        parts = [f"[{self.index + 1}/{len(self.fields)}] {field.label}"]
        if field.hint:
            parts.append(f"({field.hint})")
        current = self.values.get(field.name, "")
        if current:
            shown = current.replace(";", ", ") if field.multi else current
            parts.append(f"[{shown}]")
        if field.long:
            parts.append(f"— or {EDIT_SENTINEL} for $EDITOR")
        return " ".join(parts) + ": "

    def _accept(self, field: ProfileField, text: str) -> None:
        validator = self.validators.get(field.name)
        if validator is not None:
            validator(text)
        if field.multi:
            items = [
                clean_field(item, field.name, required=False, error=SuiteError)
                for item in text.split(",")
            ]
            items = [item for item in items if item]
            for item in items:
                if ";" in item:
                    raise SuiteError(
                        f"{field.name} entries must not contain ';' "
                        "(it is the list separator in the registry file)"
                    )
            self.values[field.name] = ";".join(items)
        else:
            self.values[field.name] = clean_field(
                text, field.name, required=False, error=SuiteError
            )

    def _advance(self) -> tuple[str, bool]:
        self.index += 1
        if self.index >= len(self.fields):
            return self._commit(), True
        return self._prompt(), False

    def _commit(self) -> str:
        return self.commit(self.values)

    def _editor_handoff(self, field: ProfileField) -> EditorHandoff:
        current = self.values.get(field.name, "")

        def resume(text: str | None) -> tuple[str, bool]:
            if text is None:
                note = "editor aborted — kept the current value"
            else:
                flattened = flatten_long_text(text)
                if flattened:
                    self.values[field.name] = flattened
                note = (
                    f"{field.label.lower()} recorded via editor "
                    f"({len(flattened)} chars)"
                    if flattened
                    else "empty composition — kept the current value"
                )
            output, done = self._advance()
            return f"{note}\n{output}" if output else note, done

        return EditorHandoff(
            label=f"{field.label} ({field.name})",
            initial_text=current.replace("; ", "\n"),
            instructions=(
                f"Compose the {field.label.lower()} for this profile.",
                "Lines starting with # are instructions and are never saved.",
                "Save and exit to keep; exit without saving (or empty) to abort.",
            ),
            resume=resume,
        )
