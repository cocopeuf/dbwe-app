import sqlalchemy as sa
from flask import request, url_for, abort, jsonify
from app import db
from app.models import DinnerEvent, User
from app.api import bp
from app.api.auth import token_auth
from app.api.errors import bad_request

# API Documentation
# 
# GET /api/dinner_events/<id> - Retrieve details of a specific Dinner Event (only if the user is invited or it's public)
# GET /api/dinner_events - Retrieve a paginated list of Dinner Events the user is invited to or are public
# POST /api/dinner_events - Create a new Dinner Event
# DELETE /api/dinner_events/<id> - Delete an existing Dinner Event (only if the user is the creator)

@bp.route('/dinner_events/<int:id>', methods=['GET'])
@token_auth.login_required
def get_dinner_event(id):
    """Retrieve details of a specific Dinner Event, only if the user is invited or it's public"""
    user = token_auth.current_user()
    event = db.get_or_404(DinnerEvent, id)
    
    if not event.is_public and user not in event.invited and user.id != event.creator_id:
        abort(403)
    
    return event.to_dict()

@bp.route('/dinner_events', methods=['GET'])
@token_auth.login_required
def get_dinner_events():
    """Retrieve a paginated list of Dinner Events the user is invited to or are public"""
    user = token_auth.current_user()
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    query = sa.select(DinnerEvent).where(
        sa.or_(
            DinnerEvent.is_public == True,
            DinnerEvent.invited.any(User.id == user.id),
            DinnerEvent.creator_id == user.id
        )
    )
    return DinnerEvent.to_collection_dict(query, page, per_page, 'api.get_dinner_events')

@bp.route('/dinner_events', methods=['POST'])
@token_auth.login_required
def create_dinner_event():
    """Erstellt ein neues Dinner Event mit optionalen Einladungen per Benutzername"""
    data = request.get_json()
    # Prüfe, ob alle erforderlichen Felder vorhanden sind
    if not data or not all(key in data for key in ['title', 'description', 'external_event_url', 'event_date', 'is_public']):
        return bad_request('Must include title, description, external_event_url, event_date, and is_public fields')
    # Neues DinnerEvent-Objekt erstellen
    event = DinnerEvent()
    event.from_dict(data, new_event=True)
    event.creator_id = token_auth.current_user().id
    # Falls das Event privat ist, verarbeite die eingeladenen Benutzer (Usernamen)
    if not event.is_public and 'invitees' in data:
        for username in data['invitees']:
            user = db.session.scalar(sa.select(User).where(User.username == username))
            if user:
                event.invite_user(user)
    db.session.add(event)
    db.session.commit()
    
    return event.to_dict(), 201, {'Location': url_for('api.get_dinner_event', id=event.id)}


@bp.route('/dinner_events/<int:id>', methods=['DELETE'])
@token_auth.login_required
def delete_dinner_event(id):
    """Delete an existing Dinner Event"""
    event = db.get_or_404(DinnerEvent, id)
    if token_auth.current_user().id != event.creator_id:
        abort(403)
    db.session.delete(event)
    db.session.commit()
    return jsonify({'message': 'Event deleted successfully'}), 200
