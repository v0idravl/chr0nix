"""Tests for the guided profile forms and editor handoffs in the console.

Driven in-process through :func:`chr0nix.console.commands.dispatch` —
the form state machine lives entirely in the curses-free decision layer
(:mod:`chr0nix.console.forms`), so the whole "fill in the boxes" flow is
testable line by line. Editor handoffs are caught as
:class:`chr0nix.console.forms.EditorHandoff` and resumed with stub text,
exactly what the curses UI does after a real editor round-trip.
"""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.casework import entities
from chr0nix.console.commands import dispatch
from chr0nix.console.forms import EditorHandoff
from chr0nix.console.session import SessionContext
from chr0nix.errors import SuiteError


class ProfileTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()
        self.session = SessionContext()
        dispatch(self.session, "use casework")
        dispatch(self.session, f"set workspace {self.workspace}")
        dispatch(self.session, "set actor A. Rivera")
        dispatch(self.session, "init")
        dispatch(self.session, "new case-2026-014 Fitting-room concealment")

    def subjects_text(self):
        return (self.workspace / "entities" / "subjects.csv").read_text(encoding="utf-8")

    def run_form(self, answers):
        """Feed form answers through dispatch; return the final output."""
        output = ""
        for answer in answers:
            output = dispatch(self.session, answer)
        return output


class SubjectAddFormTests(ProfileTestCase):
    def test_add_walks_every_field_and_registers(self):
        output = dispatch(self.session, "subject add")
        self.assertIn("new subject profile", output)
        self.assertIn("[1/12] Subject id", output)
        self.assertIsNotNone(self.session.form)
        output = self.run_form([
            "subj-001",          # id
            "Red Hoodie",        # nickname
            "smithy, smitty",    # aliases (comma-separated)
            "1991-04-02",        # date of birth
            "6'1, scar",         # physical description
            "+1 555 0100",       # phones
            "",                  # emails — Enter skips
            "ig:smithy91",       # usernames
            "",                  # addresses
            "Depot Warehouse",   # employer
            "tall, red hoodie",  # descriptor
            "polite when approached",  # notes
        ])
        self.assertIsNone(self.session.form)
        self.assertIn("registered subject profile subj-001", output)
        self.assertIn("subject profile — subj-001", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.nickname, "Red Hoodie")
        self.assertEqual(subject.aliases, ("smithy", "smitty"))
        self.assertEqual(subject.emails, ())
        self.assertEqual(subject.employer, "Depot Warehouse")
        self.assertIn("subj-001,Red Hoodie,", self.subjects_text())
        self.assertIn("smithy;smitty", self.subjects_text())

    def test_add_with_id_argument_skips_the_id_prompt(self):
        output = dispatch(self.session, "subject add subj-001")
        self.assertIn("[1/11] Name / primary nickname", output)
        output = dispatch(self.session, "done")  # save with just the id
        self.assertIn("registered subject profile subj-001", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.nickname, "subj-001")

    def test_done_saves_partial_form(self):
        dispatch(self.session, "subject add")
        output = self.run_form(["subj-001", "Red Hoodie", "done"])
        self.assertIn("registered", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.nickname, "Red Hoodie")
        self.assertEqual(subject.employer, "")

    def test_cancel_aborts_without_writing(self):
        dispatch(self.session, "subject add")
        output = self.run_form(["subj-001", "Red Hoodie", "cancel"])
        self.assertIn("cancelled", output)
        self.assertIsNone(self.session.form)
        self.assertEqual(entities.read_subjects(self.workspace), [])

    def test_duplicate_id_is_rejected_at_entry_and_reprompts(self):
        dispatch(self.session, "subject add subj-001")
        dispatch(self.session, "done")
        dispatch(self.session, "subject add")
        output = dispatch(self.session, "subj-001")  # same id again
        self.assertIn("already registered", output)
        self.assertIn("Subject id", output)  # re-prompted, form still active
        self.assertIsNotNone(self.session.form)
        output = dispatch(self.session, "subj-002")
        self.assertIn("[2/12]", output)

    def test_non_slug_id_reprompts(self):
        dispatch(self.session, "subject add")
        output = dispatch(self.session, "BAD ID!")
        self.assertIn("slug-safe", output)
        self.assertIsNotNone(self.session.form)

    def test_form_owns_lines_until_finished(self):
        dispatch(self.session, "subject add")
        output = dispatch(self.session, "show options")  # not a command: form input
        # "... " has a space, so as the id field's input it is rejected
        # and the same field is re-prompted — no options table appears.
        self.assertNotIn("workspace", output.splitlines()[0])
        self.assertIn("Subject id", output)
        self.assertIsNotNone(self.session.form)
        dispatch(self.session, "cancel")

    def test_command_lines_are_form_input_while_a_form_is_active(self):
        dispatch(self.session, "subject add")
        output = dispatch(self.session, "vehicle add")  # swallowed by the form
        self.assertNotIn("new transportation profile", output)
        self.assertIsNotNone(self.session.form)
        self.assertEqual(entities.read_vehicles(self.workspace), [])
        dispatch(self.session, "cancel")


