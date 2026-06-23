import os
import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import BROWN, FEMALE, LIGHT, MASTER_2, MASTER_3, PURPLE
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
        brown_master_3_light = Division(
            gi=True,
            gender=FEMALE,
            age=MASTER_3,
            belt=BROWN,
            weight=LIGHT,
        )
        db.session.add_all([team, event, purple_master_2_light, brown_master_3_light])
        db.session.flush()

        promoted = Athlete(
            name="Promoted Master Athlete",
            normalized_name="promoted master athlete",
            slug="promoted-master-athlete",
        )
        opponent = Athlete(
            name="Purple Master Opponent",
            normalized_name="purple master opponent",
            slug="purple-master-opponent",
        )
        db.session.add_all([promoted, opponent])
        db.session.flush()
        cls.promoted_id = promoted.id

        match = Match(
            event_id=event.id,
            division_id=purple_master_2_light.id,
            happened_at=datetime.now() - timedelta(days=1),
            rated=True,
        )
        db.session.add(match)
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

        db.session.add(
            RegistrationLinkCompetitor(
                registration_link_id=registration_link.id,
                athlete_name=promoted.name,
                division_id=brown_master_3_light.id,
            )
        )
        db.session.commit()

        generate_current_ratings(db, gi=True, nogi=False, rank_previous_date=None)
        db.session.commit()

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
                    AthleteRating.age == MASTER_3,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNotNone(brown_master_3_light)
        self.assertEqual(
            brown_master_3_light.rating, 1500.0 + COLOR_PROMOTION_RATING_BUMP
        )

    def test_future_registration_does_not_promote_into_old_age(self):
        with self.app_module.app.app_context():
            brown_master_2_light = (
                db.session.query(AthleteRating)
                .filter(
                    AthleteRating.athlete_id == self.promoted_id,
                    AthleteRating.belt == BROWN,
                    AthleteRating.age == MASTER_2,
                    AthleteRating.weight == LIGHT,
                )
                .one_or_none()
            )

        self.assertIsNone(brown_master_2_light)


if __name__ == "__main__":
    unittest.main()
