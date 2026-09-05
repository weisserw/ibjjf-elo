import os
import sys
import unittest
import uuid
from datetime import datetime, timedelta, timezone, date
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from extensions import db
from models import (
    Athlete,
    Division,
    RegistrationLink,
    RegistrationLinkCompetitor,
    Watchlist,
    WatchlistSchedule,
    WatchlistRefreshSlot,
)
from constants import ADULT, BLACK, MALE, LIGHT
from test_db import TestDbMixin
from watchlist_schedule import (
    BASE,
    SourceError,
    day_date,
    homepage_links,
    parse_page,
    scan_tournament,
    source_url,
)
from watchlist_refresh import claim, finish, renew, utc, trigger
from watchlists import purge

FIXTURES = Path(__file__).parent / "fixtures" / "watchlists"


def page(cards="", mats=(1,), page_links="", count=1):
    return (
        f"<a href='/tournaments/1/tournament_days/2'>Day 1 Friday, 09/04 ({count} Mats)</a>"
        + page_links
        + "".join(
            f'<div class="sliding-columns__column"><div class="grid-column__header">Mat {mat}</div><ul class="tournament-day__mats">{cards if mat == mats[0] else ""}</ul></div>'
            for mat in mats
        )
    )


def card(
    athlete="100",
    opponent="200",
    fight=1,
    when="09:30 AM",
    category="BLACK / Adult / Male / Light",
):
    return f"""<li><span class="match-header__fight">FIGHT {fight}</span>
      <span class="match-header__when">{when}</span><span class="match-header__category-name">{category}</span>
      <div class="match-card__competitor" id="competitor-{athlete}"><span class="match-card__competitor-name">Alex Example</span></div>
      <div class="match-card__competitor" id="competitor-{opponent}"><span class="match-card__competitor-name">Opponent</span></div></li>"""