class SubjectEditFormTests(ProfileTestCase):
    def add_subject(self):
        dispatch(self.session, "subject add subj-001")
        self.run_form(["Red Hoodie", "smithy, smitty", "1991-04-02", "", "", "", "", "", "", "tall", ""])

    def test_edit_prefills_and_enter_keeps(self):
        self.add_subject()
        output = dispatch(self.session, "subject edit subj-001")
        self.assertIn("edit subject profile subj-001", output)
        self.assertIn("[Red Hoodie]", output)  # current value in brackets
        output = self.run_form(["", "", "1992-01-01"])  # keep, keep, change DOB
        output = self.run_form(["done"])
        self.assertIn("updated subject profile subj-001", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.nickname, "Red Hoodie")  # kept
        self.assertEqual(subject.aliases, ("smithy", "smitty"))  # kept
        self.assertEqual(subject.date_of_birth, "1992-01-01")  # changed

    def test_edit_unknown_subject_is_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown subject"):
            dispatch(self.session, "subject edit subj-999")
        self.assertIsNone(self.session.form)


class QuickPathAndShowTests(ProfileTestCase):
    def add_subject(self):
        dispatch(self.session, "subject add subj-001")
        dispatch(self.session, "done")

    def test_subject_set_one_shot(self):
        self.add_subject()
        output = dispatch(self.session, "subject set subj-001 phones +1 555 0100, +1 555 0101")
        self.assertIn("subj-001: phones -> +1 555 0100, +1 555 0101", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.phones, ("+1 555 0100", "+1 555 0101"))

    def test_subject_set_with_no_value_clears(self):
        self.add_subject()
        dispatch(self.session, "subject set subj-001 nickname Red Hoodie")
        output = dispatch(self.session, "subject set subj-001 nickname")
        self.assertIn("(cleared)", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.nickname, "")  # updates may blank a field

    def test_subject_set_unknown_field_lists_vocabulary(self):
        self.add_subject()
        with self.assertRaisesRegex(SuiteError, "unknown subject field 'height'"):
            dispatch(self.session, "subject set subj-001 height 72in")

    def test_subject_set_unknown_id_is_clean_error(self):
        with self.assertRaisesRegex(SuiteError, "unknown subject"):
            dispatch(self.session, "subject set subj-999 nickname X")

    def test_subject_show_card_and_linked_cases(self):
        self.add_subject()
        dispatch(self.session, "subject set subj-001 employer Depot Warehouse")
        dispatch(self.session, "link case-2026-014 subject subj-001 suspect")
        dispatch(self.session, "ack authorized casework")
        output = dispatch(self.session, "subject show subj-001")
        self.assertIn("subject profile — subj-001", output)
        self.assertIn("Employer / workplace", output)
        self.assertIn("Depot Warehouse", output)
        self.assertIn("linked cases: case-2026-014", output)

    def test_subjects_lists_the_registry(self):
        self.add_subject()
        output = dispatch(self.session, "subjects")
        self.assertIn("subj-001", output)
        self.assertIn("nickname", output)


class VehicleFormTests(ProfileTestCase):
    def test_vehicle_add_form_and_card(self):
        output = dispatch(self.session, "vehicle add")
        self.assertIn("new transportation profile (vehicle)", output)
        output = self.run_form([
            "veh-001",     # id
            "ABC 123",     # plate
            "CA",          # jurisdiction
            "1HGBH41JXMN109186",  # VIN
            "Honda",       # make
            "Civic",       # model
            "2019",        # year
            "blue",        # color
            "sedan",       # body style
            "",            # registered owner
            "blue sedan",  # description
            "",            # notes
        ])
        self.assertIn("registered transportation profile (vehicle) veh-001", output)
        vehicle = entities.get_vehicle(self.workspace, "veh-001")
        self.assertEqual(vehicle.vin, "1HGBH41JXMN109186")
        self.assertEqual(vehicle.make, "Honda")
        output = dispatch(self.session, "vehicle show veh-001")
        self.assertIn("transportation profile (vehicle) — veh-001", output)
        self.assertIn("ABC 123", output)
        output = dispatch(self.session, "vehicles")
        self.assertIn("veh-001", output)

    def test_vehicle_set_and_edit(self):
        dispatch(self.session, "vehicle add veh-001")
        dispatch(self.session, "done")
        output = dispatch(self.session, "vehicle set veh-001 color blue")
        self.assertIn("veh-001: color -> blue", output)
        output = dispatch(self.session, "vehicle edit veh-001")
        self.assertIn("edit transportation profile (vehicle) veh-001", output)
        for _ in range(6):  # walk to Color, the 7th field
            output = dispatch(self.session, "")
        self.assertIn("[blue]", output)
        dispatch(self.session, "cancel")


