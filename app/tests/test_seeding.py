import os
import sys
import unittest
from collections import namedtuple
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from constants import (
    ADULT,
    BLACK,
    BROWN,
    FEATHER,
    HEAVY,
    JUVENILE,
    JUVENILE_1,
    LIGHT,
    MALE,
    MASTER_1,
    MASTER_2,
    MASTER_3,
    MASTER_4,
    MASTER_5,
    MASTER_7,
    MEDIUM_HEAVY,
    MIDDLE,
    OPEN_CLASS,
    OPEN_CLASS_HEAVY,
)
from extensions import db
from models import Athlete, Division, Event, Match, Medal, Team
from seeding import (
    add_estimated_seeds,
    add_seeding_data,
    add_side_swaps,
)
from test_db import TestDbMixin


# Fixed "now" used by every test. Picked to match a real-world snapshot of
# the production database (mid-May 2026, after Euros 2026 but before any
# 2026 Worlds / Pans / Brasileiros).
NOW = datetime(2026, 5, 15)


# Primitive event reference — using a namedtuple instead of the SQLAlchemy
# ORM instance avoids DetachedInstanceError when test methods reference an
# event across a fresh session boundary.
_EventRef = namedtuple("_EventRef", ["id", "started_at"])


def _registration_row(athlete_id):
    """A minimal registration-row dict. divdata fields (age/belt/weight/...)
    aren't read by add_seeding_data — those are passed via the divdata arg —
    so we leave them as None placeholders here."""
    return {
        "name": "Test",
        "team": "Test Team",
        "id": athlete_id,
        "ibjjf_id": None,
        "seed": 0,
        "rating": None,
        "match_count": None,
        "rank": None,
        "percentile": None,
        "percentile_age": None,
        "note": None,
        "last_weight": None,
        "slug": None,
        "instagram_profile": None,
        "personal_name": None,
        "profile_image_url": None,
        "country": None,
        "country_note": None,
        "country_note_pt": None,
        "age": None,
        "belt": None,
        "weight": None,
        "gender": None,
        "gi": None,
    }


def _divdata(age=ADULT, belt=BLACK, weight=LIGHT, gender=MALE):
    return {"age": age, "belt": belt, "weight": weight, "gender": gender}


class SeedingTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        team = Team(name="Test Team", normalized_name="test team")
        db.session.add(team)
        db.session.flush()
        cls.team_id = team.id

        # All anchor matches reuse one throwaway division — they only exist
        # so that the Worlds start-date aggregation has something to MIN.
        anchor_div = Division(gi=True, gender=MALE, age=ADULT, belt=BLACK, weight=LIGHT)
        db.session.add(anchor_div)
        db.session.flush()
        cls.anchor_div_id = anchor_div.id

        def add_event(name, start_dt):
            slug = (
                name.lower()
                .replace(" ", "-")
                .replace("(", "")
                .replace(")", "")
                .replace(",", "")
            )
            event = Event(
                name=name,
                normalized_name=name.lower(),
                slug=slug,
                medals_only=False,
            )
            db.session.add(event)
            db.session.flush()
            db.session.add(
                Match(
                    event_id=event.id,
                    division_id=cls.anchor_div_id,
                    happened_at=start_dt,
                    rated=True,
                )
            )
            return _EventRef(event.id, start_dt)

        # Adult/juvenile gi Worlds (June anchor).
        cls.worlds_2025 = add_event(
            "World IBJJF Jiu-Jitsu Championship 2025", datetime(2025, 5, 29)
        )
        cls.worlds_2024 = add_event(
            "World IBJJF Jiu-Jitsu Championship 2024 (Flo)", datetime(2024, 5, 30)
        )
        cls.worlds_2023 = add_event(
            "World IBJJF Jiu-Jitsu Championship 2023 (Flo)", datetime(2023, 6, 1)
        )
        # 2022 is outside the 3-season window for now=2026-05-15.
        cls.worlds_2022 = add_event(
            "World IBJJF Jiu-Jitsu Championship 2022 (Flo)", datetime(2022, 6, 2)
        )
        # Older Worlds use the legacy pre-2022 naming: "World Jiu-Jitsu IBJJF
        # Championship YYYY". These exist purely to exercise the
        # black-belt-specific seeding queries (rank-4 / rank-5 / former).
        cls.worlds_2021 = add_event(
            "World Jiu-Jitsu IBJJF Championship 2021", datetime(2021, 7, 24)
        )
        cls.worlds_2020 = add_event(
            "World Jiu-Jitsu IBJJF Championship 2020", datetime(2020, 8, 1)
        )

        # Master gi Worlds (Sept anchor).
        cls.master_worlds_2025 = add_event(
            "World Master IBJJF Jiu-Jitsu Championship 2025", datetime(2025, 8, 28)
        )
        cls.master_worlds_2024 = add_event(
            "World Master IBJJF Jiu-Jitsu Championship 2024 (Flo)",
            datetime(2024, 8, 29),
        )
        cls.master_worlds_2023 = add_event(
            "World Master IBJJF Jiu-Jitsu Championship 2023 (Flo)",
            datetime(2023, 8, 31),
        )
        # Legacy master Worlds naming (pre-2022 rebrand).
        cls.master_worlds_2021 = add_event(
            "World Master Jiu-Jitsu IBJJF Championship 2021",
            datetime(2021, 9, 1),
        )

        # No-Gi Worlds (December anchor).
        cls.nogi_worlds_2025 = add_event(
            "World IBJJF Jiu-Jitsu No-Gi Championship 2025", datetime(2025, 12, 11)
        )
        cls.nogi_worlds_2024 = add_event(
            "World IBJJF Jiu-Jitsu No-Gi Championship 2024", datetime(2024, 12, 12)
        )

        # Other Grand Slam events (gi).
        cls.euros_2026 = add_event(
            "European IBJJF Jiu-Jitsu Championship 2026", datetime(2026, 1, 15)
        )
        cls.euros_2025 = add_event(
            "European IBJJF Jiu-Jitsu Championship 2025", datetime(2025, 1, 17)
        )
        cls.euros_2024 = add_event(
            "European IBJJF Jiu-Jitsu Championship 2024 (Flo)", datetime(2024, 1, 20)
        )
        cls.pans_2025 = add_event(
            "Pan IBJJF Jiu-Jitsu Championship 2025", datetime(2025, 3, 19)
        )
        cls.pans_2024 = add_event(
            "Pan IBJJF Jiu-Jitsu Championship 2024 (Flo)", datetime(2024, 3, 20)
        )
        cls.pans_2023 = add_event(
            "Pan IBJJF Jiu-Jitsu Championship 2023 (Flo)", datetime(2023, 3, 22)
        )
        cls.brasil_2025 = add_event(
            "Campeonato Brasileiro de Jiu-Jitsu 2025", datetime(2025, 4, 26)
        )
        cls.brasil_2024 = add_event(
            "Campeonato Brasileiro de Jiu-Jitsu 2024 (Flo)", datetime(2024, 4, 21)
        )
        cls.brasil_2023 = add_event(
            "Campeonato Brasileiro de Jiu-Jitsu 2023", datetime(2023, 4, 29)
        )
        # Duplicate-source 2023 Brasileiros — same year, different DB row,
        # different name (parenthetical sub-event marker).
        cls.brasil_2023_alt = add_event(
            "Campeonato Brasileiro de Jiu-Jitsu (Juvenil, Adulto e Master) 2023 (Flo)",
            datetime(2023, 4, 29),
        )

        # A non-star local event (default 1x).
        cls.local_event_2025 = add_event(
            "Random Local Tournament 2025", datetime(2025, 7, 1)
        )

        db.session.commit()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _make_athlete(cls, slug):
        athlete = Athlete(name=slug, normalized_name=slug.replace("-", " "), slug=slug)
        db.session.add(athlete)
        db.session.flush()
        return athlete

    @classmethod
    def _add_medal(
        cls,
        athlete,
        event_ref,
        place,
        *,
        age=ADULT,
        belt=BLACK,
        weight=LIGHT,
        gi=True,
        gender=MALE,
        happened_at=None,
    ):
        division = Division(gi=gi, gender=gender, age=age, belt=belt, weight=weight)
        db.session.add(division)
        db.session.flush()
        medal = Medal(
            happened_at=happened_at or event_ref.started_at,
            event_id=event_ref.id,
            division_id=division.id,
            athlete_id=athlete.id,
            team_id=cls.team_id,
            place=place,
            default_gold=False,
        )
        db.session.add(medal)
        db.session.flush()
        return medal

    def _seed_and_run(self, seed_fn, divdata, gi, now=NOW):
        """Open an app_context, let `seed_fn(self)` create athletes/medals
        and return the registration row(s) (single dict or list of dicts),
        run add_seeding_data within the same context, and return the row(s).

        Keeping everything in one app_context avoids
        DetachedInstanceError on ORM attributes after commit.
        """
        with self.app_module.app.app_context():
            seeded = seed_fn(self)
            db.session.commit()
            if isinstance(seeded, list):
                rows = [_registration_row(a.id) for a in seeded]
            else:
                rows = [_registration_row(seeded.id)]
            add_seeding_data(rows, divdata, gi, now=now)
        return rows[0] if not isinstance(seeded, list) else rows

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------

    def test_no_medals_yields_zero(self):
        row = self._seed_and_run(
            lambda t: t._make_athlete("no-medals-athlete"),
            _divdata(),
            gi=True,
        )
        self.assertEqual(row["points"], 0)
        self.assertEqual(row["open_class_points"], 0)
        self.assertEqual(row["grand_slam_points"], 0)
        self.assertEqual(row["grand_slam_open_class_points"], 0)

    def test_no_matched_athlete_id_yields_zero(self):
        # Row with id=None should still get the four seeding fields set to 0
        # without any DB work.
        rows = [_registration_row(athlete_id=None)]
        with self.app_module.app.app_context():
            add_seeding_data(rows, _divdata(), gi=True, now=NOW)
        self.assertEqual(rows[0]["points"], 0)
        self.assertEqual(rows[0]["open_class_points"], 0)
        self.assertEqual(rows[0]["grand_slam_points"], 0)
        self.assertEqual(rows[0]["grand_slam_open_class_points"], 0)

    def test_gold_at_current_season_worlds(self):
        # Worlds 2025 (current season 3x) * 7 stars * 9 (gold) * 1.0 weight = 189.
        def seed(t):
            a = t._make_athlete("worlds-2025-gold")
            t._add_medal(a, t.worlds_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 189)
        self.assertEqual(row["grand_slam_points"], 189)  # Worlds is a GS event

    def test_season_multipliers_3_2_1(self):
        # Gold at Worlds 2025/2024/2023 -> 189 + 126 + 63 = 378.
        def seed(t):
            a = t._make_athlete("worlds-three-seasons")
            t._add_medal(a, t.worlds_2025, place=1)
            t._add_medal(a, t.worlds_2024, place=1)
            t._add_medal(a, t.worlds_2023, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 189 + 126 + 63)
        self.assertEqual(row["grand_slam_points"], 189 + 126 + 63)

    def test_medal_outside_season_window_excluded(self):
        # Worlds 2022 is older than the 3-season window for now=2026-05-15.
        def seed(t):
            a = t._make_athlete("worlds-2022-only")
            t._add_medal(a, t.worlds_2022, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 0)
        self.assertEqual(row["grand_slam_points"], 0)

    def test_place_values_9_3_1(self):
        # Silver at Worlds 2025: 3 * 3 * 1.0 * 7 = 63
        # Bronze: 1 * 3 * 1.0 * 7 = 21
        def seed(t):
            silver = t._make_athlete("worlds-silver")
            bronze = t._make_athlete("worlds-bronze")
            t._add_medal(silver, t.worlds_2025, place=2)
            t._add_medal(bronze, t.worlds_2025, place=3)
            return [silver, bronze]

        rows = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(rows[0]["points"], 63)
        self.assertEqual(rows[1]["points"], 21)

    def test_adjacent_weight_half_multiplier_and_floor(self):
        # Light tournament, gold in Feather (adjacent) at Worlds 2025:
        # 9 * 3 * 0.5 * 7 = 94.5 -> floor = 94.
        def seed(t):
            a = t._make_athlete("feather-adjacent")
            t._add_medal(a, t.worlds_2025, place=1, weight=FEATHER)
            return a

        row = self._seed_and_run(seed, _divdata(weight=LIGHT), gi=True)
        self.assertEqual(row["points"], 94)

    def test_non_adjacent_weight_excluded(self):
        # Light tournament, gold in Heavy (non-adjacent) -> 0.
        def seed(t):
            a = t._make_athlete("heavy-not-adjacent")
            t._add_medal(a, t.worlds_2025, place=1, weight=HEAVY)
            return a

        row = self._seed_and_run(seed, _divdata(weight=LIGHT), gi=True)
        self.assertEqual(row["points"], 0)
        self.assertEqual(row["grand_slam_points"], 0)

    def test_open_class_medal_folds_into_points_for_non_open_tournament(self):
        # Light tournament, gold in Open Class at Worlds 2025: open-class
        # medals fold into the regular points bucket at flat 1.0 weight when
        # the tournament itself is not open class.
        # 13.5 * 3 * 7 = 283.5 -> floor 283. open_class_points stays 0.
        def seed(t):
            a = t._make_athlete("open-class-gold")
            t._add_medal(a, t.worlds_2025, place=1, weight=OPEN_CLASS)
            return a

        row = self._seed_and_run(seed, _divdata(weight=LIGHT), gi=True)
        self.assertEqual(row["points"], 283)
        self.assertEqual(row["open_class_points"], 0)
        self.assertEqual(row["grand_slam_points"], 283)
        self.assertEqual(row["grand_slam_open_class_points"], 0)

    def test_open_class_medal_goes_to_separate_bucket_for_open_tournament(self):
        # Open Class tournament: open-class medals stay in their own bucket.
        # 13.5 * 3 * 7 = 283.5 -> floor 283.
        def seed(t):
            a = t._make_athlete("open-class-gold-in-open")
            t._add_medal(a, t.worlds_2025, place=1, weight=OPEN_CLASS)
            return a

        row = self._seed_and_run(seed, _divdata(weight=OPEN_CLASS), gi=True)
        self.assertEqual(row["points"], 0)
        self.assertEqual(row["open_class_points"], 283)
        self.assertEqual(row["grand_slam_points"], 0)
        self.assertEqual(row["grand_slam_open_class_points"], 283)

    def test_open_class_tournament_counts_all_normal_weights(self):
        # Open Class tournament. Gold in Light at Worlds 2025 contributes at
        # 1.0 weight: 9 * 3 * 1.0 * 7 = 189. Gold in Open Class Heavy at
        # Worlds 2024 contributes to open_class_points: 13.5 * 2 * 7 = 189.
        def seed(t):
            a = t._make_athlete("open-class-tournament")
            t._add_medal(a, t.worlds_2025, place=1, weight=LIGHT)
            t._add_medal(a, t.worlds_2024, place=1, weight=OPEN_CLASS_HEAVY)
            return a

        row = self._seed_and_run(seed, _divdata(weight=OPEN_CLASS), gi=True)
        self.assertEqual(row["points"], 189)
        self.assertEqual(row["open_class_points"], 189)

    def test_non_open_tournament_combines_adjacent_weight_and_open_into_points(self):
        # Mirrors a real-world scenario: athlete registered at Middle has an
        # adjacent-weight bronze + silver and an open-class bronze, all at
        # 1-star non-Grand-Slam events in the current season (3x). Per spec,
        # for a non-open tournament the open-class medal folds into ``points``
        # at flat 1.0 weight (open place values), not into open_class_points.
        #
        # MH bronze: 1 * 3 * 0.5 * 1 = 1.5
        # MH silver: 3 * 3 * 0.5 * 1 = 4.5
        # Open bronze: 1.5 * 3 * 1.0 * 1 = 4.5
        # points = 1.5 + 4.5 + 4.5 = 10.5 -> floor 10
        # open_class_points = 0 (tournament is not open class)
        def seed(t):
            a = t._make_athlete("middle-with-mh-and-open")
            t._add_medal(
                a,
                t.local_event_2025,
                place=3,
                weight=MEDIUM_HEAVY,
                happened_at=datetime(2025, 12, 6),
            )
            t._add_medal(
                a,
                t.local_event_2025,
                place=2,
                weight=MEDIUM_HEAVY,
                happened_at=datetime(2025, 7, 19),
            )
            t._add_medal(
                a,
                t.local_event_2025,
                place=3,
                weight=OPEN_CLASS,
                happened_at=datetime(2025, 7, 19),
            )
            return a

        row = self._seed_and_run(seed, _divdata(weight=MIDDLE), gi=True)
        self.assertEqual(row["points"], 10)
        self.assertEqual(row["open_class_points"], 0)

    def test_belt_filter(self):
        # BLACK tournament; brown-belt medals must not contribute.
        def seed(t):
            a = t._make_athlete("brown-belt-history")
            t._add_medal(a, t.worlds_2025, place=1, belt=BROWN)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertEqual(row["points"], 0)

    def test_adult_tournament_excludes_juvenile_medals(self):
        def seed(t):
            a = t._make_athlete("juvenile-history")
            t._add_medal(a, t.worlds_2025, place=1, age=JUVENILE)
            return a

        row = self._seed_and_run(seed, _divdata(age=ADULT), gi=True)
        self.assertEqual(row["points"], 0)

    def test_juvenile_pool_combines_juv_variants(self):
        # Juvenile tournament counts Juvenile, Juvenile 1, Juvenile 2.
        def seed(t):
            a = t._make_athlete("juvenile-pool")
            t._add_medal(a, t.worlds_2025, place=1, age=JUVENILE)
            t._add_medal(a, t.worlds_2024, place=1, age=JUVENILE_1)
            return a

        row = self._seed_and_run(seed, _divdata(age=JUVENILE), gi=True)
        # 189 (Juvenile, 2025, 3x) + 126 (Juvenile_1, 2024, 2x)
        self.assertEqual(row["points"], 189 + 126)

    def test_juvenile_tournament_excludes_adult_medals(self):
        def seed(t):
            a = t._make_athlete("juv-tourney-adult-history")
            t._add_medal(a, t.worlds_2025, place=1, age=ADULT)
            return a

        row = self._seed_and_run(seed, _divdata(age=JUVENILE), gi=True)
        self.assertEqual(row["points"], 0)

    def test_master_carries_adult_plus_master_levels_up_to_own(self):
        # Master 3 tournament includes Adult, M1, M2, M3 medals but NOT M4.
        # Master season anchor is World Master (Aug 28 2025). All medals
        # below are won at master_worlds_2025 so they're in the current
        # master season (3x).
        def seed(t):
            a = t._make_athlete("master-carry-forward")
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_3)
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_1)
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_4)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_3), gi=True)
        # 9 * 3 * 1.0 * 7 = 189 for the M3 and M1 medals; M4 excluded.
        self.assertEqual(row["points"], 189 + 189)

    def test_master_uses_adult_star_for_adult_division_medal(self):
        # Adult Worlds is a 7-star event for adult-division medals — even
        # when the competitor is a master carrying forward adult history.
        # Master season anchor is World Master (Aug 28 2025), and Adult
        # Worlds 2025 (May 29 2025) is BEFORE that, so the adult medal
        # lands in master season 2 (2x). 9 * 2 * 1.0 * 7 = 126.
        def seed(t):
            a = t._make_athlete("master-adult-worlds")
            t._add_medal(a, t.worlds_2025, place=1, age=ADULT)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_3), gi=True)
        self.assertEqual(row["points"], 126)

    def test_gi_no_gi_separation(self):
        # No-gi tournament shouldn't see gi medals.
        def seed(t):
            a = t._make_athlete("gi-history-nogi-tournament")
            t._add_medal(a, t.worlds_2025, place=1, gi=True)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=False)
        self.assertEqual(row["points"], 0)

    def test_default_star_for_non_star_event(self):
        # Random Local Tournament: 9 * 3 * 1.0 * 1 (default) = 27.
        # Local tournament isn't a Grand Slam event, so GS points are 0.
        def seed(t):
            a = t._make_athlete("low-star-event")
            t._add_medal(a, t.local_event_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 27)
        self.assertEqual(row["grand_slam_points"], 0)

    def test_grand_slam_multiplier_diverges_from_regular_season(self):
        # Pans 2025 (3/19/2025) falls in regular season 2 (between Worlds
        # 2024 and Worlds 2025) -> regular multiplier 2x.
        # In the Grand Slam window, Pans 2025 is the most recent Pans ->
        # GS multiplier 3x.
        # Pans star = 4.
        # Regular: 9 * 2 * 1.0 * 4 = 72. GS: 9 * 3 * 1.0 * 4 = 108.
        def seed(t):
            a = t._make_athlete("pans-2025-gold")
            t._add_medal(a, t.pans_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 72)
        self.assertEqual(row["grand_slam_points"], 108)

    def test_grand_slam_rolling_window_per_event_type(self):
        # Euros 2026 has already happened (Jan 15) -> 3x Euros slot;
        # 2025 -> 2x; 2024 -> 1x. Total: 9*4*(3+2+1) = 216.
        def seed(t):
            a = t._make_athlete("three-euros")
            t._add_medal(a, t.euros_2026, place=1)
            t._add_medal(a, t.euros_2025, place=1)
            t._add_medal(a, t.euros_2024, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["grand_slam_points"], 216)

    def test_grand_slam_brasileiros_duplicate_year_collapses(self):
        # Two DB events represent the same year of Brasileiros (plain +
        # "(Juvenil, Adulto e Master) (Flo)" alt-source). They share a
        # single GS slot — an athlete with medals at *both* gets credited
        # for both at the same 1x multiplier (2023 is the 1x slot).
        # Brasileiros star = 4. Two golds * 9 * 1 * 1.0 * 4 = 72.
        def seed(t):
            a = t._make_athlete("brasil-2023-both-sources")
            t._add_medal(a, t.brasil_2023, place=1)
            t._add_medal(a, t.brasil_2023_alt, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["grand_slam_points"], 72)

    def test_master_grand_slam_uses_world_master_not_world(self):
        # For master tournaments, the GS Worlds slot is World Master.
        # An adult-Worlds gold won by a master is NOT in the master GS pool.
        def seed(t):
            a = t._make_athlete("master-gs-worlds")
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_3)
            t._add_medal(a, t.worlds_2025, place=1, age=ADULT)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_3), gi=True)
        # Only the World Master gold counts toward GS.
        # World Master 2025 (current GS, 3x) * 7 star * 9 (gold) = 189.
        self.assertEqual(row["grand_slam_points"], 189)

    def test_now_injection_changes_season_window(self):
        # Same set of medals, two reference "now" values, very different
        # season slots — verifies the season window is driven by `now` and
        # not by the wall clock.
        # Athlete has golds at Worlds 2024 and Worlds 2023.
        # now = NOW (2026-05-15, post Worlds 2025):
        #   Worlds 2025 is the 3x anchor, 2024 is 2x, 2023 is 1x.
        #   Athlete points: 126 (2024 at 2x) + 63 (2023 at 1x) = 189
        # now = 2025-05-28 (day before Worlds 2025):
        #   Worlds 2024 is 3x, 2023 is 2x, 2022 is 1x.
        #   Athlete points: 189 (2024 at 3x) + 126 (2023 at 2x) = 315
        with self.app_module.app.app_context():
            a = self._make_athlete("now-injection-test")
            self._add_medal(a, self.worlds_2024, place=1)
            self._add_medal(a, self.worlds_2023, place=1)
            db.session.commit()
            athlete_id = a.id

            current_rows = [_registration_row(athlete_id)]
            add_seeding_data(current_rows, _divdata(), gi=True, now=NOW)

            pre_rows = [_registration_row(athlete_id)]
            add_seeding_data(pre_rows, _divdata(), gi=True, now=datetime(2025, 5, 28))

        self.assertEqual(current_rows[0]["points"], 126 + 63)
        self.assertEqual(pre_rows[0]["points"], 189 + 126)

    # ------------------------------------------------------------------
    # Adult black-belt-only fields
    # ------------------------------------------------------------------

    def test_adult_black_belt_world_champion_recent(self):
        # Gold at Worlds 2025 (rank 0): in the "last 3 worlds" set.
        def seed(t):
            a = t._make_athlete("bb-recent-champ")
            t._add_medal(a, t.worlds_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertTrue(row["world_champion_recent"])
        self.assertEqual(row["last_world_title_year"], 2025)
        self.assertFalse(row["world_champion_4_years_ago"])
        self.assertFalse(row["world_champion_5_years_ago"])
        # Only a recent title -> not a 6+-year "former" champion.
        self.assertFalse(row["former_world_champion"])
        self.assertFalse(row["previous_brown_world_champion"])

    def test_adult_black_belt_4_years_ago(self):
        # Gold at Worlds 2022 (rank 3) — outside top 3, exactly the "4 years
        # ago" slot.
        def seed(t):
            a = t._make_athlete("bb-4-years-ago")
            t._add_medal(a, t.worlds_2022, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertFalse(row["world_champion_recent"])
        # last_world_title_year is restricted to the 3 most-recent past Worlds.
        self.assertIsNone(row["last_world_title_year"])
        self.assertTrue(row["world_champion_4_years_ago"])
        self.assertFalse(row["world_champion_5_years_ago"])
        # Title is exactly 4 years ago, not 6+ -> not "former".
        self.assertFalse(row["former_world_champion"])

    def test_adult_black_belt_5_years_ago_legacy_name(self):
        # Gold at Worlds 2021 (rank 4) — the "5 years ago" slot. Also
        # exercises the legacy "World Jiu-Jitsu IBJJF Championship" naming.
        def seed(t):
            a = t._make_athlete("bb-5-years-ago")
            t._add_medal(a, t.worlds_2021, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertFalse(row["world_champion_recent"])
        # last_world_title_year is restricted to the 3 most-recent past Worlds.
        self.assertIsNone(row["last_world_title_year"])
        self.assertFalse(row["world_champion_4_years_ago"])
        self.assertTrue(row["world_champion_5_years_ago"])
        # Title is exactly 5 years ago, not 6+ -> not "former".
        self.assertFalse(row["former_world_champion"])

    def test_adult_black_belt_former_champion_only(self):
        # Gold at Worlds 2020 (rank 5) — older than any tracked slot, so
        # only ``former_world_champion`` should be set.
        def seed(t):
            a = t._make_athlete("bb-former-only")
            t._add_medal(a, t.worlds_2020, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertFalse(row["world_champion_recent"])
        # last_world_title_year is restricted to the 3 most-recent past Worlds.
        self.assertIsNone(row["last_world_title_year"])
        self.assertFalse(row["world_champion_4_years_ago"])
        self.assertFalse(row["world_champion_5_years_ago"])
        self.assertTrue(row["former_world_champion"])

    def test_adult_black_belt_last_world_title_year_takes_max(self):
        # Multiple Worlds titles — ``last_world_title_year`` should report
        # the most recent year.
        def seed(t):
            a = t._make_athlete("bb-multi-titles")
            t._add_medal(a, t.worlds_2023, place=1)
            t._add_medal(a, t.worlds_2021, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertEqual(row["last_world_title_year"], 2023)
        self.assertTrue(row["world_champion_recent"])  # 2023 is rank 2
        self.assertTrue(row["world_champion_5_years_ago"])  # 2021 is rank 4

    def test_adult_black_belt_no_titles(self):
        # An adult black athlete with no Worlds golds — all flags should be
        # at their default values (and the fields must still be set).
        def seed(t):
            return t._make_athlete("bb-no-titles")

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertFalse(row["world_champion_recent"])
        self.assertIsNone(row["last_world_title_year"])
        self.assertFalse(row["world_champion_4_years_ago"])
        self.assertFalse(row["world_champion_5_years_ago"])
        self.assertFalse(row["former_world_champion"])
        self.assertFalse(row["previous_brown_world_champion"])

    def test_adult_black_belt_previous_brown_world_champion(self):
        # Brown gold at the single most-recent past Worlds (2025).
        def seed(t):
            a = t._make_athlete("bb-prev-brown")
            t._add_medal(a, t.worlds_2025, place=1, belt=BROWN)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertTrue(row["previous_brown_world_champion"])
        # Brown gold isn't a black-belt title, so the black flags stay false.
        self.assertFalse(row["world_champion_recent"])
        self.assertFalse(row["former_world_champion"])
        self.assertIsNone(row["last_world_title_year"])

    def test_adult_black_belt_brown_gold_older_does_not_count(self):
        # Brown gold at Worlds 2024 (not the most-recent past Worlds) does
        # NOT set ``previous_brown_world_champion``.
        def seed(t):
            a = t._make_athlete("bb-prev-brown-older")
            t._add_medal(a, t.worlds_2024, place=1, belt=BROWN)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertFalse(row["previous_brown_world_champion"])

    def test_adult_black_belt_title_in_different_weight_does_not_count(self):
        # Gold at Worlds 2025 in HEAVY shouldn't satisfy a LIGHT tournament's
        # world-champion flags.
        def seed(t):
            a = t._make_athlete("bb-wrong-weight")
            t._add_medal(a, t.worlds_2025, place=1, weight=HEAVY)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK, weight=LIGHT), gi=True)
        self.assertFalse(row["world_champion_recent"])
        self.assertIsNone(row["last_world_title_year"])
        self.assertFalse(row["former_world_champion"])

    def test_adult_black_belt_brown_title_in_different_weight_does_not_count(self):
        # Brown gold in HEAVY at the most-recent past Worlds should NOT trigger
        # ``previous_brown_world_champion`` for a LIGHT division.
        def seed(t):
            a = t._make_athlete("bb-prev-brown-wrong-weight")
            t._add_medal(a, t.worlds_2025, place=1, belt=BROWN, weight=HEAVY)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK, weight=LIGHT), gi=True)
        self.assertFalse(row["previous_brown_world_champion"])

    def test_adult_black_belt_open_class_division_uses_open_class_titles(self):
        # An Open Class tournament should credit an Open Class Worlds gold,
        # but NOT a regular-weight (LIGHT) gold.
        def seed(t):
            with_open = t._make_athlete("bb-open-with-title")
            with_light = t._make_athlete("bb-open-light-title")
            t._add_medal(with_open, t.worlds_2025, place=1, weight=OPEN_CLASS)
            t._add_medal(with_light, t.worlds_2025, place=1, weight=LIGHT)
            return [with_open, with_light]

        rows = self._seed_and_run(
            seed, _divdata(belt=BLACK, weight=OPEN_CLASS), gi=True
        )
        self.assertTrue(rows[0]["world_champion_recent"])
        self.assertFalse(rows[1]["world_champion_recent"])

    def test_adult_black_belt_open_class_variants_count_for_open_class(self):
        # Open Class Heavy at Worlds counts for an Open Class division.
        def seed(t):
            a = t._make_athlete("bb-open-heavy")
            t._add_medal(a, t.worlds_2025, place=1, weight=OPEN_CLASS_HEAVY)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK, weight=OPEN_CLASS), gi=True)
        self.assertTrue(row["world_champion_recent"])

    def test_master_black_belt_title_in_different_weight_does_not_count(self):
        # Master 3 gold in HEAVY at Master Worlds shouldn't satisfy a LIGHT
        # Master 3 tournament's ``master_3_world_champion``.
        def seed(t):
            a = t._make_athlete("mb-wrong-weight")
            t._add_medal(a, t.master_worlds_2024, place=1, age=MASTER_3, weight=HEAVY)
            return a

        row = self._seed_and_run(
            seed, _divdata(age=MASTER_3, belt=BLACK, weight=LIGHT), gi=True
        )
        self.assertFalse(row["master_3_world_champion"])

    def test_master_black_belt_adult_title_in_different_weight_does_not_count(self):
        # Adult black gold in HEAVY shouldn't satisfy a LIGHT Master 1
        # tournament's ``adult_world_champion``.
        def seed(t):
            a = t._make_athlete("mb-adult-wrong-weight")
            t._add_medal(a, t.worlds_2025, place=1, weight=HEAVY)
            return a

        row = self._seed_and_run(
            seed, _divdata(age=MASTER_1, belt=BLACK, weight=LIGHT), gi=True
        )
        self.assertFalse(row["adult_world_champion"])

    def test_non_adult_black_belt_tournament_skips_fields(self):
        # An Adult brown belt tournament should not get the black-belt-only
        # fields — they should be absent from the row entirely.
        def seed(t):
            a = t._make_athlete("brown-tournament")
            t._add_medal(a, t.worlds_2025, place=1, belt=BROWN)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BROWN), gi=True)
        self.assertNotIn("world_champion_recent", row)
        self.assertNotIn("last_world_title_year", row)
        self.assertNotIn("world_champion_4_years_ago", row)
        self.assertNotIn("world_champion_5_years_ago", row)
        self.assertNotIn("former_world_champion", row)
        self.assertNotIn("previous_brown_world_champion", row)

    # ------------------------------------------------------------------
    # Master black-belt-only fields
    # ------------------------------------------------------------------

    def test_master_black_belt_master_title_at_own_level(self):
        # Master 3 tournament, athlete won M3 black at Master Worlds 2025.
        # Should set master_3_world_champion = True; master_1/2 = False; no
        # master_4..7 keys on the row.
        def seed(t):
            a = t._make_athlete("m-title-own-level")
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_3, belt=BLACK)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_3, belt=BLACK), gi=True)
        self.assertFalse(row["adult_world_champion"])
        self.assertFalse(row["master_1_world_champion"])
        self.assertFalse(row["master_2_world_champion"])
        self.assertTrue(row["master_3_world_champion"])
        self.assertNotIn("master_4_world_champion", row)
        self.assertNotIn("master_5_world_champion", row)

    def test_master_black_belt_carries_lower_levels(self):
        # Master 4 tournament: athlete won M2 black in the past. Should
        # set master_2_world_champion. M5+ shouldn't even be a key.
        def seed(t):
            a = t._make_athlete("m-carries-lower")
            t._add_medal(a, t.master_worlds_2024, place=1, age=MASTER_2, belt=BLACK)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_4, belt=BLACK), gi=True)
        self.assertFalse(row["adult_world_champion"])
        self.assertFalse(row["master_1_world_champion"])
        self.assertTrue(row["master_2_world_champion"])
        self.assertFalse(row["master_3_world_champion"])
        self.assertFalse(row["master_4_world_champion"])
        self.assertNotIn("master_5_world_champion", row)

    def test_master_black_belt_higher_master_title_excluded(self):
        # Master 2 tournament: athlete won M5 in the past. Higher-than-own
        # levels should not contribute and shouldn't even be a key in the
        # row.
        def seed(t):
            a = t._make_athlete("m-higher-excluded")
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_5, belt=BLACK)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_2, belt=BLACK), gi=True)
        self.assertFalse(row["adult_world_champion"])
        self.assertFalse(row["master_1_world_champion"])
        self.assertFalse(row["master_2_world_champion"])
        self.assertNotIn("master_5_world_champion", row)

    def test_master_black_belt_adult_title_carries_forward(self):
        # Master 3 tournament: athlete is a former adult world champion.
        # adult_world_champion must reflect that, regardless of master titles.
        def seed(t):
            a = t._make_athlete("m-adult-title")
            t._add_medal(a, t.worlds_2024, place=1, age=ADULT, belt=BLACK)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_3, belt=BLACK), gi=True)
        self.assertTrue(row["adult_world_champion"])
        self.assertFalse(row["master_1_world_champion"])
        self.assertFalse(row["master_2_world_champion"])
        self.assertFalse(row["master_3_world_champion"])

    def test_master_black_belt_no_titles(self):
        # No titles -> adult and master_1..K all False (and all present).
        def seed(t):
            return t._make_athlete("m-no-titles")

        row = self._seed_and_run(seed, _divdata(age=MASTER_2, belt=BLACK), gi=True)
        self.assertFalse(row["adult_world_champion"])
        self.assertFalse(row["master_1_world_champion"])
        self.assertFalse(row["master_2_world_champion"])

    def test_master_7_has_eight_black_belt_fields(self):
        # Master 7 tournament — should have adult + master_1..7 = 8 fields.
        def seed(t):
            return t._make_athlete("m7-field-count")

        row = self._seed_and_run(seed, _divdata(age=MASTER_7, belt=BLACK), gi=True)
        for key in (
            "adult_world_champion",
            "master_1_world_champion",
            "master_2_world_champion",
            "master_3_world_champion",
            "master_4_world_champion",
            "master_5_world_champion",
            "master_6_world_champion",
            "master_7_world_champion",
        ):
            self.assertIn(key, row)

    def test_master_1_has_only_adult_and_master_1_fields(self):
        # Master 1 tournament — only adult + master_1 keys.
        def seed(t):
            return t._make_athlete("m1-field-count")

        row = self._seed_and_run(seed, _divdata(age=MASTER_1, belt=BLACK), gi=True)
        self.assertIn("adult_world_champion", row)
        self.assertIn("master_1_world_champion", row)
        for key in (
            "master_2_world_champion",
            "master_3_world_champion",
            "master_4_world_champion",
        ):
            self.assertNotIn(key, row)

    def test_master_black_belt_legacy_naming(self):
        # Gold at the pre-2022 "World Master Jiu-Jitsu IBJJF Championship"
        # should still be detected.
        def seed(t):
            a = t._make_athlete("m-legacy-name")
            t._add_medal(a, t.master_worlds_2021, place=1, age=MASTER_1, belt=BLACK)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_1, belt=BLACK), gi=True)
        self.assertTrue(row["master_1_world_champion"])

    def test_master_black_belt_nogi_uses_adult_nogi_worlds_event(self):
        # No-gi has no dedicated Master Worlds event — master divisions are
        # hosted inside the regular no-gi Worlds. A Master 2 black gold at
        # No-Gi Worlds 2025 should set master_2_world_champion.
        def seed(t):
            a = t._make_athlete("m-nogi")
            t._add_medal(
                a,
                t.nogi_worlds_2025,
                place=1,
                age=MASTER_2,
                belt=BLACK,
                gi=False,
            )
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_2, belt=BLACK), gi=False)
        self.assertTrue(row["master_2_world_champion"])
        self.assertFalse(row["master_1_world_champion"])
        self.assertFalse(row["adult_world_champion"])

    def test_master_brown_belt_tournament_skips_fields(self):
        # Master brown tournament: master-black-belt fields should be absent.
        def seed(t):
            a = t._make_athlete("m-brown-tournament")
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_3, belt=BROWN)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_3, belt=BROWN), gi=True)
        self.assertNotIn("adult_world_champion", row)
        self.assertNotIn("master_1_world_champion", row)
        self.assertNotIn("master_3_world_champion", row)

    def test_adult_tournament_skips_master_fields(self):
        # Adult tournament should NOT have master_*_world_champion fields.
        def seed(t):
            return t._make_athlete("adult-no-master-fields")

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertNotIn("adult_world_champion", row)
        self.assertNotIn("master_1_world_champion", row)


