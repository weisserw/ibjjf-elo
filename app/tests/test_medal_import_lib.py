import os
import sys
import unittest
import uuid
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(
    0,
    os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "scripts")),
)

from constants import (
    ADULT,
    BLACK,
    BLUE,
    BROWN,
    FEATHER,
    LIGHT,
    MALE,
    PURPLE,
    WHITE,
)
from extensions import db
from models import (
    Athlete,
    Division,
    Event,
    Match,
    MatchParticipant,
    Medal,
    ResultMedal,
    Team,
)
from test_db import TestDbMixin

import medal_import_lib as lib


class PureFunctionTestCase(unittest.TestCase):
    def test_is_no_gi_event_matches_variants(self):
        self.assertTrue(
            lib.is_no_gi_event("World IBJJF Jiu-Jitsu No-Gi Championship 2024")
        )
        self.assertTrue(lib.is_no_gi_event("Some Tournament No Gi 2023"))
        self.assertTrue(
            lib.is_no_gi_event("Campeonato Brasileiro de Jiu-Jitsu Sem Kimono 2022")
        )
        self.assertTrue(lib.is_no_gi_event("ALL CAPS NO-GI EVENT 2024"))

    def test_is_no_gi_event_false_for_gi(self):
        self.assertFalse(lib.is_no_gi_event("World IBJJF Jiu-Jitsu Championship 2024"))
        self.assertFalse(lib.is_no_gi_event("Pan IBJJF Jiu-Jitsu Championship 2023"))

    def test_parse_division_parts_canonical_order(self):
        self.assertEqual(
            lib.parse_division_parts("BLACK / Adult / Male / Feather"),
            (BLACK, ADULT, MALE, FEATHER),
        )

    def test_parse_division_parts_reordered(self):
        self.assertEqual(
            lib.parse_division_parts("Adult / Male / BLACK / Feather"),
            (BLACK, ADULT, MALE, FEATHER),
        )

    def test_parse_division_parts_strips_trailing_paren(self):
        self.assertEqual(
            lib.parse_division_parts("BLACK / Adult / Male / Feather (-70kg)"),
            (BLACK, ADULT, MALE, FEATHER),
        )

    def test_parse_division_parts_returns_none_on_garbage(self):
        self.assertIsNone(lib.parse_division_parts("nonsense"))
        self.assertIsNone(lib.parse_division_parts("only / three / parts"))

    def test_belt_rank_orders_belts(self):
        self.assertLess(lib.belt_rank(BLUE), lib.belt_rank(PURPLE))
        self.assertLess(lib.belt_rank(PURPLE), lib.belt_rank(BROWN))
        self.assertLess(lib.belt_rank(BROWN), lib.belt_rank(BLACK))
        self.assertLess(lib.belt_rank(WHITE), lib.belt_rank(BLUE))

    def test_name_score_subset_does_not_score_100(self):
        # Regression: token_set_ratio (the inflating component of token_ratio)
        # returned 100 for "Eduardo Garcia" vs "Hugo Eduardo Mercado Garcia",
        # tying with the exact match and breaking the auto-import gap rule.
        # token_sort_ratio penalizes the length mismatch and leaves room for the
        # exact match to win.
        exact = lib.name_score(
            "Hugo Eduardo Mercado Garcia", "Hugo Eduardo Mercado Garcia"
        )
        subset = lib.name_score("Hugo Eduardo Mercado Garcia", "Eduardo Garcia")
        self.assertEqual(exact, 100)
        self.assertLess(subset, 90)
        self.assertGreater(exact - subset, 8)  # gap rule satisfied

    def test_name_score_token_order_insensitive(self):
        # We still want order-insensitive matching — "Silva Maria" should match
        # "Maria Silva" (some sources list surname first).
        score = lib.name_score("Maria Silva", "Silva Maria")
        self.assertEqual(score, 100)

    def test_name_score_middle_name_extension_clears_soft_tier(self):
        # Regression for the Pedro case: result_medal has "Pedro Vinicius Roque",
        # our DB has "Pedro Vinicius Rodrigues Roque" (extra middle name). Score
        # is around 82 and the next-best candidate scores ~66. Auto-import
        # *must* fire via the soft tier (>= 75 with gap >= 15).
        right = lib.name_score("Pedro Vinicius Roque", "Pedro Vinicius Rodrigues Roque")
        wrong = lib.name_score("Pedro Vinicius Roque", "Vinícius Maziero Oliveira")
        gap = right - wrong
        self.assertGreaterEqual(right, 75)
        self.assertGreaterEqual(gap, 12)

    def test_name_score_abbreviated_middle_name_clears_soft_tier(self):
        # Regression for the second Pedro case: full name vs abbreviated middle
        # initial ("M." for Machado). Should clear the soft tier comfortably.
        right = lib.name_score(
            "Pedro Henrique Pinheiro Machado de Souza",
            "Pedro Henrique Pinheiro M. de Souza",
        )
        wrong = lib.name_score(
            "Pedro Henrique Pinheiro Machado de Souza",
            "Pedro Henrique Souza da Silva",
        )
        gap = right - wrong
        self.assertGreaterEqual(right, 75)
        self.assertGreaterEqual(gap, 12)

    # ---- decide_auto_import_names (adaptive fuzzy) ----

    _DECIDE_KW = dict(
        auto_threshold=92,
        gap_threshold=8,
        soft_threshold=75,
        soft_gap_threshold=12,
        similar_threshold=85,
        max_similar_candidates=3,
    )

    def test_decide_auto_import_rare_name_soft_tier(self):
        # Soft-tier rare name: middling score with dissimilar runner-ups.
        # Only one candidate is above similar_threshold, so the namespace is
        # not crowded and the dual-tier rule applies. first_and_last_match
        # passes (first 'pedro'='pedro', last 'roque'='roque'); only the
        # middle differs.
        merged = [
            ("Pedro Vinicius Rodrigues Roque", 82),
            ("Vinícius Maziero Oliveira", 60),
            ("Yet Another", 40),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged, query_name="Pedro Vinicius Roque", **self._DECIDE_KW
            ),
            {"Pedro Vinicius Rodrigues Roque"},
        )

    def test_decide_auto_import_rare_name_high_tier(self):
        # Near-exact rare-name match: classic HIGH tier, easy auto.
        merged = [
            ("Sevada Khashadoorian", 100),
            ("Some Other Person", 50),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged, query_name="Sevada Khashadoorian", **self._DECIDE_KW
            ),
            {"Sevada Khashadoorian"},
        )

    def test_decide_auto_import_soft_tier_rejected_by_first_last_guard(self):
        # Daniel/Amaral regression: SOFT-tier auto would fire on score+gap alone
        # (84, gap 14 — both clear soft_threshold=75, soft_gap_threshold=12), but
        # the first/last guard catches it: last token differs ('abdalla' vs
        # 'amaral') so we route to review.
        merged = [
            ("Daniel de Jesus Amaral", 84),
            ("Some Distractor", 70),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged,
                query_name="Daniel de Jesus Abdalla",
                **self._DECIDE_KW,
            ),
            set(),
        )

    def test_decide_auto_import_soft_tier_allows_abbreviated_middle(self):
        # Abbreviation case: candidate has 'M.' where query has 'Machado' in
        # the middle. First ('pedro') and last ('souza') match, so the
        # first/last guard passes and SOFT auto fires.
        merged = [
            ("Pedro Henrique Pinheiro M. de Souza", 82),
            ("Pedro Henrique Souza da Silva", 66),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged,
                query_name="Pedro Henrique Pinheiro Machado de Souza",
                **self._DECIDE_KW,
            ),
            {"Pedro Henrique Pinheiro M. de Souza"},
        )

    def test_decide_auto_import_rare_namespace_tied_top_scores_review_only(self):
        # Two unknown spellings tied at the top, in a rare namespace.
        # Known-alias spellings are filtered out before this function runs (the
        # CLI handles them separately), so a tie here means two distinct unknown
        # names — genuinely ambiguous. Gap=0 fails both HIGH and SOFT, so the
        # function returns empty and both go to review.
        merged = [
            ("Unknown Spelling One", 100),
            ("Unknown Spelling Two", 100),
            ("Far Other", 30),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged, query_name="Some Query", **self._DECIDE_KW
            ),
            set(),
        )

    def test_decide_auto_import_crowded_namespace_blocks_imperfect_top(self):
        # Lucas-style: many similar candidates, top score is high but not 100.
        # Crowded-namespace rule requires score==100 AND runner-up<100; this
        # case fails so it goes to review.
        merged = [
            ("Lucas Rodrigues Souza", 92),
            ("Mateus Rodrigues de Souza", 90),
            ("Alan Rodrigues de Souza", 88),
            ("Pedro Souza Rodrigues", 87),
            ("Carlos Rodrigues", 86),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged,
                query_name="Lucas de Souza Rodrigues",
                **self._DECIDE_KW,
            ),
            set(),
        )

    def test_decide_auto_import_crowded_namespace_blocks_100_with_100_runner_up(self):
        # Two perfect matches in a crowded namespace means we genuinely can't
        # disambiguate which athlete the medal belongs to.
        merged = [
            ("Lucas Rodrigues Souza", 100),
            ("Souza Lucas Rodrigues", 100),
            ("Mateus Rodrigues de Souza", 90),
            ("Alan Rodrigues de Souza", 88),
            ("Pedro Souza Rodrigues", 86),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged,
                query_name="Lucas Rodrigues Souza",
                **self._DECIDE_KW,
            ),
            set(),
        )

    def test_decide_auto_import_crowded_namespace_allows_unique_perfect_match(self):
        # The only safe auto under high collision: top == 100 and runner-up < 100.
        merged = [
            ("Lucas Rodrigues Souza", 100),
            ("Mateus Rodrigues de Souza", 90),
            ("Alan Rodrigues de Souza", 88),
            ("Pedro Souza Rodrigues", 87),
            ("Carlos Rodrigues", 86),
        ]
        self.assertEqual(
            lib.decide_auto_import_names(
                merged,
                query_name="Lucas Rodrigues Souza",
                **self._DECIDE_KW,
            ),
            {"Lucas Rodrigues Souza"},
        )

    def test_decide_auto_import_empty_merged(self):
        self.assertEqual(
            lib.decide_auto_import_names([], query_name="Anything", **self._DECIDE_KW),
            set(),
        )

    # ---- first_and_last_match (SOFT-tier identity guard) ----

    def test_first_and_last_match_extra_middle_passes(self):
        # Pedro case: candidate has extra middle name. First and last match.
        self.assertTrue(
            lib.first_and_last_match(
                "Pedro Vinicius Roque", "Pedro Vinicius Rodrigues Roque"
            )
        )

    def test_first_and_last_match_extra_middle_on_query_passes(self):
        # Symmetric: query has the extra middle, candidate is shorter.
        self.assertTrue(lib.first_and_last_match("Dustin Ray Hurst", "Dustin Hurst"))

    def test_first_and_last_match_abbreviated_middle_passes(self):
        # 'M.' for 'Machado' in the middle position — first/last unchanged.
        self.assertTrue(
            lib.first_and_last_match(
                "Pedro Henrique Pinheiro Machado de Souza",
                "Pedro Henrique Pinheiro M. de Souza",
            )
        )

    def test_first_and_last_match_eder_abbreviated_middle_passes(self):
        # Eder Daniel G. de Souza <- Eder Daniel Garcia de Souza
        self.assertTrue(
            lib.first_and_last_match(
                "Eder Daniel G. de Souza",
                "Eder Daniel Garcia de Souza",
            )
        )

    def test_first_and_last_match_konrad_abbreviated_middle_passes(self):
        # Konrad Vitus Stempkowski <- Konrad V. Stempkowski
        self.assertTrue(
            lib.first_and_last_match(
                "Konrad Vitus Stempkowski",
                "Konrad V. Stempkowski",
            )
        )

    def test_first_and_last_match_different_surname_fails(self):
        # Daniel/Amaral pattern.
        self.assertFalse(
            lib.first_and_last_match(
                "Daniel de Jesus Abdalla", "Daniel de Jesus Amaral"
            )
        )

    def test_first_and_last_match_different_first_name_fails(self):
        # Jordan/Richard pattern — query has extra leading first name.
        self.assertFalse(
            lib.first_and_last_match("Jordan Richard Thompson", "Richard Thompson")
        )

    def test_first_and_last_match_different_first_name_fails_chad(self):
        # Chad/Jeffrey pattern — same subset shape as Jordan/Richard.
        self.assertFalse(
            lib.first_and_last_match("Chad Jeffrey Lewis", "Jeffrey Lewis")
        )

    def test_first_and_last_match_different_last_name_fails(self):
        # Roberto Gonzalez Ruiz <- Roberto J Gonzalez: first matches, last differs.
        # Even though candidate has 'J' as middle initial (which alone is fine),
        # the last token differs (Ruiz vs Gonzalez) — different person.
        self.assertFalse(
            lib.first_and_last_match("Roberto Gonzalez Ruiz", "Roberto J Gonzalez")
        )

    def test_first_and_last_match_swapped_first_last_fails(self):
        # Simone Mura / Max Simone: 'Simone' is the surname on one side and a
        # given name on the other. First/last positional check correctly rejects.
        self.assertFalse(lib.first_and_last_match("Simone Mura", "Max Simone"))

    def test_first_and_last_match_single_letter_first_rejected(self):
        # Don't trust a 1-char first name as a basis for matching.
        self.assertFalse(lib.first_and_last_match("P. Souza", "Pedro Souza"))

    def test_first_and_last_match_identical_passes(self):
        self.assertTrue(lib.first_and_last_match("Maria Silva", "Maria Silva"))

    def test_first_and_last_match_empty_inputs_fail(self):
        self.assertFalse(lib.first_and_last_match("", "Maria Silva"))
        self.assertFalse(lib.first_and_last_match("Maria Silva", ""))


