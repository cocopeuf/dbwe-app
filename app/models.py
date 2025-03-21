from datetime import datetime, timezone, timedelta
from hashlib import md5
import json
import secrets
from time import time
from typing import Optional
import sqlalchemy as sa
import sqlalchemy.orm as so
from flask import current_app, url_for
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
import jwt
import redis
import rq
from app import db, login
from app.search import add_to_index, remove_from_index, query_index
from sqlalchemy import Boolean

# Teilweise von miguelgrinberg übernommen, eigene Anpassungen sind mit "Selbstergstellt" dokumentiert

class SearchableMixin:
    @classmethod
    def search(cls, expression, page, per_page):
        ids, total = query_index(cls.__tablename__, expression, page, per_page)
        if total == 0:
            return [], 0
        when = []
        for i in range(len(ids)):
            when.append((ids[i], i))
        query = sa.select(cls).where(cls.id.in_(ids)).order_by(
            db.case(*when, value=cls.id))
        return db.session.scalars(query), total

    @classmethod
    def before_commit(cls, session):
        session._changes = {
            'add': list(session.new),
            'update': list(session.dirty),
            'delete': list(session.deleted)
        }

    @classmethod
    def after_commit(cls, session):
        for obj in session._changes['add']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['update']:
            if isinstance(obj, SearchableMixin):
                add_to_index(obj.__tablename__, obj)
        for obj in session._changes['delete']:
            if isinstance(obj, SearchableMixin):
                remove_from_index(obj.__tablename__, obj)
        session._changes = None

    @classmethod
    def reindex(cls):
        for obj in db.session.scalars(sa.select(cls)):
            add_to_index(cls.__tablename__, obj)


db.event.listen(db.session, 'before_commit', SearchableMixin.before_commit)
db.event.listen(db.session, 'after_commit', SearchableMixin.after_commit)


class PaginatedAPIMixin(object):
    @staticmethod
    def to_collection_dict(query, page, per_page, endpoint, **kwargs):
        resources = db.paginate(query, page=page, per_page=per_page,
                                error_out=False)
        data = {
            'items': [item.to_dict() for item in resources.items],
            '_meta': {
                'page': page,
                'per_page': per_page,
                'total_pages': resources.pages,
                'total_items': resources.total
            },
            '_links': {
                'self': url_for(endpoint, page=page, per_page=per_page,
                                **kwargs),
                'next': url_for(endpoint, page=page + 1, per_page=per_page,
                                **kwargs) if resources.has_next else None,
                'prev': url_for(endpoint, page=page - 1, per_page=per_page,
                                **kwargs) if resources.has_prev else None
            }
        }
        return data


followers = sa.Table(
    'followers',
    db.metadata,
    sa.Column('follower_id', sa.Integer, sa.ForeignKey('user.id'),
              primary_key=True),
    sa.Column('followed_id', sa.Integer, sa.ForeignKey('user.id'),
              primary_key=True)
)

