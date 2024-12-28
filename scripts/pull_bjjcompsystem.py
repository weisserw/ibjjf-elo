#!/usr/bin/env python3

import argparse
import requests
import csv
import traceback
import sys
import gzip
from datetime import datetime
from bs4 import BeautifulSoup
import os
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Google API setup
SCOPES = ['https://www.googleapis.com/auth/drive.file', 'https://www.googleapis.com/auth/spreadsheets']
SERVICE_ACCOUNT_FILE = '/etc/secrets/service-account.json'

def get_folder_id(drive_service, folder_name):
    query = f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    items = results.get('files', [])
    if not items:
        raise FileNotFoundError(f"Folder '{folder_name}' not found.")
    return items[0]['id']

def upload_to_drive(file_path):
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=credentials)

    folder_id = get_folder_id(drive_service, 'IBJJF CSV Files')

    file_metadata = {
        'name': os.path.basename(file_path),
        'parents': [folder_id]
    }
    media = MediaFileUpload(file_path, mimetype='text/csv')
    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id').execute()
    return file.get('id')

def create_google_sheet(filename, data):
    credentials = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    drive_service = build('drive', 'v3', credentials=credentials)
    sheets_service = build('sheets', 'v4', credentials=credentials)
    gc = gspread.authorize(credentials)

    folder_id = get_folder_id(drive_service, "IBJJF Spreadsheets")

    spreadsheet = {
        'properties': {
            'title': filename
        }
    }
    spreadsheet = sheets_service.spreadsheets().create(body=spreadsheet, fields='spreadsheetId').execute()
    spreadsheet_id = spreadsheet.get('spreadsheetId')

    drive_service.files().update(fileId=spreadsheet_id, addParents=folder_id, removeParents=None, fields='id, parents').execute()

    permission = {
        'type': 'anyone',
        'role': 'reader'
    }
    drive_service.permissions().create(fileId=spreadsheet_id, body=permission).execute()

    sheet = gc.open_by_key(spreadsheet_id)
    worksheet = sheet.get_worksheet(0)
    worksheet.update([data[0]] + data[1:])

    return f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"

