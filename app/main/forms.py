from flask import request
from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, TextAreaField, BooleanField
from wtforms.validators import ValidationError, DataRequired, Length, URL, Optional
import sqlalchemy as sa
from flask_babel import _, lazy_gettext as _l
from app import db
from app.models import User
from wtforms.fields import DateTimeField
from datetime import datetime


class EditProfileForm(FlaskForm):
    username = StringField(_l('Username'), validators=[DataRequired()])
    about_me = TextAreaField(_l('About me'),
                             validators=[Length(min=0, max=140)])
    submit = SubmitField(_l('Submit'))

    def __init__(self, original_username, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.original_username = original_username

    def validate_username(self, username):
        if username.data != self.original_username:
            user = db.session.scalar(sa.select(User).where(
                User.username == username.data))
            if user is not None:
                raise ValidationError(_('Please use a different username.'))


class EmptyForm(FlaskForm):
    submit = SubmitField('Submit')


class MessageForm(FlaskForm):
    message = TextAreaField(_l('Message'), validators=[
        DataRequired(), Length(min=1, max=140)])
    submit = SubmitField(_l('Submit'))


class DinnerEventForm(FlaskForm):
    title = StringField(_l('Title'), validators=[DataRequired(), Length(max=128)])
    description = TextAreaField(_l('Description'))
    external_event_url = StringField(_l('Event URL'), validators=[Optional(), URL(), Length(max=256)])
    date = DateTimeField(_l('Event Date'), format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    invite = StringField(_l('Invite Users (comma separated)'))
    is_public = BooleanField(_l('Public Event?'))
    submit = SubmitField(_l('Create Dinner Event'))

    def validate_date(form, field):
        if isinstance(field.data, str):
            try:
                field.data = datetime.strptime(field.data, '%Y-%m-%dT%H:%M')
            except ValueError:
                raise ValidationError(_('Invalid date format. Please use the format YYYY-MM-DDTHH:MM.'))

    def prefill_invite(self, invited_users):
        self.invite.data = ', '.join(user.username for user in invited_users)


class CommentForm(FlaskForm):
    body = TextAreaField(_l('Comment'), validators=[DataRequired(), Length(min=1, max=500)])
    submit = SubmitField(_l('Post Comment'))
