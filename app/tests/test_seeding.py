import os
import sys
import unittest
from collections import namedtuple
from datetime import datetime

from bs4 import BeautifulSoup

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
from models import Athlete, Division, Event, Match, Medal, RegistrationLink, Team
from seeding import (
    _bracket_slots,
    _side,
    add_estimated_seeds,
    add_seeding_data,
    add_side_swaps,
)
from routes.brackets import add_canonical_display_match_numbers, parse_seed_swaps
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


def _live_match(match_num, red_seed, blue_seed, final=False):
    return {
        "match_num": match_num,
        "final": final,
        "when": None,
        "where": "Mat 1",
        "fight_num": match_num,
        "red_bye": False,
        "red_id": f"athlete-{red_seed}",
        "red_seed": red_seed,
        "red_next_description": None,
        "blue_bye": False,
        "blue_id": f"athlete-{blue_seed}",
        "blue_seed": blue_seed,
        "blue_next_description": None,
    }


def _live_bye_match(match_num, seed):
    bye_seed = None
    match = _live_match(match_num, seed, bye_seed)
    match["blue_bye"] = True
    match["blue_id"] = None
    match["blue_seed"] = None
    return match


def _live_child_match(match_num, red_description, blue_description, final=False):
    return {
        "match_num": match_num,
        "final": final,
        "when": None,
        "where": "Mat 1",
        "fight_num": match_num,
        "red_bye": False,
        "red_id": None,
        "red_seed": None,
        "red_next_description": red_description,
        "blue_bye": False,
        "blue_id": None,
        "blue_seed": None,
        "blue_next_description": blue_description,
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

        # Upcoming Worlds registration row. There is intentionally no
        # corresponding Event/Match row for 2026 in this fixture; regular
        # season boundaries should still advance for target tournaments that
        # happen after this start date.
        db.session.add(
            RegistrationLink(
                name="World IBJJF Jiu-Jitsu Championship 2026",
                normalized_name="world ibjjf jiu-jitsu championship 2026",
                updated_at=datetime(2026, 5, 1),
                link="internal:worlds-2026",
                hidden=False,
                event_start_date=datetime(2026, 5, 28),
                event_end_date=datetime(2026, 5, 31),
            )
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
        # Tournaments whose medals do not count toward seeding.
        cls.sul_brasil_2025 = add_event(
            "Campeonato Sul-Brasileiro de Jiu-Jitsu 2025", datetime(2025, 7, 12)
        )
        cls.portuguese_championship_2026 = add_event(
            "Campeonato Português de Jiu-Jitsu 2026", datetime(2026, 2, 7)
        )
        cls.portuguese_championship_ascii_2026 = add_event(
            "Campeonato Portugues 2026", datetime(2026, 2, 8)
        )
        cls.portuguese_championship_2025 = add_event(
            "Campeonato Português de Jiu-Jitsu 2025", datetime(2025, 2, 8)
        )
        cls.portuguese_championship_2024 = add_event(
            "Campeonato Português de Jiu-Jitsu 2024", datetime(2024, 2, 10)
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

    def _seed_and_run(
        self,
        seed_fn,
        divdata,
        gi,
        now=NOW,
        medal_cutoff=None,
    ):
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
            add_seeding_data(rows, divdata, gi, now=now, medal_cutoff=medal_cutoff)
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
            add_seeding_data(
                rows,
                _divdata(),
                gi=True,
                now=NOW,
            )
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

    def test_grand_slam_registration_anchor_consumes_empty_event_slot_after_end(self):
        # A registration-only Pans 2026 row should consume the newest Pans
        # GS slot after the event ends, pushing Pans 2025 from 3x to 2x
        # without creating any fake medal-scoring event.
        with self.app_module.app.app_context():
            pans_link = RegistrationLink(
                name="Pan IBJJF Jiu-Jitsu Championship 2026",
                normalized_name="pan ibjjf jiujitsu championship 2026",
                updated_at=datetime(2026, 2, 1),
                link="internal:pans-2026",
                hidden=False,
                event_start_date=datetime(2026, 3, 18),
                event_end_date=datetime(2026, 3, 22),
            )
            db.session.add(pans_link)
            a = self._make_athlete("pans-registration-gs-rollover")
            self._add_medal(a, self.pans_2025, place=1)
            db.session.commit()
            athlete_id = a.id

            pre_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                pre_rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 3, 17),
            )

            during_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                during_rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 3, 20),
            )

            post_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                post_rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 3, 23),
            )

            db.session.delete(pans_link)
            db.session.commit()

        self.assertEqual(pre_rows[0]["grand_slam_points"], 108)
        self.assertEqual(during_rows[0]["grand_slam_points"], 108)
        self.assertEqual(post_rows[0]["grand_slam_points"], 72)

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
            add_seeding_data(
                current_rows,
                _divdata(),
                gi=True,
                now=NOW,
            )

            pre_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                pre_rows,
                _divdata(),
                gi=True,
                now=datetime(2025, 5, 28),
            )

        self.assertEqual(current_rows[0]["points"], 126 + 63)
        self.assertEqual(pre_rows[0]["points"], 189 + 126)

    def test_upcoming_worlds_registration_advances_regular_season_anchor(self):
        # There is no Worlds 2026 Event/Match row in the fixture, only a
        # RegistrationLink running 2026-05-28 through 2026-05-31. For a
        # target after that event ends, the regular season should advance:
        # Worlds 2025 is now 2x, Worlds 2024 is 1x, and Worlds 2023 is
        # outside the window.
        def seed(t):
            a = t._make_athlete("future-target-season-rollover")
            t._add_medal(a, t.worlds_2025, place=1)
            t._add_medal(a, t.worlds_2024, place=1)
            t._add_medal(a, t.worlds_2023, place=1)
            return a

        row = self._seed_and_run(
            seed,
            _divdata(),
            gi=True,
            now=datetime(2026, 6, 1),
        )
        self.assertEqual(row["points"], 126 + 63)
        # The registration-only Worlds 2026 row also consumes the newest
        # Worlds GS slot, but contributes no medals itself. Worlds 2025 drops
        # to 2x, Worlds 2024 to 1x, and Worlds 2023 drops out.
        self.assertEqual(row["grand_slam_points"], 126 + 63)

    def test_worlds_registration_does_not_advance_while_event_is_running(self):
        # During a multi-day Worlds event, IBJJF open-class seeding still uses
        # the previous season's multipliers. The new Worlds start date becomes
        # a medal boundary later, but it does not occupy the 3x multiplier slot
        # until after the event end date.
        def seed(t):
            a = t._make_athlete("in-progress-worlds-season-still-current")
            t._add_medal(a, t.worlds_2025, place=1)
            t._add_medal(a, t.worlds_2024, place=1)
            t._add_medal(a, t.worlds_2023, place=1)
            return a

        row = self._seed_and_run(
            seed,
            _divdata(),
            gi=True,
            now=datetime(2026, 5, 30),
        )
        self.assertEqual(row["points"], 189 + 126 + 63)
        self.assertEqual(row["grand_slam_points"], 189 + 126 + 63)

    def test_worlds_result_event_does_not_advance_while_event_is_running(self):
        # Even if match records have started arriving for the current Worlds,
        # the matching registration end date keeps the multiplier rollover
        # from happening mid-event.
        with self.app_module.app.app_context():
            event = Event(
                name="World IBJJF Jiu-Jitsu Championship 2026",
                normalized_name="world ibjjf jiu-jitsu championship 2026",
                slug="world-ibjjf-jiu-jitsu-championship-2026-in-progress-test",
                medals_only=False,
            )
            db.session.add(event)
            db.session.flush()
            match = Match(
                event_id=event.id,
                division_id=self.anchor_div_id,
                happened_at=datetime(2026, 5, 28),
                rated=True,
            )
            db.session.add(match)
            a = self._make_athlete("in-progress-worlds-result-event-still-current")
            self._add_medal(a, self.worlds_2025, place=1)
            self._add_medal(a, self.worlds_2024, place=1)
            self._add_medal(a, self.worlds_2023, place=1)
            db.session.commit()
            athlete_id = a.id

            rows = [_registration_row(athlete_id)]
            add_seeding_data(rows, _divdata(), gi=True, now=datetime(2026, 5, 30))

            db.session.delete(match)
            db.session.delete(event)
            db.session.commit()

        self.assertEqual(rows[0]["points"], 189 + 126 + 63)
        self.assertEqual(rows[0]["grand_slam_points"], 189 + 126 + 63)

    def test_upcoming_worlds_registration_does_not_advance_before_start_date(self):
        # The same RegistrationLink should not matter for targets before
        # Worlds 2026 starts.
        def seed(t):
            a = t._make_athlete("pre-worlds-season-still-current")
            t._add_medal(a, t.worlds_2025, place=1)
            t._add_medal(a, t.worlds_2024, place=1)
            t._add_medal(a, t.worlds_2023, place=1)
            return a

        row = self._seed_and_run(
            seed,
            _divdata(),
            gi=True,
            now=datetime(2026, 5, 27),
        )
        self.assertEqual(row["points"], 189 + 126 + 63)

    def test_future_target_cutoff_does_not_advance_registration_anchor(self):
        # Registration pages cap medals at the target event start, but season
        # anchors should still be evaluated as of the current date. Before
        # Worlds 2026 starts, its own RegistrationLink must not push Worlds
        # 2025 down to 2x.
        def seed(t):
            a = t._make_athlete("future-worlds-target-still-current")
            t._add_medal(a, t.worlds_2025, place=1)
            t._add_medal(a, t.worlds_2024, place=1)
            t._add_medal(a, t.worlds_2023, place=1)
            return a

        row = self._seed_and_run(
            seed,
            _divdata(),
            gi=True,
            now=datetime(2026, 5, 26),
            medal_cutoff=datetime(2026, 5, 28),
        )
        self.assertEqual(row["points"], 189 + 126 + 63)
        self.assertEqual(row["grand_slam_points"], 189 + 126 + 63)

    def test_worlds_medals_from_first_day_count_in_new_season_after_event_ends(self):
        with self.app_module.app.app_context():
            event = Event(
                name="World IBJJF Jiu-Jitsu Championship 2026",
                normalized_name="world ibjjf jiu-jitsu championship 2026",
                slug="world-ibjjf-jiu-jitsu-championship-2026-test",
                medals_only=False,
            )
            db.session.add(event)
            db.session.flush()
            match = Match(
                event_id=event.id,
                division_id=self.anchor_div_id,
                happened_at=datetime(2026, 5, 28),
                rated=True,
            )
            db.session.add(match)
            a = self._make_athlete("worlds-2026-first-day-counts-after-end")
            medal = self._add_medal(
                a,
                _EventRef(event.id, datetime(2026, 5, 28)),
                place=1,
                happened_at=datetime(2026, 5, 28),
            )
            db.session.commit()
            athlete_id = a.id

            rows = [_registration_row(athlete_id)]
            add_seeding_data(rows, _divdata(), gi=True, now=datetime(2026, 6, 1))

            medal_division = db.session.get(Division, medal.division_id)
            db.session.delete(medal)
            if medal_division is not None:
                db.session.delete(medal_division)
            db.session.delete(match)
            db.session.delete(event)
            db.session.commit()

        self.assertEqual(rows[0]["points"], 189)
        self.assertEqual(rows[0]["grand_slam_points"], 189)

    # ------------------------------------------------------------------
    # Source tournament classification
    # ------------------------------------------------------------------

    def test_sul_brasileiro_source_never_scores(self):
        # Sul-Brasileiro medals must not contribute.
        def seed(t):
            a = t._make_athlete("sul-brasil-never-scores")
            t._add_medal(a, t.sul_brasil_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 0)

    def test_portuguese_championship_2026_and_later_source_never_scores(self):
        # The 2026+ Portuguese Championship is excluded, including the
        # accentless short spelling.
        def seed(t):
            a = t._make_athlete("portuguese-2026-never-scores")
            t._add_medal(a, t.portuguese_championship_2026, place=1)
            t._add_medal(a, t.portuguese_championship_ascii_2026, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 0)

    def test_portuguese_championship_before_2026_still_scores(self):
        # The exclusion starts with the 2026 edition; 2025 and 2024 remain
        # normal 1-star tournaments. They fall in the 2x and 1x IBJJF
        # seasons, respectively.
        def seed(t):
            a = t._make_athlete("portuguese-2025-still-scores")
            t._add_medal(a, t.portuguese_championship_2025, place=1)
            t._add_medal(a, t.portuguese_championship_2024, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 27)

    def test_brazilian_source_uses_ibjjf_schedule(self):
        # Brasileiros 2025 (2025-04-26):
        # - Regular: IBJJF Worlds-anchored seasons; 2025-04-26 is before
        #   Worlds 2025 (2025-05-29) and after Worlds 2024 (2024-05-30) ->
        #   2x slot. Star=4. Points: 9 * 2 * 1.0 * 4 = 72.
        # - Grand Slam: brasil_2025 is the most-recent Brasileiros -> 3x.
        #   GS points: 9 * 3 * 1.0 * 4 = 108.
        def seed(t):
            a = t._make_athlete("brasileiros-into-pan")
            t._add_medal(a, t.brasil_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 72)
        self.assertEqual(row["grand_slam_points"], 108)

    def test_brasileiros_registration_advances_grand_slam_slot_only(self):
        # A registration-only Brasileiros 2026 row should advance the
        # Brasileiros Grand Slam slot after it ends. Regular points still
        # use the IBJJF Worlds-anchored season.
        with self.app_module.app.app_context():
            brasileiros_link = RegistrationLink(
                name="Campeonato Brasileiro de Jiu-Jitsu 2026",
                normalized_name="campeonato brasileiro de jiu-jitsu 2026",
                updated_at=datetime(2026, 4, 1),
                link="internal:brasileiros-2026",
                hidden=False,
                event_start_date=datetime(2026, 4, 24),
                event_end_date=datetime(2026, 5, 3),
            )
            db.session.add(brasileiros_link)
            a = self._make_athlete("brasileiros-registration-rollover")
            self._add_medal(a, self.brasil_2025, place=1)
            db.session.commit()
            athlete_id = a.id

            pre_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                pre_rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 4, 23),
            )

            during_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                during_rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 4, 25),
            )

            post_rows = [_registration_row(athlete_id)]
            add_seeding_data(
                post_rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 5, 4),
            )

            db.session.delete(brasileiros_link)
            db.session.commit()

        self.assertEqual(pre_rows[0]["points"], 72)
        self.assertEqual(pre_rows[0]["grand_slam_points"], 108)
        self.assertEqual(during_rows[0]["points"], 72)
        self.assertEqual(during_rows[0]["grand_slam_points"], 108)
        self.assertEqual(post_rows[0]["points"], 72)
        self.assertEqual(post_rows[0]["grand_slam_points"], 72)

    def test_brasileiros_kids_registration_does_not_delay_adult_grand_slam_slot(self):
        # Parenthetical qualifiers are stripped for duplicate-source matching,
        # but the separate age-4-to-15 event must not share the adult
        # Brasileiros anchor.
        with self.app_module.app.app_context():
            adult_link = RegistrationLink(
                name="Campeonato Brasileiro de Jiu-Jitsu 2026",
                normalized_name="campeonato brasileiro de jiu-jitsu 2026",
                updated_at=datetime(2026, 4, 1),
                link="internal:brasileiros-adult-2026",
                hidden=False,
                event_start_date=datetime(2026, 4, 24),
                event_end_date=datetime(2026, 5, 3),
            )
            kids_link = RegistrationLink(
                name="Campeonato Brasileiro de Jiu-Jitsu (idade 04 a 15 anos) 2026",
                normalized_name="campeonato brasileiro de jiu-jitsu idade 04 a 15 anos 2026",
                updated_at=datetime(2026, 5, 1),
                link="internal:brasileiros-kids-2026",
                hidden=False,
                event_start_date=datetime(2026, 6, 12),
                event_end_date=datetime(2026, 6, 14),
            )
            db.session.add(adult_link)
            db.session.add(kids_link)
            a = self._make_athlete("brasileiros-kids-link-does-not-delay")
            self._add_medal(a, self.brasil_2025, place=1)
            db.session.commit()
            athlete_id = a.id

            rows = [_registration_row(athlete_id)]
            add_seeding_data(
                rows,
                _divdata(),
                gi=True,
                now=datetime(2026, 5, 4),
            )

            db.session.delete(adult_link)
            db.session.delete(kids_link)
            db.session.commit()

        self.assertEqual(rows[0]["grand_slam_points"], 72)

    def test_ibjjf_only_source_uses_ibjjf_schedule(self):
        # Worlds 2025 medal uses the IBJJF schedule.
        # 9 (gold) * 3 (regular season 3x) * 1.0 (weight) * 7 (star) = 189.
        def seed(t):
            a = t._make_athlete("worlds-only-source")
            t._add_medal(a, t.worlds_2025, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(), gi=True)
        self.assertEqual(row["points"], 189)

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
        self.assertEqual(row["former_world_champion"], 2025)
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
        self.assertEqual(row["former_world_champion"], 2022)

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
        self.assertEqual(row["former_world_champion"], 2021)

    def test_adult_black_belt_former_champion_only(self):
        # Gold at Worlds 2020 (rank 5) — older than any tracked slot, so
        # only ``former_world_champion`` should have a value.
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
        self.assertEqual(row["former_world_champion"], 2020)

    def test_adult_black_belt_last_world_title_year_takes_max(self):
        # Multiple Worlds titles — ``last_world_title_year`` should report
        # the most recent year among the 3 most-recent past Worlds. Older
        # tracked-year flags are independent, and former_world_champion is
        # the most-recent title in any weight.
        def seed(t):
            a = t._make_athlete("bb-multi-titles")
            t._add_medal(a, t.worlds_2023, place=1)
            t._add_medal(a, t.worlds_2021, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertEqual(row["last_world_title_year"], 2023)
        self.assertTrue(row["world_champion_recent"])  # 2023 is rank 2
        self.assertFalse(row["world_champion_4_years_ago"])
        self.assertTrue(row["world_champion_5_years_ago"])
        self.assertEqual(row["former_world_champion"], 2023)

    def test_adult_black_belt_title_flags_are_independent(self):
        def seed(t):
            a = t._make_athlete("bb-independent-title-flags")
            t._add_medal(a, t.worlds_2025, place=1)
            t._add_medal(a, t.worlds_2022, place=1)
            t._add_medal(a, t.worlds_2021, place=1)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK), gi=True)
        self.assertTrue(row["world_champion_recent"])
        self.assertEqual(row["last_world_title_year"], 2025)
        self.assertTrue(row["world_champion_4_years_ago"])
        self.assertTrue(row["world_champion_5_years_ago"])
        self.assertEqual(row["former_world_champion"], 2025)

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
        self.assertIsNone(row["former_world_champion"])
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
        self.assertIsNone(row["former_world_champion"])
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
        # weight-scoped flags, but it *does* set ``former_world_champion``
        # (which matches a black-belt gold in any weight class).
        def seed(t):
            a = t._make_athlete("bb-wrong-weight")
            t._add_medal(a, t.worlds_2025, place=1, weight=HEAVY)
            return a

        row = self._seed_and_run(seed, _divdata(belt=BLACK, weight=LIGHT), gi=True)
        self.assertFalse(row["world_champion_recent"])
        self.assertIsNone(row["last_world_title_year"])
        self.assertFalse(row["world_champion_4_years_ago"])
        self.assertFalse(row["world_champion_5_years_ago"])
        self.assertEqual(row["former_world_champion"], 2025)

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
        # Master 4 tournament: athlete is the current M2 black champ.
        # Should set master_2_world_champion. M5+ shouldn't even be a key.
        def seed(t):
            a = t._make_athlete("m-carries-lower")
            t._add_medal(a, t.master_worlds_2025, place=1, age=MASTER_2, belt=BLACK)
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
        # Master 3 tournament: athlete is the current adult world champion.
        # adult_world_champion must reflect that, regardless of master titles.
        def seed(t):
            a = t._make_athlete("m-adult-title")
            t._add_medal(a, t.worlds_2025, place=1, age=ADULT, belt=BLACK)
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

    def test_master_black_belt_only_current_title_counts(self):
        # Only the most-recent past Master Worlds counts for
        # master_K_world_champion. An old (pre-2022 legacy-named) gold
        # must NOT set the flag.
        def seed(t):
            a = t._make_athlete("m-old-title")
            t._add_medal(a, t.master_worlds_2021, place=1, age=MASTER_1, belt=BLACK)
            return a

        row = self._seed_and_run(seed, _divdata(age=MASTER_1, belt=BLACK), gi=True)
        self.assertFalse(row["master_1_world_champion"])

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
                former_world_champion=None,
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
                former_world_champion=2025,
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
                former_world_champion=2024,
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
                former_world_champion=2025,
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
                former_world_champion=None,
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
                former_world_champion=2018,
                points=0,
            ),
        ]
        add_estimated_seeds(rows, {"age": ADULT, "belt": BLACK, "weight": LIGHT})
        self.assertEqual(self._seeds(rows), [2, 1])

    def test_adult_black_former_world_champion_year_tiebreak(self):
        rows = [
            _seed_row(
                1,
                world_champion_recent=False,
                last_world_title_year=None,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=2021,
                points=0,
            ),
            _seed_row(
                2,
                world_champion_recent=False,
                last_world_title_year=None,
                grand_slam_points=0,
                world_champion_4_years_ago=False,
                world_champion_5_years_ago=False,
                previous_brown_world_champion=False,
                former_world_champion=2024,
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
                former_world_champion=2025,
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
                former_world_champion=2025,
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


class BracketSlotsTestCase(unittest.TestCase):
    """Tests for _bracket_slots(n) — the first-round slot layout."""

    def test_n_less_than_4_returns_none(self):
        for n in (0, 1, 2, 3):
            with self.subTest(n=n):
                slots, size = _bracket_slots(n)
                self.assertIsNone(slots)
                self.assertIsNone(size)

    def test_n4_slots(self):
        slots, size = _bracket_slots(4)
        self.assertEqual(slots, [(1, 4), (2, 3)])
        self.assertEqual(size, 4)

    def test_n8_slots(self):
        slots, size = _bracket_slots(8)
        self.assertEqual(slots, [(1, 8), (6, 4), (3, 5), (2, 7)])
        self.assertEqual(size, 8)

    def test_n7_slots_match_canonical_order(self):
        slots, size = _bracket_slots(7)
        self.assertEqual(slots, [(1, None), (6, 4), (3, 5), (2, 7)])
        self.assertEqual(size, 8)

    def test_n11_slots_match_canonical_order(self):
        slots, size = _bracket_slots(11)
        self.assertEqual(
            slots,
            [
                (1, None),
                (8, 11),
                (6, None),
                (4, None),
                (3, None),
                (5, 9),
                (2, None),
                (7, 10),
            ],
        )
        self.assertEqual(size, 16)

    def test_n13_slots_match_canonical_order(self):
        slots, size = _bracket_slots(13)
        self.assertEqual(
            slots,
            [
                (1, None),
                (8, 12),
                (6, 10),
                (4, 13),
                (3, None),
                (5, 9),
                (2, None),
                (7, 11),
            ],
        )
        self.assertEqual(size, 16)

    def test_n14_slots_match_canonical_order(self):
        slots, size = _bracket_slots(14)
        self.assertEqual(
            slots,
            [
                (1, None),
                (8, 12),
                (6, 10),
                (4, 14),
                (3, 13),
                (5, 9),
                (2, None),
                (7, 11),
            ],
        )
        self.assertEqual(size, 16)

    def test_n10_slots_match_canonical_order(self):
        slots, size = _bracket_slots(10)
        self.assertEqual(
            slots,
            [
                (1, None),
                (8, 10),
                (6, None),
                (4, None),
                (3, None),
                (5, None),
                (2, None),
                (7, 9),
            ],
        )
        self.assertEqual(size, 16)

    def test_n16_slots_match_canonical_order(self):
        slots, size = _bracket_slots(16)
        self.assertEqual(
            slots,
            [
                (1, 16),
                (8, 12),
                (4, 14),
                (6, 10),
                (2, 15),
                (7, 11),
                (3, 13),
                (5, 9),
            ],
        )
        self.assertEqual(size, 16)

    def test_n20_slots_match_canonical_order(self):
        slots, size = _bracket_slots(20)
        self.assertEqual(
            slots,
            [
                (1, None),
                (16, 20),
                (8, None),
                (12, None),
                (4, None),
                (14, 18),
                (6, None),
                (10, None),
                (2, None),
                (15, 19),
                (7, None),
                (11, None),
                (3, None),
                (13, 17),
                (5, None),
                (9, None),
            ],
        )
        self.assertEqual(size, 32)

    def test_n33_slots_match_canonical_order(self):
        slots, size = _bracket_slots(33)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, None),
                (16, None),
                (24, None),
                (8, None),
                (28, None),
                (12, None),
                (20, None),
                (4, None),
                (30, None),
                (14, None),
                (22, None),
                (6, None),
                (26, None),
                (10, None),
                (18, None),
                (2, None),
                (31, None),
                (15, None),
                (23, None),
                (7, None),
                (27, None),
                (11, None),
                (19, None),
                (3, None),
                (29, 33),
                (13, None),
                (21, None),
                (5, None),
                (25, None),
                (9, None),
                (17, None),
            ],
        )
        self.assertEqual(size, 64)

    def test_n35_slots_match_canonical_order(self):
        slots, size = _bracket_slots(35)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, None),
                (16, None),
                (24, None),
                (8, None),
                (28, None),
                (12, None),
                (20, None),
                (4, None),
                (30, 34),
                (14, None),
                (22, None),
                (6, None),
                (26, None),
                (10, None),
                (18, None),
                (2, None),
                (31, 35),
                (15, None),
                (23, None),
                (7, None),
                (27, None),
                (11, None),
                (19, None),
                (3, None),
                (29, 33),
                (13, None),
                (21, None),
                (5, None),
                (25, None),
                (9, None),
                (17, None),
            ],
        )
        self.assertEqual(size, 64)

    def test_n36_slots_match_canonical_order(self):
        slots, size = _bracket_slots(36)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, 36),
                (16, None),
                (24, None),
                (8, None),
                (28, None),
                (12, None),
                (20, None),
                (4, None),
                (30, 34),
                (14, None),
                (22, None),
                (6, None),
                (26, None),
                (10, None),
                (18, None),
                (2, None),
                (31, 35),
                (15, None),
                (23, None),
                (7, None),
                (27, None),
                (11, None),
                (19, None),
                (3, None),
                (29, 33),
                (13, None),
                (21, None),
                (5, None),
                (25, None),
                (9, None),
                (17, None),
            ],
        )
        self.assertEqual(size, 64)

    def test_n40_slots_match_canonical_order(self):
        slots, size = _bracket_slots(40)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, 40),
                (16, None),
                (24, None),
                (8, None),
                (28, 36),
                (12, None),
                (20, None),
                (4, None),
                (30, 38),
                (14, None),
                (22, None),
                (6, None),
                (26, 34),
                (10, None),
                (18, None),
                (2, None),
                (31, 39),
                (15, None),
                (23, None),
                (7, None),
                (27, 35),
                (11, None),
                (19, None),
                (3, None),
                (29, 37),
                (13, None),
                (21, None),
                (5, None),
                (25, 33),
                (9, None),
                (17, None),
            ],
        )
        self.assertEqual(size, 64)

    def test_n44_slots_match_canonical_order(self):
        slots, size = _bracket_slots(44)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, 40),
                (16, None),
                (24, None),
                (8, None),
                (28, 44),
                (12, None),
                (20, 36),
                (4, None),
                (30, 38),
                (14, None),
                (22, None),
                (6, None),
                (26, 42),
                (10, None),
                (18, 34),
                (2, None),
                (31, 39),
                (15, None),
                (23, None),
                (7, None),
                (27, 43),
                (11, None),
                (19, 35),
                (3, None),
                (29, 37),
                (13, None),
                (21, None),
                (5, None),
                (25, 41),
                (9, None),
                (17, 33),
            ],
        )
        self.assertEqual(size, 64)

    def test_n52_slots_match_canonical_order(self):
        slots, size = _bracket_slots(52)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, 48),
                (16, 52),
                (24, 40),
                (8, None),
                (28, 44),
                (12, None),
                (20, 36),
                (4, None),
                (30, 46),
                (14, 50),
                (22, 38),
                (6, None),
                (26, 42),
                (10, None),
                (18, 34),
                (2, None),
                (31, 47),
                (15, 51),
                (23, 39),
                (7, None),
                (27, 43),
                (11, None),
                (19, 35),
                (3, None),
                (29, 45),
                (13, 49),
                (21, 37),
                (5, None),
                (25, 41),
                (9, None),
                (17, 33),
            ],
        )
        self.assertEqual(size, 64)

    def test_n55_slots_match_canonical_order(self):
        slots, size = _bracket_slots(55)
        self.assertEqual(
            slots,
            [
                (1, None),
                (32, 48),
                (16, 55),
                (24, 40),
                (8, None),
                (28, 44),
                (12, 52),
                (20, 36),
                (4, None),
                (30, 46),
                (14, 54),
                (22, 38),
                (6, None),
                (26, 42),
                (10, 50),
                (18, 34),
                (2, None),
                (31, 47),
                (15, 53),
                (23, 39),
                (7, None),
                (27, 43),
                (11, 51),
                (19, 35),
                (3, None),
                (29, 45),
                (13, 49),
                (21, 37),
                (5, None),
                (25, 41),
                (9, None),
                (17, 33),
            ],
        )
        self.assertEqual(size, 64)

    def test_n66_slots_match_canonical_order(self):
        slots, size = _bracket_slots(66)
        self.assertEqual(
            slots,
            [
                (1, None),
                (64, None),
                (32, None),
                (48, None),
                (16, None),
                (56, None),
                (24, None),
                (40, None),
                (8, None),
                (60, None),
                (28, None),
                (44, None),
                (12, None),
                (52, None),
                (20, None),
                (36, None),
                (4, None),
                (62, None),
                (30, None),
                (46, None),
                (14, None),
                (54, None),
                (22, None),
                (38, None),
                (6, None),
                (58, 66),
                (26, None),
                (42, None),
                (10, None),
                (50, None),
                (18, None),
                (34, None),
                (2, None),
                (63, None),
                (31, None),
                (47, None),
                (15, None),
                (55, None),
                (23, None),
                (39, None),
                (7, None),
                (59, None),
                (27, None),
                (43, None),
                (11, None),
                (51, None),
                (19, None),
                (35, None),
                (3, None),
                (61, None),
                (29, None),
                (45, None),
                (13, None),
                (53, None),
                (21, None),
                (37, None),
                (5, None),
                (57, 65),
                (25, None),
                (41, None),
                (9, None),
                (49, None),
                (17, None),
                (33, None),
            ],
        )
        self.assertEqual(size, 128)

    def test_n72_slots_match_canonical_order(self):
        slots, size = _bracket_slots(72)
        self.assertEqual(
            slots,
            [
                (1, None),
                (64, 72),
                (32, None),
                (48, None),
                (16, None),
                (56, None),
                (24, None),
                (40, None),
                (8, None),
                (60, 68),
                (28, None),
                (44, None),
                (12, None),
                (52, None),
                (20, None),
                (36, None),
                (4, None),
                (62, 70),
                (30, None),
                (46, None),
                (14, None),
                (54, None),
                (22, None),
                (38, None),
                (6, None),
                (58, 66),
                (26, None),
                (42, None),
                (10, None),
                (50, None),
                (18, None),
                (34, None),
                (2, None),
                (63, 71),
                (31, None),
                (47, None),
                (15, None),
                (55, None),
                (23, None),
                (39, None),
                (7, None),
                (59, 67),
                (27, None),
                (43, None),
                (11, None),
                (51, None),
                (19, None),
                (35, None),
                (3, None),
                (61, 69),
                (29, None),
                (45, None),
                (13, None),
                (53, None),
                (21, None),
                (37, None),
                (5, None),
                (57, 65),
                (25, None),
                (41, None),
                (9, None),
                (49, None),
                (17, None),
                (33, None),
            ],
        )
        self.assertEqual(size, 128)

    def test_n5_play_in(self):
        # Seed 5 is the play-in partner of seed 4.
        slots, size = _bracket_slots(5)
        self.assertEqual(size, 8)
        self.assertIn((4, 5), slots)
        self.assertIn((1, None), slots)
        self.assertIn((2, None), slots)
        self.assertIn((3, None), slots)

    def test_n6_slots_match_ibjjf_pairings(self):
        slots, size = _bracket_slots(6)
        self.assertEqual(size, 8)
        self.assertEqual(slots, [(1, None), (4, 6), (2, None), (3, 5)])

    def test_n15_power_up_layout(self):
        # usePowerUpLayout: uses 16-slot table with seed 16 as a bye.
        slots, size = _bracket_slots(15)
        self.assertEqual(size, 16)
        self.assertEqual(len(slots), 8)
        # Seed 1 gets a bye (no partner in a 15-person bracket).
        self.assertIn((1, None), slots)

    def test_seed_1_and_seed_2_are_in_opposite_visual_halves(self):
        for n in [4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 16, 32]:
            with self.subTest(n=n):
                slots, _ = _bracket_slots(n)
                half = len(slots) // 2
                seed1_idx = next(
                    i for i, (a, b) in enumerate(slots) if a == 1 or b == 1
                )
                seed2_idx = next(
                    i for i, (a, b) in enumerate(slots) if a == 2 or b == 2
                )
                self.assertNotEqual(seed1_idx < half, seed2_idx < half)

    def test_all_seeds_present(self):
        for n in [
            4,
            5,
            6,
            7,
            8,
            9,
            10,
            11,
            13,
            15,
            16,
            33,
            35,
            36,
            40,
            44,
            52,
            55,
            66,
            72,
        ]:
            with self.subTest(n=n):
                slots, _ = _bracket_slots(n)
                seen = set()
                for a, b in slots:
                    if a is not None:
                        seen.add(a)
                    if b is not None:
                        seen.add(b)
                self.assertEqual(seen, set(range(1, n + 1)))

    def test_bracket_match_count(self):
        # bracket_match_count = bracket_size - 1
        for n, expected_size in [(4, 4), (8, 8), (5, 8), (9, 16), (15, 16), (16, 16)]:
            with self.subTest(n=n):
                _, size = _bracket_slots(n)
                self.assertEqual(size - 1, expected_size - 1)