class WatchlistParserTests(unittest.TestCase):
    def setUp(self):
        self.day = {"day_id": "2", "date": "2026-09-04"}
        self.url = BASE + "/tournaments/1/tournament_days/2?page=1&locale=en"
        self.event = {
            "event_id": "1",
            "start": datetime(2026, 9, 4),
            "end": datetime(2026, 9, 4),
        }

    def test_clock_stays_local_and_delayed_cards_remain(self):
        result = parse_page(page(card(when="09:30AM")), self.url, "1", self.day)
        self.assertEqual(result["matches"][0]["local_time"], "09:30")
        self.assertEqual(result["matches"][0]["local_date"], "2026-09-04")
        self.assertNotIn("scheduled_at", result["matches"][0])

    def test_search_widget_does_not_count_as_presence(self):
        result = parse_page(
            page() + '<div id="competitor-100">search widget</div>',
            self.url,
            "1",
            self.day,
        )
        self.assertEqual(result["matches"], [])

    def test_placeholder_has_no_identity_even_with_competitor_id(self):
        html = card().replace(
            '<span class="match-card__competitor-name">Opponent</span>',
            '<span class="match-card__child-description">Winner of Fight 4</span>',
        )
        side = parse_page(page(html), self.url, "1", self.day)["matches"][0]["sides"][1]
        self.assertIsNone(side["ibjjf_id"])
        self.assertEqual(side["description"], "Winner of Fight 4")

    def test_same_athlete_can_appear_in_multiple_fights(self):
        matches = parse_page(page(card() + card(fight=2)), self.url, "1", self.day)[
            "matches"
        ]
        self.assertEqual(len(matches), 2)

    def test_pagination_visits_self_only_once(self):
        calls = []
        html = page(card(), page_links="<a href='?page=1'>Last</a>")

        def fetch(url):
            calls.append(url)
            return html

        matches, coverage, _ = scan_tournament(
            fetch, self.url, self.event, date(2026, 9, 4)
        )
        self.assertEqual(len(calls), 1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(coverage[0]["state"], "complete")

    def test_missing_and_duplicate_mats_fail_closed(self):
        for html in [page(count=2), page(mats=(1, 1))]:
            with self.subTest(html=html), self.assertRaises(SourceError):
                scan_tournament(lambda _: html, self.url, self.event, date(2026, 9, 4))

    def test_all_nine_pages_and_short_empty_final_page(self):
        from urllib.parse import parse_qs, urlsplit

        calls = []

        def fetch(url):
            number = int(parse_qs(urlsplit(url).query)["page"][0])
            calls.append(number)
            return page(
                mats=range((number - 1) * 4 + 1, min(number * 4, 34) + 1),
                count=34,
                page_links=f"<a href='?page={max(1,number-1)}'>Previous</a><a href='?page={min(9,number+1)}'>Next</a>",
            )

        matches, coverage, _ = scan_tournament(
            fetch, self.url, self.event, date(2026, 9, 4)
        )
        self.assertEqual(matches, [])
        self.assertEqual(sorted(calls), list(range(1, 10)))
        self.assertEqual(coverage[0]["mats"], list(range(1, 35)))

    def test_topology_change_is_retried_once(self):
        calls = 0

        def fetch(url):
            nonlocal calls
            calls += 1
            second = "page=2&" in url
            return page(
                mats=(5, 6, 7, 8) if second else (1, 2, 3, 4),
                count=4 if calls == 2 else 8,
            )

        _, coverage, _ = scan_tournament(fetch, self.url, self.event, date(2026, 9, 4))
        self.assertEqual(calls, 4)
        self.assertEqual(coverage[0]["mats"], list(range(1, 9)))

    def test_future_day_not_in_navigation_is_unpublished(self):
        self.event["end"] = datetime(2026, 9, 5)
        _, coverage, _ = scan_tournament(
            lambda _: page(), self.url, self.event, date(2026, 9, 4)
        )
        self.assertIn(
            {"date": "2026-09-05", "state": "unpublished", "pages": [], "mats": []},
            coverage,
        )

    def test_unrecognized_error_is_not_empty_success(self):
        for html in [
            "<h1>Login</h1>",
            "<h1>Internal Server Error</h1>",
            "<p>not published</p>",
        ]:
            with self.subTest(html=html), self.assertRaises(SourceError):
                parse_page(html, self.url, "1", self.day)

    def test_year_rollover(self):
        self.assertEqual(
            day_date("Day 2 01/01", datetime(2026, 12, 31), datetime(2027, 1, 2)),
            date(2027, 1, 1),
        )

    def test_fetch_urls_restricted(self):
        for value in [
            "https://evil.example/tournaments/1/tournament_days/2",
            "/tournaments/2/tournament_days/2",
            "/tournaments/1/tournament_days/2?page=evil",
            "http://www.bjjcompsystem.com/tournaments/1/tournament_days/2",
        ]:
            self.assertIsNone(source_url(value, "1"))
        self.assertEqual(
            homepage_links("<a href='/tournaments/1/tournament_days/2'>Day</a>")["1"],
            self.url,
        )

    def test_observed_source_fixture(self):
        path = FIXTURES / "observed-populated.html"
        html = path.read_text()
        result = parse_page(
            html,
            BASE + "/tournaments/900001/tournament_days/910003?page=2&locale=en",
            "900001",
            {"day_id": "910003", "date": "2026-09-05"},
        )
        self.assertEqual(result["mats"], [5, 6, 7, 8])
        self.assertTrue(result["matches"])
        self.assertEqual(result["matches"][0]["sides"][0]["ibjjf_id"], "990000000001")
        self.assertTrue(
            all(
                side["name"].startswith("Fixture Athlete ")
                for match in result["matches"]
                for side in match["sides"]
                if side["name"]
            )
        )
        self.assertTrue(
            all(
                side["team"].startswith("Fixture Team ")
                for match in result["matches"]
                for side in match["sides"]
                if side["team"]
            )
        )


class WatchlistApiTests(TestDbMixin, unittest.TestCase):
    @classmethod
    def _seed_data(cls):
        pass

    def setUp(self):
        self.app = self.app_module.app
        self.app.config["WATCHLIST_REFRESH_ENABLED"] = False
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()
        self.client = self.app.test_client()
        now = datetime.now()
        self.day = now.date().isoformat()
        self.events = [
            RegistrationLink(
                name=f"Open {i}",
                normalized_name=f"open {i}",
                event_id=str(i),
                updated_at=now,
                link=f"https://www.ibjjfdb.com/ChampionshipResults/{i}/PublicRegistrations?lang=en-US",
                hidden=False,
                event_start_date=now - timedelta(days=1),
                event_end_date=now + timedelta(days=2),
            )
            for i in (1, 2, 3)
        ]
        self.athletes = [
            Athlete(
                name="Alex Example",
                normalized_name="alex example",
                personal_name="Private Alex",
                normalized_personal_name="private alex",
                slug="alex-1",
                ibjjf_id="100",
                hide_full_name=True,
            ),
            Athlete(
                name="Alex Example",
                normalized_name="alex example",
                slug="alex-2",
                ibjjf_id="101",
            ),
            Athlete(
                name="Other Person",
                normalized_name="other person",
                slug="other",
                ibjjf_id="200",
            ),
            Athlete(
                name="Untracked Person",
                normalized_name="untracked person",
                slug="untracked",
            ),
        ]
        division = Division(gi=True, gender=MALE, age=ADULT, belt=BLACK, weight=LIGHT)
        db.session.add_all([*self.events, *self.athletes, division])
        db.session.flush()
        for event, name, team in [
            (0, "Alex Example", "Selected Team"),
            (1, "Alex Example", "Second Team"),
            (2, "Alex Example", "Excluded Team"),
            (0, "Other Person", "Selected Team"),
            (0, "Untracked Person", "Selected Team"),
        ]:
            db.session.add(
                RegistrationLinkCompetitor(
                    registration_link_id=self.events[event].id,
                    athlete_name=name,
                    team_name=team,
                    division_id=division.id,
                )
            )
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def save(self, event_ids=None, athlete_ids=None):
        return self.client.post(
            "/api/watchlists",
            json={
                "event_ids": event_ids or ["1"],
                "athlete_ids": athlete_ids or [str(self.athletes[0].id)],
            },
        )

    def snapshot(self, matches, event="1", error=None, coverage=None):
        cache = db.session.get(WatchlistSchedule, event) or WatchlistSchedule(
            event_id=event
        )
        cache.snapshot = matches
        cache.snapshot_version = uuid.uuid4()
        cache.fetched_at = datetime.now(timezone.utc)
        cache.coverage = coverage or [{"state": "complete"}]
        cache.last_error_code = error
        db.session.add(cache)
        db.session.commit()

    def match(
        self,
        time="09:00",
        opponent="200",
        event="1",
        division="BLACK / Adult / Male / Light",
        fight=1,
    ):
        return {
            "event_id": event,
            "day_id": "2",
            "local_date": self.day,
            "local_time": time,
            "mat": 1,
            "fight_number": fight,
            "source_order": 0,
            "division": division,
            "sides": [
                {
                    "ibjjf_id": "100",
                    "name": "Alex Example",
                    "team": "Team A",
                    "description": None,
                },
                {
                    "ibjjf_id": opponent,
                    "name": "Other Person",
                    "team": "Team B",
                    "description": None,
                },
            ],
        }

    def test_search_personal_name_eligibility_and_hide_full_name(self):
        result = self.client.get(
            "/api/watchlists/athletes?event_id=1&q=Private"
        ).get_json()
        self.assertEqual(len(result["athletes"]), 1)
        self.assertIsNone(result["athletes"][0]["full_name"])
        self.assertEqual(result["athletes"][0]["name"], "Private Alex")
        self.athletes[0].name = "Not Registered"
        db.session.commit()
        self.assertEqual(
            self.client.get("/api/watchlists/athletes?event_id=1&q=Private").get_json()[
                "athletes"
            ],
            [],
        )

    def test_team_search_scoped_and_distinct_by_uuid(self):
        result = self.client.get(
            "/api/watchlists/athletes?event_id=1&event_id=2&mode=team&q=Selected"
        ).get_json()
        self.assertEqual(len(result["athletes"]), 4)
        self.assertEqual(len({a["id"] for a in result["athletes"]}), 4)
        self.assertEqual(
            self.client.get(
                "/api/watchlists/athletes?event_id=1&mode=team&q=Excluded"
            ).get_json()["athletes"],
            [],
        )
        self.assertEqual(
            self.client.get(
                "/api/watchlists/athletes?event_id=1&mode=team&q=%25"
            ).get_json()["athletes"],
            [],
        )

    def test_unified_search_matches_names_and_teams(self):
        registration = (
            db.session.query(RegistrationLinkCompetitor)
            .filter_by(
                registration_link_id=self.events[0].id, athlete_name="Other Person"
            )
            .one()
        )
        registration.team_name = "Alex Team"
        db.session.commit()
        result = self.client.get(
            "/api/watchlists/athletes?event_id=1&q=Alex"
        ).get_json()
        self.assertEqual(
            {a["id"] for a in result["athletes"]},
            {str(a.id) for a in self.athletes[:3]},
        )
        self.assertEqual(result["teams"], ["Alex Team"])
        result = self.client.get(
            "/api/watchlists/athletes?event_id=1&q=Excluded"
        ).get_json()
        self.assertEqual(result["teams"], [])
        self.assertEqual(result["athletes"], [])
        for query in ("", "   ", "%", "_"):
            result = self.client.get(
                "/api/watchlists/athletes", query_string={"event_id": "1", "q": query}
            ).get_json()
            self.assertEqual(result["teams"], [])
            self.assertEqual(result["athletes"], [])

    def test_exact_team_search_paginates_trackable_members(self):
        for i in range(40):
            db.session.add(
                Athlete(
                    name="Alex Example",
                    normalized_name="alex example",
                    slug=f"team-page-{i}",
                    ibjjf_id=str(2000 + i),
                )
            )
        # A similarly named team must not be included by ADD ALL.
        registration = (
            db.session.query(RegistrationLinkCompetitor)
            .filter_by(
                registration_link_id=self.events[0].id, athlete_name="Other Person"
            )
            .one()
        )
        registration.team_name = "Selected Team Extra"
        db.session.commit()
        params = {"event_id": "1", "mode": "team_exact", "q": "Selected Team"}
        first = self.client.get(
            "/api/watchlists/athletes", query_string=params
        ).get_json()
        self.assertEqual(len(first["athletes"]), 30)
        params["cursor"] = first["next_cursor"]
        second = self.client.get(
            "/api/watchlists/athletes", query_string=params
        ).get_json()
        members = first["athletes"] + second["athletes"]
        self.assertEqual(len({a["id"] for a in members}), 42)
        self.assertTrue(all(a["trackable"] for a in members))
        self.assertNotIn(str(self.athletes[2].id), {a["id"] for a in members})
        self.assertIsNone(second["next_cursor"])

    def test_selection_canonical_and_edits_immutable(self):
        a = str(self.athletes[0].id)
        first = self.save(["2", "1", "1"], [a, a]).get_json()
        self.assertEqual(first["url"], "/watchlists/" + first["id"])
        second = self.save(["1", "2"], [a]).get_json()
        changed = self.save(["1"], [a]).get_json()
        self.assertEqual(first["id"], second["id"])
        self.assertNotEqual(first["id"], changed["id"])
        self.assertEqual(
            self.client.get("/api/watchlists/" + first["id"]).get_json()["selection"][
                "event_ids"
            ],
            ["1", "2"],
        )
        self.assertEqual(db.session.query(Watchlist).count(), 2)

    def test_save_requires_live_id_and_eligibility(self):
        self.assertEqual(
            self.save(athlete_ids=[str(self.athletes[3].id)]).status_code, 400
        )
        self.assertEqual(self.save(athlete_ids=[str(uuid.uuid4())]).status_code, 400)
        for value in [
            None,
            [],
            {},
            {"event_ids": [], "athlete_ids": []},
            {"event_ids": [True], "athlete_ids": ["bad"]},
        ]:
            self.assertEqual(
                self.client.post("/api/watchlists", json=value).status_code, 400
            )

    def test_creation_cap_rejects_new_selections_but_allows_reuse(self):
        with patch.dict(self.app.config, WATCHLIST_MAX_SAVED=1):
            first = self.save().get_json()
            rejected = self.save(athlete_ids=[str(self.athletes[1].id)])
            self.assertEqual(rejected.status_code, 503)
            self.assertEqual(rejected.get_json()["error"], "watchlist_capacity_reached")
            self.assertEqual(self.save().get_json()["id"], first["id"])
            self.assertEqual(db.session.query(Watchlist).count(), 1)

    def test_tournament_summaries_detect_kids_names(self):
        for name in (
            "Test Kids Open",
            "Test Crianças Open",
            "Test Criancas Open",
            "Test Open idade 04 a 15 anos",
        ):
            with self.subTest(name=name):
                self.events[0].name = name
                db.session.commit()
                summaries = self.client.get("/api/watchlists/tournaments").get_json()[
                    "tournaments"
                ]
                event = next(event for event in summaries if event["event_id"] == "1")
                self.assertTrue(event["is_kids_tournament"])
        self.events[0].name = "Test Adult Open"
        db.session.commit()
        summaries = self.client.get("/api/watchlists/tournaments").get_json()[
            "tournaments"
        ]
        event = next(event for event in summaries if event["event_id"] == "1")
        self.assertFalse(event["is_kids_tournament"])

    def test_kids_excluded_from_search_team_add_and_save(self):
        db.session.query(Division).update({"age": "Junior 1"})
        db.session.commit()
        for mode, query in (
            ("all", "Selected"),
            ("name", "Private"),
            ("team_exact", "Selected Team"),
        ):
            result = self.client.get(
                "/api/watchlists/athletes",
                query_string={
                    "event_id": "1",
                    "mode": mode,
                    "q": query,
                    "selected_id": str(self.athletes[0].id),
                },
            ).get_json()
            self.assertEqual(result["athletes"], [])
            self.assertEqual(result["teams"], [])
            self.assertEqual(result["eligible_selected_ids"], [])
        self.assertEqual(self.save().status_code, 400)

    def test_teen_search_save_and_schedule_without_ratings(self):
        db.session.query(Division).update({"age": "Teen 1"})
        db.session.commit()
        result = self.client.get(
            "/api/watchlists/athletes?event_id=1&q=Private"
        ).get_json()
        self.assertEqual(len(result["athletes"]), 1)
        identity = self.save().get_json()["id"]
        self.snapshot([self.match(division="Teen 1 / Male / GREEN / Light")])
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertEqual(row["state"], "scheduled")
        self.assertEqual(
            row["match"]["bracket_category"], "GREEN / Teen 1 / Male / Light"
        )
        for side in (row["competitor"], row["opponent"]):
            self.assertIsNone(side["rating"])
            self.assertIsNone(side["win_probability"])

    def test_kids_schedule_cards_hidden_without_changing_snapshot(self):
        identity = self.save().get_json()["id"]
        self.snapshot([self.match(division="Junior 1 / Male / GREY / Light")])
        result = self.client.get("/api/watchlists/" + identity + "/data").get_json()
        self.assertEqual(result["rows"], [])
        self.assertEqual(result["athletes"], [])
        self.assertEqual(len(db.session.get(WatchlistSchedule, "1").snapshot), 1)

    def test_live_bracket_category_normalizes_schedule_order(self):
        identity = self.save().get_json()["id"]
        self.snapshot([self.match(division="Master 1 / Male / BLUE / Feather")])
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertEqual(
            row["match"]["bracket_category"], "BLUE / Master 1 / Male / Feather"
        )
        self.assertEqual(row["match"]["division"], "Master 1 / Male / BLUE / Feather")

    def test_pagination_stable(self):
        # Same registered name resolves to many distinct local UUIDs.
        for i in range(40):
            db.session.add(
                Athlete(
                    name="Alex Example",
                    normalized_name="alex example",
                    slug=f"page-{i}",
                    ibjjf_id=str(1000 + i),
                )
            )
        db.session.commit()
        first = self.client.get(
            "/api/watchlists/athletes?event_id=1&mode=team&q=Selected"
        ).get_json()
        second = self.client.get(
            "/api/watchlists/athletes",
            query_string={
                "event_id": "1",
                "mode": "team",
                "q": "Selected",
                "cursor": first["next_cursor"],
            },
        ).get_json()
        self.assertEqual(len(first["athletes"]), 30)
        self.assertEqual(len(second["athletes"]), 14)
        self.assertFalse(
            {a["id"] for a in first["athletes"]} & {a["id"] for a in second["athletes"]}
        )
        self.assertEqual(
            self.client.get(
                "/api/watchlists/athletes?event_id=1&cursor=!!"
            ).status_code,
            400,
        )

    def test_unknown_dates_hidden_internal_and_expired_excluded(self):
        self.events[0].event_start_date = datetime.now()
        self.events[0].event_end_date = None
        self.events[1].hidden = True
        self.events[2].link = "internal:test"
        db.session.commit()
        rows = self.client.get("/api/watchlists/tournaments").get_json()["tournaments"]
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["selectable"])
        self.assertEqual(self.save().status_code, 400)

    def test_blank_search_preserves_selected_athlete_validation(self):
        selected = str(self.athletes[0].id)
        for mode in ("name", "team"):
            for query in ("", "   "):
                with self.subTest(mode=mode, query=query):
                    response = self.client.get(
                        "/api/watchlists/athletes",
                        query_string={
                            "event_id": "1",
                            "mode": mode,
                            "q": query,
                            "selected_id": selected,
                        },
                    )
                    self.assertEqual(response.status_code, 200)
                    result = response.get_json()
                    self.assertEqual(result["athletes"], [])
                    self.assertIsNone(result["next_cursor"])
                    self.assertEqual(result["eligible_selected_ids"], [selected])

    def test_tournament_picker_calendar_month_window(self):
        from datetime import date

        for today, cutoff in (
            (date(2026, 1, 31), date(2026, 2, 28)),
            (date(2026, 12, 4), date(2027, 1, 4)),
        ):
            for start, included in (
                (today - timedelta(days=1), True),
                (today, True),
                (cutoff, True),
                (cutoff + timedelta(days=1), False),
                (None, False),
            ):
                with self.subTest(today=today, start=start):
                    for event in self.events:
                        event.event_start_date = (
                            datetime.combine(start, datetime.min.time())
                            if start
                            else None
                        )
                        event.event_end_date = datetime(2027, 2, 1)
                    db.session.commit()
                    with patch("routes.watchlists.date") as mock_date:
                        mock_date.today.return_value = today
                        mock_date.side_effect = date
                        rows = self.client.get(
                            "/api/watchlists/tournaments"
                        ).get_json()["tournaments"]
                    self.assertEqual(len(rows), 3 if included else 0)

    def test_tournament_picker_includes_ongoing_but_not_finished_events(self):
        today = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        for event, end in zip(
            self.events, (today, today + timedelta(days=1), today - timedelta(days=1))
        ):
            event.event_start_date = today - timedelta(days=3)
            event.event_end_date = end
        db.session.commit()
        rows = self.client.get("/api/watchlists/tournaments").get_json()["tournaments"]
        self.assertEqual({row["event_id"] for row in rows}, {"1", "2"})

    def test_successful_empty_registration_import_is_ready(self):
        db.session.query(RegistrationLinkCompetitor).delete()
        self.events[0].registrations_imported_at = datetime.now(timezone.utc)
        db.session.commit()
        result = self.client.get("/api/watchlists/athletes?event_id=1").get_json()
        self.assertTrue(result["registration_ready"])
        self.assertEqual(result["athletes"], [])

    def test_future_empty_schedule_is_not_gray(self):
        identity = self.save().get_json()["id"]
        self.events[0].event_start_date = datetime.now() + timedelta(days=1)
        db.session.commit()
        self.snapshot([])
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertEqual(row["state"], "not_posted")

    def test_name_search_literal_wildcards(self):
        for q in ["%", "_", "Alex%"]:
            result = self.client.get(
                "/api/watchlists/athletes", query_string={"event_id": "1", "q": q}
            ).get_json()
            self.assertEqual(result["athletes"], [])

    def test_untrusted_registration_link_cannot_supply_selected_event_eligibility(self):
        athlete = Athlete(
            name="Only Untrusted",
            normalized_name="only untrusted",
            slug="untrusted",
            ibjjf_id="777",
        )
        link = RegistrationLink(
            name="Untrusted",
            normalized_name="untrusted",
            event_id="1",
            updated_at=datetime.now(),
            link="https://example.invalid/registrations",
            hidden=False,
        )
        db.session.add_all([athlete, link])
        db.session.flush()
        db.session.add(
            RegistrationLinkCompetitor(
                registration_link_id=link.id,
                athlete_name=athlete.name,
                team_name="Other Team",
                division_id=db.session.query(Division).first().id,
            )
        )
        db.session.commit()
        result = self.client.get(
            "/api/watchlists/athletes?event_id=1&q=Untrusted"
        ).get_json()
        self.assertEqual(result["athletes"], [])

    def test_ended_unpublished_event_does_not_become_reliable_absence(self):
        identity = self.save().get_json()["id"]
        self.snapshot([], coverage=[{"state": "unpublished"}])
        self.events[0].event_end_date = datetime.now() - timedelta(days=1)
        cache = db.session.get(WatchlistSchedule, "1")
        cache.fetched_at = datetime.now(timezone.utc) - timedelta(hours=24)
        db.session.commit()
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertNotEqual(row["state"], "not_on_schedule")

    def test_mighty_mite_competitors_are_hidden(self):
        identity = self.save().get_json()["id"]
        self.snapshot([self.match(division="WHITE / Mighty Mite 1 / Male / Light")])
        rows = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ]
        self.assertEqual(rows, [])

    def test_reads_do_not_revalidate_registration(self):
        identity = self.save().get_json()["id"]
        db.session.query(RegistrationLinkCompetitor).delete()
        db.session.commit()
        self.assertEqual(
            self.client.get("/api/watchlists/" + identity).status_code, 200
        )

    def test_expiry_reconciles_and_then_deletes_on_access(self):
        identity = self.save().get_json()["id"]
        self.events[0].event_end_date = datetime.now() + timedelta(days=4)
        db.session.commit()
        result = self.client.get("/api/watchlists/" + identity).get_json()
        self.assertEqual(
            result["expires_at"][:10],
            (datetime.now() + timedelta(days=6)).date().isoformat(),
        )
        self.events[0].event_end_date = datetime.now() - timedelta(days=4)
        db.session.commit()
        self.assertEqual(
            self.client.get("/api/watchlists/" + identity + "/data").status_code, 410
        )
        self.assertEqual(
            self.client.get("/api/watchlists/" + identity).status_code, 404
        )

    def test_reduction_open_class_two_watched_sides_and_defaults(self):
        identity = self.save(
            ["1", "2"], [str(self.athletes[0].id), str(self.athletes[2].id)]
        ).get_json()["id"]
        self.snapshot(
            [
                self.match("12:00"),
                self.match(
                    "11:00", division="BLACK / Adult / Male / Open Class", fight=2
                ),
            ]
        )
        self.snapshot([self.match("10:00", event="2")], event="2")
        result = self.client.get("/api/watchlists/" + identity + "/data").get_json()
        self.assertEqual(len(result["rows"]), 2)
        for row in result["rows"]:
            self.assertEqual(row["match"]["local_time"], "10:00")
            self.assertEqual(row["match"]["event_id"], "2")
            self.assertEqual(row["competitor"]["match_count"], 0)
            self.assertIsNotNone(row["opponent"]["rating"])
            self.assertAlmostEqual(
                row["competitor"]["win_probability"]
                + row["opponent"]["win_probability"],
                1,
            )

    def test_strict_ids_dont_match_same_name_unknown_opponent(self):
        identity = self.save().get_json()["id"]
        self.snapshot([self.match(opponent="99999")])
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertIsNone(row["opponent"]["profile_url"])
        self.assertIsNotNone(row["opponent"]["rating"])
        self.assertEqual(row["opponent"]["match_count"], 0)

    def test_placeholder_omits_prediction(self):
        identity = self.save().get_json()["id"]
        match = self.match(opponent=None)
        match["sides"][1].update(description="Winner of Fight 4", name=None)
        self.snapshot([match])
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertEqual(row["opponent"]["description"], "Winner of Fight 4")
        self.assertIsNone(row["opponent"]["rating"])
        self.assertIsNone(row["competitor"]["win_probability"])

    def test_empty_complete_vs_no_snapshot_and_failure(self):
        identity = self.save().get_json()["id"]
        path = "/api/watchlists/" + identity + "/data"
        self.assertEqual(
            self.client.get(path).get_json()["rows"][0]["state"], "populating"
        )
        self.snapshot([])
        self.assertEqual(
            self.client.get(path).get_json()["rows"][0]["state"], "not_on_schedule"
        )
        self.snapshot([], error="timeout")
        self.assertEqual(
            self.client.get(path).get_json()["rows"][0]["state"], "unavailable"
        )

    def test_stale_known_match_survives_failure_without_warning_field(self):
        identity = self.save(["1", "2"]).get_json()["id"]
        self.snapshot([self.match()], error="timeout")
        result = self.client.get("/api/watchlists/" + identity + "/data").get_json()
        self.assertEqual(result["rows"][0]["state"], "scheduled")
        self.assertNotIn("incomplete", result["rows"][0])

    def test_unknown_time_stays_visible_past_dates_ignored(self):
        identity = self.save().get_json()["id"]
        old = self.match("08:00")
        old["local_date"] = "2020-01-01"
        self.snapshot([old, self.match(None)])
        row = self.client.get("/api/watchlists/" + identity + "/data").get_json()[
            "rows"
        ][0]
        self.assertIsNone(row["match"]["local_time"])
        self.assertEqual(row["state"], "scheduled")

    def test_routine_refresh_keeps_complete_snapshot_with_regular_polling(self):
        identity = self.save().get_json()["id"]
        self.snapshot([self.match()])
        now = datetime.now(timezone.utc)
        for age, lease, error, coverage in (
            (181, 60, None, "complete"),
            (239, 60, None, "complete"),
            (240, 60, None, "complete"),
            (600, 60, None, "complete"),
            (181, -1, None, "complete"),
            (181, 60, "timeout", "complete"),
            (181, 60, None, "unpublished"),
        ):
            with self.subTest(age=age, lease=lease, error=error, coverage=coverage):
                cache = db.session.get(WatchlistSchedule, "1")
                cache.fetched_at = now - timedelta(seconds=age)
                cache.lease_until = now + timedelta(seconds=lease)
                cache.last_error_code = error
                cache.coverage = [{"state": coverage}]
                db.session.commit()
                with patch("watchlists.database_now", return_value=now):
                    result = self.client.get(
                        "/api/watchlists/" + identity + "/data"
                    ).get_json()
                self.assertEqual(result["rows"][0]["state"], "scheduled")
                self.assertNotIn("incomplete", result["rows"][0])
                self.assertEqual(result["poll_after_seconds"], 180)

    def test_loaded_watchlist_does_not_poll_at_nearby_refresh_deadline(self):
        identity = self.save().get_json()["id"]
        self.snapshot([self.match()])
        now = datetime.now(timezone.utc)
        cache = db.session.get(WatchlistSchedule, "1")
        cache.next_attempt_at = now + timedelta(seconds=3)
        db.session.commit()
        with patch("watchlists.database_now", return_value=now):
            result = self.client.get("/api/watchlists/" + identity + "/data").get_json()
        self.assertEqual(result["poll_after_seconds"], 180)

    def test_initial_population_always_uses_regular_polling(self):
        identity = self.save().get_json()["id"]
        path = "/api/watchlists/" + identity + "/data"
        self.assertEqual(self.client.get(path).get_json()["poll_after_seconds"], 180)
        now = datetime.now(timezone.utc)
        db.session.add(
            WatchlistSchedule(
                event_id="1",
                last_error_code="timeout",
                next_attempt_at=now + timedelta(seconds=300),
            )
        )
        db.session.commit()
        with patch("watchlists.database_now", return_value=now):
            result = self.client.get(path).get_json()
        self.assertEqual(result["poll_after_seconds"], 180)

    def test_http_handlers_never_fetch_upstream(self):
        identity = self.save().get_json()["id"]
        self.app.config["WATCHLIST_REFRESH_ENABLED"] = True
        with patch("watchlist_refresh.threading.Thread.start"), patch(
            "watchlist_refresh.requests.get",
            side_effect=AssertionError("synchronous HTTP"),
        ):
            response = self.client.get("/api/watchlists/" + identity + "/data")
        # Mocked startup deliberately does not run the worker/finally.
        from watchlist_refresh import _capacity

        _capacity.release()
        self.assertEqual(response.status_code, 200)

    def test_leases_global_capacity_and_stale_publisher(self):
        first = claim("1")
        self.assertIsNotNone(first)
        self.assertIsNone(claim("1"))
        second = claim("2")
        self.assertIsNotNone(second)
        self.assertIsNone(claim("3"))
        renew("1", *first, 400)
        self.assertFalse(finish("1", uuid.uuid4(), first[1], result=([], [], {})))
        self.assertTrue(finish("1", *first, result=([], [{"state": "complete"}], {})))
        self.assertIsNotNone(claim("3"))
        self.assertIsNone(claim("1"))

    def test_failure_keeps_snapshot_and_backoff(self):
        lease = claim("1")
        self.snapshot([self.match()])
        self.assertTrue(finish("1", *lease, error=SourceError("timeout", 600)))
        db.session.expire_all()
        row = db.session.get(WatchlistSchedule, "1")
        self.assertEqual(len(row.snapshot), 1)
        self.assertEqual(row.failure_count, 1)
        self.assertGreater(
            (utc(row.next_attempt_at) - datetime.now(timezone.utc)).total_seconds(), 590
        )
        self.assertIsNone(claim("1"))

    def test_dead_worker_reclaimed_and_cannot_publish(self):
        old = claim("1")
        past = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.session.query(WatchlistSchedule).update({"lease_until": past})
        db.session.query(WatchlistRefreshSlot).update({"lease_until": past})
        db.session.commit()
        new = claim("1")
        self.assertNotEqual(old[0], new[0])
        self.assertFalse(finish("1", *old, result=([self.match()], [], {})))
        self.assertTrue(finish("1", *new, result=([], [], {})))

    def test_failed_thread_start_releases_owned_work(self):
        self.app.config["WATCHLIST_REFRESH_ENABLED"] = True
        with patch(
            "watchlist_refresh.threading.Thread.start",
            side_effect=RuntimeError("cannot start"),
        ):
            self.assertFalse(trigger({"event_id": "1"}))
        db.session.expire_all()
        self.assertIsNone(db.session.get(WatchlistSchedule, "1").refresh_token)
        self.assertEqual(
            db.session.query(WatchlistRefreshSlot)
            .filter(WatchlistRefreshSlot.owner_token.isnot(None))
            .count(),
            0,
        )

    def test_renewal_cannot_revive_expired_lease_or_exceed_deadline(self):
        lease = claim("1")
        with self.assertRaises(SourceError):
            renew("1", *lease, 0)
        db.session.query(WatchlistSchedule).filter_by(event_id="1").update(
            {"lease_until": datetime.now(timezone.utc) - timedelta(seconds=1)}
        )
        db.session.commit()
        with self.assertRaises(SourceError):
            renew("1", *lease, 600)

    def test_worker_timeout_keeps_snapshot_and_releases_connection(self):
        from watchlist_refresh import _capacity, _run
        import requests

        lease = claim("1")
        self.snapshot([self.match()])
        _capacity.acquire()
        event = {
            "event_id": "1",
            "start": datetime.now() - timedelta(days=1),
            "end": datetime.now() + timedelta(days=1),
        }

        def timeout(*args, **kwargs):
            # The thread's SQLAlchemy session must not own a transaction while fetching.
            self.assertFalse(db.session().in_transaction())
            raise requests.Timeout("slow source")

        with patch("watchlist_refresh.requests.get", side_effect=timeout):
            _run(self.app, event, *lease)
        db.session.expire_all()
        cache = db.session.get(WatchlistSchedule, "1")
        self.assertEqual(len(cache.snapshot), 1)
        self.assertIsNone(cache.refresh_token)
        self.assertEqual(cache.failure_count, 1)

    def test_worker_publishes_only_after_entire_scan(self):
        from watchlist_refresh import _capacity, _run
        from unittest.mock import MagicMock

        lease = claim("1")
        _capacity.acquire()
        now = datetime.now()
        html = page(card()).replace("09/04", now.strftime("%m/%d"))

        def response_for(url, **kwargs):
            self.assertFalse(db.session().in_transaction())
            response = MagicMock()
            response.status_code = 200
            response.encoding = "utf-8"
            body = (
                "<a href='/tournaments/1/tournament_days/2'>Day</a>"
                if url == BASE + "/?locale=en"
                else html
            )
            response.iter_content.return_value = [body.encode()]
            response.__enter__.return_value = response
            return response

        with self.assertLogs(
            "ibjjf.watchlist_refresh", level="INFO"
        ) as captured, patch(
            "watchlist_refresh.requests.get", side_effect=response_for
        ):
            _run(self.app, {"event_id": "1", "start": now, "end": now}, *lease)
        messages = "\n".join(captured.output)
        self.assertIn("watchlist fetch start event=1", messages)
        self.assertIn("watchlist fetch complete event=1", messages)
        self.assertIn("kind=order_of_fights", messages)
        db.session.expire_all()
        cache = db.session.get(WatchlistSchedule, "1")
        self.assertIsNone(cache.last_error_code)
        self.assertEqual(len(cache.snapshot), 1)
        self.assertIsNone(cache.refresh_token)

    def test_cleanup_preserves_live_leases(self):
        identity = self.save().get_json()["id"]
        self.events[0].event_end_date = datetime.now() - timedelta(days=4)
        db.session.commit()
        claim("orphan")
        self.snapshot([], event="unowned")
        self.assertEqual(purge(), 1)
        self.assertIsNone(db.session.get(Watchlist, uuid.UUID(identity)))
        self.assertIsNotNone(db.session.get(WatchlistSchedule, "orphan"))
        self.assertIsNone(db.session.get(WatchlistSchedule, "unowned"))


if __name__ == "__main__":
    unittest.main()
