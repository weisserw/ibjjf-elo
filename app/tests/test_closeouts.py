import os
import sys
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import ADULT, BLACK, LIGHT, MALE
from elo import CLOSEOUT_NOTE
from extensions import db
from models import (
    Athlete,
    Division,
    Event,
    Match,
    MatchParticipant,
    Medal,
    Team,
    TeamNameMapping,
)
from ratings import recompute_all_ratings
from routes.brackets import _annotate_final_closeout
from team_name_mapping import load_canonical_team_names
from test_db import TestDbMixin


class CloseoutRecomputeTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def test_recompute_persists_unrated_alias_finals_and_reloads_mappings(self):
        with self.app_module.app.app_context():
            teams = [
                Team(name=name, normalized_name=name.lower())
                for name in ("Atos HQ", "Atos East")
            ]
            athletes = [
                Athlete(name=name, normalized_name=name.lower(), slug=name.lower())
                for name in ("Red", "Blue")
            ]
            event = Event(
                name="Closeouts", normalized_name="closeouts", slug="closeouts"
            )
            division = Division(
                gi=True, gender=MALE, age=ADULT, belt=BLACK, weight=LIGHT
            )
            mapping = TeamNameMapping(name_match="Atos*", mapped_name="Atos")
            db.session.add_all([*teams, *athletes, event, division, mapping])
            db.session.flush()
            participants = []
            matches = []
            for day in (1, 2):
                match = Match(
                    event_id=event.id,
                    division_id=division.id,
                    happened_at=datetime(2026, 1, day),
                    rated=True,
                    rated_winner_only=False,
                )
                db.session.add(match)
                db.session.flush()
                matches.append(match)
                for i in range(2):
                    participant = MatchParticipant(
                        match_id=match.id,
                        athlete_id=athletes[i].id,
                        team_id=teams[i].id,
                        seed=i + 1,
                        red=i == 0,
                        winner=i == 0,
                        start_rating=2000,
                        end_rating=2010,
                        start_match_count=0,
                        end_match_count=1,
                    )
                    db.session.add(participant)
                    participants.append(participant)
            for i in range(2):
                db.session.add(
                    Medal(
                        event_id=event.id,
                        division_id=division.id,
                        happened_at=datetime(2026, 1, 2),
                        athlete_id=athletes[i].id,
                        team_id=teams[i].id,
                        place=i + 1,
                        default_gold=False,
                    )
                )
            db.session.flush()
            with patch(
                "ratings.load_canonical_team_names", wraps=load_canonical_team_names
            ) as loader:
                recompute_all_ratings(db, gi=True, rerank=False)
                loader.assert_called_once_with(db.session)
            for match in matches:
                self.assertFalse(match.rated)
            for participant in participants:
                self.assertEqual(participant.start_rating, participant.end_rating)
                self.assertEqual(participant.start_match_count, 0)
                self.assertEqual(participant.end_match_count, 0)
                self.assertIn(CLOSEOUT_NOTE, participant.rating_note)

            db.session.delete(mapping)
            db.session.flush()
            recompute_all_ratings(db, gi=True, rerank=False)
            self.assertTrue(all(match.rated for match in matches))
            self.assertEqual(participants[-1].end_match_count, 2)


class LiveCloseoutTestCase(unittest.TestCase):
    @patch(
        "routes.brackets.load_team_name_mappings",
        return_value=({}, [("Atos*", "Atos")]),
    )
    def test_alias_final_notes_both_sides_without_duplicate_notes(self, mappings):
        final = dict(
            red_medal="1",
            blue_medal="2",
            red_team="Atos HQ",
            blue_team="Atos East",
            red_note="Existing",
            blue_note=None,
        )
        _annotate_final_closeout(final)
        self.assertEqual(final["red_note"], f"Existing, {CLOSEOUT_NOTE}")
        self.assertEqual(final["blue_note"], CLOSEOUT_NOTE)
        _annotate_final_closeout(final)
        self.assertEqual(final["red_note"].count(CLOSEOUT_NOTE), 1)

    @patch("routes.brackets.load_team_name_mappings")
    def test_incomplete_final_does_not_load_mappings(self, mappings):
        _annotate_final_closeout(dict(red_medal="1", blue_medal=None))
        mappings.assert_not_called()