class LiveBracketDisplayMatchNumberTestCase(unittest.TestCase):
    def test_parse_seed_swaps_from_ibjjf_swap_list(self):
        soup = BeautifulSoup(
            """
            <ul class="tournament-category__swap">
                <li>
                    <span>10 - Sione Paul Halo</span>
                    <i class="fa fa-arrow-right"></i>
                    <span>9 - Max Christopher Oglesby</span>
                </li>
            </ul>
            """,
            "html.parser",
        )

        self.assertEqual(parse_seed_swaps(soup), {10: 9, 9: 10})

    def test_completed_n8_bracket_gets_unique_canonical_display_numbers(self):
        matches = [
            _live_match(40, 1, 8),
            _live_match(10, 6, 4),
            _live_match(70, 3, 5),
            _live_match(20, 2, 7),
            _live_match(50, 1, 4),
            _live_match(60, 3, 2),
            _live_match(30, 1, 2, final=True),
        ]

        add_canonical_display_match_numbers(matches, 8)

        display_by_match_num = {
            match["match_num"]: match["display_match_num"] for match in matches
        }
        self.assertEqual(
            display_by_match_num,
            {
                40: 1,
                10: 2,
                70: 3,
                20: 4,
                50: 5,
                60: 6,
                30: 7,
            },
        )
        self.assertEqual(
            sorted(match["display_match_num"] for match in matches),
            list(range(1, 8)),
        )

    def test_n7_live_matches_line_up_with_dependency_graph(self):
        fight5 = _live_match(5, 2, 7)
        fight6 = _live_match(6, 4, 5)
        fight8 = _live_match(8, 3, 6)
        semifinal_a = _live_child_match(
            9,
            "Winner of Fight 5, Mat 1",
            "Winner of Fight 6, Mat 1",
        )
        semifinal_b = {
            **_live_child_match(
                10,
                "",
                "Winner of Fight 8, Mat 1",
            ),
            "red_id": "athlete-1",
            "red_seed": 1,
            "red_next_description": None,
        }
        final = _live_child_match(
            11,
            "Winner of Fight 9, Mat 1",
            "Winner of Fight 10, Mat 1",
            final=True,
        )
        matches = [fight5, fight6, fight8, semifinal_a, semifinal_b, final]

        add_canonical_display_match_numbers(matches, 7)

        display_by_match_num = {
            match["match_num"]: match["display_match_num"] for match in matches
        }
        self.assertEqual(
            display_by_match_num,
            {
                5: 4,
                6: 3,
                8: 2,
                9: 6,
                10: 5,
                11: 7,
            },
        )

    def test_n11_first_round_live_matches_get_canonical_display_numbers(self):
        matches = [
            _live_match(1, 7, 10),
            _live_match(2, 5, 9),
            _live_match(3, 8, 11),
            _live_bye_match(4, 1),
            _live_bye_match(5, 2),
            _live_bye_match(6, 3),
            _live_bye_match(7, 4),
            _live_bye_match(8, 6),
        ]

        add_canonical_display_match_numbers(matches, 11)

        display_by_seed = {
            match["red_seed"]: match["display_match_num"] for match in matches
        }
        self.assertEqual(
            display_by_seed,
            {
                1: 1,
                8: 2,
                6: 3,
                4: 4,
                3: 5,
                5: 6,
                2: 7,
                7: 8,
            },
        )

    def test_n10_live_matches_with_ibjjf_swap_get_canonical_display_numbers(self):
        matches = [
            _live_match(1, 8, 9),
            _live_match(5, 7, 10),
            _live_match(9, 9, 1),
            _live_match(11, 10, 2),
            _live_bye_match(2, 1),
            _live_bye_match(6, 2),
            _live_child_match(
                13,
                "Winner of Fight 4, Mat 1",
                "Winner of Fight 6, Mat 1",
            ),
            _live_child_match(
                14,
                "Winner of Fight 5, Mat 1",
                "Winner of Fight 7, Mat 1",
            ),
            _live_bye_match(3, 4),
            _live_bye_match(7, 3),
            _live_match(10, 4, 6),
            _live_match(12, 3, 5),
            _live_bye_match(4, 6),
            _live_bye_match(8, 5),
            _live_child_match(
                15,
                "Winner of Fight 10, Mat 1",
                "Winner of Fight 9, Mat 1",
                final=True,
            ),
        ]

        for match, fight_num in zip(
            matches,
            [1, 2, 4, 7, None, None, 9, 10, None, None, 5, 6, None, None, 13],
        ):
            match["fight_num"] = fight_num

        add_canonical_display_match_numbers(matches, 10, {9: 10, 10: 9})

        display_by_match_num = {
            match["match_num"]: match["display_match_num"] for match in matches
        }
        self.assertEqual(
            display_by_match_num,
            {
                1: 2,
                2: 1,
                3: 4,
                4: 3,
                5: 8,
                6: 7,
                7: 5,
                8: 6,
                9: 9,
                10: 10,
                11: 12,
                12: 11,
                13: 13,
                14: 14,
                15: 15,
            },
        )

    def test_n14_live_matches_tolerate_stale_ibjjf_child_references(self):
        def scheduled(match, fight_num, where):
            match["fight_num"] = fight_num
            match["where"] = where
            return match

        seed1_round_two = {
            **_live_child_match(10, "Winner of Fight 35, Mat 2", ""),
            "blue_id": "athlete-1",
            "blue_seed": 1,
            "blue_next_description": None,
        }
        seed2_round_two = {
            **_live_child_match(12, "Winner of Fight 35, Mat 1", ""),
            "blue_id": "athlete-2",
            "blue_seed": 2,
            "blue_next_description": None,
        }
        matches = [
            scheduled(_live_match(1, 4, 14), 37, "Mat 3"),
            scheduled(_live_match(5, 3, 13), 35, "Mat 4"),
            scheduled(
                _live_child_match(
                    9,
                    "Winner of Fight 37, Mat 3",
                    "Winner of Fight 38, Mat 3",
                ),
                39,
                "Mat 3",
            ),
            scheduled(
                _live_child_match(
                    15,
                    "Winner of Fight 40, Mat 3",
                    "Winner of Fight 37, Mat 1",
                    final=True,
                ),
                40,
                "Mat 1",
            ),
            scheduled(
                _live_child_match(
                    11,
                    "Winner of Fight 35, Mat 4",
                    "Winner of Fight 34, Mat 4",
                ),
                37,
                "Mat 4",
            ),
            scheduled(_live_match(2, 6, 10), 38, "Mat 3"),
            scheduled(_live_match(6, 5, 9), 34, "Mat 4"),
            scheduled(
                _live_child_match(
                    13,
                    "Winner of Fight 39, Mat 3",
                    "Winner of Fight 37, Mat 2",
                ),
                40,
                "Mat 3",
            ),
            scheduled(
                _live_child_match(
                    14,
                    "Winner of Fight 37, Mat 4",
                    "Winner of Fight 36, Mat 1",
                ),
                39,
                "Mat 1",
            ),
            scheduled(_live_match(3, 8, 12), 33, "Mat 2"),
            scheduled(_live_match(7, 7, 11), 35, "Mat 1"),
            scheduled(seed1_round_two, 36, "Mat 2"),
            scheduled(seed2_round_two, 37, "Mat 1"),
            _live_bye_match(4, 1),
            _live_bye_match(8, 2),
        ]

        add_canonical_display_match_numbers(matches, 14)

        display_by_match_num = {
            match["match_num"]: match["display_match_num"] for match in matches
        }
        self.assertEqual(
            display_by_match_num,
            {
                1: 4,
                2: 3,
                3: 2,
                4: 1,
                5: 5,
                6: 6,
                7: 8,
                8: 7,
                9: 10,
                10: 9,
                11: 11,
                12: 12,
                13: 13,
                14: 14,
                15: 15,
            },
        )

    def test_n14_live_matches_do_not_promote_noncanonical_leaves(self):
        def scheduled(match, fight_num, where):
            match["fight_num"] = fight_num
            match["where"] = where
            return match

        seed1_round_two = {
            **_live_child_match(10, "Winner of Fight 35, Mat 2", ""),
            "blue_id": "athlete-1",
            "blue_seed": 1,
            "blue_next_description": None,
        }
        seed2_round_two = {
            **_live_child_match(12, "Winner of Fight 35, Mat 1", ""),
            "blue_id": "athlete-2",
            "blue_seed": 2,
            "blue_next_description": None,
        }
        matches = [
            scheduled(_live_match(1, 4, 13), 37, "Mat 3"),
            scheduled(_live_match(5, 3, 14), 35, "Mat 4"),
            scheduled(
                _live_child_match(
                    9,
                    "Winner of Fight 37, Mat 3",
                    "Winner of Fight 38, Mat 3",
                ),
                39,
                "Mat 3",
            ),
            scheduled(
                _live_child_match(
                    15,
                    "Winner of Fight 40, Mat 3",
                    "Winner of Fight 37, Mat 1",
                    final=True,
                ),
                40,
                "Mat 1",
            ),
            scheduled(
                _live_child_match(
                    11,
                    "Winner of Fight 35, Mat 4",
                    "Winner of Fight 34, Mat 4",
                ),
                37,
                "Mat 4",
            ),
            scheduled(_live_match(2, 6, 10), 38, "Mat 3"),
            scheduled(_live_match(6, 5, 9), 34, "Mat 4"),
            scheduled(
                _live_child_match(
                    13,
                    "Winner of Fight 39, Mat 3",
                    "Winner of Fight 37, Mat 2",
                ),
                40,
                "Mat 3",
            ),
            scheduled(
                _live_child_match(
                    14,
                    "Winner of Fight 37, Mat 4",
                    "Winner of Fight 36, Mat 1",
                ),
                39,
                "Mat 1",
            ),
            scheduled(_live_match(3, 8, 12), 33, "Mat 2"),
            scheduled(_live_match(7, 7, 11), 35, "Mat 1"),
            scheduled(seed1_round_two, 36, "Mat 2"),
            scheduled(seed2_round_two, 37, "Mat 1"),
            _live_bye_match(4, 1),
            _live_bye_match(8, 2),
        ]

        add_canonical_display_match_numbers(matches, 14)

        display_by_match_num = {
            match["match_num"]: match["display_match_num"] for match in matches
        }
        self.assertEqual(sorted(display_by_match_num.values()), list(range(1, 16)))
        self.assertLessEqual(display_by_match_num[1], 8)
        self.assertLessEqual(display_by_match_num[5], 8)
        self.assertEqual(display_by_match_num[15], 15)