#Selbstergstellt
dinner_event_invites = sa.Table(
    'dinner_event_invites',
    db.metadata,
    sa.Column('dinner_event_id', sa.Integer, sa.ForeignKey('dinnerevent.id'), primary_key=True),
    sa.Column('user_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True)
)
#Selbstergstellt
dinner_event_pending = sa.Table(
    'dinner_event_pending',
    db.metadata,
    sa.Column('dinner_event_id', sa.Integer, sa.ForeignKey('dinnerevent.id'), primary_key=True),
    sa.Column('user_id', sa.Integer, sa.ForeignKey('user.id'), primary_key=True)
)
#Selbstergstellt
class DinnerEventRsvp(db.Model):
    __tablename__ = 'dinner_event_rsvps'
    dinner_event_id = db.Column(db.Integer, db.ForeignKey('dinnerevent.id'), primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    status = db.Column(sa.String(16), nullable=False, server_default='no_response')
    user = db.relationship('User', back_populates='dinner_event_rsvps')
    event = db.relationship('DinnerEvent', back_populates='rsvps')

# Erweitert um dinner_event_rsvps
class User(PaginatedAPIMixin, UserMixin, db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    username: so.Mapped[str] = so.mapped_column(sa.String(64), index=True,
                                                unique=True)
    email: so.Mapped[str] = so.mapped_column(sa.String(120), index=True,
                                             unique=True)
    password_hash: so.Mapped[Optional[str]] = so.mapped_column(sa.String(256))
    about_me: so.Mapped[Optional[str]] = so.mapped_column(sa.String(140))
    last_seen: so.Mapped[Optional[datetime]] = so.mapped_column(
        default=lambda: datetime.now(timezone.utc))
    last_message_read_time: so.Mapped[Optional[datetime]]
    token: so.Mapped[Optional[str]] = so.mapped_column(
        sa.String(32), index=True, unique=True)
    token_expiration: so.Mapped[Optional[datetime]]

    following: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.follower_id == id),
        secondaryjoin=(followers.c.followed_id == id),
        back_populates='followers')
    followers: so.WriteOnlyMapped['User'] = so.relationship(
        secondary=followers, primaryjoin=(followers.c.followed_id == id),
        secondaryjoin=(followers.c.follower_id == id),
        back_populates='following')
    notifications: so.WriteOnlyMapped['Notification'] = so.relationship(
        back_populates='user')
    tasks: so.WriteOnlyMapped['Task'] = so.relationship(back_populates='user')
    dinner_event_rsvps = db.relationship('DinnerEventRsvp', back_populates='user')

    def __repr__(self):
        return '<User {}>'.format(self.username)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return f'https://www.gravatar.com/avatar/{digest}?d=identicon&s={size}'

    def follow(self, user):
        if not self.is_following(user):
            self.following.add(user)

    def unfollow(self, user):
        if self.is_following(user):
            self.following.remove(user)

    def is_following(self, user):
        query = self.following.select().where(User.id == user.id)
        return db.session.scalar(query) is not None

    def followers_count(self):
        query = sa.select(sa.func.count()).select_from(
            self.followers.select().subquery())
        return db.session.scalar(query)

    def following_count(self):
        query = sa.select(sa.func.count()).select_from(
            self.following.select().subquery())
        return db.session.scalar(query)

    def get_reset_password_token(self, expires_in=600):
        return jwt.encode(
            {'reset_password': self.id, 'exp': time() + expires_in},
            current_app.config['SECRET_KEY'], algorithm='HS256')

    @staticmethod
    def verify_reset_password_token(token):
        try:
            id = jwt.decode(token, current_app.config['SECRET_KEY'],
                            algorithms=['HS256'])['reset_password']
        except Exception:
            return
        return db.session.get(User, id)

    def unread_message_count(self):
        last_read_time = self.last_message_read_time or datetime(1900, 1, 1)
        query = sa.select(Message).where(Message.recipient == self,
                                         Message.timestamp > last_read_time)
        return db.session.scalar(sa.select(sa.func.count()).select_from(
            query.subquery()))

    def add_notification(self, name, data):
        n = Notification(name=name, payload_json=json.dumps(data), user=self)
        db.session.add(n)
        return n

    def launch_task(self, name, description, *args, **kwargs):
        rq_job = current_app.task_queue.enqueue(f'app.tasks.{name}', self.id,
                                                *args, **kwargs)
        task = Task(id=rq_job.get_id(), name=name, description=description,
                    user=self)
        db.session.add(task)
        return task

    def get_tasks_in_progress(self):
        query = self.tasks.select().where(Task.complete == False)
        return db.session.scalars(query)

    def get_task_in_progress(self, name):
        query = self.tasks.select().where(Task.name == name,
                                          Task.complete == False)
        return db.session.scalar(query)

    def to_dict(self, include_email=False):
        data = {
            'id': self.id,
            'username': self.username,
            'last_seen': self.last_seen.replace(
                tzinfo=timezone.utc).isoformat(),
            'about_me': self.about_me,
            'follower_count': self.followers_count(),
            'following_count': self.following_count(),
            '_links': {
                'self': url_for('api.get_user', id=self.id),
                'followers': url_for('api.get_followers', id=self.id),
                'following': url_for('api.get_following', id=self.id),
                'avatar': self.avatar(128)
            }
        }
        if include_email:
            data['email'] = self.email
        return data

    def from_dict(self, data, new_user=False):
        for field in ['username', 'email', 'about_me']:
            if field in data:
                setattr(self, field, data[field])
        if new_user and 'password' in data:
            self.set_password(data['password'])

    def get_token(self, expires_in=3600):
        now = datetime.now(timezone.utc)
        if self.token and self.token_expiration.replace(
                tzinfo=timezone.utc) > now + timedelta(seconds=60):
            return self.token
        self.token = secrets.token_hex(16)
        self.token_expiration = now + timedelta(seconds=expires_in)
        db.session.add(self)
        return self.token

    def revoke_token(self):
        self.token_expiration = datetime.now(timezone.utc) - timedelta(
            seconds=1)

    @staticmethod
    def check_token(token):
        user = db.session.scalar(sa.select(User).where(User.token == token))
        if user is None or user.token_expiration.replace(
                tzinfo=timezone.utc) < datetime.now(timezone.utc):
            return None
        return user


@login.user_loader
def load_user(id):
    return db.session.get(User, int(id))


class Notification(db.Model):
    id: so.Mapped[int] = so.mapped_column(primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id),
                                               index=True)
    timestamp: so.Mapped[float] = so.mapped_column(index=True, default=time)
    payload_json: so.Mapped[str] = so.mapped_column(sa.Text)

    user: so.Mapped[User] = so.relationship(back_populates='notifications')

    def get_data(self):
        return json.loads(str(self.payload_json))

class Task(db.Model):
    id: so.Mapped[str] = so.mapped_column(sa.String(36), primary_key=True)
    name: so.Mapped[str] = so.mapped_column(sa.String(128), index=True)
    description: so.Mapped[Optional[str]] = so.mapped_column(sa.String(128))
    user_id: so.Mapped[int] = so.mapped_column(sa.ForeignKey(User.id))
    complete: so.Mapped[bool] = so.mapped_column(default=False)

    user: so.Mapped[User] = so.relationship(back_populates='tasks')

    def get_rq_job(self):
        try:
            rq_job = rq.job.Job.fetch(self.id, connection=current_app.redis)
        except (redis.exceptions.RedisError, rq.exceptions.NoSuchJobError):
            return None
        return rq_job

    def get_progress(self):
        job = self.get_rq_job()
        return job.meta.get('progress', 0) if job is not None else 100

