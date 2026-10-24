"""The Odynza Radar app: sign-in, the M0/M1/M2 routes and the single-page site."""
import os
import unittest

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.security import hash_password
from db.database import Base, User, get_db

PASSWORD = 'correct horse battery'


@pytest.mark.real_auth
class AppTests(unittest.TestCase):
    def setUp(self):
        os.environ.pop('N8N_SHARED_TOKEN', None)
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)

        def database():
            with self.factory() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.client = TestClient(app, follow_redirects=False)
        with self.factory() as db:
            db.add(User(username='alice', password_hash=hash_password(PASSWORD), role='admin'))
            db.commit()

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.client.close()
        self.engine.dispose()

    def test_health_is_not_shadowed_by_sections(self):
        self.assertEqual(self.client.get('/health').json(), {'status': 'ok', 'site': 'odynza-radar'})

    def test_watch_needs_sign_in_and_works_after(self):
        self.assertEqual(self.client.get('/watch/client').status_code, 401)
        self.assertEqual(self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD}).status_code, 200)
        self.assertEqual(self.client.get('/watch/client').status_code, 200)

    def test_m1_strategy_and_m2_content_need_sign_in(self):
        self.assertEqual(self.client.get('/strategy/radar/plans').status_code, 401)
        self.assertEqual(self.client.get('/content/runs').status_code, 401)
        self.assertEqual(self.client.post('/discover/stream', json={}).status_code, 401)
        self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD})
        self.assertEqual(self.client.get('/content/runs').json(), [])

    def test_sections_serve_the_site_and_unknown_paths_do_not(self):
        for path in ('/', '/overview', '/data', '/profile', '/strategy', '/content', '/team'):
            r = self.client.get(path)
            self.assertIn(r.status_code, (200, 503), path)
        self.assertEqual(self.client.get('/nope-not-a-section').status_code, 404)


def test_brief_is_a_mission_debrief():
    from api.watch.brief import brief_html, status
    snap = {'numbers': {'rivals': 1, 'posts_7d': 2, 'live_ads': None, 'news': 3, 'jobs': 0}, 'takeaways': ['Calm week.'],
            'rivals': [{'key': 'c1', 'name': 'Rival <One>', 'tier': 'direct', 'posts_7d': 2, 'news': 3, 'live_ads': None,
                        'jobs': None, 'followers': 10, 'platform': 'instagram'}],
            'standing': [], 'posts': [], 'news': [], 'ads': [], 'as_of': '2026-10-19T10:00'}
    quiet = {'id': 7, 'week_start': '2026-10-12', 'items': [], 'quiet': True}
    html = brief_html('Odynza', quiet, snapshot=snap)
    assert 'STATUS: QUIET SKIES' in html and 'DEBRIEF 007' in html and '<svg' in html
    assert 'Rival &lt;One&gt;' in html and 'Rival <One>' not in html
    assert '<svg' not in brief_html('Odynza', quiet, snapshot=snap, radar=False)
    assert status({'items': [{'score': 5}]})[0] == 'RED ALERT'
    assert status({'items': [{'score': 4}]})[0] == 'CONTACTS INBOUND'


def test_brief_view_page_may_use_inline_styles():
    from api.security import content_security_policy
    csp = content_security_policy('/watch/briefs/3/view')
    assert "style-src 'unsafe-inline'" in csp and "script-src 'none'" in csp
    assert "'unsafe-inline'" not in content_security_policy('/watch/briefs/3')