class SideTestCase(unittest.TestCase):
    """Tests for _side(seed, n) — the layout-based bracket-half assignment."""

    def test_seed_1_always_side_0(self):
        for n in [4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 16, 32]:
            with self.subTest(n=n):
                self.assertEqual(_side(1, n), 0)

    def test_seed_2_always_side_1(self):
        for n in [4, 5, 6, 7, 8, 9, 10, 11, 13, 15, 16, 32]:
            with self.subTest(n=n):
                self.assertEqual(_side(2, n), 1)

    def test_n4_layout(self):
        # Layout [(1,4),(2,3)]: side 0 = {1,4}, side 1 = {2,3}.
        for seed, expected in [(1, 0), (4, 0), (2, 1), (3, 1)]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 4), expected)

    def test_n8_layout(self):
        # N=8 uses the 8-slot layout directly (no play-ins).
        # Side 0: 1, 4, 6, 8 — side 1: 2, 3, 5, 7 (parity holds here).
        for seed, expected in [
            (1, 0),
            (4, 0),
            (6, 0),
            (8, 0),
            (2, 1),
            (3, 1),
            (5, 1),
            (7, 1),
        ]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 8), expected)

    def test_n5_play_in_seed_on_seed1_side(self):
        # N=5: seed 5 is the play-in partner of seed 4 → side 0.
        # Parity (seed 5 is odd) would wrongly assign it to side 1.
        # Side 0: 1, 4, 5 — side 1: 2, 3.
        for seed, expected in [(1, 0), (4, 0), (5, 0), (2, 1), (3, 1)]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 5), expected)

    def test_n6_play_in_seeds(self):
        # N=6: IBJJF uses play-in pairs (4,6) and (3,5).
        # Side 0: 1, 4, 6 — side 1: 2, 3, 5.
        for seed, expected in [
            (1, 0),
            (4, 0),
            (6, 0),
            (2, 1),
            (3, 1),
            (5, 1),
        ]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 6), expected)

    def test_n7_play_in_seeds(self):
        # N=7: one short of an 8-slot bracket, so seed 8 is the missing bye.
        # Side 0: 1, 4, 6 — side 1: 2, 3, 5, 7.
        for seed, expected in [
            (1, 0),
            (4, 0),
            (6, 0),
            (2, 1),
            (3, 1),
            (5, 1),
            (7, 1),
        ]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 7), expected)

    def test_n9_play_in_seed_on_seed1_side(self):
        # N=9: seed 9 is the play-in partner of seed 8 → side 0.
        # Parity (odd) would wrongly assign seed 9 to side 1.
        # Side 0: 1, 6, 4, 8, 9 — side 1: 3, 5, 2, 7.
        for seed, expected in [
            (1, 0),
            (6, 0),
            (4, 0),
            (8, 0),
            (9, 0),
            (3, 1),
            (5, 1),
            (2, 1),
            (7, 1),
        ]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 9), expected)

    def test_n11_play_in_seeds(self):
        # N=11: side 0: 1, 8, 11, 6, 4 — side 1: 3, 5, 9, 2, 7, 10.
        # Parity: seed 10 → side 0 (wrong), seed 11 → side 1 (wrong).
        for seed, expected in [
            (1, 0),
            (8, 0),
            (11, 0),
            (6, 0),
            (4, 0),
            (3, 1),
            (5, 1),
            (9, 1),
            (2, 1),
            (7, 1),
            (10, 1),
        ]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 11), expected)

    def test_n13_play_in_seed_on_seed1_side(self):
        # N=13: seed 13 is a play-in partner of seed 4 → side 0.
        # Parity (odd) would wrongly assign it to side 1.
        # Side 0: 1, 8, 12, 6, 10, 4, 13 — side 1: 3, 5, 9, 2, 7, 11.
        for seed, expected in [
            (1, 0),
            (8, 0),
            (12, 0),
            (6, 0),
            (10, 0),
            (4, 0),
            (13, 0),
            (3, 1),
            (5, 1),
            (9, 1),
            (2, 1),
            (7, 1),
            (11, 1),
        ]:
            with self.subTest(seed=seed):
                self.assertEqual(_side(seed, 13), expected)

    def test_n15_power_up_layout(self):
        # N=15 triggers usePowerUpLayout with the 16-slot table (seed 16 is a bye).
        # Side 0: 1, 8, 12, 4, 14, 6, 10 — side 1: 2, 15, 7, 11, 3, 13, 5, 9.
        for seed in [1, 8, 12, 4, 14, 6, 10]:
            with self.subTest(seed=seed, expected_side=0):
                self.assertEqual(_side(seed, 15), 0)
        for seed in [2, 15, 7, 11, 3, 13, 5, 9]:
            with self.subTest(seed=seed, expected_side=1):
                self.assertEqual(_side(seed, 15), 1)

    def test_n16_full_layout(self):
        # N=16: no play-ins, uses 16-slot layout directly.
        # Side 0: 1, 16, 8, 12, 4, 14, 6, 10 — side 1: 2, 15, 7, 11, 3, 13, 5, 9.
        for seed in [1, 16, 8, 12, 4, 14, 6, 10]:
            with self.subTest(seed=seed, expected_side=0):
                self.assertEqual(_side(seed, 16), 0)
        for seed in [2, 15, 7, 11, 3, 13, 5, 9]:
            with self.subTest(seed=seed, expected_side=1):
                self.assertEqual(_side(seed, 16), 1)


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
        # IBJJF parity sides for N=8: seed 1=T, 2=B, 3=B, 4=T, 5=B, 6=T, 7=B,
        # 8=T. Seeds 2 (B) and 4 (T) are on different sides.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[1]["team"] = "Pair"  # seed 2 (B)
        rows[3]["team"] = "Pair"  # seed 4 (T)
        result = add_side_swaps(rows)
        self.assertEqual(result["swaps"], [])
        self.assertEqual(self._seeds(rows), list(range(1, 9)))

    def test_seed_plus_one_swap_fixes_pair(self):
        # N=8: seeds 4 and 6 are both T (even -> side 0). seed+1 = 7 (odd
        # -> B) flips the worse-seeded teammate to the other side.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[3]["team"] = "Pair"  # seed 4 (T)
        rows[5]["team"] = "Pair"  # seed 6 (T)
        result = add_side_swaps(rows)
        self.assertEqual(result["bailout_teams"], [])
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["swaps"][0]["name_a"], "A6")  # would move down
        self.assertEqual(result["swaps"][0]["name_b"], "A7")  # would move up
        # est_seed is not mutated; the seeding shown reflects natural order
        self.assertEqual(rows[5]["est_seed"], 6)
        self.assertEqual(rows[6]["est_seed"], 7)

    def test_falls_back_to_seed_minus_one_when_seed_plus_one_oob(self):
        # N=8: seeds 6 (T) and 8 (T) same team. seed+1 = 9 is OOB, so fall
        # back to seed-1 = 7 (B) which flips.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[5]["team"] = "Pair"  # seed 6 (T)
        rows[7]["team"] = "Pair"  # seed 8 (T)
        result = add_side_swaps(rows)
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["swaps"][0]["name_a"], "A8")
        self.assertEqual(result["swaps"][0]["name_b"], "A7")
        # est_seed is not mutated; natural seeds remain in place
        self.assertEqual(rows[7]["est_seed"], 8)
        self.assertEqual(rows[6]["est_seed"], 7)

    def test_seeds_two_and_three_same_team_swaps(self):
        # Quirky parity edge: seeds 2 and 3 are both on side B (only
        # adjacent pair that shares a side under the parity rule).
        # seed+1 = 4 (T) flips.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[1]["team"] = "Pair"  # seed 2 (B)
        rows[2]["team"] = "Pair"  # seed 3 (B)
        result = add_side_swaps(rows)
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["swaps"][0]["name_a"], "A3")
        self.assertEqual(result["swaps"][0]["name_b"], "A4")

    def test_size_four_two_same_team_pairs(self):
        # N=4 parity sides: 1=T, 2=B, 3=B, 4=T. Teams: A at (1,4)=T,T; B at
        # (2,3)=B,B. Process team A first (lower seed 1): seed+1 = 5 OOB so
        # fall back to seed-1 = 3 (B) -> swap seed 4 with seed 3.
        # After: A at (1,3) T,B fixed. The athlete previously at seed 3
        # (team B) is now at seed 4, so team B becomes (2,4) -> B,T, also
        # fixed.
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

    def test_high_min_seed_first_resolves_adjacent_pairs_in_one_swap(self):
        # N=8. P at (3, 7) — both B; Q at (4, 6) — both T. Both pairs
        # are same-side. Under high-to-low processing, Q (min=4) goes
        # before P (min=3); Q's worse seed is 6 and +1=7 lands on P's
        # worse seed A7, itself same-side, so the swap moves A7 to the
        # T side and simultaneously resolves P. Result: a single swap
        # fixes both pairs, no chain.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 9)]
        rows[2]["team"] = "P"  # seed 3 (B)
        rows[6]["team"] = "P"  # seed 7 (B)
        rows[3]["team"] = "Q"  # seed 4 (T)
        rows[5]["team"] = "Q"  # seed 6 (T)
        result = add_side_swaps(rows)
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(
            {result["swaps"][0]["name_a"], result["swaps"][0]["name_b"]},
            {"A6", "A7"},
        )

    def test_uses_seed_plus_three_when_seed_plus_one_would_break_another_pair(self):
        # N=32. P=(27,29) both B; Q=(11,30) currently different sides
        # (11=B, 30=T). When P is processed, s2+1=30 would pull Q into
        # a same-side conflict, so IBJJF skips it. The next odd offset
        # upward is s2+3=32, which is A32 (solo) — safe. The algorithm
        # must NOT fall down to s2-1=28 first; IBJJF prefers upward
        # odd offsets.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 33)]
        rows[26]["team"] = "P"
        rows[28]["team"] = "P"
        rows[10]["team"] = "Q"
        rows[29]["team"] = "Q"
        result = add_side_swaps(rows)
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["swaps"][0]["name_a"], "A29")
        self.assertEqual(result["swaps"][0]["name_b"], "A32")

    def test_empty_team_field_does_not_pair(self):
        rows = [_swap_row(i, f"A{i}", "") for i in range(1, 9)]
        rows[3]["team"] = "Pair"  # seed 4 (T)
        rows[5]["team"] = "Pair"  # seed 6 (T)
        result = add_side_swaps(rows)
        # Empty-team athletes are not grouped, so only the real "Pair" pair
        # is detected and swapped.
        self.assertEqual(len(result["swaps"]), 1)
        self.assertEqual(result["bailout_teams"], [])

    # ------------------------------------------------------------------
    # Non-power-of-2 brackets — cases where parity rule breaks
    # ------------------------------------------------------------------

    def test_n5_teammates_at_4_and_5_are_same_side(self):
        # N=5: seeds 4 and 5 are both on side 0 (seed 1's half).
        # The old parity rule treated seed 5 as side 1 (odd) and would miss
        # this collision entirely. The layout-based rule catches it.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 6)]
        rows[3]["team"] = "Pair"  # seed 4 (side 0)
        rows[4]["team"] = "Pair"  # seed 5 (side 0)
        result = add_side_swaps(rows)
        self.assertEqual(result["bailout_teams"], [])
        self.assertEqual(len(result["swaps"]), 1)
        # s2=5, closest opposite-side seed: direction=-1, offset 2 → seed 3.
        self.assertEqual(result["swaps"][0]["name_a"], "A5")
        self.assertEqual(result["swaps"][0]["name_b"], "A3")

    def test_n7_teammates_at_3_and_6_are_split(self):
        # N=7 uses the 8-slot layout with seed 8 as the missing bye.
        # Seeds 3 and 6 are already split across the seed-2 and seed-1 halves.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 8)]
        rows[2]["team"] = "Pair"  # seed 3 (side 1)
        rows[5]["team"] = "Pair"  # seed 6 (side 0)
        result = add_side_swaps(rows)
        self.assertEqual(result["bailout_teams"], [])
        self.assertEqual(result["swaps"], [])

    def test_n9_teammates_at_8_and_9_are_same_side(self):
        # N=9: seeds 8 and 9 are both on side 0 (seed 1's half).
        # Parity treats seed 9 as side 1 (odd) and would miss the collision.
        rows = [_swap_row(i, f"A{i}", f"Team{i}") for i in range(1, 10)]
        rows[7]["team"] = "Pair"  # seed 8 (side 0)
        rows[8]["team"] = "Pair"  # seed 9 (side 0)
        result = add_side_swaps(rows)
        self.assertEqual(result["bailout_teams"], [])
        self.assertEqual(len(result["swaps"]), 1)
        # s2=9, direction=+1: OOB. direction=-1: seed 8=s1 skip, seed 7 (side 1). Swap A9 ↔ A7.
        self.assertEqual(result["swaps"][0]["name_a"], "A9")
        self.assertEqual(result["swaps"][0]["name_b"], "A7")


if __name__ == "__main__":
    unittest.main()
