import os
from flask import Flask, send_from_directory, request, jsonify
from extensions import db, migrate
from models import CurrentRating, Athlete

app = Flask(__name__, static_folder='frontend/dist', static_url_path='/')
if os.getenv('RENDER'):
    app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'

db.init_app(app)
migrate.init_app(app, db)

@app.route('/')
def index():
    return send_from_directory(app.static_folder, 'index.html')

@app.route('/api/top')
def top():
    gender = request.args.get('gender')
    age = request.args.get('age')
    belt = request.args.get('belt')
    gi = request.args.get('gi')
    name = request.args.get('name')

    if not all([gender, age, belt, gi]):
        return jsonify({"error": "Missing mandatory query parameters"}), 400
    
    gi = gi.lower() == 'true'

    query = db.session.query(CurrentRating).join(Athlete).filter(
        CurrentRating.gender == gender,
        CurrentRating.age == age,
        CurrentRating.belt == belt,
        CurrentRating.gi == gi
    )

    if name:
        query = query.filter(Athlete.name.ilike(f'%{name}%'))

    results = query.order_by(CurrentRating.rating.desc(), CurrentRating.match_happened_at.desc()).limit(30).all()

    response = []
    previous_rating = None
    rank = 0
    for index, result in enumerate(results):
        rounded_rating = round(result.rating)
        if rounded_rating != previous_rating:
            rank = index + 1
        response.append({
            "rank": rank,
            "name": result.athlete.name,
            "rating": rounded_rating
        })
        previous_rating = rounded_rating

    return jsonify(response)

if __name__ == '__main__':
    app.run()
