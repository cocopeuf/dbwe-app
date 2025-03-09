from datetime import datetime, timezone, date
import json
import sqlalchemy as sa
from flask import render_template, flash, redirect, url_for, request, g, current_app, jsonify
from flask_login import current_user, login_required
from flask_babel import _, get_locale
from sqlalchemy.orm import joinedload

from app import db
from app.main import bp
from app.main.forms import EditProfileForm, EmptyForm, MessageForm, DinnerEventForm, CommentForm  
from app.models import User, Message, Notification, DinnerEvent, Comment

# --- Helper-Funktionen ---

def get_user_by_username(username):
    return db.first_or_404(sa.select(User).where(User.username == username))

def process_invites(event, invite_str):
    """Verarbeitet die Komma-separierte Invite-Liste für einen DinnerEvent."""
    invitees = [i.strip() for i in invite_str.split(',') if i.strip()]
    for identifier in invitees:
        user = db.session.scalar(
            sa.select(User).where(sa.or_(User.username == identifier, User.email == identifier))
        )
        if user is not None and user not in event.invited:
            event.invite_user(user)
            user.add_notification('dinner_event_invite', {
                'message': _('You have been invited to the event: %(event_title)s', event_title=event.title),
                'event_id': event.id
            })

# --- Vor-Anfrage ---
@bp.before_app_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.now(timezone.utc)
        db.session.commit()
    g.locale = str(get_locale())

# --- Startseiten ---
@bp.route('/', methods=['GET'])
@bp.route('/index', methods=['GET'])
@login_required
def index():
    now = datetime.now()
    upcoming_events = db.session.scalars(
        sa.select(DinnerEvent)
          .where(DinnerEvent.event_date >= now)
          .order_by(DinnerEvent.event_date.asc())
    ).all()
    created_upcoming_events = db.session.scalars(
        sa.select(DinnerEvent)
          .where(DinnerEvent.creator_id == current_user.id, DinnerEvent.event_date >= now)
          .order_by(DinnerEvent.event_date.asc())
    ).all()
    created_previous_events = db.session.scalars(
        sa.select(DinnerEvent)
          .where(DinnerEvent.creator_id == current_user.id, DinnerEvent.event_date < now)
          .order_by(DinnerEvent.event_date.desc())
    ).all()
    need_accept_optins_events = [event for event in created_upcoming_events if event.pending_opt_ins]
    return render_template('index.html', title=_('Home'),
                           upcoming_events=upcoming_events,
                           created_upcoming_events=created_upcoming_events,
                           created_previous_events=created_previous_events,
                           need_accept_optins_events=need_accept_optins_events)

@bp.route('/explore')
def explore():
    now = datetime.now()
    upcoming = db.session.scalars(
        sa.select(DinnerEvent)
          .where(DinnerEvent.event_date >= now, DinnerEvent.is_public == True)
          .order_by(DinnerEvent.event_date.asc())
    ).all()
    previous = db.session.scalars(
        sa.select(DinnerEvent)
          .where(DinnerEvent.event_date < now, DinnerEvent.is_public == True)
          .order_by(DinnerEvent.event_date.desc())
    ).all()
    description = ""
    if not current_user.is_authenticated:
        description = ("Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod "
                       "tempor incididunt ut labore et dolore magna aliqua. Please <a href='{}'>login</a> "
                       "to see more that Webapp.").format(url_for('auth.login'))
    return render_template('explore.html', title=_('Explore'), upcoming=upcoming, previous=previous, description=description)

# --- User-bezogene Routen ---
@bp.route('/user/<username>')
@login_required
def user(username):
    user_obj = get_user_by_username(username)
    form = EmptyForm()
    event_history = db.session.scalars(
        sa.select(DinnerEvent).where(
            sa.or_(
                DinnerEvent.is_public == True,
                DinnerEvent.creator_id == user_obj.id,
                DinnerEvent.invited.any(User.id == user_obj.id)
            )
        ).order_by(DinnerEvent.event_date.desc())
    ).all()
    return render_template('user.html', user=user_obj, form=form, event_history=event_history)

