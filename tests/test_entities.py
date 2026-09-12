"""Tests for the casework entity layer (chr0nix/casework/entities.py).

Covers the rich Phase 4 profiles: full-field round-trips, multi-value
fields, profile updates, the legacy (three-column) registry upgrade on
first write, and the aligned profile cards. Driven against a
TemporaryDirectory workspace, no console involved.
"""

import csv
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from chr0nix.casework import CaseworkError
from chr0nix.casework import entities, workspace as workspace_mod


class EntityTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.workspace = Path(self._tmp.name) / "ws"
        self.workspace.mkdir()
        workspace_mod.init_workspace(self.workspace)

    def subjects_path(self):
        return self.workspace / "entities" / "subjects.csv"

    def vehicles_path(self):
        return self.workspace / "entities" / "vehicles.csv"

    def rows(self, path):
        with path.open("r", newline="", encoding="utf-8") as handle:
            return list(csv.reader(handle))


class SubjectProfileTests(EntityTestCase):
    def test_full_profile_round_trip(self):
        entities.register_subject(
            self.workspace, "subj-001",
            nickname="Red Hoodie", descriptor_summary="tall, red hoodie",
            aliases=["smithy", "smitty"], date_of_birth="1991-04-02",
            physical_description="6'1, scar left brow",
            phones=["+1 555 0100", "+1 555 0101"],
            emails=["smith@example.com"],
            usernames=["ig:smithy91", "x:smitty"],
            addresses=["12 Main St, Apt 4"],
            employer="Depot Warehouse", notes="polite when approached",
        )
        (subject,) = entities.read_subjects(self.workspace)
        self.assertEqual(subject.subject_id, "subj-001")
        self.assertEqual(subject.nickname, "Red Hoodie")
        self.assertEqual(subject.aliases, ("smithy", "smitty"))
        self.assertEqual(subject.date_of_birth, "1991-04-02")
        self.assertEqual(subject.physical_description, "6'1, scar left brow")
        self.assertEqual(subject.phones, ("+1 555 0100", "+1 555 0101"))
        self.assertEqual(subject.emails, ("smith@example.com",))
        self.assertEqual(subject.usernames, ("ig:smithy91", "x:smitty"))
        self.assertEqual(subject.addresses, ("12 Main St, Apt 4",))
        self.assertEqual(subject.employer, "Depot Warehouse")
        self.assertEqual(subject.notes, "polite when approached")

    def test_multi_fields_store_semicolon_joined_one_line(self):
        entities.register_subject(self.workspace, "subj-001", aliases=["a", "b"])
        row = self.rows(self.subjects_path())[1]
        self.assertEqual(len(row), len(entities.SUBJECT_FIELDS))
        self.assertEqual(row[3], "a;b")

    def test_multi_entry_separator_is_rejected(self):
        with self.assertRaisesRegex(CaseworkError, "list separator"):
            entities.register_subject(self.workspace, "subj-001", aliases=["a;b"])

    def test_blank_multi_entries_are_dropped(self):
        entities.register_subject(self.workspace, "subj-001", phones=["", "+1 555 0100", " "])
        (subject,) = entities.read_subjects(self.workspace)
        self.assertEqual(subject.phones, ("+1 555 0100",))

    def test_duplicate_id_still_rejected(self):
        entities.register_subject(self.workspace, "subj-001")
        with self.assertRaisesRegex(CaseworkError, "already registered"):
            entities.register_subject(self.workspace, "subj-001")

    def test_default_nickname_is_the_id(self):
        subject = entities.register_subject(self.workspace, "subj-001")
        self.assertEqual(subject.nickname, "subj-001")


class VehicleProfileTests(EntityTestCase):
    def test_full_profile_round_trip(self):
        entities.register_vehicle(
            self.workspace, "veh-001",
            plate="ABC 123", description="blue sedan", jurisdiction="CA",
            vin="1HGBH41JXMN109186", make="Honda", model="Civic", year="2019",
            color="blue", body_style="sedan", registered_owner="J. Doe",
            notes="bumper sticker: fish",
        )
        (vehicle,) = entities.read_vehicles(self.workspace)
        self.assertEqual(vehicle.plate, "ABC 123")
        self.assertEqual(vehicle.jurisdiction, "CA")
        self.assertEqual(vehicle.vin, "1HGBH41JXMN109186")
        self.assertEqual(vehicle.make, "Honda")
        self.assertEqual(vehicle.model, "Civic")
        self.assertEqual(vehicle.year, "2019")
        self.assertEqual(vehicle.color, "blue")
        self.assertEqual(vehicle.body_style, "sedan")
        self.assertEqual(vehicle.registered_owner, "J. Doe")
        self.assertEqual(vehicle.notes, "bumper sticker: fish")
        row = self.rows(self.vehicles_path())[1]
        self.assertEqual(len(row), len(entities.VEHICLE_FIELDS))


