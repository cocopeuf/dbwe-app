import unittest
from datetime import datetime, timezone, timedelta
from app import create_app, db
from app.models import User, DinnerEvent, DinnerEventRsvp

# Basis-Setup von miguelgrinberg übernommen und für DinnerEvent-Model erweitert

class TestConfig:
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    WTF_CSRF_ENABLED = False
    ELASTICSEARCH_URL = None
    REDIS_URL = "redis://localhost:6379/0"

class UserModelCase(unittest.TestCase):
    
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(TestConfig)
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        db.create_all()

    @classmethod
    def tearDownClass(cls):
        db.session.remove()
        db.drop_all()
        cls.app_context.pop()

    def setUp(self):
        db.session.rollback()
        db.session.query(User).delete()
        db.session.query(DinnerEvent).delete() # Erweiterung für DinnerEvent-Model
        db.session.query(DinnerEventRsvp).delete() # Erweiterung für DinnerEvent-Model
        db.session.commit()

# Selbsterstellte Funktionen für die Erstellung von Testdaten
    def create_default_user(self):
        user = User.query.filter_by(username="defaultuser").first()
        if not user:
            user = User(username="defaultuser", email="default@example.com")
            db.session.add(user)
            db.session.commit()
        return user

    def create_default_event(self, user, is_public=True):
        event = DinnerEvent(
            title='Test Event',
            description='Test description',
            external_event_url='http://example.com',
            event_date=datetime.now(timezone.utc) + timedelta(days=1),
            creator_id=user.id,
            is_public=is_public
        )
        db.session.add(event)
        db.session.commit()
        return event

    def test_create_public_event(self):
        user = self.create_default_user()
        event = self.create_default_event(user, is_public=True)
        self.assertTrue(event.is_public)

    def test_create_private_event_with_invite(self):
        user = self.create_default_user()
        event = self.create_default_event(user, is_public=False)
        self.assertFalse(event.is_public)

    def test_edit_event(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        event.title = "Updated Event Title"
        db.session.commit()
        updated_event = db.session.get(DinnerEvent, event.id)
        self.assertEqual(updated_event.title, "Updated Event Title")

    def test_delete_event(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        db.session.delete(event)
        db.session.commit()
        self.assertIsNone(db.session.get(DinnerEvent, event.id))

    def test_delete_rsvp(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        rsvp = DinnerEventRsvp(user_id=user.id, dinner_event_id=event.id, status='deleted')
        db.session.add(rsvp)
        db.session.commit()
        db.session.delete(rsvp)
        db.session.commit()
        self.assertIsNone(db.session.get(DinnerEventRsvp, (rsvp.dinner_event_id, rsvp.user_id)))

    def test_rsvp_accept(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        rsvp = DinnerEventRsvp(user_id=user.id, dinner_event_id=event.id, status='accepted')
        db.session.add(rsvp)
        db.session.commit()
        self.assertEqual(rsvp.status, 'accepted')

    def test_rsvp_decline(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        rsvp = DinnerEventRsvp(user_id=user.id, dinner_event_id=event.id, status='declined')
        db.session.add(rsvp)
        db.session.commit()
        self.assertEqual(rsvp.status, 'declined')

    def test_accept_opt_in(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        event.pending_opt_ins.append(user)
        db.session.commit()
        event.pending_opt_ins.remove(user)
        event.invited.append(user)
        db.session.commit()
        self.assertIn(user, event.invited)

    def test_decline_opt_in(self):
        user = self.create_default_user()
        event = self.create_default_event(user)
        event.pending_opt_ins.append(user)
        db.session.commit()
        event.pending_opt_ins.remove(user)
        db.session.commit()
        self.assertNotIn(user, event.pending_opt_ins)

# Testfälle für User-Model von miguelgrinberg übernommen

    def test_user_login(self):
        user = User(username='loginuser', email='login@example.com')
        user.set_password('mypassword')
        db.session.add(user)
        db.session.commit()
        logged_user = User.query.filter_by(username='loginuser').first()
        self.assertTrue(logged_user.check_password('mypassword'))
        self.assertFalse(logged_user.check_password('wrongpassword'))

    def test_user_registration(self):
        user = User(username='newuser', email='newuser@example.com')
        user.set_password('securepassword')
        db.session.add(user)
        db.session.commit()
        self.assertIsNotNone(User.query.filter_by(username='newuser').first())

    def test_password_hashing(self):
        user = User(username='hashuser', email='hash@example.com')
        user.set_password('secret-password')
        db.session.add(user)
        db.session.commit()
        self.assertTrue(user.check_password('secret-password'))
        self.assertFalse(user.check_password('wrong-password'))


if __name__ == '__main__':
    loader = unittest.TestLoader()

    # Definierte Reihenfolge der Testcases (Selbsterstellt)
    test_order = [
        "test_user_login",
        "test_user_registration",
        "test_password_hashing",
        "test_create_public_event",
        "test_create_private_event_with_invite",
        "test_edit_event",
        "test_rsvp_accept",
        "test_rsvp_decline",
        "test_accept_opt_in",
        "test_decline_opt_in",
        "test_delete_event",
        "test_delete_rsvp",
    ]

    suite = unittest.TestSuite()
    
    for test_name in test_order:
        suite.addTest(UserModelCase(test_name))
    
    runner = unittest.TextTestRunner(verbosity=2)
    runner.run(suite)
