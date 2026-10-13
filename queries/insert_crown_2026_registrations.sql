-- IBJJF Crown 2026: November 8, 2026; 37 invited athletes.
-- Edit the placeholder athlete names and blank team names before running.
-- Division assignments follow the supplied invitation list.
-- Run with: psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f queries/insert_crown_2026_registrations.sql
-- This file is transactional. Stable IDs make reruns skip previously inserted
-- competitors, preserving subsequent name/team edits. To correct an existing
-- row after running, UPDATE it directly; rerunning this file does not update it.
-- Keep slot numbers unchanged: they identify athletes independently of names.

BEGIN;

INSERT INTO registration_links (
    id, name, normalized_name, updated_at, link, hidden,
    event_start_date, event_end_date, event_id, registrations_imported_at
)
VALUES (
    md5('internal:crown_2026')::uuid,
    'IBJJF Crown 2026',
    'ibjjf crown 2026',
    CURRENT_TIMESTAMP,
    'internal:crown_2026',
    false,
    TIMESTAMP '2026-11-08 00:00:00',
    TIMESTAMP '2026-11-08 00:00:00',
    NULL,
    NULL
)
ON CONFLICT (link) DO NOTHING;

WITH invited (slot, athlete_name, division_id, team_name) AS (
    VALUES
        -- Male / Adult / BLACK / Feather
        (1, 'Jun Yong Cho',          '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'Wire Jiu-Jitsu'),
        (2, 'Keven Carrasco',        '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'Ares BJJ'),
        (3, 'João Pedro Bueno Mendes', '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'Alliance'),
        (4, 'William James Wilson',           '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'Carlson Gracie South Bay'),
        (5, 'Mateo Cardona',         '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'AOJ'),
        (6, 'Ademir Barreto de Araújo',        '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'GF Team'),
        (7, 'Samuel A. Nagai Hatchwell',             '9232ca7b-7e8b-4464-8a5b-e05d581097ef'::uuid, 'Inevat Brazilian Jiu-Jitsu'),

        -- Male / Adult / BLACK / Middle
        (8,  'Tarcisio Damasceno Santos', 'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'Marcio Andre Jiu-Jitsu'),
        (9,  'José Steve Nduazulu Ndilu',      'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'DreamArt'),
        (10, 'Leonardo Souza de Oliveira',       'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'Six Blades Jiu-Jitsu'),
        (11, 'Rafael Belmont Gamba',    'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'Alliance'),
        (12, 'Jackson Nagai Hatchwell Junior',   'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'Inevat Brazilian Jiu-Jitsu'),
        (13, 'Micael Ferreira Galvâo',     'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'Thyago Martins BJJ Academy'),
        (14, 'Uanderson Ferreira de Oliveira', 'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'Sertão Brazilian Jiu-Jitsu Internacional'),
        (15, 'Andy Tomas Murasaki Pereira', 'af34fb3c-c84f-49c8-a7ee-8453681d8c5b'::uuid, 'AOJ'),

        -- Male / Adult / BLACK / Heavy
        (16, 'Vinicius Liberati', '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Soldiers Brazilian Jiu-Jitsu'),
        (17, 'Fellipe Andrew Leandro Silva',    '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Del Mar Jiu-Jitsu Club'),
        (18, 'Windson Alves de Oliveira Torres',    '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Six Blades Jiu-Jitsu'),
        (19, 'Leonardo Silveira Ferreira',      '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Alliance'),
        (20, 'Omar Tariq N. Nada',         '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Unity Jiu-jitsu'),
        (21, 'Davi Vetoraci de Menezes', '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Blvckout Grappling'),
        (22, 'Nicholas Maglicic', '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Atos Jiu-Jitsu'),
        (23, 'Nolan Patrick Braga Stuart', '73759d48-b08c-4e8c-8a8b-493de4a69603'::uuid, 'Brea Jiu-Jitsu'),

        -- Male / Adult / BLACK / Ultra Heavy
        (24, 'Francisco Papasidero', 'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'Brea Jiu-Jitsu'),
        (25, 'Seif-Eddine Houmine',  'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'GF Team'),
        (26, 'Helder Jose Rodrigues Júnior',     'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'Atos Jiu-Jitsu'),
        (27, 'Thierry Felipe Alves Lima de Souza',       'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'Marcio Andre Jiu-Jitsu'),
        (28, 'Alexander Sak',        'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'Abdullaev Team'),
        (29, 'Pedro Henrique Pinheiro M. de Souza',        'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'Atos Jiu-Jitsu'),
        (30, 'Matheus Vetoraci de Menezes', 'cad80b3f-b0ad-4edd-8348-42dbf50d1989'::uuid, 'Blvckout Grappling'),

        -- Female / Adult / BLACK / Light
        (31, 'Nikolett Kis',     '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'Sigma Jiu-Jitsu'),
        (32, 'Janaina Maia de Menezes',    '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'Alliance'),
        (33, 'Eliza Carvalho Nascimento', '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'Marcio Andre Jiu-Jitsu'),
        (34, 'Elisabeth Ann Clay',   '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'Six Blades Jiu-Jitsu'),
        (35, 'Aghata Adriane Rabelo Fernandes',    '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'CheckMat'),
        (36, 'Keanna Carolyn Klay',      '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'Gracie Barra'),
        (37, 'Sabrina Rogéria Ataide B. Gondim', '97308d3f-f1a6-48f3-b920-d2ba1f8f9e6d'::uuid, 'Fight Sports'),

        -- Female / Adult / BLACK / Super Heavy
        (38, 'Larissa Dias de Almeida',          '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'Elementum Jiu-Jitsu'),
        (39, 'Yara Soares do Nascimento',           '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'DreamArt'),
        (40, 'Hazel Rose Butcher-Salazar', '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'Alliance'),
        (41, 'Ingridd Alves de Sousa',         '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'AGR Jiu-Jitsu'),
        (42, 'Maria Raniele Alencar Lima',         '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'Atos Jiu-Jitsu'),
        (43, 'Maria Vitória G. Ruffatto-Gilpin', '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'Canby Jiu-Jitsu'),
        (44, 'Anabel Lopez Beard', '27ccea96-27cc-450a-af34-ba2ea4c529da'::uuid, 'CheckMat')
)
INSERT INTO registration_link_competitors (
    id, registration_link_id, athlete_name, division_id, team_name
)
SELECT
    md5('internal:crown_2026:competitor:' || invited.slot::text)::uuid,
    registration_links.id,
    invited.athlete_name,
    invited.division_id,
    invited.team_name
FROM invited
CROSS JOIN registration_links
WHERE registration_links.link = 'internal:crown_2026'
ON CONFLICT (id) DO NOTHING;

-- Show the resulting registration counts before committing.
SELECT d.gender, d.weight, count(*) AS competitors
FROM registration_link_competitors AS c
JOIN registration_links AS r ON r.id = c.registration_link_id
JOIN divisions AS d ON d.id = c.division_id
WHERE r.link = 'internal:crown_2026'
GROUP BY d.gender, d.weight
ORDER BY d.gender, d.weight;

COMMIT;
