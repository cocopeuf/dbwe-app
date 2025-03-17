import os
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask import jsonify
from app import create_app, db
from app.models import User, Message, Notification, Task, DinnerEvent

app = create_app()
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///db.sqlite3')


@app.route('/api/dinner_events', methods=['GET'])
def get_dinner_events():
    events = db.session.scalars(sa.select(DinnerEvent)).all()
    return jsonify([event.to_dict() for event in events])


@app.shell_context_processor
def make_shell_context():
    return {'sa': sa, 'so': so, 'db': db, 'User': User, 'DinnerEvent': DinnerEvent, 'Message': Message, 'Notification': Notification, 'Task': Task}
