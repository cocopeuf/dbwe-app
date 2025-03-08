from datetime import datetime, timezone
from flask import render_template, flash, redirect, url_for, request, g, \
    current_app
from flask_login import current_user, login_required
from flask_babel import _, get_locale
import sqlalchemy as sa
from langdetect import detect, LangDetectException
from app import db
from app.main.forms import EditProfileForm, EmptyForm, PostForm, SearchForm, \
    MessageForm, DinnerEventForm, CommentForm  # add import with existing form imports
from app.models import User, Post, Message, Notification, DinnerEvent, Comment  # add import for Comment
from app.translate import translate
from app.main import bp
from sqlalchemy.orm import joinedload


@bp.before_app_request
def before_request():
    if current_user.is_authenticated:
        current_user.last_seen = datetime.now(timezone.utc)
        db.session.commit()
        g.search_form = SearchForm()
    g.locale = str(get_locale())


@bp.route('/', methods=['GET', 'POST'])
@bp.route('/index', methods=['GET', 'POST'])
@login_required
def index():
    form = PostForm()
    if form.validate_on_submit():
        try:
            language = detect(form.post.data)
        except LangDetectException:
            language = ''
        post = Post(body=form.post.data, author=current_user,
                    language=language)
        db.session.add(post)
        db.session.commit()
        flash(_('Your post is now live!'))
        return redirect(url_for('main.index'))
    page = request.args.get('page', 1, type=int)
    posts = db.paginate(current_user.following_posts(), page=page,
                        per_page=current_app.config['POSTS_PER_PAGE'],
                        error_out=False)
    # New: Fetch up to 3 upcoming dinner events
    upcoming_events = db.session.scalars(
        sa.select(DinnerEvent).where(DinnerEvent.event_date >= datetime.now()).order_by(DinnerEvent.event_date.asc()).limit(3)
    ).all()
    next_url = url_for('main.index', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('index.html', title=_('Home'), form=form,
                           posts=posts.items, next_url=next_url,
                           prev_url=prev_url, upcoming_events=upcoming_events)


@bp.route('/explore')
@login_required
def explore():
    from datetime import datetime
    now = datetime.now()
    upcoming = db.session.scalars(
        sa.select(DinnerEvent).where(DinnerEvent.event_date >= now).order_by(DinnerEvent.event_date.asc())
    ).all()
    previous = db.session.scalars(
        sa.select(DinnerEvent).where(DinnerEvent.event_date < now).order_by(DinnerEvent.event_date.desc())
    ).all()
    return render_template('explore.html', title=_('Explore'), upcoming=upcoming, previous=previous)


@bp.route('/user/<username>')
@login_required
def user(username):
    user = db.first_or_404(sa.select(User).where(User.username == username))
    page = request.args.get('page', 1, type=int)
    query = user.posts.select().order_by(Post.timestamp.desc())
    posts = db.paginate(query, page=page,
                        per_page=current_app.config['POSTS_PER_PAGE'],
                        error_out=False)
    next_url = url_for('main.user', username=user.username,
                       page=posts.next_num) if posts.has_next else None
    prev_url = url_for('main.user', username=user.username,
                       page=posts.prev_num) if posts.has_prev else None
    form = EmptyForm()
    return render_template('user.html', user=user, posts=posts.items,
                           next_url=next_url, prev_url=prev_url, form=form)


@bp.route('/user/<username>/popup')
@login_required
def user_popup(username):
    user = db.first_or_404(sa.select(User).where(User.username == username))
    form = EmptyForm()
    return render_template('user_popup.html', user=user, form=form)


@bp.route('/edit_profile', methods=['GET', 'POST'])
@login_required
def edit_profile():
    form = EditProfileForm(current_user.username)
    if form.validate_on_submit():
        current_user.username = form.username.data
        current_user.about_me = form.about_me.data
        db.session.commit()
        flash(_('Your changes have been saved.'))
        return redirect(url_for('main.edit_profile'))
    elif request.method == 'GET':
        form.username.data = current_user.username
        form.about_me.data = current_user.about_me
    return render_template('edit_profile.html', title=_('Edit Profile'),
                           form=form)


@bp.route('/follow/<username>', methods=['POST'])
@login_required
def follow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.username == username))
        if user is None:
            flash(_('User %(username)s not found.', username=username))
            return redirect(url_for('main.index'))
        if user == current_user:
            flash(_('You cannot follow yourself!'))
            return redirect(url_for('main.user', username=username))
        current_user.follow(user)
        db.session.commit()
        flash(_('You are following %(username)s!', username=username))
        return redirect(url_for('main.user', username=username))
    else:
        return redirect(url_for('main.index'))


