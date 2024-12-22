import os
from datetime import datetime
from sqlalchemy.sql import text
from flask import Flask, send_from_directory, request, jsonify
from extensions import db, migrate
from models import CurrentRating, Athlete, MatchParticipant, Division, Match, Event
from routes.top import top_route
from routes.matches import matches_route

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/')
if os.getenv('DATABASE_URL'):
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'

db.init_app(app)
migrate.init_app(app, db)

@app.route('/', defaults={'path': ''})
@app.route('/<path:path>')
def index(path):
    return send_from_directory(app.static_folder, 'index.html')

RATINGS_PAGE_SIZE = 30
MATCH_PAGE_SIZE = 12

app.register_blueprint(top_route)
app.register_blueprint(matches_route)

application = app

if __name__ == '__main__':
    app.run()
