import csv
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from pull import headers, pull_tournament


class PullDefaultGoldTestCase(unittest.TestCase):
    def pull_rows(self, podium="", disqualified=False, incomplete=False):
        categories = """
        <li class="categories-grid__category">
          <a href="/category/1"></a>
          <div class="category-card__age-division">Adult</div>
          <span class="category-card__belt-label">Black</span>
          <span class="category-card__weight-label">Light</span>
        </li>
        """
        loser_class = "match-competitor--loser" if disqualified else ""
        dq = (
            '<i class="match-card__disqualification" title="DQ"></i>'
            if disqualified
            else ""
        )
        bracket = f"""
        <div class="tournament-category__match">
          <div class="bracket-match-header__when">Fri 10/02 at 10:00 AM</div>
          <div class="tournament-category__match-card match-1">
            <div class="match-card__competitor match-card__competitor--red" id="competitor-123">
              <span class="match-card__competitor-n">1</span>
              <span class="match-card__competitor-description {loser_class}">
                <div class="match-card__competitor-name">Solo Athlete</div>
                <div class="match-card__club-name">Test Team</div>
                {dq}
              </span>
            </div>
            <div class="match-card__competitor">
              <span class="match-card__competitor-description">
                <div class="match-card__bye">BYE</div>
              </span>
            </div>
          </div>
        </div>
        {podium}
        """
        output = io.StringIO()
        responses = [
            SimpleNamespace(status_code=200, content=html.encode())
            for html in (categories, bracket)
        ]
        with (
            patch("pull.rate_limit_get", side_effect=responses),
            redirect_stdout(io.StringIO()),
        ):
            pull_tournament(
                output,
                csv.writer(output),
                "TEST",
                "Test Event",
                True,
                [("https://example.test/categories", "Male")],
                "https://example.test",
                2026,
                incomplete=incomplete,
            )
        return list(csv.DictReader(io.StringIO(output.getvalue()), fieldnames=headers))

    def podium(self, name="Solo Athlete", place="1"):
        return f"""
        <div class="podium__step">
          <div class="podium__competitor-name">{name}</div>
          <span class="podium__place">{place}</span>
        </div>
        """

    def test_confirmed_gold_is_exported(self):
        rows = self.pull_rows(self.podium())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["Red ID"], "123")
        self.assertEqual(rows[0]["Red Name"], "Solo Athlete")
        self.assertEqual(rows[0]["Red Medal"], "1")
        self.assertEqual(rows[0]["Blue ID"], "DEFAULT_GOLD")

    def test_unconfirmed_gold_is_not_exported(self):
        for podium in (
            "",
            self.podium(name=""),
            self.podium(place=""),
            self.podium(name="Other Athlete"),
            self.podium(place="2"),
            self.podium(place="3"),
        ):
            with self.subTest(podium=podium):
                self.assertEqual(self.pull_rows(podium), [])

    def test_disqualified_entrant_is_not_exported_even_with_gold(self):
        self.assertEqual(self.pull_rows(self.podium(), disqualified=True), [])

    def test_incomplete_import_still_requires_confirmed_gold(self):
        self.assertEqual(self.pull_rows(incomplete=True), [])


if __name__ == "__main__":
    unittest.main()
