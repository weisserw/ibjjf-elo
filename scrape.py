#!/usr/bin/env python3

import argparse
import requests
import csv
from datetime import datetime
from bs4 import BeautifulSoup

def main():
    parser = argparse.ArgumentParser(description='Scrape tournament matches.')
    parser.add_argument('tournament_id', type=str, help='The ID of the tournament')
    parser.add_argument('tournament_name', type=str, help='The name of the tournament')
    parser.add_argument('--nogi', action='store_true', help='Specifies a no-gi tournament')
    args = parser.parse_args()

    urls = [('Male', f'https://www.bjjcompsystem.com/tournaments/{args.tournament_id}/categories'),
            ('Female', f'https://www.bjjcompsystem.com/tournaments/{args.tournament_id}/categories?gender_id=2')]

    output_file = args.tournament_id + ".csv"
    with open(output_file, mode='w', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['Tournament ID', 'Tournament Name', 'Link', 'Gi', 'Gender', 'Age', 'Belt', 'Weight', 'Date', 'Red ID', 'Red Seed', 'Red Winner', 'Red Name', 'Red Team', 'Red Note', 'Blue ID', 'Blue Seed', 'Blue Winner', 'Blue Name', 'Blue Team', 'Blue Note'])

        for gender, url in urls:
            response = requests.get(url)
            
            if response.status_code != 200:
                print(f"Failed to retrieve data for {url}: {response.status_code}")
                continue

            soup = BeautifulSoup(response.content, 'html.parser')
            categories = soup.find_all('li', class_='categories-grid__category')

            for category in categories:
                link = category.find('a')['href']
                age = category.find('div', class_='category-card__age-division').get_text(strip=True)
                belt = category.find('span', class_='category-card__belt-label').get_text(strip=True)
                weight = category.find('span', class_='category-card__weight-label').get_text(strip=True)

                if not (age.lower().startswith('master') or age.lower().startswith('juvenil') or age.lower().startswith('adult')):
                    continue

                categoryurl = f'https://www.bjjcompsystem.com{link}'
                response = requests.get(categoryurl)
                if response.status_code != 200:
                    print(f"Failed to retrieve data for {categoryurl}: {response.status_code}")
                    continue

                category_soup = BeautifulSoup(response.content, 'html.parser')
                matches = category_soup.find_all('div', class_='tournament-category__match')

                for match in matches:
                    match_when = match.find('div', class_='bracket-match-header__when')
                    if match_when:
                        current_year = datetime.now().year
                        match_datetime = match_when.get_text(strip=True)
                        match_datetime_parsed = datetime.strptime(match_datetime, '%a %m/%d at %I:%M %p')
                        match_datetime_parsed = match_datetime_parsed.replace(year=current_year)
                        match_datetime_iso = match_datetime_parsed.strftime('%Y-%m-%dT%H:%M:%S')
                    else:
                        match_datetime_iso = ''
                    red_competitor = match.find('div', class_='match-card__competitor--red')
                    blue_competitor = match.find_all('div', class_='match-card__competitor')[1]

                    red_competitor_description = red_competitor.find('span', class_='match-card__competitor-description')
                    blue_competitor_description = blue_competitor.find('span', class_='match-card__competitor-description')

                    if not red_competitor_description or not blue_competitor_description:
                        continue

                    if red_competitor_description.find('div', class_='match-card__bye'):
                        continue
                    if blue_competitor_description.find('div', class_='match-card__bye'):
                        continue

                    red_competitor_id = red_competitor['id'].split('-')[-1]
                    red_competitor_seed = red_competitor.find('span', class_='match-card__competitor-n').get_text(strip=True)
                    red_competitor_loser = 'match-competitor--loser' in red_competitor_description['class']
                    red_competitor_name = red_competitor.find('div', class_='match-card__competitor-name').get_text(strip=True)
                    red_competitor_team = red_competitor.find('div', class_='match-card__club-name').get_text(strip=True)
                    red_competitor_note = red_competitor_description.find('i', class_='match-card__disqualification')
                    red_competitor_note = red_competitor_note['title'] if red_competitor_note else ''

                    blue_competitor_id = blue_competitor['id'].split('-')[-1]
                    blue_competitor_seed = blue_competitor.find('span', class_='match-card__competitor-n').get_text(strip=True)
                    blue_competitor_loser = 'match-competitor--loser' in blue_competitor_description['class']
                    blue_competitor_name = blue_competitor.find('div', class_='match-card__competitor-name').get_text(strip=True)
                    blue_competitor_team = blue_competitor.find('div', class_='match-card__club-name').get_text(strip=True)
                    blue_competitor_note = blue_competitor_description.find('i', class_='match-card__disqualification')
                    blue_competitor_note = blue_competitor_note['title'] if blue_competitor_note else ''

                    writer.writerow([args.tournament_id, args.tournament_name, link, 'false' if args.nogi else 'true', gender, age, belt, weight, match_datetime_iso, red_competitor_id, red_competitor_seed, 'false' if red_competitor_loser else 'true', red_competitor_name, red_competitor_team, red_competitor_note, blue_competitor_id, blue_competitor_seed, 'false' if blue_competitor_loser else 'true', blue_competitor_name, blue_competitor_team, blue_competitor_note])
                    file.flush()

    print(f"Wrote data to {output_file}")

if __name__ == '__main__':
    main()