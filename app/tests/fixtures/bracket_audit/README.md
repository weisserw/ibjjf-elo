# Bracket Audit Discovery Fixtures

These fixtures were captured during the September 3, 2026 planning review for
`docs/workflows/LIVE_BRACKET_SEEDING_AUDIT_PLAN.md`. Names, IDs, and teams are
synthetic; headers, cell encodings, swap sequences, match numbers, seeds, byes,
and first-round row order retain the behavior needed by parser tests.

| Fixture | Source and cache capture | Expected headers | Why retained |
| --- | --- | --- | --- |
| `regular_weight_one_swap.html` | [2649/2570165](https://www.bjjcompsystem.com/tournaments/2649/categories/2570165), 2025-02-21 | `Nº — Competitor`, `Team`, `Grand Slam Pts`, `Overall PTS` | Regular weight shape and one swap; the displayed seed still joins the same ranking row. |
| `regular_open.html` | [2692/2590920](https://www.bjjcompsystem.com/tournaments/2692/categories/2590920), 2025-03-21 | identity/team plus `Grand Slam Open Class PTS`, `Grand Slam Overall PTS`, `Overall Open Class PTS`, `Overall PTS (without Open Class)` | Regular open-class mapping and the longer Grand Slam alias. |
| `adult_black_weight.html` | [2965/2743141](https://www.bjjcompsystem.com/tournaments/2965/categories/2743141), 2026-01-14 | adult-black weight headers shown in the fixture | Year list, optional year, `Yes`/`No`, and former-champion year encodings. |
| `adult_black_open.html` | [2684/2586047](https://www.bjjcompsystem.com/tournaments/2684/categories/2586047), 2025-06-29 | adult-black open headers shown in the fixture | Open points and `World Champ. Last Edition`; intentionally omits the weight table's last-title/former columns. |
| `master_black_weight.html` | [2704/2596998](https://www.bjjcompsystem.com/tournaments/2704/categories/2596998), 2025-04-27 | identity/team, `Adult World Champ.`, `M1 World Champ.`, `M2 World Champ.`, `Grand Slam Pts`, `Overall PTS` | Dynamic Master-K flags for a Master 2 weight division. |
| `master_black_open.html` | [2815/2659935](https://www.bjjcompsystem.com/tournaments/2815/categories/2659935), 2025-05-29 | Master 2 headers plus open-class and regular point columns | Dynamic Master-K open-class variant. |
| `portuguese_adult_black_weight.html` | [2704/2596883](https://www.bjjcompsystem.com/tournaments/2704/categories/2596883), 2025-05-04 | Portuguese adult-black aliases shown in the fixture; `Last World Title` remains English | Localized semantic mapping and English `Yes`/`No` values inside the localized table. |
| `absent_ranking_n9.html` | [2721/2606307](https://www.bjjcompsystem.com/tournaments/2721/categories/2606307), 2025-02-16 | no ranking table | Proves a nine-person layout can remain verifiable when criteria cannot. |
| `n21_chained_swaps.html` | [2965/2743148](https://www.bjjcompsystem.com/tournaments/2965/categories/2743148), 2025-12-17 | regular weight headers | Twenty-one seeds, byes/play-ins, three swaps with seed 18 reused, and matching non-bye pairings in a different display order. |

The corpus also exposed Master 1 through Master 7 header expansions. Tests
should generate the intermediate `M{K}`/`master_{K}_world_champion` mappings as
table-driven cases rather than retaining seven otherwise identical HTML files.

For `n21_chained_swaps.html`, composing the swaps in document order gives the
displayed-seed-to-original-slot cycle `17→18`, `18→21`, `21→17` and the pair
`19↔20`. The non-bye pairings equal `_bracket_slots(21)`, but row order differs.
The flat dictionary in the pre-audit helper instead duplicates 18 and loses 17;
that behavior is deliberately not the expected result.