@bp.route('/unfollow/<username>', methods=['POST'])
@login_required
def unfollow(username):
    form = EmptyForm()
    if form.validate_on_submit():
        user = db.session.scalar(
            sa.select(User).where(User.username == username))
        if user is None:
            flash(_('User %(username)s not found.', username=username))
            return redirect(url_for('main.index'))
        if user == current_user:
            flash(_('You cannot unfollow yourself!'))
            return redirect(url_for('main.user', username=username))
        current_user.unfollow(user)
        db.session.commit()
        flash(_('You are not following %(username)s.', username=username))
        return redirect(url_for('main.user', username=username))
    else:
        return redirect(url_for('main.index'))


@bp.route('/translate', methods=['POST'])
@login_required
def translate_text():
    data = request.get_json()
    return {'text': translate(data['text'],
                              data['source_language'],
                              data['dest_language'])}


@bp.route('/search')
@login_required
def search():
    if not g.search_form.validate():
        return redirect(url_for('main.explore'))
    page = request.args.get('page', 1, type=int)
    posts, total = Post.search(g.search_form.q.data, page,
                               current_app.config['POSTS_PER_PAGE'])
    next_url = url_for('main.search', q=g.search_form.q.data, page=page + 1) \
        if total > page * current_app.config['POSTS_PER_PAGE'] else None
    prev_url = url_for('main.search', q=g.search_form.q.data, page=page - 1) \
        if page > 1 else None
    return render_template('search.html', title=_('Search'), posts=posts,
                           next_url=next_url, prev_url=prev_url)


@bp.route('/send_message/<recipient>', methods=['GET', 'POST'])
@login_required
def send_message(recipient):
    user = db.first_or_404(sa.select(User).where(User.username == recipient))
    form = MessageForm()
    if form.validate_on_submit():
        msg = Message(author=current_user, recipient=user,
                      body=form.message.data)
        db.session.add(msg)
        user.add_notification('unread_message_count',
                              user.unread_message_count())
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
    page = request.args.get('page', 1, type=int)
    query = current_user.messages_received.select().order_by(
        Message.timestamp.desc())
    messages = db.paginate(query, page=page,
                           per_page=current_app.config['POSTS_PER_PAGE'],
                           error_out=False)
    next_url = url_for('main.messages', page=messages.next_num) \
        if messages.has_next else None
    prev_url = url_for('main.messages', page=messages.prev_num) \
        if messages.has_prev else None
    return render_template('messages.html', messages=messages.items,
                           next_url=next_url, prev_url=prev_url)


@bp.route('/export_posts')
@login_required
def export_posts():
    if current_user.get_task_in_progress('export_posts'):
        flash(_('An export task is currently in progress'))
    else:
        current_user.launch_task('export_posts', _('Exporting posts...'))
        db.session.commit()
    return redirect(url_for('main.user', username=current_user.username))


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


@bp.route('/create_dinner_event', methods=['GET', 'POST'])
@login_required
def create_dinner_event():
    form = DinnerEventForm()
    if form.validate_on_submit():
        event = DinnerEvent(
            title=form.title.data,
            description=form.description.data,
            menu_url=form.menu_url.data,
            event_date=form.date.data,  # assign event_date
            creator=current_user
        )
        db.session.add(event)
        # Process invite field if any
        if form.invite.data:
            invitees = [i.strip() for i in form.invite.data.split(',') if i.strip()]
            for identifier in invitees:
                # Search by username or email
                user = db.session.scalar(sa.select(User).where(
                    sa.or_(User.username == identifier, User.email == identifier)
                ))
                if user is not None:
                    event.invite_user(user)
                    # Add notification for invite
                    user.add_notification('dinner_event_invite', 
                        {'message': _('You have been invited to the event: %(event_title)s', event_title=event.title),
                         'event_id': event.id})
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
    # Added permission check: Only show event if current_user is creator or invited
    if event.creator != current_user and current_user not in event.invited:
        flash(_('You are not allowed to view this dinner event.'))
        return redirect(url_for('main.dinner_events_list'))
    # Find the RSVP record for the current user, if any
    user_rsvp = next((r for r in event.rsvps if r.user_id == current_user.id), None)
    comment_form = CommentForm()
    return render_template('dinner_event_detail.html', event=event, user_rsvp=user_rsvp, comment_form=comment_form)

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
        # Redirect back to the event detail page
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
    user = db.session.scalar(sa.select(User).where(
        sa.or_(User.username == identifier, User.email == identifier)
    ))
    if user is None:
        flash(_('User %(identifier)s not found.', identifier=identifier))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.invite_user(user)
    user.add_notification('dinner_event_invite', 
        {'message': _('You have been invited to the event: %(event_title)s', event_title=event.title),
         'event_id': event.id})
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
    user = db.session.scalar(sa.select(User).where(
        sa.or_(User.username == identifier, User.email == identifier)
    ))
    if user is None or user not in event.invited:
        flash(_('User %(identifier)s is not invited.', identifier=identifier))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.uninvite_user(user)
    db.session.commit()
    flash(_('User %(identifier)s has been uninvited.', identifier=identifier))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))