def main():
    try:
        parser = argparse.ArgumentParser(description='Pull tournament matches from bjjcompsystem.com')
        parser.add_argument('tournament_id', type=str, help='The ID of the tournament')
        parser.add_argument('tournament_name', type=str, help='The name of the tournament')
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument('--nogi', action='store_false', dest='gi', help='Specifies a no-gi tournament')
        group.add_argument('--gi', action='store_true', dest='gi', help='Specifies a gi tournament')
        args = parser.parse_args()

        tournament_name_lower = args.tournament_name.lower()

        # Check for "no gi" or "no-gi" in the tournament name
        if ('no gi' in tournament_name_lower or 'no-gi' in tournament_name_lower) and args.gi:
            input("Warning: This tournament name indicates it is no-gi, but you are importing it as gi. Press Enter to continue or Ctrl-C to abort.\n")
        elif not ('no gi' in tournament_name_lower or 'no-gi' in tournament_name_lower) and not args.gi:
            input("Warning: The tournament name does not indicate no-gi, but you are importing it as no-gi. Press Enter to continue or Ctrl-C to abort.\n")

        urls = [('Male', f'https://www.bjjcompsystem.com/tournaments/{args.tournament_id}/categories'),
                ('Female', f'https://www.bjjcompsystem.com/tournaments/{args.tournament_id}/categories?gender_id=2')]

        output_dir = "IBJJF CSV Files"
        os.makedirs(output_dir, exist_ok=True)
        output_file = os.path.join(output_dir, f"{args.tournament_id}.{args.tournament_name.replace(' ', '_')}.{datetime.now().strftime('%Y%m%d%H%M')}.csv")

        with open(output_file, mode='w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(['Tournament ID', 'Tournament Name', 'Link', 'Gi', 'Gender', 'Age', 'Belt', 'Weight', 'Date', 'Red ID', 'Red Seed', 'Red Winner', 'Red Name', 'Red Team', 'Red Note', 'Blue ID', 'Blue Seed', 'Blue Winner', 'Blue Name', 'Blue Team', 'Blue Note'])

            total_matches = 0
            total_defaults = 0
            total_categories = 0

            for gender, url in urls:
                print(f"Fetching data for {gender} categories from {url}")
                response = requests.get(url)

                if response.status_code != 200:
                    print(f"Failed to retrieve data for {url}: {response.status_code}")
                    return

                soup = BeautifulSoup(response.content, 'html.parser')
                categories = soup.find_all('li', class_='categories-grid__category')

                for category in categories:
                    category_matches = 0
                    category_defaults = 0

                    link = category.find('a')['href']
                    age = category.find('div', class_='category-card__age-division').get_text(strip=True)
                    belt = category.find('span', class_='category-card__belt-label').get_text(strip=True)
                    weight = category.find('span', class_='category-card__weight-label').get_text(strip=True)

                    age_lower = age.lower()

                    if not (age_lower.startswith('master') or age_lower.startswith('juvenil') or age_lower.startswith('adult')):
                        continue

                    total_categories += 1

                    print(f"Fetching data for {age} / {belt} / {weight} from {link}")

                    categoryurl = f'https://www.bjjcompsystem.com{link}'
                    response = requests.get(categoryurl)
                    if response.status_code != 200:
                        print(f"Failed to retrieve data for {categoryurl}: {response.status_code}")
                        return

                    category_soup = BeautifulSoup(response.content, 'html.parser')
                    matches = category_soup.find_all('div', class_='tournament-category__match')

                    num_matches = len(matches)

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

                        red_competitor_id = red_competitor['id'].split('-')[-1]
                        red_competitor_seed = red_competitor.find('span', class_='match-card__competitor-n').get_text(strip=True)
                        red_competitor_loser = 'match-competitor--loser' in red_competitor_description['class']
                        red_competitor_name = red_competitor.find('div', class_='match-card__competitor-name').get_text(strip=True)
                        red_competitor_team = red_competitor.find('div', class_='match-card__club-name').get_text(strip=True)
                        red_competitor_note = red_competitor_description.find('i', class_='match-card__disqualification')
                        red_competitor_note = red_competitor_note['title'] if red_competitor_note else ''

                        if blue_competitor_description.find('div', class_='match-card__bye'):
                            if num_matches == 1 and not red_competitor_loser: # default gold
                                writer.writerow([args.tournament_id, args.tournament_name, link, 'true' if args.gi else 'false', gender, age, belt, weight, match_datetime_iso, red_competitor_id, red_competitor_seed, 'true', red_competitor_name, red_competitor_team, red_competitor_note, 'DEFAULT_GOLD', '', '', '', '', ''])
                                file.flush()
                                category_defaults += 1
                                total_defaults += 1
                            continue

                        blue_competitor_id = blue_competitor['id'].split('-')[-1]
                        blue_competitor_seed = blue_competitor.find('span', class_='match-card__competitor-n').get_text(strip=True)
                        blue_competitor_loser = 'match-competitor--loser' in blue_competitor_description['class']
                        blue_competitor_name = blue_competitor.find('div', class_='match-card__competitor-name').get_text(strip=True)
                        blue_competitor_team = blue_competitor.find('div', class_='match-card__club-name').get_text(strip=True)
                        blue_competitor_note = blue_competitor_description.find('i', class_='match-card__disqualification')
                        blue_competitor_note = blue_competitor_note['title'] if blue_competitor_note else ''

                        writer.writerow([args.tournament_id, args.tournament_name, link, 'true' if args.gi else 'false', gender, age, belt, weight, match_datetime_iso, red_competitor_id, red_competitor_seed, 'false' if red_competitor_loser else 'true', red_competitor_name, red_competitor_team, red_competitor_note, blue_competitor_id, blue_competitor_seed, 'false' if blue_competitor_loser else 'true', blue_competitor_name, blue_competitor_team, blue_competitor_note])
                        file.flush()

                        category_matches += 1
                        total_matches += 1

                    print(f"Recorded {category_matches} matches and {category_defaults} default golds for {age} / {belt} / {weight}")

            print(f"Wrote data to {output_file}")
            print(f"Total matches recorded: {total_matches}, Total default golds recorded: {total_defaults}, Total divisions processed: {total_categories}")

        if os.getenv('ENABLE_GOOGLE_API') == 'true':
            # Make a gzip copy of the file
            with open(output_file, 'rb') as f_in:
                with gzip.open(f"{output_file}.gz", 'wb') as f_out:
                    f_out.writelines(f_in)
            
            # Upload to Google Drive
            upload_to_drive("{output_file}.gz")
            print(f"File uploaded to Google Drive.")

            # Delete the gzip file
            os.remove(f"{output_file}.gz")

            # Create Google Sheet and get the link
            with open(output_file, 'r') as file:
                reader = csv.reader(file)
                data = list(reader)
            sheet_link = create_google_sheet(output_file, data)
            print(f"Google Sheet Created: {sheet_link}")

    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()