@bp.route('/user/<username>/popup', methods=['GET', 'POST'])
@login_required
def user_popup(username):
    user_obj = get_user_by_username(username)
    form = EditProfileForm(original_username=current_user.username)
    if form.validate_on_submit():
        current_user.about_me = form.about_me.data
        db.session.commit()
        flash(_('Your changes have been saved.'))
        return redirect(url_for('main.edit_profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', title=_('Edit Profile'), form=form)

@bp.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user_obj = db.session.scalar(sa.select(User).where(User.username == username))
        if user_obj is None:
            flash(_('User %(username)s not found.', username=username))
        elif user_obj == current_user:
            flash(_('You cannot follow yourself!'))
        else:
            current_user.follow(user_obj)
            db.session.commit()
            flash(_('You are following %(username)s!', username=username))
        return redirect(url_for('main.user', username=username))
    return redirect(url_for('main.index'))

@bp.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user_obj = db.session.scalar(sa.select(User).where(User.username == username))
        if user_obj is None:
            flash(_('User %(username)s not found.', username=username))
        elif user_obj == current_user:
            flash(_('You cannot unfollow yourself!'))
        else:
            current_user.unfollow(user_obj)
            db.session.commit()
            flash(_('You are not following %(username)s.', username=username))
        return redirect(url_for('main.user', username=username))
    return redirect(url_for('main.index'))

@bp.route('/send_message/<recipient>', methods=['GET', 'POST'])
@login_required
def send_message(recipient):
    user_obj = get_user_by_username(recipient)
    form = MessageForm()
    if form.validate_on_submit():
        msg = Message(author=current_user, recipient=user_obj,
                      body=form.message.data)
        db.session.add(msg)
        user_obj.add_notification('unread_message_count', user_obj.unread_message_count())
        db.session.commit()
        flash(_('Your message has been sent.'))
        return redirect(url_for('main.user', username=recipient))
    return render_template('send_message.html', title=_('Send Message'),
                           form=form, recipient=recipient)

@bp.route('/messages')
@login_required
def messages():
    current_user.last_message_read_time = datetime.now(timezone.utc)
    current_user.add_notification('unread_message_count', 0)
    db.session.commit()
    # Sortierung der empfangenen Nachrichten
    messages_list = sorted(current_user.messages_received, key=lambda m: m.timestamp, reverse=True)
    
    event_notif = ["event_created", "dinner_event_invite", "rsvp_updated", "uninvited"]
    history_query = current_user.notifications.select().where(
        Notification.name.in_(event_notif)
    ).order_by(Notification.timestamp.desc())
    history = list(db.session.scalars(history_query))
    
    return render_template('messages.html', messages=messages_list,
                           next_url=None, prev_url=None, history=history)

@bp.route('/notifications')
@login_required
def notifications():
    since = request.args.get('since', 0.0, type=float)
    query = current_user.notifications.select().where(
        Notification.timestamp > since).order_by(Notification.timestamp.asc())
    notifications = db.session.scalars(query)
    return [{
        'name': n.name,
        'data': n.get_data(),
        'timestamp': n.timestamp
    } for n in notifications]

# --- Dinner Event Routen ---
@bp.route('/dinner_event/create', methods=['GET', 'POST'])
@login_required
def create_dinner_event():
    form = DinnerEventForm()
    if form.validate_on_submit():
        event = DinnerEvent(
            title=form.title.data,
            description=form.description.data,
            external_event_url=form.external_event_url.data,
            event_date=form.date.data,
            creator=current_user,
            is_public=form.is_public.data
        )
        db.session.add(event)
        db.session.commit()  # Event speichern, um eine ID zu erhalten
        if form.invite.data and not form.is_public.data:
            process_invites(event, form.invite.data)
        # Notification für Event-Erstellung
        current_user.add_notification('event_created', {
            'message': _('You created the event: %(event_title)s', event_title=event.title),
            'event_id': event.id,
            'event_title': event.title
        })
        db.session.commit()
        flash(_('Dinner event created successfully!'))
        return redirect(url_for('main.dinner_event_detail', event_id=event.id))
    return render_template('create_dinner_event.html', title=_('Create Dinner Event'), form=form)

@bp.route('/dinner_event/<int:event_id>')
@login_required
def dinner_event_detail(event_id):
    q = sa.select(DinnerEvent).options(
            joinedload(DinnerEvent.creator),
            joinedload(DinnerEvent.invited),
            joinedload(DinnerEvent.rsvps),
            joinedload(DinnerEvent.comments).joinedload(Comment.user)
        ).where(DinnerEvent.id == event_id)
    event = db.session.scalar(q)
    if event is None:
        flash(_('Dinner event not found.'))
        return redirect(url_for('main.index'))
    if not event.is_public and event.creator != current_user and current_user not in event.invited:
        flash(_('You are not allowed to view this dinner event.'))
        return redirect(url_for('main.dinner_events_list'))
    user_rsvp = next((r for r in event.rsvps if r.user_id == current_user.id), None)
    pending_opt_ins = [user for user in event.invited if user not in event.rsvps]
    comment_form = CommentForm()
    return render_template('dinner_event_detail.html', event=event, user_rsvp=user_rsvp,
                           comment_form=comment_form, pending_opt_ins=pending_opt_ins)

@bp.route('/dinner_event/<int:event_id>/comment', methods=['POST'])
@login_required
def comment_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None or (current_user not in event.invited and event.creator != current_user):
        flash(_('You are not allowed to comment on this dinner event.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    form = CommentForm()
    if form.validate_on_submit():
        comment = Comment(body=form.body.data, user=current_user, event=event)
        db.session.add(comment)
        db.session.commit()
        flash(_('Your comment has been posted.'))
    else:
        flash(_('Failed to post comment.'))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/comment/<int:comment_id>/delete', methods=['POST'])
@login_required
def delete_comment(comment_id):
    comment = db.session.get(Comment, comment_id)
    if comment is None or comment.user != current_user:
        flash(_('You are not allowed to delete this comment.'))
        return redirect(url_for('main.dinner_event_detail', event_id=comment.event_id if comment else 0))
    event_id = comment.event_id
    db.session.delete(comment)
    db.session.commit()
    flash(_('Your comment has been deleted.'))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_event/<int:event_id>/invite/<identifier>', methods=['POST'])
@login_required
def invite_to_dinner_event(event_id, identifier):
    event = db.session.get(DinnerEvent, event_id)
    if event is None or event.creator != current_user:
        flash(_('You are not allowed to invite users to this dinner event.'))
        return redirect(url_for('main.index'))
    user_obj = db.session.scalar(
        sa.select(User).where(sa.or_(User.username == identifier, User.email == identifier))
    )
    if user_obj is None:
        flash(_('User %(identifier)s not found.', identifier=identifier))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.invite_user(user_obj)
    user_obj.add_notification('dinner_event_invite', {
        'message': _('You have been invited to the event: %(event_title)s', event_title=event.title),
        'event_id': event.id,
        'event_title': event.title
    })
    msg_body = _('%(creator)s invited you to "<a href="%(event_link)s">%(event_title)s</a>".',
                 creator=event.creator.username,
                 event_title=event.title,
                 event_link=url_for('main.dinner_event_detail', event_id=event.id, _external=True))
    msg = Message(author=current_user, recipient=user_obj, body=msg_body)
    db.session.add(msg)
    db.session.commit()
    flash(_('User %(identifier)s has been invited.', identifier=identifier))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_event/<int:event_id>/uninvite/<identifier>', methods=['POST'], endpoint='uninvite_to_dinner_event')
@login_required
def uninvite_to_dinner_event(event_id, identifier):
    event = db.session.get(DinnerEvent, event_id)
    if event is None or event.creator != current_user:
        flash(_('You are not allowed to uninvite users from this dinner event.'))
        return redirect(url_for('main.index'))
    user_obj = db.session.scalar(
        sa.select(User).where(sa.or_(User.username == identifier, User.email == identifier))
    )
    if user_obj is None or user_obj not in event.invited:
        flash(_('User %(identifier)s is not invited.', identifier=identifier))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.uninvite_user(user_obj)
    user_obj.add_notification('uninvited', {
        'message': _('You have been uninvited from the event: %(event_title)s', event_title=event.title),
        'event_id': event.id,
        'event_title': event.title
    })
    notifications_query = sa.select(Notification).where(
        Notification.user_id == user_obj.id,
        Notification.name == 'dinner_event_invite',
        Notification.payload_json.contains(f'"event_id": {event.id}')
    )
    notifications = db.session.scalars(notifications_query).all()
    for notification in notifications:
        db.session.delete(notification)
    db.session.commit()
    flash(_('User %(identifier)s has been uninvited.', identifier=identifier))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_events')
@login_required
def dinner_events_list():
    q = sa.select(DinnerEvent).options(
        joinedload(DinnerEvent.creator),
        joinedload(DinnerEvent.invited),
        joinedload(DinnerEvent.pending_opt_ins)
    ).where(
        sa.or_(
            DinnerEvent.creator_id == current_user.id,
            DinnerEvent.invited.any(User.id == current_user.id),
            DinnerEvent.pending_opt_ins.any(User.id == current_user.id)
        )
    ).order_by(DinnerEvent.id.desc())
    events = db.session.execute(q).unique().scalars().all()
    return render_template('dinner_events_list.html', title=_('Dinner Events'), events=events)

@bp.route('/edit_dinner_event/<int:event_id>', methods=['GET', 'POST'])
@login_required
def edit_dinner_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None or event.creator != current_user:
        flash(_('You are not allowed to edit this dinner event.'))
        return redirect(url_for('main.dinner_events_list'))
    form = DinnerEventForm(obj=event)
    if request.method == 'GET':
        form.date.data = event.event_date.strftime('%Y-%m-%dT%H:%M')
        form.prefill_invite(event.invited)
    if form.validate_on_submit():
        event.title = form.title.data
        event.description = form.description.data
        event.external_event_url = form.external_event_url.data
        event.event_date = form.date.data
        event.is_public = form.is_public.data
        if form.invite.data and not form.is_public.data:
            process_invites(event, form.invite.data)
        db.session.commit()
        flash(_('Dinner event updated.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event.id))
    # Falls form.date.data als String vorliegt, in ein datetime umwandeln
    if isinstance(form.date.data, str):
        form.date.data = datetime.strptime(form.date.data, '%Y-%m-%dT%H:%M')
    return render_template('edit_dinner_event.html', title=_('Edit Dinner Event'), form=form, event=event)

@bp.route('/upcoming_events')
@login_required
def upcoming_events():
    all_events = db.session.scalars(
        sa.select(DinnerEvent)
          .where(sa.func.date(DinnerEvent.event_date) >= date.today())
          .order_by(DinnerEvent.event_date.asc())
    ).all()
    events = [event for event in all_events if event.is_public or current_user in event.invited]
    return render_template('upcoming_events.html', title=_('Upcoming Events'), events=events)

# --- Dinner Event Opt-In ---
@bp.route('/dinner_event/<int:event_id>/opt_in', methods=['POST'])
@login_required
def opt_in_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None or not event.is_public or current_user in event.pending_opt_ins:
        flash(_('You cannot opt-in to this event.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.pending_opt_ins.append(current_user)
    db.session.commit()
    flash(_('You have opted-in to the event. The creator will review your request.'))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_event/<int:event_id>/accept_opt_in/<int:user_id>', methods=['POST'])
@login_required
def accept_opt_in(event_id, user_id):
    event = db.session.get(DinnerEvent, event_id)
    user_obj = db.session.get(User, user_id)
    if event is None or user_obj is None or event.creator != current_user:
        flash(_('You are not allowed to accept opt-ins for this dinner event.'))
        return redirect(url_for('main.index'))
    if user_obj in event.pending_opt_ins:
        event.pending_opt_ins.remove(user_obj)
        if user_obj not in event.invited:
            event.invite_user(user_obj)
        db.session.commit()
        flash(_('User %(username)s has been added to the event.', username=user_obj.username))
    else:
        flash(_('User %(username)s is not pending opt-in.', username=user_obj.username))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_event/<int:event_id>/decline_opt_in/<int:user_id>', methods=['POST'])
@login_required
def decline_opt_in(event_id, user_id):
    event = db.session.get(DinnerEvent, event_id)
    user_obj = db.session.get(User, user_id)
    if event is None or user_obj is None or event.creator != current_user:
        flash(_('You are not allowed to modify opt-ins for this dinner event.'))
        return redirect(url_for('main.index'))
    if user_obj in event.pending_opt_ins:
        event.pending_opt_ins.remove(user_obj)
        db.session.commit()
        flash(_('User %(username)s opt-in has been declined.', username=user_obj.username))
    else:
        flash(_('User %(username)s is not pending opt-in.', username=user_obj.username))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_event/<int:event_id>/rsvp', methods=['POST'])
@login_required
def rsvp_dinner_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None:
        flash(_('Dinner event not found.'))
        return redirect(url_for('main.index'))
    if current_user not in event.invited and event.creator != current_user:
        flash(_('You are not invited to RSVP this dinner event.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    rsvp_choice = request.form.get('rsvp')
    if rsvp_choice not in ['accepted', 'declined']:
        flash(_('Invalid RSVP choice.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.rsvp(current_user, rsvp_choice)
    current_user.add_notification('rsvp_updated', {
        'message': _('Your RSVP for event: %(event_title)s has been updated', event_title=event.title),
        'event_id': event.id,
        'event_title': event.title,
        'status': rsvp_choice
    })
    msg_body = _('%(user)s has updated their RSVP to "%(status)s" for your event "<a href="%(event_link)s">%(event_title)s</a>".',
                 user=current_user.username,
                 status=rsvp_choice,
                 event_title=event.title,
                 event_link=url_for('main.dinner_event_detail', event_id=event.id, _external=True))
    msg = Message(author=current_user, recipient=event.creator, body=msg_body)
    db.session.add(msg)
    db.session.commit()
    flash(_('Your RSVP has been recorded as %(status)s.', status=rsvp_choice))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/calendar')
@login_required
def event_calendar():
    all_events = db.session.scalars(sa.select(DinnerEvent)).all()
    created_events = [e for e in all_events if e.creator == current_user]
    invited_events = [e for e in all_events if e.creator != current_user and current_user in e.invited]
    rsvp_events = [e for e in invited_events if any(r.user_id == current_user.id and r.status != 'no_response' for r in e.rsvps)]
    invited_only = [e for e in invited_events if e not in rsvp_events]

    events_list = []
    for event in created_events:
        events_list.append({
            'title': event.title,
            'start': event.event_date.isoformat(),
            'color': '#007bff',  # blue
            'allDay': True,
            'url': url_for('main.dinner_event_detail', event_id=event.id)
        })
    for event in invited_only:
        events_list.append({
            'title': event.title,
            'start': event.event_date.isoformat(),
            'color': '#28a745',  # green
            'allDay': True,
            'url': url_for('main.dinner_event_detail', event_id=event.id)
        })
    for event in rsvp_events:
        events_list.append({
            'title': event.title,
            'start': event.event_date.isoformat(),
            'color': '#6f42c1',  # violet
            'allDay': True,
            'url': url_for('main.dinner_event_detail', event_id=event.id)
        })
    return render_template('event_calendar.html', events=events_list)

@bp.route('/dinner_event/<int:event_id>/delete', methods=['POST'])
@login_required
def delete_dinner_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None:
        flash(_('Dinner event not found.'))
        return redirect(url_for('main.dinner_events_list'))
    if event.creator != current_user:
        flash(_('You are not allowed to delete this dinner event.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    db.session.delete(event)
    db.session.commit()
    flash(_('Dinner event deleted successfully.'))
    return redirect(url_for('main.dinner_events_list'))

@bp.route('/delete_message/<int:message_id>', methods=['POST'])
@login_required
def delete_message(message_id):
    message = db.session.get(Message, message_id)
    if message is None or message.recipient != current_user:
        flash(_('You are not allowed to delete this message.'))
        return redirect(url_for('main.messages'))
    db.session.delete(message)
    db.session.commit()
    flash(_('Message deleted successfully.'))
    return redirect(url_for('main.messages'))

@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(original_username=current_user.username)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.about_me = form.about_me.data
        db.session.commit()
        flash(_('Your changes have been saved.'))
        return redirect(url_for('main.user', username=current_user.username))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', title=_('Edit Profile'), form=form)