class UpdateTests(EntityTestCase):
    def test_update_replaces_one_row_and_keeps_the_rest(self):
        entities.register_subject(self.workspace, "subj-001", nickname="One")
        entities.register_subject(self.workspace, "subj-002", nickname="Two")
        updated = entities.update_subject(
            self.workspace, "subj-001", employer="Depot Warehouse",
            phones=["+1 555 0100"],
        )
        self.assertEqual(updated.employer, "Depot Warehouse")
        subjects = {s.subject_id: s for s in entities.read_subjects(self.workspace)}
        self.assertEqual(subjects["subj-001"].phones, ("+1 555 0100",))
        self.assertEqual(subjects["subj-001"].nickname, "One")  # untouched fields keep
        self.assertEqual(subjects["subj-002"].nickname, "Two")

    def test_update_unknown_subject_is_clean_error(self):
        with self.assertRaisesRegex(CaseworkError, "unknown subject"):
            entities.update_subject(self.workspace, "subj-999", nickname="X")

    def test_update_unknown_field_is_clean_error(self):
        entities.register_subject(self.workspace, "subj-001")
        with self.assertRaisesRegex(CaseworkError, "unknown subject field"):
            entities.update_subject(self.workspace, "subj-001", height="72in")

    def test_update_multi_field_accepts_stored_string_form(self):
        entities.register_subject(self.workspace, "subj-001", aliases=["a", "b"])
        updated = entities.update_subject(self.workspace, "subj-001", aliases="c;d")
        self.assertEqual(updated.aliases, ("c", "d"))

    def test_update_vehicle(self):
        entities.register_vehicle(self.workspace, "veh-001", plate="ABC 123")
        updated = entities.update_vehicle(
            self.workspace, "veh-001", color="blue", vin="1HGBH41JXMN109186"
        )
        self.assertEqual(updated.color, "blue")
        self.assertEqual(updated.plate, "ABC 123")
        with self.assertRaisesRegex(CaseworkError, "unknown vehicle field"):
            entities.update_vehicle(self.workspace, "veh-001", aliases=["x"])


class LegacyMigrationTests(EntityTestCase):
    """V1 (three-column) registries keep working and upgrade on write."""

    def write_legacy(self):
        self.subjects_path().write_text(
            "subject_id,nickname,descriptor_summary\n"
            "subj-001,subj-001,repeat visitor\n",
            encoding="utf-8",
        )
        self.vehicles_path().write_text(
            "vehicle_id,plate,description\n"
            "veh-001,,getaway car\n",
            encoding="utf-8",
        )

    def test_legacy_files_read_with_padded_profiles(self):
        self.write_legacy()
        (subject,) = entities.read_subjects(self.workspace)
        self.assertEqual(subject.nickname, "subj-001")
        self.assertEqual(subject.descriptor_summary, "repeat visitor")
        self.assertEqual(subject.aliases, ())
        self.assertEqual(subject.employer, "")
        (vehicle,) = entities.read_vehicles(self.workspace)
        self.assertEqual(vehicle.description, "getaway car")
        self.assertEqual(vehicle.vin, "")

    def test_first_write_upgrades_the_header_and_preserves_rows(self):
        self.write_legacy()
        entities.register_subject(self.workspace, "subj-002", nickname="New")
        rows = self.rows(self.subjects_path())
        self.assertEqual(tuple(rows[0]), entities.SUBJECT_FIELDS)
        self.assertEqual(rows[1][:3], ["subj-001", "subj-001", "repeat visitor"])
        self.assertEqual(len(rows[1]), len(entities.SUBJECT_FIELDS))
        self.assertEqual(rows[2][1], "New")

    def test_auto_registration_on_link_upgrades_legacy_file(self):
        from chr0nix.casework import cases

        self.write_legacy()
        cases.create_case(self.workspace, "case-2026-014", "Title", "A. Rivera")
        entities.append_link(self.workspace, "case-2026-014", "vehicle", "veh-002", "seen")
        rows = self.rows(self.vehicles_path())
        self.assertEqual(tuple(rows[0]), entities.VEHICLE_FIELDS)
        self.assertEqual(rows[1][:3], ["veh-001", "", "getaway car"])
        self.assertEqual(rows[2][:3], ["veh-002", "", "seen"])

    def test_unknown_header_still_fails_loudly(self):
        self.subjects_path().write_text("a,b,c\n", encoding="utf-8")
        with self.assertRaisesRegex(CaseworkError, "unexpected header"):
            entities.read_subjects(self.workspace)


class CardTests(EntityTestCase):
    def test_subject_card_is_aligned_and_complete(self):
        entities.register_subject(
            self.workspace, "subj-001", nickname="Red Hoodie",
            aliases=["smithy", "smitty"], employer="Depot Warehouse",
        )
        card = entities.render_subject_card(
            entities.get_subject(self.workspace, "subj-001")
        )
        self.assertIn("subject profile — subj-001", card)
        self.assertIn("Name / primary nickname", card)
        self.assertIn("Red Hoodie", card)
        self.assertIn("smithy, smitty", card)  # multi shown comma-separated
        self.assertIn("Depot Warehouse", card)
        self.assertIn("(not recorded)", card)  # empty fields shown, not hidden

    def test_vehicle_card_titles_transportation_profile(self):
        entities.register_vehicle(self.workspace, "veh-001", plate="ABC 123")
        card = entities.render_vehicle_card(
            entities.get_vehicle(self.workspace, "veh-001")
        )
        self.assertIn("transportation profile (vehicle) — veh-001", card)
        self.assertIn("VIN", card)
        self.assertIn("ABC 123", card)


if __name__ == "__main__":
    unittest.main()
