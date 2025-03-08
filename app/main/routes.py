from datetime import datetime, timezone
from flask import render_template, flash, redirect, url_for, request, g, \
    current_app
from flask_login import current_user, login_required
from flask_babel import _, get_locale
import sqlalchemy as sa
from langdetect import detect, LangDetectException
from app import db
from app.main.forms import EditProfileForm, EmptyForm, PostForm, SearchForm, \
    MessageForm, DinnerEventForm  # import the new form
from app.models import User, Post, Message, Notification, DinnerEvent  # import DinnerEvent
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
    next_url = url_for('main.index', page=posts.next_num) \
        if posts.has_next else None
    prev_url = url_for('main.index', page=posts.prev_num) \
        if posts.has_prev else None
    return render_template('index.html', title=_('Home'), form=form,
                           posts=posts.items, next_url=next_url,
                           prev_url=prev_url)


@bp.route('/explore')
@login_required
def explore():
    page = request.args.get('page', 1, type=int)
    per_page = current_app.config.get('POSTS_PER_PAGE', 10)
    query = sa.select(Post).order_by(Post.timestamp.desc())
    total = db.session.scalar(sa.select(sa.func.count()).select_from(Post))
    posts = db.session.scalars(
        query.offset((page - 1) * per_page).limit(per_page)
    ).all()
    next_url = url_for('main.explore', page=page + 1) if page * per_page < total else None
    prev_url = url_for('main.explore', page=page - 1) if page > 1 else None
    return render_template('index.html', title=_('Explore'),
                           posts=posts, next_url=next_url,
                           prev_url=prev_url)


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
            date=form.date.data,  # assign event date
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
            joinedload(DinnerEvent.invited)
        ).where(DinnerEvent.id == event_id)
    event = db.session.scalar(q)
    if event is None:
        flash(_('Dinner event not found.'))
        return redirect(url_for('main.index'))
    # Added permission check: Only show event if current_user is creator or invited
    if event.creator != current_user and current_user not in event.invited:
        flash(_('You are not allowed to view this dinner event.'))
        return redirect(url_for('main.dinner_events_list'))
    return render_template('dinner_event_detail.html', event=event)

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
    if form.validate_on_submit():
        event.title = form.title.data
        event.description = form.description.data
        event.menu_url = form.menu_url.data
        event.date = form.date.data  # update event date
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

# New route: Message Board for Upcoming Events
@bp.route('/upcoming_events')
@login_required
def upcoming_events():
    from datetime import datetime
    # Select events with date in the future
    q = sa.select(DinnerEvent).where(DinnerEvent.date >= datetime.now()).order_by(DinnerEvent.date.asc())
    events = db.session.scalars(q).all()
    return render_template('upcoming_events.html', title=_('Upcoming Events'), events=events)