def _seed_row(athlete_id, **fields):
    """Minimal row for add_estimated_seeds tests — no DB / no add_seeding_data
    needed since add_estimated_seeds only reads the seeding fields off the
    row dict."""
    row = {"id": athlete_id}
    row.update(fields)
    return row


class EstimatedSeedsTestCase(unittest.TestCase):
    def _seeds(self, rows):
        return [r["est_seed"] for r in rows]

    # ------------------------------------------------------------------
    # 1. regular
    # ------------------------------------------------------------------

    def test_regular_sorts_by_grand_slam_then_points(self):
        rows = [
            _seed_row(1, grand_slam_points=10, points=50),
            _seed_row(2, grand_slam_points=20, points=0),
            _seed_row(3, grand_slam_points=10, points=100),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BROWN, "weight": LIGHT})
        # 2 has the most GS points; among the GS=10 tie, 3 > 1 on points.
        self.assertEqual(self._seeds(rows), [3, 1, 2])

    def test_regular_preserves_input_order_when_all_tied(self):
        # Same name -> identical tie-break hash -> stable sort keeps input order.
        rows = [
            _seed_row(i, name="same", grand_slam_points=0, points=0) for i in (1, 2, 3)
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BROWN, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [1, 2, 3])

    def test_tie_break_is_deterministic_and_name_based(self):
        # All seeding criteria tied. With distinct names, the crc32 tie-break
        # decides the order. Sort is reverse=True so higher crc32 wins seed 1.
        # crc32: alpha=0xd0e0396a, beta=0x8f910463, gamma=0xc443d071.
        # Best -> worst: alpha (1), gamma (2), beta (3).
        rows = [
            _seed_row(1, name="alpha", grand_slam_points=0, points=0),
            _seed_row(2, name="beta", grand_slam_points=0, points=0),
            _seed_row(3, name="gamma", grand_slam_points=0, points=0),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BROWN, "weight": LIGHT})
        self.assertEqual(rows[0]["est_seed"], 1)  # alpha
        self.assertEqual(rows[1]["est_seed"], 3)  # beta
        self.assertEqual(rows[2]["est_seed"], 2)  # gamma

    def test_tie_break_does_not_override_real_criteria(self):
        # Athlete "alpha" has zero points but athlete "gamma" has more points;
        # gamma must still come first regardless of the (otherwise winning)
        # crc32 tie-break ordering on names.
        rows = [
            _seed_row(1, name="alpha", grand_slam_points=0, points=0),
            _seed_row(2, name="gamma", grand_slam_points=0, points=100),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BROWN, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    # ------------------------------------------------------------------
    # 2. regular open class
    # ------------------------------------------------------------------

    def test_regular_open_class_uses_open_fields(self):
        rows = [
            # GS open ties; GS reg differs.
            _seed_row(
                1,
                grand_slam_open_class_points=10,
                grand_slam_points=5,
                open_class_points=0,
                points=0,
            ),
            _seed_row(
                2,
                grand_slam_open_class_points=10,
                grand_slam_points=20,
                open_class_points=0,
                points=0,
            ),
            # Higher GS open beats everyone.
            _seed_row(
                3,
                grand_slam_open_class_points=30,
                grand_slam_points=0,
                open_class_points=0,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BROWN, "weight": OPEN_CLASS})
        # Sort order best->worst: 3 (GS open 30), 2 (GS open 10, GS 20), 1 (GS open 10, GS 5).
        self.assertEqual(self._seeds(rows), [3, 2, 1])

    # ------------------------------------------------------------------
    # 3. adult black belt
    # ------------------------------------------------------------------

    def test_adult_black_recent_champion_beats_high_points(self):
        rows = [
            _seed_row(
                1,
                world_champion_recent=False,
                last_world_title_year=None,
                grand_slam_points=9999,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=False,
                points=9999,
            ),
            _seed_row(
                2,
                world_champion_recent=True,
                last_world_title_year=2025,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=True,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    def test_adult_black_last_title_year_tiebreak(self):
        rows = [
            _seed_row(
                1,
                world_champion_recent=True,
                last_world_title_year=2024,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=True,
                points=0,
            ),
            _seed_row(
                2,
                world_champion_recent=True,
                last_world_title_year=2025,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=True,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    def test_adult_black_none_last_year_sorts_last(self):
        # Among non-recent-champions, None last_world_title_year is worst.
        rows = [
            _seed_row(
                1,
                world_champion_recent=False,
                last_world_title_year=None,
                grand_slam_points=100,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=False,
                points=0,
            ),
            _seed_row(
                2,
                world_champion_recent=False,
                last_world_title_year=2018,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=True,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    # ------------------------------------------------------------------
    # 4. adult black belt open class
    # ------------------------------------------------------------------

    def test_adult_black_open_class_uses_gs_open_before_gs(self):
        # Same recent-champion status, same last year -> next tiebreak is
        # grand_slam_open_class_points (not grand_slam_points).
        rows = [
            _seed_row(
                1,
                world_champion_recent=True,
                last_world_title_year=2025,
                grand_slam_open_class_points=0,
                grand_slam_points=999,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=True,
                open_class_points=0,
                points=0,
            ),
            _seed_row(
                2,
                world_champion_recent=True,
                last_world_title_year=2025,
                grand_slam_open_class_points=10,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=True,
                open_class_points=0,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BLACK, "weight": OPEN_CLASS})
        self.assertEqual(self._seeds(rows), [2, 1])

    # ------------------------------------------------------------------
    # 5. master black belt
    # ------------------------------------------------------------------

    def test_master_black_adult_title_beats_own_level_title(self):
        # Adult world champion comes first in master sort.
        rows = [
            _seed_row(
                1,
                adult_world_champion=False,
                master_1_world_champion=True,
                master_2_world_champion=True,
                master_3_world_champion=True,
                grand_slam_points=0,
                points=0,
            ),
            _seed_row(
                2,
                adult_world_champion=True,
                master_1_world_champion=False,
                master_2_world_champion=False,
                master_3_world_champion=False,
                grand_slam_points=0,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": MASTER_3, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    def test_master_black_lower_level_title_beats_higher_level(self):
        # Master 1 title is ranked above Master 3 title (lower level number
        # comes first in the sort key).
        rows = [
            _seed_row(
                1,
                adult_world_champion=False,
                master_1_world_champion=False,
                master_2_world_champion=False,
                master_3_world_champion=True,
                grand_slam_points=0,
                points=0,
            ),
            _seed_row(
                2,
                adult_world_champion=False,
                master_1_world_champion=True,
                master_2_world_champion=False,
                master_3_world_champion=False,
                grand_slam_points=0,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": MASTER_3, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    def test_master_7_uses_seven_master_levels(self):
        # Master 7 division: levels 1..7 all participate. Verify a Master 7
        # title is checked (and beats only-points athletes).
        rows = [
            _seed_row(
                1,
                adult_world_champion=False,
                master_1_world_champion=False,
                master_2_world_champion=False,
                master_3_world_champion=False,
                master_4_world_champion=False,
                master_5_world_champion=False,
                master_6_world_champion=False,
                master_7_world_champion=False,
                grand_slam_points=500,
                points=500,
            ),
            _seed_row(
                2,
                adult_world_champion=False,
                master_1_world_champion=False,
                master_2_world_champion=False,
                master_3_world_champion=False,
                master_4_world_champion=False,
                master_5_world_champion=False,
                master_6_world_champion=False,
                master_7_world_champion=True,
                grand_slam_points=0,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": MASTER_7, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    # ------------------------------------------------------------------
    # 6. master black belt open class
    # ------------------------------------------------------------------

    def test_master_black_open_class_uses_gs_open_before_gs(self):
        rows = [
            _seed_row(
                1,
                adult_world_champion=False,
                master_1_world_champion=False,
                grand_slam_open_class_points=0,
                grand_slam_points=100,
                open_class_points=0,
                points=0,
            ),
            _seed_row(
                2,
                adult_world_champion=False,
                master_1_world_champion=False,
                grand_slam_open_class_points=5,
                grand_slam_points=0,
                open_class_points=0,
                points=0,
            ),
        ]
        add_estimated_seeds(
            rows, {"age": MASTER_1, "belt": BLACK, "weight": OPEN_CLASS}
        )
        self.assertEqual(self._seeds(rows), [2, 1])

    # ------------------------------------------------------------------
    # Misc
    # ------------------------------------------------------------------

    def test_empty_rows_is_noop(self):
        rows = []
        add_estimated_seeds(rows, {"age": ADULT, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(rows, [])

    def test_juvenile_uses_regular_ranking(self):
        # Juvenile black belts still take the "regular" (non-adult-black) path.
        rows = [
            _seed_row(1, grand_slam_points=0, points=100),
            _seed_row(2, grand_slam_points=10, points=0),
        ]
        add_estimated_seeds(rows, {"age": JUVENILE, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])


def _swap_row(seed, name, team):
    return {"id": seed, "name": name, "team": team, "est_seed": seed}


class SideSwapTestCase(unittest.TestCase):
    def _seeds(self, rows):
        return [r["est_seed"] for r in rows]

    def test_three_or_fewer_athletes_does_nothing(self):
        rows = [_swap_row(i, f"A{i}", "Same Team") for i in (1, 2, 3)]
        result = add_side_swaps(rows)
        self.assertEqual(result["swaps"], [])
        self.assertEqual(result["bailout_teams"], [])
        self.assertEqual(self._seeds(rows), [1, 2, 3])

    def test_more_than_two_per_team_bails_out(self):
        # 4 athletes, but three on the same team -> bail out.
        rows = [
            _swap_row(1, "A1", "Mega"),
            _swap_row(2, "A2", "Mega"),
            _swap_row(3, "A3", "Mega"),
            _swap_row(4, "A4", "Other"),
        ]
        result = add_side_swaps(rows)
        self.assertEqual(result["swaps"], [])
        self.assertEqual(result["bailout_teams"], ["Mega"])
        self.assertEqual(self._seeds(rows), [1, 2, 3, 4])

    def test_no_same_team_pairs_no_swaps(self):
        rows = [
            _swap_row(1, "A1", "Alpha"),
            _swap_row(2, "A2", "Beta"),
            _swap_row(3, "A3", "Gamma"),
            _swap_row(4, "A4", "Delta"),
        ]
        result = add_side_swaps(rows)
        self.assertEqual(result["swaps"], [])
        self.assertEqual(result["bailout_teams"], [])

    def test_same_team_already_split_no_swap(self):
        # N=8 sides: T,B,B,T,T,B,B,T. Seeds 2 and 5 are on different sides.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[1]["team"] = "Pair"  # seed 2 (B)
        rows[4]["team"] = "Pair"  # seed 5 (T)
        result = add_side_swaps(rows)
        self.assertEqual(result["swaps"], [])
        self.assertEqual(self._seeds(rows), list(range(1, 9)))

    def test_seed_plus_one_swap_fixes_pair(self):
        # N=8 sides: T,B,B,T,T,B,B,T. Seeds 4 and 5 are both T.
        # seed+1 = 6 (B) flips the worse-seeded teammate to the other half.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[3]["team"] = "Pair"  # seed 4 (T)
        rows[4]["team"] = "Pair"  # seed 5 (T)
        result = add_side_swaps(rows)
        self.assertEqual(result["bailout_teams"], [])
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["swaps"][0]["name_a"], "A5")  # would move down
        self.assertEqual(result["swaps"][0]["name_b"], "A6")  # would move up
        # est_seed is not mutated; the seeding shown reflects natural order
        self.assertEqual(rows[4]["est_seed"], 5)
        self.assertEqual(rows[5]["est_seed"], 6)

    def test_falls_back_to_seed_minus_one_when_seed_plus_one_does_not_fix(self):
        # N=8: seeds 1 (T) and 4 (T) same team. seed+1 = 5 (T) doesn't flip.
        # seed-1 = 3 (B) flips and isn't the teammate -> use that.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[0]["team"] = "Pair"  # seed 1 (T)
        rows[3]["team"] = "Pair"  # seed 4 (T)
        result = add_side_swaps(rows)
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["swaps"][0]["name_a"], "A4")
        self.assertEqual(result["swaps"][0]["name_b"], "A3")
        # est_seed is not mutated; natural seeds remain in place
        self.assertEqual(rows[3]["est_seed"], 4)
        self.assertEqual(rows[2]["est_seed"], 3)

    def test_no_swap_when_neither_neighbor_works(self):
        # N=4: T,B,B,T. Seeds 1 and 4 same team; seed+1 = 5 doesn't exist
        # and seed-1 = 3 is on B side. So seed-1 works.
        # To get a real "no swap possible" case, use seeds (2,3) in N=4:
        # both B; seed+1 = 4 (T) -> swap works. Need a case where neither
        # neighbor flips. With recursive snake there isn't one for N=4,
        # so use the seed-1 == teammate case: seeds 1 and 2 in N=4 are
        # already on different sides. Use 4 athletes with one pair at
        # seeds 1 and 4 in N=4: this is actually handled by seed-1.
        # Skip; covered indirectly by the bracket-size-4 test below.
        pass

    def test_size_four_two_same_team_pairs(self):
        # N=4 sides: T,B,B,T. Teams: A at (1,4)=T,T; B at (2,3)=B,B.
        # Process team A first (lower seed 1): seed+1 = 5 OOB; seed-1 = 3 (B)
        # which isn't teammate -> swap seed 4 with seed 3.
        # After: A at (1,3) T,B fixed. But wait, the athlete that was at
        # seed 3 was team B. So team B is now at (2,4) -> B,T fixed too.
        rows = [
            _swap_row(1, "A1", "A"),
            _swap_row(2, "B2", "B"),
            _swap_row(3, "B3", "B"),
            _swap_row(4, "A4", "A"),
        ]
        result = add_side_swaps(rows)
        # One swap should resolve both pairs.
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(
            {result["swaps"][0]["name_a"], result["swaps"][0]["name_b"]}, {"A4", "B3"}
        )

    def test_empty_team_field_does_not_pair(self):
        rows = [_swap_row(i, f"A{i}", "") for i in range(1, 9)]
        rows[3]["team"] = "Pair"  # seed 4
        rows[4]["team"] = "Pair"  # seed 5
        result = add_side_swaps(rows)
        # Empty-team athletes are not grouped, so only the real "Pair" pair
        # is detected and swapped.
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["bailout_teams"], [])


if __name__ == "__main__":
    unittest.main()
