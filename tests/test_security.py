"""Real sign-in, sessions, CSRF, rate limits and HTTP hardening (no dependency overrides for auth)."""
import os
import unittest

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from api.main import app
from api.security import hash_password, verify_password, password_problem, token_hash, CSRF_COOKIE, SESSION_COOKIE
from db.database import AuthSession, Base, User, get_db

PASSWORD = 'correct horse battery'


@pytest.mark.real_auth
class SecurityTests(unittest.TestCase):
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

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.client.close()
        self.engine.dispose()

    def add_user(self, name='alice', role='admin', disabled=False):
        with self.factory() as db:
            db.add(User(username=name, password_hash=hash_password(PASSWORD), role=role, disabled=disabled))
            db.commit()

    def login(self, client=None, name='alice', password=PASSWORD):
        client = client or self.client
        r = client.post('/auth/login', json={'username': name, 'password': password})
        return r

    def csrf(self, client=None):
        return {'X-CSRF-Token': (client or self.client).cookies.get(CSRF_COOKIE)}

    # ---- passwords --------------------------------------------------------------------
    def test_password_hash_round_trip_and_policy(self):
        stored = hash_password(PASSWORD)
        self.assertTrue(stored.startswith('scrypt$'))
        self.assertNotIn(PASSWORD, stored)
        self.assertTrue(verify_password(PASSWORD, stored))
        self.assertFalse(verify_password(PASSWORD + 'x', stored))
        self.assertFalse(verify_password(PASSWORD, 'garbage'))
        self.assertIsNotNone(password_problem('short'))
        self.assertIsNotNone(password_problem('password123'))
        self.assertIsNotNone(password_problem('alice-is-great', 'alice'))
        self.assertIsNone(password_problem(PASSWORD, 'alice'))

    # ---- sign-in ----------------------------------------------------------------------
    def test_api_needs_sign_in(self):
        for path in ('/content/runs', '/watch/client', '/strategy/radar/plans', '/strategy/plans/p1'):
            self.assertEqual(self.client.get(path).status_code, 401, path)
        for path in ('/docs', '/openapi.json'):
            self.assertEqual(self.client.get(path).status_code, 404, path)
        self.assertEqual(self.client.post('/discover', json={'company_name': 'Odynza'}).status_code, 401)
        self.assertEqual(self.client.get('/health').status_code, 200)
        self.assertIn(self.client.get('/').status_code, (200, 503))  # 503 until the site is built

    def test_page_link_redirects_to_sign_in(self):
        r = self.client.get('/watch/briefs/1/view', headers={'Accept': 'text/html'})
        self.assertEqual(r.status_code, 303)
        self.assertEqual(r.headers['location'], '/?next=/watch/briefs/1/view')

    def test_login_sets_hardened_cookies_and_stores_only_hashes(self):
        self.add_user()
        r = self.login()
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()['user']['username'], 'alice')
        cookies = r.headers.get_list('set-cookie')
        session = next(c for c in cookies if c.startswith(SESSION_COOKIE + '='))
        self.assertIn('HttpOnly', session)
        self.assertIn('SameSite=lax', session)
        token = self.client.cookies.get(SESSION_COOKIE)
        with self.factory() as db:
            self.assertIsNone(db.get(AuthSession, token))
            self.assertIsNotNone(db.get(AuthSession, token_hash(token)))
        self.assertEqual(self.client.get('/content/runs').status_code, 200)
        status = self.client.get('/auth/status').json()
        self.assertTrue(status['authenticated'])
        self.assertEqual(status['csrf'], self.client.cookies.get(CSRF_COOKIE))

    def test_wrong_password_and_unknown_user_look_the_same(self):
        self.add_user()
        a = self.login(password='wrong password!!')
        b = self.login(name='nobody')
        self.assertEqual((a.status_code, a.json()), (b.status_code, b.json()))
        self.assertEqual(a.status_code, 401)

    def test_disabled_user_cannot_sign_in(self):
        self.add_user(disabled=True)
        self.assertEqual(self.login().status_code, 401)

    def test_repeated_failures_are_throttled(self):
        self.add_user()
        codes = [self.login(password='not the password').status_code for _ in range(9)]
        self.assertEqual(codes[:8], [401] * 8)
        self.assertEqual(codes[8], 429)
        r = self.login()  # even the right password waits now
        self.assertEqual(r.status_code, 429)
        self.assertIn('Retry-After', r.headers)

    def test_logout_ends_session(self):
        self.add_user()
        self.login()
        self.assertEqual(self.client.post('/auth/logout', headers=self.csrf()).status_code, 200)
        self.assertEqual(self.client.get('/content/runs').status_code, 401)

    def test_new_sign_in_replaces_old_session(self):
        self.add_user()
        self.login()
        first = self.client.cookies.get(SESSION_COOKIE)
        self.login()
        with self.factory() as db:
            self.assertIsNone(db.get(AuthSession, token_hash(first)))

    # ---- CSRF / cross-site ------------------------------------------------------------
    def test_writes_need_csrf_token(self):
        self.add_user()
        self.login()
        self.assertEqual(self.client.delete('/content/runs/r1').status_code, 403)
        self.assertEqual(self.client.delete('/content/runs/r1', headers={'X-CSRF-Token': 'forged'}).status_code, 403)
        self.assertEqual(self.client.delete('/content/runs/r1', headers=self.csrf()).status_code, 404)  # allowed, batch missing

    def test_cross_site_writes_blocked_before_routing(self):
        self.add_user()
        self.login()
        for headers in ({'Origin': 'https://evil.example'}, {'Sec-Fetch-Site': 'cross-site'}, {'Origin': 'null'}):
            r = self.client.post('/auth/logout', headers={**self.csrf(), **headers})
            self.assertEqual(r.status_code, 403, headers)
        same = self.client.post('/auth/logout', headers={**self.csrf(), 'Origin': 'http://testserver', 'Sec-Fetch-Site': 'same-origin'})
        self.assertEqual(same.status_code, 200)

    def test_login_itself_rejects_cross_site(self):
        self.add_user()
        r = self.client.post('/auth/login', json={'username': 'alice', 'password': PASSWORD},
                             headers={'Origin': 'https://evil.example'})
        self.assertEqual(r.status_code, 403)

    # ---- first admin and user management ---------------------------------------------
    def test_first_admin_only_from_this_computer(self):
        self.assertTrue(self.client.get('/auth/status').json()['setup_required'])
        self.assertEqual(self.client.post('/auth/setup', json={'username': 'boss', 'password': PASSWORD}).status_code, 403)
        local = TestClient(app, client=('127.0.0.1', 5000))
        proxied = local.post('/auth/setup', json={'username': 'boss', 'password': PASSWORD},
                             headers={'X-Forwarded-For': '203.0.113.9'})
        self.assertEqual(proxied.status_code, 403)
        self.assertEqual(local.post('/auth/setup', json={'username': 'boss', 'password': PASSWORD}).status_code, 200)
        self.assertEqual(local.post('/auth/setup', json={'username': 'two', 'password': PASSWORD}).status_code, 409)
        local.close()

    def test_admin_manages_users_member_cannot(self):
        self.add_user()
        self.login()
        r = self.client.post('/auth/users', json={'username': 'Bob', 'password': PASSWORD, 'role': 'member'}, headers=self.csrf())
        self.assertEqual(r.status_code, 201)
        self.assertEqual(r.json()['username'], 'bob')
        self.assertNotIn('password_hash', r.json())
        self.assertEqual(self.client.post('/auth/users', json={'username': 'bob', 'password': PASSWORD}, headers=self.csrf()).status_code, 409)
        self.assertEqual(self.client.post('/auth/users', json={'username': 'weak', 'password': 'abc'}, headers=self.csrf()).status_code, 422)
        member = TestClient(app)
        self.login(member, 'bob')
        self.assertEqual(member.get('/auth/users').status_code, 403)
        self.assertEqual(member.get('/content/runs').status_code, 200)
        # Disabling signs the member out immediately.
        bob = r.json()['id']
        self.assertEqual(self.client.patch(f'/auth/users/{bob}', json={'disabled': True}, headers=self.csrf()).status_code, 200)
        self.assertEqual(member.get('/content/runs').status_code, 401)
        member.close()

    def test_viewer_can_read_but_not_change_anything(self):
        self.add_user()
        self.add_user('vera', role='viewer')
        viewer = TestClient(app)
        self.assertEqual(self.login(viewer, 'vera').status_code, 200)
        h = self.csrf(viewer)
        for path in ('/content/runs', '/auth/me'):
            self.assertEqual(viewer.get(path).status_code, 200, path)
        self.assertEqual(viewer.delete('/content/runs/r1', headers=h).status_code, 403)
        self.assertEqual(viewer.post('/discover/stream', json={'company_name': 'Odynza'}, headers=h).status_code, 403)
        self.assertEqual(viewer.post('/content/runs', json={}, headers=h).status_code, 403)
        self.assertEqual(viewer.delete('/strategy/plans/p1', headers=h).status_code, 403)
        self.assertEqual(viewer.get('/auth/users').status_code, 403)
        ok = viewer.post('/auth/password', json={'current_password': PASSWORD, 'new_password': 'viewer own password'}, headers=h)
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(viewer.post('/auth/logout', headers=self.csrf(viewer)).status_code, 200)
        viewer.close()
        # An admin can create viewers and change roles.
        self.login()
        r = self.client.post('/auth/users', json={'username': 'sam', 'password': PASSWORD, 'role': 'viewer'}, headers=self.csrf())
        self.assertEqual((r.status_code, r.json()['role']), (201, 'viewer'))
        r = self.client.patch(f"/auth/users/{r.json()['id']}", json={'role': 'member'}, headers=self.csrf())
        self.assertEqual(r.json()['role'], 'member')

    def test_sign_up_waits_for_admin_approval(self):
        os.environ.pop('SIGNUP_MODE', None)
        self.assertEqual(self.client.post('/auth/signup', json={'username': 'early', 'password': PASSWORD}).status_code, 403)  # no admin yet
        self.add_user()
        self.assertEqual(self.client.get('/auth/status').json()['signup'], 'approval')
        r = self.client.post('/auth/signup', json={'username': 'Newbie', 'password': PASSWORD})
        self.assertEqual((r.status_code, r.json()), (201, {'authenticated': False, 'pending': True}))
        self.assertIsNone(self.client.cookies.get(SESSION_COOKIE))
        self.assertEqual(self.client.post('/auth/signup', json={'username': 'newbie', 'password': PASSWORD}).status_code, 409)
        self.assertEqual(self.client.post('/auth/signup', json={'username': 'weak', 'password': 'short'}).status_code, 422)
        self.assertEqual(self.login(name='newbie').status_code, 403)  # pending
        self.login()
        users = {u['username']: u for u in self.client.get('/auth/users').json()}
        self.assertEqual(users['newbie']['role'], 'pending')
        self.client.patch(f"/auth/users/{users['newbie']['id']}", json={'role': 'viewer'}, headers=self.csrf())
        other = TestClient(app)
        self.assertEqual(self.login(other, 'newbie').status_code, 200)
        self.assertEqual(other.post('/content/runs', json={}, headers=self.csrf(other)).status_code, 403)
        other.close()

    def test_sign_up_modes(self):
        self.add_user()
        try:
            os.environ['SIGNUP_MODE'] = 'off'
            self.assertEqual(self.client.post('/auth/signup', json={'username': 'x1user', 'password': PASSWORD}).status_code, 403)
            os.environ['SIGNUP_MODE'] = 'viewer'
            r = self.client.post('/auth/signup', json={'username': 'x2user', 'password': PASSWORD})
            self.assertEqual(r.json()['user']['role'], 'viewer')
            self.assertEqual(self.client.get('/content/runs').status_code, 200)
            codes = [self.client.post('/auth/signup', json={'username': f'flood{i}', 'password': PASSWORD}).status_code for i in range(5)]
            self.assertEqual(codes[-1], 429)  # 5 per hour per address, including the one above
        finally:
            os.environ.pop('SIGNUP_MODE', None)

    def test_last_admin_is_kept(self):
        self.add_user()
        self.login()
        me = self.client.get('/auth/me').json()['user']['id']
        self.assertEqual(self.client.patch(f'/auth/users/{me}', json={'role': 'member'}, headers=self.csrf()).status_code, 409)
        self.assertEqual(self.client.delete(f'/auth/users/{me}', headers=self.csrf()).status_code, 409)

    def test_password_change_signs_out_other_browsers(self):
        self.add_user()
        other = TestClient(app)
        self.login(other)
        self.login()
        bad = self.client.post('/auth/password', json={'current_password': 'nope nope nope', 'new_password': 'another fine password'}, headers=self.csrf())
        self.assertEqual(bad.status_code, 403)
        ok = self.client.post('/auth/password', json={'current_password': PASSWORD, 'new_password': 'another fine password'}, headers=self.csrf())
        self.assertEqual(ok.status_code, 200)
        self.assertEqual(other.get('/content/runs').status_code, 401)
        self.assertEqual(self.client.get('/content/runs').status_code, 200)
        other.close()

    # ---- rate limits on paid endpoints -----------------------------------------------
    def test_paid_endpoints_are_rate_limited(self):
        os.environ['LIMIT_SEARCHES_PER_10_MIN'] = '20'
        self.add_user()
        self.login()
        codes = [self.client.post('/discover', json={}, headers=self.csrf()).status_code for _ in range(21)]
        self.assertEqual(codes[:20], [422] * 20)
        self.assertEqual(codes[20], 429)

    # ---- HTTP hardening ---------------------------------------------------------------
    def test_security_headers(self):
        r = self.client.get('/health')
        self.assertEqual(r.headers['x-content-type-options'], 'nosniff')
        self.assertEqual(r.headers['x-frame-options'], 'DENY')
        self.assertIn("frame-ancestors 'none'", r.headers['content-security-policy'])
        self.assertIn("script-src 'self'", r.headers['content-security-policy'])
        self.assertNotIn('unsafe-inline', r.headers['content-security-policy'].split('script-src')[1].split(';')[0])
        self.assertEqual(r.headers['cache-control'], 'no-store')

    def test_unknown_host_rejected(self):
        self.assertEqual(self.client.get('/health', headers={'Host': 'attacker.example'}).status_code, 400)

    def test_large_body_rejected(self):
        r = self.client.post('/auth/login', content=b'x' * (1024 * 1024 + 1), headers={'Content-Type': 'application/json'})
        self.assertEqual(r.status_code, 413)

    def test_n8n_callback_needs_token_or_direct_local_call(self):
        body = {'error': 'x'}
        self.assertEqual(self.client.post('/strategy/plans/p1/fail', json=body).status_code, 403)
        local = TestClient(app, client=('127.0.0.1', 5000))
        relayed = local.post('/strategy/plans/p1/fail', json=body, headers={'X-Forwarded-For': '198.51.100.7'})
        self.assertEqual(relayed.status_code, 403)
        self.assertEqual(local.post('/strategy/plans/p1/fail', json=body).status_code, 404)  # allowed, plan missing
        os.environ['N8N_SHARED_TOKEN'] = 'shared-secret-value'
        try:
            self.assertEqual(local.post('/strategy/plans/p1/fail', json=body).status_code, 401)
            ok = self.client.post('/strategy/plans/p1/fail', json=body, headers={'X-Radar-Token': 'shared-secret-value'})
            self.assertEqual(ok.status_code, 404)
        finally:
            os.environ.pop('N8N_SHARED_TOKEN', None)
            local.close()


class NetworkGuardTests(unittest.TestCase):
    def test_scraper_refuses_private_addresses(self):
        import asyncio
        from api.netguard import url_is_public
        for url in ('http://127.0.0.1:8000/auth/users', 'http://localhost/', 'http://10.0.0.5/', 'http://192.168.1.1/',
                    'http://169.254.169.254/latest/meta-data', 'http://[::1]/', 'file:///etc/passwd', 'ftp://example.com/',
                    'http://user:pw@example.com/', 'http://0.0.0.0/'):
            self.assertFalse(asyncio.run(url_is_public(url)), url)
        self.assertTrue(asyncio.run(url_is_public('data:text/plain,hi')))


if __name__ == '__main__':
    unittest.main()