#Selbstergstellt
class DinnerEvent(PaginatedAPIMixin, db.Model):
    __tablename__ = 'dinnerevent'
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(sa.String(128), nullable=False)
    description = db.Column(sa.Text)
    external_event_url = db.Column(sa.String(256), nullable=False)
    event_date = db.Column(sa.DateTime, nullable=False, server_default=sa.text('CURRENT_TIMESTAMP'))
    creator_id = db.Column(sa.Integer, sa.ForeignKey('user.id'), nullable=False)
    is_public = db.Column(Boolean, nullable=False, default=True, server_default=sa.true())  # NEW FIELD
    # relationships
    creator = db.relationship('User', backref='created_dinner_events')
    invited = db.relationship(
        'User',
        secondary=dinner_event_invites,
        primaryjoin="dinner_event_invites.c.dinner_event_id == DinnerEvent.id",
        secondaryjoin="dinner_event_invites.c.user_id == User.id",
        backref='invited_dinner_events'
    )
    # NEW: pending opt-ins relationship for public events
    pending_opt_ins = db.relationship(
        'User',
        secondary=dinner_event_pending,
        backref='pending_dinner_events'
    )
    rsvps = db.relationship('DinnerEventRsvp', back_populates='event', cascade='all, delete-orphan')  # Add cascade delete
    comments = db.relationship('Comment', back_populates='event', cascade='all, delete-orphan')

    def invite_user(self, user):
        if user not in self.invited:
            self.invited.append(user)
            
    def uninvite_user(self, user):
        if user in self.invited:
            self.invited.remove(user)
            # Remove existing RSVP, if any, for this user
            rsvp = next((r for r in self.rsvps if r.user_id == user.id), None)
            if rsvp:
                db.session.delete(rsvp)

    # New: RSVP helper method
    def rsvp(self, user, status):
        existing = next((r for r in self.rsvps if r.user_id == user.id), None)
        if existing:
            existing.status = status
        else:
            new_rsvp = DinnerEventRsvp(user=user, status=status)
            self.rsvps.append(new_rsvp)
    # Erweiterung für  RESTful API  Dinner Events
    def to_dict(self):
        return {
            'id': self.id,
            'title': self.title,
            'description': self.description,
            'external_event_url': self.external_event_url,
            'event_date': self.event_date.isoformat(),
            'creator_id': self.creator_id,
            'is_public': self.is_public,
            'invited': [user.id for user in self.invited],
            'pending_opt_ins': [user.id for user in self.pending_opt_ins],
            'rsvps': [{'user_id': rsvp.user_id, 'status': rsvp.status} for rsvp in self.rsvps],
            'comments': [{'id': comment.id, 'body': comment.body, 'timestamp': comment.timestamp.isoformat(), 'user_id': comment.user_id} for comment in self.comments]
        }
    
    def from_dict(self, data, new_event=False):
        """Setzt Event-Daten aus einem Dictionary (z. B. aus einem API-Request)."""
        for field in ['title', 'description', 'external_event_url', 'event_date', 'is_public']:
            if field in data:
                setattr(self, field, data[field])
        if new_event:
            self.creator_id = data.get('creator_id')

        # Falls `invitees` (Liste von Usernamen) übergeben wurde, Nutzer hinzufügen
        if 'invitees' in data:
            from app.models import User  # Import hier notwendig, um zyklische Imports zu vermeiden
            self.invited.clear()
            for username in data['invitees']:
                user = db.session.scalar(sa.select(User).where(User.username == username))
                if user:
                    self.invite_user(user)

# Angepassung für Dinner Events
class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    body = db.Column(db.Text, nullable=False)
    timestamp = db.Column(sa.DateTime, default=lambda: datetime.now(timezone.utc), index=True)
    user_id = db.Column(db.Integer, sa.ForeignKey('user.id'), nullable=False)
    event_id = db.Column(db.Integer, sa.ForeignKey('dinnerevent.id'), nullable=False)
    user = db.relationship('User', backref='comments')
    event = db.relationship('DinnerEvent', back_populates='comments')

    def __repr__(self):
        return f'<Comment {self.body[:20]}>'

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    recipient_id = db.Column(db.Integer, db.ForeignKey('user.id'), index=True)
    body = db.Column(db.String(500))
    timestamp = db.Column(db.DateTime, index=True, default=lambda: datetime.now(timezone.utc))
    # Relationships (adjust backrefs as needed)
    author = db.relationship('User', foreign_keys=[sender_id], backref='messages_sent')
    recipient = db.relationship('User', foreign_keys=[recipient_id], backref='messages_received')
    
    def __repr__(self):
        return f'<Message {self.body[:20]}>'