@bp.route('/dinner_events')
@login_required
def dinner_events_list():
    q = sa.select(DinnerEvent).options(
        joinedload(DinnerEvent.creator),
        joinedload(DinnerEvent.invited)
    ).where(
        sa.or_(
            DinnerEvent.creator_id == current_user.id,
            DinnerEvent.invited.any(User.id == current_user.id)
        )
    ).order_by(DinnerEvent.id.desc())
    events = db.session.execute(q).unique().scalars().all()
    return render_template('dinner_events_list.html', title=_('Dinner Events'), events=events)

@bp.route('/dinner_event/<int:event_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_dinner_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None or event.creator != current_user:
        flash(_('You are not allowed to edit this dinner event.'))
        return redirect(url_for('main.dinner_events_list'))
    form = DinnerEventForm(obj=event)
    if request.method == 'GET':
        # Ensure the date field shows the current event date (as a date object)
        form.date.data = event.event_date.date()
    if form.validate_on_submit():
        event.title = form.title.data
        event.description = form.description.data
        event.menu_url = form.menu_url.data
        event.event_date = form.date.data  # update event_date
        # Process new invitations if any
        if form.invite.data:
            invitees = [i.strip() for i in form.invite.data.split(',') if i.strip()]
            for identifier in invitees:
                user = db.session.scalar(sa.select(User).where(
                    sa.or_(User.username == identifier, User.email == identifier)
                ))
                if user is not None:
                    event.invite_user(user)
                    user.add_notification('dinner_event_invite', 
                        {'message': _('You have been invited to the event: %(event_title)s', event_title=event.title),
                         'event_id': event.id})
        db.session.commit()
        flash(_('Dinner event updated.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event.id))
    return render_template('edit_dinner_event.html', title=_('Edit Dinner Event'), form=form, event=event)

@bp.route('/upcoming_events')
@login_required
def upcoming_events():
    from datetime import datetime
    # Select events with date in the future
    all_events = db.session.scalars(
        sa.select(DinnerEvent).where(DinnerEvent.event_date >= datetime.now()).order_by(DinnerEvent.event_date.asc())
    ).all()
    events = []
    for event in all_events:
        rsvp = next((r for r in event.rsvps if r.user_id == current_user.id), None)
        if rsvp and rsvp.status == 'declined':
            continue
        events.append(event)
    return render_template('upcoming_events.html', title=_('Upcoming Events'), events=events)

@bp.route('/dinner_event/<int:event_id>/rsvp', methods=['POST'])
@login_required
def rsvp_dinner_event(event_id):
    event = db.session.get(DinnerEvent, event_id)
    if event is None:
        flash(_('Dinner event not found.'))
        return redirect(url_for('main.index'))
    # Allow RSVP if current_user is invited or is the creator
    if current_user not in event.invited and event.creator != current_user:
        flash(_('You are not invited to RSVP this dinner event.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    rsvp_choice = request.form.get('rsvp')
    if rsvp_choice not in ['accepted', 'declined']:
        flash(_('Invalid RSVP choice.'))
        return redirect(url_for('main.dinner_event_detail', event_id=event_id))
    event.rsvp(current_user, rsvp_choice)
    db.session.commit()
    flash(_('Your RSVP has been recorded as %(status)s.', status=rsvp_choice))
    return redirect(url_for('main.dinner_event_detail', event_id=event_id))