class LibDbTestCase(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        cls.team = Team(name="Test Team", normalized_name="test team")
        cls.other_team = Team(name="Other Team", normalized_name="other team")
        db.session.add_all([cls.team, cls.other_team])

        cls.athlete = Athlete(
            name="Maria Silva",
            normalized_name="maria silva",
            slug="maria-silva",
        )
        cls.other_athlete = Athlete(
            name="John Doe",
            normalized_name="john doe",
            slug="john-doe",
        )
        db.session.add_all([cls.athlete, cls.other_athlete])

        # Two events: one with brackets (matches), one without (medals only).
        cls.bracket_event = Event(
            name="World IBJJF Jiu-Jitsu Championship 2024",
            normalized_name="world ibjjf jiu jitsu championship 2024",
            slug="worlds-2024",
            ibjjf_id="EVT_BRACKET",
            medals_only=False,
        )
        cls.suffix_event = Event(
            name="Some Open 2023 (BJJHeroes)",
            normalized_name="some open 2023 bjjheroes",
            slug="some-open-2023-bjjheroes",
            medals_only=False,
        )
        db.session.add_all([cls.bracket_event, cls.suffix_event])

        cls.blue_div = Division(
            gi=True, gender=MALE, age=ADULT, belt=BLUE, weight=LIGHT
        )
        cls.purple_div = Division(
            gi=True, gender=MALE, age=ADULT, belt=PURPLE, weight=LIGHT
        )
        cls.black_div = Division(
            gi=True, gender=MALE, age=ADULT, belt=BLACK, weight=FEATHER
        )
        cls.black_div_nogi = Division(
            gi=False, gender=MALE, age=ADULT, belt=BLACK, weight=FEATHER
        )
        db.session.add_all(
            [cls.blue_div, cls.purple_div, cls.black_div, cls.black_div_nogi]
        )
        db.session.flush()

        # Athlete competed at BLUE in 2022 and at PURPLE in 2024 (belts go up).
        for happened, division in [
            (datetime(2022, 5, 1, 12, 0, 0), cls.blue_div),
            (datetime(2024, 6, 1, 12, 0, 0), cls.purple_div),
        ]:
            match = Match(
                event_id=cls.bracket_event.id,
                division_id=division.id,
                happened_at=happened,
                rated=True,
            )
            db.session.add(match)
            db.session.flush()
            db.session.add(
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=cls.athlete.id,
                    team_id=cls.team.id,
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1500.0,
                    end_rating=1510.0,
                    start_match_count=1,
                    end_match_count=2,
                )
            )

        # Pre-seed an existing medal so we can test the duplicate guard.
        cls.existing_medal = Medal(
            happened_at=datetime(2024, 6, 1, 12, 0, 0),
            event_id=cls.bracket_event.id,
            division_id=cls.purple_div.id,
            athlete_id=cls.athlete.id,
            team_id=cls.team.id,
            place=1,
            default_gold=False,
        )
        db.session.add(cls.existing_medal)

        # result_medals: one solo gold, one with a sibling silver (default_gold cases).
        cls.solo_gold = ResultMedal(
            id=uuid.uuid4(),
            event_name="World IBJJF Jiu-Jitsu Championship 2024",
            event_ibjjf_id="EVT_BRACKET",
            division="BLACK / Adult / Male / Feather",
            team_name="Test Team",
            athlete_name="Maria Silva",
            place=1,
            source="ibjjf",
        )
        cls.silver_sibling = ResultMedal(
            id=uuid.uuid4(),
            event_name="Other Event 2023",
            event_ibjjf_id=None,
            division="BLACK / Adult / Male / Feather",
            team_name="Test Team",
            athlete_name="Other Person",
            place=2,
            source="ibjjf",
        )
        cls.gold_with_silver = ResultMedal(
            id=uuid.uuid4(),
            event_name="Other Event 2023",
            event_ibjjf_id=None,
            division="BLACK / Adult / Male / Feather",
            team_name="Test Team",
            athlete_name="Some Winner",
            place=1,
            source="ibjjf",
        )
        # scraped_at is NOT NULL on the model — set it on all of these.
        for rm in (cls.solo_gold, cls.silver_sibling, cls.gold_with_silver):
            rm.scraped_at = datetime(2025, 1, 1, 0, 0, 0)
        db.session.add_all([cls.solo_gold, cls.silver_sibling, cls.gold_with_silver])
        db.session.commit()

        # Capture IDs so tests can use them outside the session context.
        cls.athlete_id = cls.athlete.id
        cls.other_athlete_id = cls.other_athlete.id
        cls.team_id = cls.team.id
        cls.bracket_event_id = cls.bracket_event.id
        cls.suffix_event_id = cls.suffix_event.id
        cls.blue_div_id = cls.blue_div.id
        cls.purple_div_id = cls.purple_div.id
        cls.black_div_id = cls.black_div.id
        cls.black_div_nogi_id = cls.black_div_nogi.id

    # ---- compute_default_gold ----

    def test_compute_default_gold_alone(self):
        with self.app_module.app.app_context():
            rm = (
                db.session.query(ResultMedal)
                .filter_by(athlete_name="Maria Silva")
                .one()
            )
            self.assertTrue(lib.compute_default_gold(db.session, rm))

    def test_compute_default_gold_when_silver_present(self):
        with self.app_module.app.app_context():
            rm = (
                db.session.query(ResultMedal)
                .filter_by(athlete_name="Some Winner")
                .one()
            )
            self.assertFalse(lib.compute_default_gold(db.session, rm))

    def test_compute_default_gold_silver_is_never_default(self):
        with self.app_module.app.app_context():
            rm = (
                db.session.query(ResultMedal)
                .filter_by(athlete_name="Other Person")
                .one()
            )
            self.assertFalse(lib.compute_default_gold(db.session, rm))

    # ---- find_event ----

    def test_find_event_by_ibjjf_id(self):
        with self.app_module.app.app_context():
            found = lib.find_event(
                db.session, "Whatever the name", event_ibjjf_id="EVT_BRACKET"
            )
            self.assertIsNotNone(found)
            self.assertEqual(found.ibjjf_id, "EVT_BRACKET")

    def test_find_event_by_exact_name(self):
        with self.app_module.app.app_context():
            found = lib.find_event(
                db.session,
                "World IBJJF Jiu-Jitsu Championship 2024",
                event_ibjjf_id=None,
            )
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "World IBJJF Jiu-Jitsu Championship 2024")

    def test_find_event_by_prefix_when_stored_has_suffix(self):
        with self.app_module.app.app_context():
            found = lib.find_event(db.session, "Some Open 2023", event_ibjjf_id=None)
            self.assertIsNotNone(found)
            self.assertEqual(found.name, "Some Open 2023 (BJJHeroes)")

    def test_find_event_returns_none_when_unknown(self):
        with self.app_module.app.app_context():
            self.assertIsNone(
                lib.find_event(
                    db.session, "Some Brand New Tournament 2024", event_ibjjf_id=None
                )
            )

    # ---- find_or_create_team ----

    def test_find_or_create_team_returns_existing(self):
        with self.app_module.app.app_context():
            before = db.session.query(Team).count()
            t = lib.find_or_create_team(db.session, "Test Team")
            self.assertEqual(t.id, self.team_id)
            db.session.commit()
            self.assertEqual(db.session.query(Team).count(), before)

    def test_find_or_create_team_creates_new(self):
        with self.app_module.app.app_context():
            t = lib.find_or_create_team(db.session, "Brand New Academy")
            db.session.commit()
            self.assertIsNotNone(t.id)
            self.assertEqual(t.normalized_name, "brand new academy")

    # ---- compute_happened_at ----

    def test_compute_happened_at_uses_athlete_last_match(self):
        with self.app_module.app.app_context():
            event = db.session.query(Event).filter_by(ibjjf_id="EVT_BRACKET").one()
            t = lib.compute_happened_at(db.session, self.athlete_id, event, event.name)
            self.assertEqual(t, datetime(2024, 6, 1, 12, 0, 0))

    def test_compute_happened_at_falls_back_to_event_last_match(self):
        with self.app_module.app.app_context():
            event = db.session.query(Event).filter_by(ibjjf_id="EVT_BRACKET").one()
            # Use other_athlete who has no matches in this event; falls back to
            # last match in the event by any athlete.
            t = lib.compute_happened_at(
                db.session, self.other_athlete_id, event, event.name
            )
            self.assertEqual(t, datetime(2024, 6, 1, 12, 0, 0))

    def test_compute_happened_at_major_event_no_matches(self):
        with self.app_module.app.app_context():
            # No matches => major-event hardcoded date for "World" is June 1.
            empty_event = Event(
                name="World IBJJF Jiu-Jitsu Championship 2019",
                normalized_name="world ibjjf jiu jitsu championship 2019",
                slug="worlds-2019",
                medals_only=True,
            )
            db.session.add(empty_event)
            db.session.flush()
            t = lib.compute_happened_at(
                db.session,
                self.athlete_id,
                empty_event,
                empty_event.name,
            )
            self.assertEqual(t, datetime(2019, 6, 1))

    def test_compute_happened_at_jan_1_fallback(self):
        with self.app_module.app.app_context():
            empty_event = Event(
                name="Some Local Open 2018",
                normalized_name="some local open 2018",
                slug="some-local-open-2018",
                medals_only=True,
            )
            db.session.add(empty_event)
            db.session.flush()
            t = lib.compute_happened_at(
                db.session, self.athlete_id, empty_event, empty_event.name
            )
            self.assertEqual(t, datetime(2018, 1, 1))

    # ---- medal_already_exists ----

    def test_medal_already_exists_true(self):
        with self.app_module.app.app_context():
            self.assertTrue(
                lib.medal_already_exists(
                    db.session,
                    self.athlete_id,
                    self.bracket_event_id,
                    self.purple_div_id,
                )
            )

    def test_medal_already_exists_false(self):
        with self.app_module.app.app_context():
            self.assertFalse(
                lib.medal_already_exists(
                    db.session,
                    self.athlete_id,
                    self.bracket_event_id,
                    self.blue_div_id,
                )
            )

    # ---- belt-rank filter ----

    def test_belt_bounds_at_known_date(self):
        with self.app_module.app.app_context():
            # On the same day as the 2022 BLUE match, lo == hi == rank(BLUE).
            lo, hi = lib.athlete_belt_bounds_at(
                db.session, self.athlete_id, datetime(2022, 5, 1, 12, 0, 0)
            )
            self.assertEqual(lo, lib.belt_rank(BLUE))
            self.assertEqual(hi, lib.belt_rank(BLUE))

    def test_medal_is_plausible_rejects_brown_before_blue_known(self):
        # Athlete had a BLUE match in 2022, so a BROWN medal in 2020 is impossible
        # (they couldn't have already been at brown then).
        with self.app_module.app.app_context():
            self.assertFalse(
                lib.medal_is_plausible(
                    db.session, self.athlete_id, BROWN, datetime(2020, 1, 1)
                )
            )

    def test_medal_is_plausible_allows_white_before_blue(self):
        # White is lower than blue; a 2020 white-belt medal is consistent with
        # being at blue by 2022.
        with self.app_module.app.app_context():
            self.assertTrue(
                lib.medal_is_plausible(
                    db.session, self.athlete_id, WHITE, datetime(2020, 1, 1)
                )
            )

    def test_medal_is_plausible_rejects_black_between_known_belts(self):
        # On a date between BLUE-2022 and PURPLE-2024, athlete can be BLUE or PURPLE.
        # BLACK should be rejected.
        with self.app_module.app.app_context():
            self.assertFalse(
                lib.medal_is_plausible(
                    db.session, self.athlete_id, BLACK, datetime(2023, 6, 1)
                )
            )

    def test_medal_is_plausible_allows_black_after_known_belts(self):
        # After the last known match (PURPLE in 2024), the athlete could have
        # since been promoted to BROWN or BLACK.
        with self.app_module.app.app_context():
            self.assertTrue(
                lib.medal_is_plausible(
                    db.session, self.athlete_id, BLACK, datetime(2026, 1, 1)
                )
            )

    # ---- gender filter ----

    def test_gender_filter_rejects_opposite_gender(self):
        # Seeded athlete only competed in Male divisions; a Female medal must fail.
        from constants import FEMALE

        with self.app_module.app.app_context():
            self.assertFalse(
                lib.gender_is_plausible(db.session, self.athlete_id, FEMALE)
            )

    def test_gender_filter_allows_matching_gender(self):
        with self.app_module.app.app_context():
            self.assertTrue(lib.gender_is_plausible(db.session, self.athlete_id, MALE))

    def test_gender_filter_unconstrained_when_no_data(self):
        from constants import FEMALE

        with self.app_module.app.app_context():
            # other_athlete has no matches and no medals — passes either way.
            self.assertTrue(
                lib.gender_is_plausible(db.session, self.other_athlete_id, MALE)
            )
            self.assertTrue(
                lib.gender_is_plausible(db.session, self.other_athlete_id, FEMALE)
            )

    # ---- age filter ----

    def test_age_filter_adult_history_rejects_teen_and_juvenile(self):
        # Seeded athlete has only Adult matches; can't drop back to Teen/Juvenile.
        from constants import JUVENILE, MASTER_2, TEEN_2

        with self.app_module.app.app_context():
            self.assertFalse(lib.age_is_plausible(db.session, self.athlete_id, TEEN_2))
            self.assertFalse(
                lib.age_is_plausible(db.session, self.athlete_id, JUVENILE)
            )
            # Adult <-> Masters is fine in both directions.
            self.assertTrue(lib.age_is_plausible(db.session, self.athlete_id, ADULT))
            self.assertTrue(lib.age_is_plausible(db.session, self.athlete_id, MASTER_2))

    def test_age_filter_unconstrained_when_no_data(self):
        from constants import JUVENILE, MASTER_3, TEEN_1

        with self.app_module.app.app_context():
            # other_athlete has no matches or medals — every age passes.
            self.assertTrue(
                lib.age_is_plausible(db.session, self.other_athlete_id, TEEN_1)
            )
            self.assertTrue(
                lib.age_is_plausible(db.session, self.other_athlete_id, JUVENILE)
            )
            self.assertTrue(
                lib.age_is_plausible(db.session, self.other_athlete_id, ADULT)
            )
            self.assertTrue(
                lib.age_is_plausible(db.session, self.other_athlete_id, MASTER_3)
            )

    def test_age_filter_juvenile_history_rejects_teen_only(self):
        # Seed an athlete whose only history is a Juvenile match. Teen medals
        # should be rejected; Juvenile/Adult/Masters should all be allowed.
        from constants import (
            BLUE,
            FEMALE,
            FEATHER,
            JUVENILE,
            MASTER_1,
            TEEN_2,
        )

        with self.app_module.app.app_context():
            juv_div = Division(
                gi=True, gender=FEMALE, age=JUVENILE, belt=BLUE, weight=FEATHER
            )
            db.session.add(juv_div)
            db.session.flush()
            athlete = Athlete(
                name="Juvenile Only",
                normalized_name="juvenile only",
                slug=f"juvenile-only-{uuid.uuid4().hex[:8]}",
            )
            db.session.add(athlete)
            db.session.flush()
            event = db.session.query(Event).filter_by(ibjjf_id="EVT_BRACKET").one()
            match = Match(
                event_id=event.id,
                division_id=juv_div.id,
                happened_at=datetime(2023, 1, 1),
                rated=True,
            )
            db.session.add(match)
            db.session.flush()
            db.session.add(
                MatchParticipant(
                    match_id=match.id,
                    athlete_id=athlete.id,
                    team_id=self.team_id,
                    note="",
                    seed=1,
                    red=True,
                    winner=True,
                    start_rating=1500.0,
                    end_rating=1510.0,
                    start_match_count=1,
                    end_match_count=2,
                )
            )
            db.session.flush()

            self.assertFalse(lib.age_is_plausible(db.session, athlete.id, TEEN_2))
            self.assertTrue(lib.age_is_plausible(db.session, athlete.id, JUVENILE))
            self.assertTrue(lib.age_is_plausible(db.session, athlete.id, ADULT))
            self.assertTrue(lib.age_is_plausible(db.session, athlete.id, MASTER_1))

    def test_age_filter_uses_medal_history_when_no_matches(self):
        # An athlete whose only DB presence is a Medal (no MatchParticipant) should
        # still be constrained by that medal's age bracket.
        from constants import (
            BLACK,
            FEMALE,
            JUVENILE,
            MASTER_4,
            MIDDLE,
            TEEN_3,
        )

        with self.app_module.app.app_context():
            masters_div = Division(
                gi=True, gender=FEMALE, age=MASTER_4, belt=BLACK, weight=MIDDLE
            )
            db.session.add(masters_div)
            db.session.flush()
            athlete = Athlete(
                name="Medal Only Masters",
                normalized_name="medal only masters",
                slug=f"medal-only-masters-{uuid.uuid4().hex[:8]}",
            )
            db.session.add(athlete)
            db.session.flush()
            event = db.session.query(Event).filter_by(ibjjf_id="EVT_BRACKET").one()
            db.session.add(
                Medal(
                    happened_at=datetime(2023, 6, 1),
                    event_id=event.id,
                    division_id=masters_div.id,
                    athlete_id=athlete.id,
                    team_id=self.team_id,
                    place=1,
                    default_gold=False,
                )
            )
            db.session.flush()

            self.assertFalse(lib.age_is_plausible(db.session, athlete.id, TEEN_3))
            self.assertFalse(lib.age_is_plausible(db.session, athlete.id, JUVENILE))
            self.assertTrue(lib.age_is_plausible(db.session, athlete.id, ADULT))
            self.assertTrue(lib.age_is_plausible(db.session, athlete.id, MASTER_4))

    def test_medal_is_plausible_unbounded_when_no_matches(self):
        with self.app_module.app.app_context():
            self.assertTrue(
                lib.medal_is_plausible(
                    db.session,
                    self.other_athlete_id,
                    BLACK,
                    datetime(2010, 1, 1),
                )
            )

    # ---- create_medals_only_event ----

    def test_create_medals_only_event(self):
        with self.app_module.app.app_context():
            evt = lib.create_medals_only_event(db.session, "Some Fresh Open 2017")
            db.session.commit()
            self.assertTrue(evt.medals_only)
            self.assertEqual(evt.name, "Some Fresh Open 2017")
            self.assertEqual(evt.normalized_name, "some fresh open 2017")
            self.assertTrue(evt.slug.startswith("some-fresh-open-2017"))

    def test_create_medals_only_event_raises_without_year(self):
        with self.app_module.app.app_context():
            with self.assertRaises(ValueError):
                lib.create_medals_only_event(db.session, "Tournament With No Year")

    # ---- find_events_with_matches_in_range ----

    def test_scan_resolves_gi_division_for_gi_event(self):
        # Regression: bracket_event is a gi event (no "no gi" in the name) and the
        # purple_div is gi=True. A result_medal in that division must resolve, not
        # fall into status='no_division'. (We previously inverted the gi flag.)
        with self.app_module.app.app_context():
            rm = ResultMedal(
                id=uuid.uuid4(),
                event_name="World IBJJF Jiu-Jitsu Championship 2024",
                event_ibjjf_id="EVT_BRACKET",
                division="PURPLE / Adult / Male / Light",
                team_name="Test Team",
                athlete_name="Maria Silva",
                place=1,
                source="ibjjf",
                scraped_at=datetime(2025, 1, 1),
            )
            db.session.add(rm)
            db.session.commit()
            event = db.session.query(Event).filter_by(ibjjf_id="EVT_BRACKET").one()
            entries = lib.scan_event_for_missing_medals(db.session, event, fuzzy=False)
            statuses = {e["status"] for e in entries}
            # The seeded existing medal for Maria already covers PURPLE+gi at this event,
            # so this row resolves to "already_imported" — proving the division IS
            # resolved (would be "no_division" if the gi flag were wrong).
            self.assertIn("already_imported", statuses)
            self.assertNotIn("no_division", statuses)

    def test_find_events_in_range_includes_null_medals_only(self):
        # Bracket-imported events from before the medals_only column existed
        # have NULL — they must still be included in the scan.
        with self.app_module.app.app_context():
            null_event = Event(
                name="Legacy Bracket Event 2024",
                normalized_name="legacy bracket event 2024",
                slug="legacy-bracket-event-2024",
                medals_only=None,
            )
            db.session.add(null_event)
            db.session.flush()
            db.session.add(
                Match(
                    event_id=null_event.id,
                    division_id=self.blue_div_id,
                    happened_at=datetime(2024, 7, 1, 12, 0, 0),
                    rated=True,
                )
            )
            db.session.commit()
            events = lib.find_events_with_matches_in_range(
                db.session, datetime(2024, 1, 1), datetime(2024, 12, 31)
            )
            names = {e.name for e in events}
            self.assertIn("Legacy Bracket Event 2024", names)

    # ---- parse_and_resolve_division (with gi flag from event) ----

    def test_parse_and_resolve_division_uses_gi_flag(self):
        with self.app_module.app.app_context():
            gi = lib.parse_and_resolve_division(
                db.session, "BLACK / Adult / Male / Feather", gi=True
            )
            nogi = lib.parse_and_resolve_division(
                db.session, "BLACK / Adult / Male / Feather", gi=False
            )
            self.assertIsNotNone(gi)
            self.assertIsNotNone(nogi)
            self.assertNotEqual(gi.id, nogi.id)
            self.assertTrue(gi.gi)
            self.assertFalse(nogi.gi)

    def test_parse_and_resolve_division_returns_none_for_unknown(self):
        with self.app_module.app.app_context():
            # No Rooster Adult Male Black Gi division was seeded.
            self.assertIsNone(
                lib.parse_and_resolve_division(
                    db.session, "BLACK / Adult / Male / Rooster", gi=True
                )
            )


if __name__ == "__main__":
    unittest.main()