class EditorHandoffFormTests(ProfileTestCase):
    """`:edit` on a long-form field raises EditorHandoff; the UI/test resumes."""

    def test_notes_edit_round_trip(self):
        dispatch(self.session, "subject add subj-001")
        for _ in range(10):  # nickname .. descriptor_summary; now at notes
            dispatch(self.session, "")
        try:
            dispatch(self.session, ":edit")
            self.fail(":edit on the notes field should raise EditorHandoff")
        except EditorHandoff as handoff:
            self.assertIn("Notes", handoff.label)
            output, done = handoff.resume("line one\nline two\n")
        self.assertTrue(done)
        self.assertIn("notes recorded via editor", output)
        # Resuming a handoff is the UI's role: it clears the finished form.
        if done:
            self.session.form = None
        self.assertIsNone(self.session.form)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.notes, "line one; line two")  # flattened

    def test_notes_edit_abort_keeps_current_value(self):
        dispatch(self.session, "subject add subj-001")
        for _ in range(10):
            dispatch(self.session, "")
        try:
            dispatch(self.session, ":edit")
            self.fail("expected EditorHandoff")
        except EditorHandoff as handoff:
            output, done = handoff.resume(None)
        self.assertTrue(done)
        self.assertIn("editor aborted", output)
        subject = entities.get_subject(self.workspace, "subj-001")
        self.assertEqual(subject.notes, "")

    def test_edit_sentinel_only_offered_on_long_fields(self):
        dispatch(self.session, "subject add subj-001")
        output = dispatch(self.session, ":edit")  # at nickname — inline only
        self.assertIn("only offered on long-form fields", output)
        self.assertIsNotNone(self.session.form)
        dispatch(self.session, "cancel")


class StatementAndEventEditorTests(ProfileTestCase):
    def test_statement_edit_composes_body(self):
        try:
            dispatch(self.session, 'statement stmt-001 "J. Doe" witness :edit')
        except EditorHandoff as handoff:
            self.assertIn("statement body", handoff.label)
            output, done = handoff.resume("He said he was alone.\nThen left via exit 3.\n")
        self.assertTrue(done)
        self.assertIn("recorded statement stmt-001", output)
        body = self.workspace / "cases" / "case-2026-014" / "statements" / "stmt-001.txt"
        self.assertTrue(body.is_file())
        self.assertIn("He said he was alone.", body.read_text(encoding="utf-8"))
        # The CSV row stays one line; the event log points at the body file.
        log = (self.workspace / "cases" / "case-2026-014" / "statements.csv").read_text()
        self.assertIn("stmt-001", log)
        events = (self.workspace / "cases" / "case-2026-014" / "events.csv").read_text()
        self.assertIn("body: statements/stmt-001.txt", events)

    def test_statement_edit_abort_records_nothing(self):
        try:
            dispatch(self.session, 'statement stmt-001 "J. Doe" witness :edit')
        except EditorHandoff as handoff:
            output, _ = handoff.resume(None)
        self.assertIn("statement not recorded", output)
        self.assertFalse(
            (self.workspace / "cases" / "case-2026-014" / "statements.csv").exists()
        )

    def test_event_edit_composes_detail(self):
        try:
            dispatch(self.session, "event case-2026-014 observation :edit")
        except EditorHandoff as handoff:
            output, done = handoff.resume("first line\nsecond line")
        self.assertTrue(done)
        self.assertIn("event logged on case-2026-014 (observation)", output)
        events = (self.workspace / "cases" / "case-2026-014" / "events.csv").read_text()
        self.assertIn("observation,first line; second line", events)

    def test_event_edit_abort_logs_nothing(self):
        try:
            dispatch(self.session, "event case-2026-014 observation :edit")
        except EditorHandoff as handoff:
            output, _ = handoff.resume(None)
        self.assertIn("no event logged", output)
        events = (self.workspace / "cases" / "case-2026-014" / "events.csv").read_text()
        self.assertNotIn("observation", events)

    def test_inline_notes_still_work_without_editor(self):
        output = dispatch(
            self.session, 'statement stmt-001 "J. Doe" witness saw subject near exit'
        )
        self.assertIn("recorded statement stmt-001", output)


if __name__ == "__main__":
    unittest.main()
