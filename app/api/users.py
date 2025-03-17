import sqlalchemy as sa
from sqlalchemy import select, or_, and_
from flask import request, url_for, abort
from app import db
from app.models import User, DinnerEvent
from app.api import bp
from app.api.auth import token_auth
from app.api.errors import bad_request

# API Documentation
# 
# GET /api/users/<id> - Retrieve details of a specific user (von miguelgrinberg übernommen)
# GET /api/users - Retrieve a paginated list of users  (von miguelgrinberg übernommen)
# GET /api/users/<id>/followers - Retrieve a list of a user's followers  (von miguelgrinberg übernommen)
# GET /api/users/<id>/following - Retrieve a list of users the user is following  (von miguelgrinberg übernommen)
# GET /api/users/<id>/dinner_events - Retrieve dinner events the user can see (public or shared with them)
# POST /api/users - Create a new user  (von miguelgrinberg übernommen)
# PUT /api/users/<id> - Update user details (only the user themselves)  (von miguelgrinberg übernommen)

@bp.route('/users/<int:id>', methods=['GET'])
@token_auth.login_required
def get_user(id):
    return db.get_or_404(User, id).to_dict()

@bp.route('/users', methods=['GET'])
@token_auth.login_required
def get_users():
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return User.to_collection_dict(sa.select(User), page, per_page, 'api.get_users')

@bp.route('/users/<int:id>/followers', methods=['GET'])
@token_auth.login_required
def get_followers(id):
    user = db.get_or_404(User, id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return User.to_collection_dict(user.followers.select(), page, per_page, 'api.get_followers', id=id)

@bp.route('/users/<int:id>/following', methods=['GET'])
@token_auth.login_required
def get_following(id):
    user = db.get_or_404(User, id)
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
    return User.to_collection_dict(user.following.select(), page, per_page, 'api.get_following', id=id)

@bp.route('/users', methods=['POST'])
def create_user():
    data = request.get_json()
    if 'username' not in data or 'email' not in data or 'password' not in data:
        return bad_request('must include username, email and password fields')
    if db.session.scalar(sa.select(User).where(
            User.username == data['username'])):
        return bad_request('please use a different username')
    if db.session.scalar(sa.select(User).where(
            User.email == data['email'])):
        return bad_request('please use a different email address')
    user = User()
    user.from_dict(data, new_user=True)
    db.session.add(user)
    db.session.commit()
    return user.to_dict(), 201, {'Location': url_for('api.get_user',
                                                     id=user.id)}

@bp.route('/users/<int:id>', methods=['PUT'])
@token_auth.login_required
def update_user(id):
    if token_auth.current_user().id != id:
        abort(403)
    user = db.get_or_404(User, id)
    data = request.get_json()
    if 'username' in data and data['username'] != user.username and db.session.scalar(sa.select(User).where(User.username == data['username'])):
        return bad_request('please use a different username')
    if 'email' in data and data['email'] != user.email and db.session.scalar(sa.select(User).where(User.email == data['email'])):
        return bad_request('please use a different email address')
    user.from_dict(data, new_user=False)
    db.session.commit()
    return user.to_dict()

# Selbsterstellt, um die DinnerEvents eines Users zu erhalten
@bp.route('/users/<int:id>/dinner_events', methods=['GET'])
@token_auth.login_required
def get_user_dinner_events(id):
    requested_user = db.get_or_404(User, id)
    current_user = token_auth.current_user()

    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 10, type=int), 100)
   # Falls der aktuelle User == requested_user ist → Alle selbst erstellten Events anzeigen
    if current_user.id == requested_user.id:
        query = sa.select(DinnerEvent).where(
            sa.or_(
                # Zeige ALLE Events, die requested_user (User1) erstellt hat
                DinnerEvent.creator_id == requested_user.id,
                # Zeige Events, zu denen requested_user eingeladen ist
                DinnerEvent.invited.any(User.id == requested_user.id)
            )
        )
    else:
        query = sa.select(DinnerEvent).where(
            sa.or_(
            # Öffentliche Events, die requested_user erstellt hat
            sa.and_(
                DinnerEvent.is_public == True,
                DinnerEvent.creator_id == requested_user.id
            ),
            # Öffentliche Events, zu denen requested_user eingeladen ist
            sa.and_(
                DinnerEvent.is_public == True,
                DinnerEvent.invited.any(User.id == requested_user.id)
            ),
            # Private Events, zu denen sowohl current_user als auch requested_user eingeladen sind
            sa.and_(
                DinnerEvent.is_public == False,
                DinnerEvent.invited.any(User.id == current_user.id),
                DinnerEvent.invited.any(User.id == requested_user.id)
            ),
            # Private Events, die current_user erstellt hat, aber requested_user ist eingeladen
            sa.and_(
                DinnerEvent.is_public == False,
                DinnerEvent.creator_id == current_user.id,
                DinnerEvent.invited.any(User.id == requested_user.id)
            ),
            # Private Events, die requested_user erstellt hat, aber current_user ist eingeladen
            sa.and_(
                DinnerEvent.is_public == False,
                DinnerEvent.creator_id == requested_user.id,
                DinnerEvent.invited.any(User.id == current_user.id)
            )
        )
    )

    return DinnerEvent.to_collection_dict(query, page, per_page, 'api.get_user_dinner_events', id=id)
