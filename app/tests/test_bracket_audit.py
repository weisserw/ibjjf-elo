import os
import sys
import unittest
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from bracket_audit import (  # noqa: E402
    compare_criteria,
    compare_layout,
    composed_seed_swap_mapping,
    first_round_slots_from_matches,
    parse_bracket_competitors,
    parse_official_ranking,
    parse_team_swaps,
    reconcile_competitors,
)


FIXTURES = Path(__file__).parent / "fixtures" / "bracket_audit"


class BracketAuditParserTestCase(unittest.TestCase):
    def fixture(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def test_parses_all_six_ranking_variants(self):
        expected = {
            "regular_weight_one_swap.html": "regular_weight",
            "regular_open.html": "regular_open",
            "adult_black_weight.html": "adult_black_weight",
            "adult_black_open.html": "adult_black_open",
            "master_black_weight.html": "master_black_weight",
            "master_black_open.html": "master_black_open",
        }
        for filename, variant in expected.items():
            with self.subTest(filename=filename):
                result = parse_official_ranking(self.fixture(filename))
                self.assertEqual(result["status"], "parsed")
                self.assertEqual(result["variant"], variant)
                self.assertEqual(
                    len(result["rows"]), 2 if "regular_weight" not in filename else 8
                )

    def test_parses_typed_champion_values_and_portuguese_aliases(self):
        adult = parse_official_ranking(self.fixture("adult_black_weight.html"))
        criteria = adult["rows"][0]["criteria"]
        self.assertEqual(criteria["world_champion_recent_years"], [2023, 2024, 2025])
        self.assertTrue(criteria["world_champion_recent"])
        self.assertEqual(criteria["last_world_title_year"], 2025)
        self.assertEqual(criteria["former_world_champion"], 2019)
        self.assertFalse(adult["rows"][1]["criteria"]["world_champion_recent"])

        localized = parse_official_ranking(
            self.fixture("portuguese_adult_black_weight.html")
        )
        self.assertEqual(localized["status"], "parsed")
        self.assertEqual(localized["variant"], "adult_black_weight")
        self.assertEqual(localized["rows"][0]["name"], "Atleta 01")
        self.assertEqual(localized["rows"][0]["criteria"]["points"], 81)

    def test_master_one_through_seven_headers_are_dynamic(self):
        for level in range(1, 8):
            headers = (
                ["Nº — Competitor", "Team", "Adult World Champ."]
                + [f"M{number} World Champ." for number in range(1, level + 1)]
                + ["Grand Slam Pts", "Overall PTS"]
            )
            values = ["Team", "No"] + ["No"] * level + ["0", "0"]
            html = (
                '<div class="tournament-category__ranking"><table class="table">'
                + "<thead><tr>"
                + "".join(f"<th>{header}</th>" for header in headers)
                + "</tr></thead><tbody><tr>"
                + '<th><div class="prioriry-number">1</div><div class="competitor-name">Athlete</div></th>'
                + "".join(f"<td>{value}</td>" for value in values)
                + "</tr></tbody></table></div>"
            )
            with self.subTest(level=level):
                result = parse_official_ranking(html)
                self.assertEqual(result["status"], "parsed")
                self.assertIn(
                    f"master_{level}_world_champion",
                    result["rows"][0]["criteria"],
                )

    def test_absent_and_unsupported_tables_are_explicit(self):
        absent = parse_official_ranking(self.fixture("absent_ranking_n9.html"))
        self.assertEqual(absent["status"], "absent")

        html = self.fixture("regular_open.html").replace(
            "Overall Open Class PTS", "Mystery Priority"
        )
        unsupported = parse_official_ranking(html)
        self.assertEqual(unsupported["status"], "unsupported")
        self.assertEqual(unsupported["unmapped_headers"], ["Mystery Priority"])

    def test_row_validation_does_not_shift_columns(self):
        html = self.fixture("regular_open.html").replace(
            "<td>81</td>", "<td>not-a-number</td>", 1
        )
        result = parse_official_ranking(html)
        self.assertEqual(result["status"], "parse_error")
        self.assertTrue(result["errors"])

    def test_bracket_competitors_keep_displayed_seed_identity(self):
        rows = parse_bracket_competitors(self.fixture("regular_weight_one_swap.html"))
        row = next(item for item in rows if item["seed"] == 5)
        self.assertEqual(row["name"], "Athlete 05")
        self.assertEqual(row["ibjjf_id"], "1005")


class BracketAuditLayoutTestCase(unittest.TestCase):
    def fixture(self, name):
        return (FIXTURES / name).read_text(encoding="utf-8")

    def parse_fixture_layout(self, html):
        soup = BeautifulSoup(html, "html.parser")
        matches = []
        for card in soup.select("div.tournament-category__match-card"):
            match_number = next(
                int(name.removeprefix("match-"))
                for name in card.get("class", [])
                if name.startswith("match-")
            )
            competitors = card.find_all(
                "div", class_="match-card__competitor", recursive=False
            )
            match = {"match_num": match_number}
            for side, competitor in zip(("red", "blue"), competitors):
                seed = competitor.select_one(".match-card__competitor-n")
                match[f"{side}_bye"] = bool(competitor.select_one(".match-card__bye"))
                match[f"{side}_seed"] = (
                    int(seed.get_text(strip=True)) if seed is not None else None
                )
            matches.append(match)
        return first_round_slots_from_matches(matches, parse_team_swaps(soup))

    def test_swaps_are_composed_in_document_order(self):
        swaps = parse_team_swaps(self.fixture("n21_chained_swaps.html"))
        self.assertEqual(swaps, [(17, 18), (20, 19), (21, 18)])
        mapping = composed_seed_swap_mapping(swaps)
        self.assertEqual(mapping[17], 18)
        self.assertEqual(mapping[18], 21)
        self.assertEqual(mapping[21], 17)
        self.assertEqual(set(mapping), set(mapping.values()))

    def test_n21_ignores_display_order_when_pairings_match(self):
        parsed = self.parse_fixture_layout(self.fixture("n21_chained_swaps.html"))
        result = compare_layout(parsed, 21)
        self.assertEqual(parsed["bracket_size"], 32)
        self.assertEqual(result["status"], "exact")
        seeds = [seed for pair in parsed["slots"] for seed in pair if seed]
        self.assertCountEqual(seeds, range(1, 22))

    def test_layout_runs_when_ranking_is_absent(self):
        parsed = self.parse_fixture_layout(self.fixture("absent_ranking_n9.html"))
        result = compare_layout(parsed)
        self.assertEqual(parsed["bracket_size"], 16)
        self.assertEqual(result["status"], "exact")
        self.assertEqual(result["competitor_count"], 9)

    def test_layout_accepts_normalized_live_matches(self):
        matches = [
            {
                "match_num": number,
                "red_seed": red,
                "red_bye": False,
                "blue_seed": blue,
                "blue_bye": False,
            }
            for number, red, blue in [
                (1, 1, 4),
                (2, 2, 3),
                (3, 1, 2),
            ]
        ]

        parsed = first_round_slots_from_matches(matches)

        self.assertEqual(parsed["bracket_size"], 4)
        self.assertEqual(parsed["slots"], [(1, 4), (2, 3)])

    def test_malformed_match_range_is_unverifiable_by_caller(self):
        html = self.fixture("absent_ranking_n9.html").replace("match-15", "match-16")
        with self.assertRaisesRegex(ValueError, "Expected match numbers"):
            self.parse_fixture_layout(html)

    def test_pairing_and_seed_coverage_mismatches_are_separate(self):
        parsed = self.parse_fixture_layout(self.fixture("n21_chained_swaps.html"))
        coverage = {**parsed, "slots": list(parsed["slots"])}
        coverage["slots"][0] = (1, 1)
        self.assertEqual(
            compare_layout(coverage, 21)["status"], "seed_coverage_mismatch"
        )

        pairing = {**parsed, "slots": list(parsed["slots"])}
        real_indexes = [
            i
            for i, pair in enumerate(pairing["slots"])
            if all(seed is not None for seed in pair)
        ]
        first, second = real_indexes[:2]
        a, b = pairing["slots"][first]
        c, d = pairing["slots"][second]
        pairing["slots"][first] = (a, c)
        pairing["slots"][second] = (b, d)
        self.assertEqual(compare_layout(pairing, 21)["status"], "pairing_mismatch")

    def test_layout_evidence_sorts_both_sides_by_seed(self):
        parsed = {
            "slots": [(4, 2), (3, 1)],
            "displayed_slots": [(4, 2), (3, 1)],
            "bracket_size": 4,
            "swaps": [],
            "swap_mapping": {},
        }

        result = compare_layout(parsed, 4)

        self.assertEqual(result["status"], "pairing_mismatch")
        self.assertEqual(result["expected_slots"], [(1, 4), (2, 3)])
        self.assertEqual(result["actual_slots"], [(1, 3), (2, 4)])


class BracketAuditCriteriaTestCase(unittest.TestCase):
    def official(self, rank, name, points=0):
        return {
            "official_rank": rank,
            "name": name,
            "team": "Team",
            "criteria": {"grand_slam_points": 0, "points": points},
            "raw_criteria": {},
        }

    def live(self, seed, name, athlete_id):
        return {"seed": seed, "name": name, "team": "Team", "ibjjf_id": athlete_id}

    def predicted(self, seed, name, athlete_id, points=0, tied=False):
        return {
            "est_seed": seed,
            "est_seed_tied": tied,
            "name": name,
            "team": "Team",
            "ibjjf_id": athlete_id,
            "grand_slam_points": 0,
            "points": points,
        }

    def test_reconciliation_prefers_live_athlete_id(self):
        official = [self.official(1, "Published Name")]
        live = [self.live(1, "Published Name", "42")]
        predicted = [self.predicted(1, "Upcoming Name", "42")]
        rows = reconcile_competitors(official, live, predicted)
        self.assertEqual(rows[0]["status"], "matched")
        self.assertEqual(rows[0]["predicted"]["name"], "Upcoming Name")

    def test_duplicate_name_and_team_is_ambiguous(self):
        official = [self.official(1, "Same Name")]
        live = [self.live(1, "Same Name", None)]
        predicted = [
            self.predicted(1, "Same Name", None),
            self.predicted(2, "Same Name", None),
        ]
        rows = reconcile_competitors(official, live, predicted)
        self.assertEqual(rows[0]["status"], "ambiguous")

    def test_tie_order_is_not_a_criteria_mismatch(self):
        official = [self.official(1, "A"), self.official(2, "B")]
        live = [self.live(1, "A", "1"), self.live(2, "B", "2")]
        predicted = [
            self.predicted(2, "A", "1", tied=True),
            self.predicted(1, "B", "2", tied=True),
        ]
        reconciled = reconcile_competitors(official, live, predicted)
        result = compare_criteria(reconciled, "regular_weight")
        self.assertEqual(result["status"], "tie_order_only")
        self.assertEqual(result["mismatched_count"], 0)

    def test_all_differing_criteria_are_recorded(self):
        official = [self.official(1, "A", points=10)]
        official[0]["criteria"]["grand_slam_points"] = 5
        live = [self.live(1, "A", "1")]
        predicted = [self.predicted(1, "A", "1", points=2)]
        reconciled = reconcile_competitors(official, live, predicted)
        result = compare_criteria(reconciled, "regular_weight")
        self.assertEqual(result["status"], "criteria_mismatch")
        self.assertEqual(result["differing_field_count"], 2)


if __name__ == "__main__":
    unittest.main()
