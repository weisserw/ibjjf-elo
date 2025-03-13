# IBJJF Elo Ratings

This is the source code for a web app to track matches in IBJJF tournaments and rank athletes with the Elo rating system.

The URL for the production app is https://ibjjfrankings.com/

If you wish to contribute to this project, please see the Issues page for a list of outstanding feature requests, or you can [donate](https://ko-fi.com/ibjjfrankings).

This app is built with the following technologies:

* The frontend is React with Typescript, with a build system created by [Vite](https://vite.dev/).
* Frontend CSS provided by [Bulma](https://bulma.io/).
* The backend is a Python web app using [Flask](https://flask.palletsprojects.com/en/stable/).
* We use [Flask-Migrate](https://flask-migrate.readthedocs.io/en/latest/) for database migrations.
* The database can be either [PostgreSQL](https://www.postgresql.org/) or [SQLite](https://www.sqlite.org/).

## How to set up a dev environment

1. Clone this repository

2. Install Python packages (create a virtual environment first):

```
pip install -r requirements.txt
```

3. Run database migrations:

```
cd app
flask db upgrade
```

This will create a SQLite database in app/instance/app.db

4. Run Python web app:

```
flask run --debug
```

5. In another terminal, install NPM packages and run the Vite dev server:

```
cd frontend
npm install
npm run dev
```

Now you can open the URL that `npm` prints to the terminal to use the app.

6. Scripts are in the `scripts/` directory. The most useful is `load_csv.py`, which loads match data from a CSV file into the database.

7. Please avoid running the `pull_bjjcompsystem.py` script unless you are actively developing it, as we don't want to stress the IBJJF's servers. Instead, if you want to help develop the app and you need sample data, contact us at [ibjjfrankings on Instagram](https://www.instagram.com/ibjjfrankings/) and we will sort you out.
