import os
import sys
import unittest
from datetime import datetime, timedelta
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import BROWN, FEMALE, LIGHT, MASTER_2, MASTER_3, MIDDLE, PURPLE
from current import generate_current_ratings
from elo import COLOR_PROMOTION_RATING_BUMP
from extensions import db
from models import (
    Athlete,
    AthleteRating,
    Division,
    Event,
    Match,
    MatchParticipant,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Team,
)
from test_db import TestDbMixin


class CurrentRatingsPromotionTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        team = Team(name="Promotion Team", normalized_name="promotion team")
        event = Event(
            name="Promotion Ratings Open",
            normalized_name="promotion ratings open",
            slug="promotion-ratings-open",
            ibjjf_id="promotion-ratings-open",
        )
        purple_master_2_light = Division(
            gi=True,
            gender=FEMALE,
            age=MASTER_2,
            belt=PURPLE,
            weight=LIGHT,
        )
        no_gi_purple_master_2_light = Division(
            gi=False,
            gender=FEMALE,
            age=MASTER_2,
            belt=PURPLE,
            weight=LIGHT,
        )
        brown_master_3_light = Division(
            gi=False,
            gender=FEMALE,
            age=MASTER_3,
            belt=BROWN,
            weight=LIGHT,
        )
        no_gi_brown_master_3_middle = Division(
            gi=False,
            gender=FEMALE,
            age=MASTER_3,
            belt=BROWN,
            weight=MIDDLE,
        )
        gi_brown_master_3_light = Division(
            gi=True,
            gender=FEMALE,
            age=MASTER_3,
            belt=BROWN,
            weight=LIGHT,
        )
        purple_master_2_middle = Division(
            gi=True,
            gender=FEMALE,
            age=MASTER_2,
            belt=PURPLE,
            weight=MIDDLE,
        )
        db.session.add_all(
            [
                team,
                event,
                purple_master_2_light,
                no_gi_purple_master_2_light,
                brown_master_3_light,
                no_gi_brown_master_3_middle,
                gi_brown_master_3_light,
                purple_master_2_middle,
            ]
        )
        db.session.flush()

        promoted = Athlete(
            name="Promoted Master Athlete",
            normalized_name="promoted master athlete",
            slug="promoted-master-athlete",
        )
        inactive_promoted = Athlete(
            name="Inactive Promoted Athlete",
            normalized_name="inactive promoted athlete",
            slug="inactive-promoted-athlete",
        )
        same_weight_promoted = Athlete(
            name="Same Weight Promoted Athlete",
            normalized_name="same weight promoted athlete",
            slug="same-weight-promoted-athlete",
        )
        cross_style_promoted = Athlete(
            name="Cross Style Promoted Athlete",
            normalized_name="cross style promoted athlete",
            slug="cross-style-promoted-athlete",
        )
        opponent = Athlete(
            name="Purple Master Opponent",
            normalized_name="purple master opponent",
            slug="purple-master-opponent",
        )
        inactive_opponent = Athlete(
            name="Inactive Purple Opponent",
            normalized_name="inactive purple opponent",
            slug="inactive-purple-opponent",
        )
        db.session.add_all(
            [
                promoted,
                inactive_promoted,
                same_weight_promoted,
                cross_style_promoted,
                opponent,
                inactive_opponent,
            ]
        )
        db.session.flush()
        cls.promoted_id = promoted.id
        cls.inactive_promoted_id = inactive_promoted.id
        cls.same_weight_promoted_id = same_weight_promoted.id
        cls.cross_style_promoted_id = cross_style_promoted.id

        match = Match(
            event_id=event.id,
            division_id=purple_master_2_light.id,
            happened_at=datetime.now(),
            rated=True,
        )
        middle_match = Match(
            event_id=event.id,
            division_id=purple_master_2_middle.id,
            happened_at=datetime.now() - timedelta(days=1),
            rated=True,
        )
        inactive_match = Match(
            event_id=event.id,
            division_id=purple_master_2_light.id,
            happened_at=datetime.now() - timedelta(days=430),
            rated=True,
        )
        same_weight_match = Match(
            event_id=event.id,
            division_id=purple_master_2_light.id,
            happened_at=datetime.now(),
            rated=True,
        )
        cross_style_gi_match = Match(
            event_id=event.id,
            division_id=purple_master_2_light.id,
            happened_at=datetime.now() - timedelta(days=10),
            rated=True,
        )
        cross_style_no_gi_match = Match(
            event_id=event.id,
            division_id=no_gi_brown_master_3_middle.id,
            happened_at=datetime.now(),
            rated=True,
        )
        cross_style_old_no_gi_match = Match(
            event_id=event.id,
            division_id=no_gi_purple_master_2_light.id,
            happened_at=datetime.now() - timedelta(days=20),
            rated=True,
        )
        db.session.add_all(
            [
                match,
                middle_match,
                inactive_match,
                same_weight_match,
                cross_style_gi_match,
                cross_style_no_gi_match,
                cross_style_old_no_gi_match,
            ]
        )
        db.session.flush()

        db.session.add_all(
            [
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1450.0,
                    end_rating=1500.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1450.0,
                    end_rating=1400.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=middle_match.id,
                    athlete_id=promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1500.0,
                    end_rating=1520.0,
                    start_match_count=6,
                    end_match_count=7,
                ),
                MatchParticipant(
                    match_id=middle_match.id,
                    athlete_id=opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1400.0,
                    end_rating=1380.0,
                    start_match_count=6,
                    end_match_count=7,
                ),
                MatchParticipant(
                    match_id=inactive_match.id,
                    athlete_id=inactive_promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1450.0,
                    end_rating=1500.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=inactive_match.id,
                    athlete_id=inactive_opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1450.0,
                    end_rating=1400.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=same_weight_match.id,
                    athlete_id=same_weight_promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1450.0,
                    end_rating=1510.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=same_weight_match.id,
                    athlete_id=opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1450.0,
                    end_rating=1390.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=cross_style_gi_match.id,
                    athlete_id=cross_style_promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1450.0,
                    end_rating=1515.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=cross_style_gi_match.id,
                    athlete_id=opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1450.0,
                    end_rating=1385.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=cross_style_no_gi_match.id,
                    athlete_id=cross_style_promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1515.0,
                    end_rating=1540.0,
                    start_match_count=6,
                    end_match_count=7,
                ),
                MatchParticipant(
                    match_id=cross_style_no_gi_match.id,
                    athlete_id=opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1385.0,
                    end_rating=1360.0,
                    start_match_count=6,
                    end_match_count=7,
                ),
                MatchParticipant(
                    match_id=cross_style_old_no_gi_match.id,
                    athlete_id=cross_style_promoted.id,
                    team_id=team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1450.0,
                    end_rating=1505.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
                MatchParticipant(
                    match_id=cross_style_old_no_gi_match.id,
                    athlete_id=opponent.id,
                    team_id=team.id,
                    seed=2,
                    red=False,
                    winner=False,
                    start_rating=1450.0,
                    end_rating=1395.0,
                    start_match_count=5,
                    end_match_count=6,
                ),
            ]
        )

        registration_link = RegistrationLink(
            name="Future Brown Open",
            normalized_name="future brown open",
            updated_at=datetime.now(),
            link="https://example.com/future-brown-open",
            event_start_date=datetime.now() + timedelta(days=30),
            event_end_date=datetime.now() + timedelta(days=31),
        )
        db.session.add(registration_link)
        db.session.flush()

        db.session.add_all(
            [
                RegistrationLinkCompetitor(
                    registration_link_id=registration_link.id,
                    athlete_name=promoted.name,
                    division_id=brown_master_3_light.id,
                ),
                RegistrationLinkCompetitor(
                    registration_link_id=registration_link.id,
                    athlete_name=promoted.name,
                    division_id=gi_brown_master_3_light.id,
                ),
                RegistrationLinkCompetitor(
                    registration_link_id=registration_link.id,
                    athlete_name=inactive_promoted.name,
                    division_id=gi_brown_master_3_light.id,
                ),
                RegistrationLinkCompetitor(
                    registration_link_id=registration_link.id,
                    athlete_name=same_weight_promoted.name,
                    division_id=gi_brown_master_3_light.id,
                ),
                RegistrationLinkCompetitor(
                    registration_link_id=registration_link.id,
                    athlete_name=cross_style_promoted.name,
                    division_id=gi_brown_master_3_light.id,
                ),
            ]
        )
        db.session.commit()

        generate_current_ratings(db, gi=True, nogi=True, rank_previous_date=None)
        db.session.commit()

    def setUp(self):
        self.client = self.app_module.app.test_client()

    def test_future_registration_promotes_athlete_out_of_old_belt(self):
        with self.app_module.app.app_context():
            purple_rows = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.promoted_id,
                    AthleteRating.belt == PURPLE,
                )
                .all()
            )

        self.assertEqual(purple_rows, [])

    def test_future_registration_adds_athlete_to_new_belt_registration_age(self):
        with self.app_module.app.app_context():
            brown_master_3_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(True),
                    AthleteRating.age == MASTER_3,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_3_light)
        self.assertEqual(
            brown_master_3_light.rating, 1500.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_future_registration_preserves_matching_historical_weight(self):
        with self.app_module.app.app_context():
            brown_master_2_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(True),
                    AthleteRating.age == MASTER_2,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_2_light)
        self.assertEqual(
            brown_master_2_light.rating, 1500.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_future_registration_preserves_other_qualified_weight(self):
        with self.app_module.app.app_context():
            brown_master_2_middle = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(True),
                    AthleteRating.age == MASTER_2,
                    AthleteRating.weight == MIDDLE,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_2_middle)
        self.assertEqual(
            brown_master_2_middle.rating, 1500.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_future_registration_promotes_inactive_gi_rating_base(self):
        with self.app_module.app.app_context():
            brown_master_3_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.inactive_promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(True),
                    AthleteRating.age == MASTER_3,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_3_light)
        self.assertEqual(
            brown_master_3_light.rating, 1500.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_future_registration_promotes_when_latest_match_weight_matches_registration(self):
        with self.app_module.app.app_context():
            brown_master_3_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.same_weight_promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(True),
                    AthleteRating.age == MASTER_3,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_3_light)
        self.assertEqual(
            brown_master_3_light.rating, 1510.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_future_registration_uses_previous_gi_belt_when_no_gi_match_sets_current_belt(
        self,
    ):
        with self.app_module.app.app_context():
            brown_master_3_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.cross_style_promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(True),
                    AthleteRating.age == MASTER_3,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_3_light)
        self.assertEqual(
            brown_master_3_light.rating, 1515.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_current_no_gi_belt_does_not_inherit_previous_no_gi_weights(self):
        with self.app_module.app.app_context():
            brown_master_3_middle = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.cross_style_promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(False),
                    AthleteRating.age == MASTER_3,
                    AthleteRating.weight == MIDDLE,
                )
                .one_or_none()
            )
            brown_master_2_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.cross_style_promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.gi.is_(False),
                    AthleteRating.age == MASTER_2,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_3_middle)
        self.assertEqual(brown_master_3_middle.rating, 1540.0)
        self.assertIsNone(brown_master_2_light)

    @mock.patch("routes.top.get_s3_client", return_value=None)
    def test_top_returns_registration_promoted_athlete(self, _mock_s3):
        response = self.client.get(
            "/api/top",
            query_string={
                "gender": FEMALE,
                "age": MASTER_3,
                "belt": BROWN,
                "gi": "true",
                "weight": LIGHT,
                "name": '"Promoted Master Athlete"',
            },
        )

        self.assertEqual(response.status_code, 200)
        rows = response.get_json()["rows"]
        self.assertEqual([row["name"] for row in rows], ["Promoted Master Athlete"])

    def test_athlete_profile_returns_registration_promoted_rank(self):
        response = self.client.get(
            "/api/athlete/promoted-master-athlete",
            query_string={"gi": "true"},
        )

        self.assertEqual(response.status_code, 200)
        ranks = response.get_json()["ranks"]
        self.assertTrue(
            any(
                rank["belt"] == BROWN
                and rank["age"] == MASTER_3
                and rank["weight"] == LIGHT
                for rank in ranks
            )
        )


if __name__ == "__main__":
    unittest.main()
