"""M0 Watch: page rules, change detection, metrics, the visit pipeline, n8n callbacks, brief and opportunity checks."""
import asyncio
import os
import unittest
import unittest.mock
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.watch_models  # noqa: F401
from api.main import app
from api.security import CSRF_COOKIE, hash_password
from api.watch import collect, engine, fields, scheduler
from db.database import Base, User, get_db
from db.watch_models import WatchChange, WatchCompetitor, WatchSnapshot, WatchSource, WatchVisit
from fastapi import HTTPException

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 600

HOME = """<html><body><nav><a href="/">Home</a></nav><main><h1>AI agents for Egyptian SMEs</h1>
<a href="/pricing">Pricing</a> <a href="/solutions">Our solutions</a> <a href="/careers">Join us</a>
<a href="/blog/post-1">Blog</a> <a href="https://other.com/pricing">Other</a>
<div class="clients"><img alt="Bank Misr logo" src="a.png"><img alt="Vodafone" src="b.png"></div>
<p>We build chatbots that answer customers in Arabic and English, all day and every day.</p></main>
<footer>© 2026 Nexa</footer><div id="cookie-banner">We use cookies</div></body></html>"""


def pricing(business='EGP 40,000', extra=''):
    return f"""<html><body><main><h1>Plans</h1>
<div class="card"><h3>Starter</h3><p>EGP 15,000 / year</p></div>
<div class="card"><h3>Business</h3><p>{business} / year</p></div>
<div class="card"><h3>Enterprise</h3><p>Contact us</p></div>{extra}
<p>All plans include Arabic and English dashboards and onboarding help.</p></main></body></html>"""


class FieldRules(unittest.TestCase):
    def test_pages_are_proposed_by_link_text_and_url_on_the_same_site(self):
        pages = fields.propose_pages(HOME, 'https://nexa.ai', 'direct')
        kinds = {p['page_kind']: p['url'] for p in pages}
        self.assertEqual(kinds['homepage'], 'https://nexa.ai')
        self.assertEqual(kinds['pricing'], 'https://nexa.ai/pricing')
        self.assertEqual(kinds['services'], 'https://nexa.ai/solutions')
        self.assertEqual(kinds['careers'], 'https://nexa.ai/careers')
        self.assertNotIn('other.com', ' '.join(kinds.values()))
        self.assertEqual([p['page_kind'] for p in fields.propose_pages(HOME, 'https://nexa.ai', 'emerging')], ['homepage'])

    def test_prices_are_read_with_their_plan_names_and_noise_is_dropped(self):
        data = fields.extract(pricing(), 'https://nexa.ai/pricing', 'pricing')
        self.assertEqual(data['fields']['prices']['Business'], 'EGP 40,000 / year')
        self.assertEqual(data['fields']['prices']['Starter'], 'EGP 15,000 / year')
        home = fields.extract(HOME, 'https://nexa.ai', 'homepage')
        self.assertEqual(home['fields']['headline'], 'AI agents for Egyptian SMEs')
        self.assertIn('Bank Misr', home['fields']['clients'])
        self.assertNotIn('cookies', home['text'])
        self.assertNotIn('©', home['text'])

    def test_price_cut_is_one_change_with_its_percentage(self):
        old = fields.extract(pricing(), 'u', 'pricing')
        new = fields.extract(pricing('EGP 34,000'), 'u', 'pricing')
        changes = fields.page_changes(old, new)
        price = [c for c in changes if c['field'] == 'price:Business']
        self.assertEqual(len(price), 1)
        self.assertEqual(price[0]['delta_pct'], -15.0)
        self.assertFalse(any(c['field'] == 'text' and '34,000' in (c['after'] or '') for c in changes))
        self.assertEqual(fields.page_changes(old, old), [])

    def test_list_items_and_new_lines_are_changes(self):
        old = fields.extract(HOME, 'u', 'homepage')
        new = fields.extract(HOME.replace('<img alt="Vodafone" src="b.png">',
                                          '<img alt="Vodafone" src="b.png"><img alt="CIB" src="c.png">'), 'u', 'homepage')
        changes = fields.page_changes(old, new)
        self.assertIn({'field': 'clients:Client', 'kind': 'added', 'before': None, 'after': 'CIB'}, changes)

    def test_social_and_ad_changes(self):
        old = {'metrics': {'bio': 'Chatbots for SMEs', 'followers': 1000, 'posts_per_week': 4, 'avg_engagement': 20},
               'items': [{'id': '1'}]}
        new = {'metrics': {'bio': 'Chatbots for SMEs and enterprise', 'followers': 1200, 'posts_per_week': 1,
                           'avg_engagement': 20},
               'items': [{'id': '1'}, {'id': '2', 'format': 'reel', 'caption': 'Launch', 'engagement_total': 90, 'url': 'x'}]}
        kinds = {c['field'] for c in fields.social_changes(old, new)}
        self.assertEqual(kinds, {'bio', 'followers', 'posting_pace', 'top_post'})
        a = {'items': [{'id': 'a', 'active': True, 'headline': 'Old'}]}
        b = {'items': [{'id': 'a', 'active': False, 'headline': 'Old'}, {'id': 'b', 'active': True, 'headline': '50% off'}]}
        self.assertEqual(sorted((c['kind'], c['after'] or c['before']) for c in fields.ad_changes(a, b)),
                         [('added', '50% off'), ('removed', 'Old')])


class Metrics(unittest.TestCase):
    def test_engagement_rate_is_per_post_over_followers_for_30_days(self):
        now = datetime(2026, 10, 15, tzinfo=timezone.utc)
        posts = [collect.post('1', 'u1', now - timedelta(days=1), 'reel', 'Hi #ai', 90, 10),
                 collect.post('2', 'u2', now - timedelta(days=3), 'image', 'Yo', 40, 10),
                 collect.post('3', 'u3', now - timedelta(days=60), 'image', 'Old', 999, 0)]
        m = collect.post_metrics(posts, 1000, now=now)
        self.assertEqual(m['engagement_rate'], 7.5)      # (100/1000 + 50/1000) / 2
        self.assertEqual(m['posts_30d'], 2)
        self.assertEqual(m['format_mix'], {'reel': 1, 'image': 1})
        self.assertEqual(m['hashtags'], ['ai'])
        self.assertEqual(m['days_since_last_post'], 1)

    def test_counts_like_12k_are_read(self):
        self.assertEqual(collect.num('12.5K'), 12500)
        self.assertIsNone(collect.num(None))


class WatchFlow(unittest.TestCase):
    def setUp(self):
        os.environ['N8N_SHARED_TOKEN'] = 'n8n-test-token'
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)

        def database():
            with self.factory() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.saved = (engine.SessionLocal, scheduler.SessionLocal, collect.load_pages, engine.send_to_n8n)
        engine.SessionLocal = scheduler.SessionLocal = self.factory
        self.pages = {'https://nexa.ai': HOME, 'https://nexa.ai/pricing': pricing(), 'https://odynza.com': HOME}
        async def fake_load(urls):
            return {u: self.pages.get(u, collect.CollectError('The page did not load.')) for u in urls}
        collect.load_pages = fake_load
        self.sent = []
        async def fake_send(visit_id, mode='changes'):
            self.sent.append((visit_id, mode))
        engine.send_to_n8n = fake_send
        import tempfile
        from pathlib import Path
        from api.watch import pictures
        self.pictures_tmp = tempfile.TemporaryDirectory()
        self.fetched, self.links_work = [], True
        async def fake_fetch(url, accept='image/*', limit=None, total=35):
            self.fetched.append(url)
            if not self.links_work:
                raise HTTPException(502, 'expired')
            return PNG, url
        self.picture_patches = [unittest.mock.patch.object(pictures, 'DIR', Path(self.pictures_tmp.name)),
                                unittest.mock.patch('api.media.fetch_public', fake_fetch)]
        for p in self.picture_patches:
            p.start()
        self.client = TestClient(app, headers={'X-Radar-Token': 'n8n-test-token'})

    def test_an_unchanged_capture_still_takes_the_new_pictures_and_ad_versions(self):
        from db.watch_models import WatchClient
        ad = {'id': '7', 'page_name': 'PluginZ', 'body': 'Your business deserves more', 'images': []}
        data = {'text': '', 'fields': {}, 'metrics': {'live': 1}, 'items': [ad]}
        with self.factory() as db:
            client = WatchClient(name='Odynza'); db.add(client); db.flush()
            source = WatchSource(client_id=client.id, kind='ads', url='https://www.facebook.com/PluginZ'); db.add(source)
            visit = WatchVisit(client_id=client.id); db.add(visit); db.flush()
            first, _ = engine.store(db, visit, source, data)
            db.commit()
            again = {**data, 'items': [{**ad, 'images': ['https://scontent/v1.jpg'], 'cards': [{'image': 'https://scontent/v1.jpg'}]}]}
            snap, changes = engine.store(db, visit, source, again)
            db.commit()
            self.assertEqual((snap.id, changes), (first.id, []))
        with self.factory() as db:
            kept = db.get(WatchSnapshot, first.id)
            self.assertEqual(kept.items[0]['images'], ['https://scontent/v1.jpg'])
            self.assertEqual(len(kept.items[0]['cards']), 1)

    def tearDown(self):
        for p in self.picture_patches:
            p.stop()
        self.pictures_tmp.cleanup()
        os.environ.pop('N8N_SHARED_TOKEN', None)
        engine.SessionLocal, scheduler.SessionLocal, collect.load_pages, engine.send_to_n8n = self.saved
        app.dependency_overrides.pop(get_db, None)
        self.client.close()
        self.engine.dispose()

    def setup_register(self):
        r = self.client.put('/watch/client', json={'name': 'Odynza', 'website': 'odynza.com', 'claims': ['Arabic-first support'],
                                                   'channels': ['LinkedIn', 'Instagram']})
        self.assertEqual(r.status_code, 200, r.text)
        r = self.client.post('/watch/competitors', json={'name': 'Nexa AI', 'website': 'https://nexa.ai', 'tier': 'direct'})
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def visit(self):
        with self.factory() as db:
            ids = [s.id for s in db.query(WatchSource).all()]
        return asyncio.run(engine.run_visit(ids, 'run_now'))

    def test_a_second_client_is_kept_apart(self):
        self.setup_register()
        r = self.client.post('/watch/clients', json={'name': 'Shop', 'website': 'https://shop.eg'})
        self.assertEqual(r.status_code, 200, r.text)
        shop = r.json()['client']['id']
        self.assertEqual(self.client.get('/watch/competitors', headers={'X-Watch-Client': str(shop)}).json(), [])
        self.assertEqual([c['name'] for c in self.client.get('/watch/competitors').json()], ['Nexa AI'])
        info = self.client.get('/watch/client', headers={'X-Watch-Client': str(shop)}).json()
        self.assertEqual(info['client']['name'], 'Shop')
        self.assertEqual(sorted(c['name'] for c in info['clients']), ['Odynza', 'Shop'])
        self.assertEqual(self.client.post('/watch/clients', json={'name': 'Shop', 'website': 'https://x.eg'}).status_code, 409)
        r = self.client.put('/watch/client/logins', json={'usernames': ['nobody']}, headers={'X-Watch-Client': str(shop)})
        self.assertEqual(r.status_code, 422)

    def test_collected_pictures_are_saved_and_outlive_their_links(self):
        self.setup_register()
        self.visit()
        data = self.client.get('/watch/data').json()
        links = [i['url'] for c in data['companies'] for i in c['images']]
        self.assertTrue(links)
        self.assertTrue(set(links) <= set(self.fetched))      # saved while collecting, not when first viewed
        self.links_work, self.fetched = False, []             # the platform link has now expired
        r = self.client.get('/watch/image', params={'u': links[0]})
        self.assertEqual((r.status_code, r.content), (200, PNG))
        self.assertEqual(self.fetched, [])

    def test_logo_is_the_site_browser_tab_icon_and_is_saved(self):
        import api.routers.watch as watch_router
        self.setup_register()
        self.visit()
        icon = b'\x89PNG\r\n\x1a\n' + b'1' * 900
        watch_router._logos.clear()
        with unittest.mock.patch('api.logos.company_logo', unittest.mock.AsyncMock(return_value=(icon, 'image/png'))) as site:
            r = self.client.get('/watch/logo/client')
        self.assertEqual((r.status_code, r.content), (200, icon))
        self.assertEqual(site.await_args.args[0], 'https://odynza.com')
        watch_router._logos.clear()
        with unittest.mock.patch('api.logos.company_logo', unittest.mock.AsyncMock(return_value=None)):
            self.assertEqual(self.client.get('/watch/logo/client').content, icon)   # kept on disk

    def test_full_pipeline_from_capture_to_brief(self):
        comp = self.setup_register()
        with self.factory() as db:
            kinds = sorted((s.page_kind or s.kind, s.url) for s in db.query(WatchSource).filter_by(competitor_id=comp['id']))
        self.assertIn(('pricing', 'https://nexa.ai/pricing'), kinds)
        self.assertIn(('web', 'https://nexa.ai'), kinds)        # web and news mentions through Serper
        first = self.visit()                       # baseline, no changes
        with self.factory() as db:
            self.assertEqual(db.query(WatchChange).count(), 0)
            self.assertEqual(db.get(WatchVisit, first).status, 'done')
        self.assertEqual(self.sent, [])
        self.pages['https://nexa.ai/pricing'] = pricing('EGP 34,000')
        second = self.visit()
        self.assertEqual(self.sent, [(second, 'changes')])
        pack = self.client.get(f'/watch/n8n/visits/{second}/pack').json()
        price = next(c for c in pack['changes'] if c['field'] == 'price:Business')
        self.assertIn('(-15%)', price['after'])
        self.assertIn('Odynza', pack['profile'])
        # n8n posts back: one real signal, one without a consequence line (refused), one noise
        r = self.client.post(f'/watch/n8n/visits/{second}/signals', json={'model': 'test', 'signals': [
            {'change_id': price['change_id'], 'type': 'pricing', 'title': 'Nexa AI cut Business 15%',
             'meaning': 'They now undercut you.', 'score': 5, 'reason': 'Direct price pressure', 'claims': ['Lowest price']}]})
        self.assertEqual(r.json()['saved'], 1)
        others = [c['change_id'] for c in pack['changes'] if c['change_id'] != price['change_id']]
        if others:
            r = self.client.post(f'/watch/n8n/visits/{second}/signals', json={'signals': [
                {'change_id': others[0], 'type': 'claim', 'title': 'x', 'meaning': '', 'score': 2}]})
            self.assertEqual(len(r.json()['rejected']), 1)
        over = self.client.get('/watch/overview').json()
        self.assertEqual(over['items'][0]['title'], 'Nexa AI cut Business 15%')
        self.assertEqual(over['items'][0]['score'], 5)
        sid = over['items'][0]['id']
        r = self.client.patch(f'/watch/signals/{sid}/score', json={'score': 4, 'reason': 'Only one plan'})
        self.assertEqual(r.json()['ai_score'], 5)
        pack = self.client.get(f'/watch/n8n/visits/{second}/pack').json()
        self.assertIn('corrected it to 4', pack['corrections'])
        detail = self.client.get(f"/watch/competitors/{comp['id']}").json()
        self.assertTrue(detail['sources'] and all('healthy' in x for x in detail['sources']))
        ads = self.client.get('/watch/ads').json()['companies']
        self.assertTrue(ads and all('ads' in a and 'facebook' in a for a in ads))
        # The Collect buttons start a visit in the background (this once failed with "no running event loop").
        started = []

        async def fake_visit(ids, trigger):
            started.append((sorted(ids), trigger))
        with unittest.mock.patch.object(engine, 'run_visit', fake_visit):
            ids = [x['id'] for x in detail['sources']][:2]
            r = self.client.post('/watch/run', json={'source_ids': ids})
            self.assertEqual(r.status_code, 202, r.text)
            self.assertEqual(r.json()['sources'], 2)
        data = self.client.get('/watch/data').json()['companies']
        self.assertEqual(data[0]['key'], 'client')
        self.assertTrue(any(c['key'] == str(comp['id']) and c['pages'] for c in data))
        self.assertEqual(self.client.get('/watch/image', params={'u': 'https://evil.example/x.png'}).status_code, 404)
        self.assertEqual(self.client.get('/watch/logo/99999').status_code, 404)
        progress = self.client.get('/watch/client').json()['progress']
        self.assertGreater(progress['captures'], 0)
        self.assertGreater(progress['repeated'], 0)
        self.assertGreater(progress['signals'], 0)
        self.assertEqual(detail['timeline'][0]['evidence']['before'], 'EGP 40,000 / year')
        self.assertTrue(any(p['page_kind'] == 'pricing' for p in detail['pages']))
        claims = self.client.get('/watch/compare').json()['claims']
        lowest = next(c for c in claims if c['label'] == 'Lowest price')
        self.assertEqual(lowest['status'], 'contested')
        arabic = next(c for c in claims if c['label'] == 'Arabic-first support')
        self.assertEqual((arabic['status'], arabic['client_claims']), ('unclaimed', True))

        # Weekly brief: never padded, and opportunities need all fields, a future expiry and real evidence.
        week = scheduler.brief_week()
        with self.factory() as db:
            from db.watch_models import WatchBrief
            b = WatchBrief(client_id=1, week_start=week)
            db.add(b)
            db.commit()
            bid = b.id
        bpack = self.client.get(f'/watch/n8n/briefs/{bid}/pack').json()
        self.assertIn(f'[{sid}]', bpack['signals'])
        r = self.client.post(f'/watch/n8n/briefs/{bid}/result', json={'headline': 'Quiet', 'quiet': True, 'items': []})
        self.assertEqual(r.status_code, 422)
        good = {'rank': 1, 'angle': 'Own Arabic-first support', 'trigger': 'Unclaimed claim', 'claim': 'Arabic-first support',
                'audience': 'SMEs', 'why_now': 'Rivals discount', 'competitors_saying': 'Nobody', 'wrong_if': 'Nexa adds Arabic',
                'confidence': 'high', 'expires_on': (date.today() + timedelta(days=20)).isoformat(),
                'evidence': [f"claim:{arabic['id']}", str(sid)]}
        bad = {**good, 'rank': 2, 'wrong_if': '', 'evidence': ['999']}
        r = self.client.post(f'/watch/n8n/briefs/{bid}/result', json={
            'headline': 'Price is the fight', 'items': [{'signal_id': sid, 'move': 'Hold price'}, {'signal_id': 999}],
            'opportunities': [good, bad]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()['items'], r.json()['opportunities'], len(r.json()['refused'])), (1, 1, 1))
        briefs = self.client.get('/watch/briefs').json()['briefs']
        self.assertEqual(briefs[0]['items'][0]['score'], 4)    # the corrected score is used
        html = self.client.get(f'/watch/briefs/{bid}/view').text
        self.assertIn('What it means for you', html)
        opp = self.client.get('/watch/opportunities').json()[0]
        self.assertEqual(opp['claim'], 'Arabic-first support')
        sent = []

        async def webhook(_client, url, json=None, **_kw):
            sent.append((url, json))
            import httpx
            return httpx.Response(200, json={'message': 'Workflow was started'})
        with unittest.mock.patch('httpx.AsyncClient.post', webhook):
            r = self.client.post(f"/watch/opportunities/{opp['id']}/act", json={})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual((r.json()['status'], sent[0][0].endswith('/radar-strategy')), ('acted', True))
        with self.factory() as db:
            from db.database import StrategyPlan
            plan = db.get(StrategyPlan, r.json()['plan_id'])
            self.assertEqual((plan.inputs['version'], plan.inputs['opportunity_id'], plan.session_id), (2, opp['id'], ''))
        r = self.client.patch(f"/watch/opportunities/{opp['id']}", json={'status': 'rejected'})
        self.assertEqual(r.status_code, 409)      # already acted on

    def test_nothing_is_collected_before_a_person_confirms(self):
        self.client.put('/watch/client', json={'name': 'Odynza', 'website': 'odynza.com'})
        with self.factory() as db:
            db.add(WatchCompetitor(client_id=1, name='Proposed Co', website='https://p.co', status='proposed'))
            db.commit()
            comp = db.query(WatchCompetitor).filter_by(name='Proposed Co').one()
            engine.add_source(db, 1, comp.id, 'page', 'https://p.co', 'homepage')
            db.commit()
            due = [s.competitor_id for s in engine.due_sources(db)]
        self.assertNotIn(comp.id, due)
        r = self.client.post('/watch/run', json={'competitor_id': comp.id})
        self.assertFalse(r.json()['started'])

    def test_failed_source_is_shown_in_health_and_others_continue(self):
        self.setup_register()
        with self.factory() as db:
            engine.add_source(db, 1, 1, 'page', 'https://nexa.ai/missing', 'news')
            db.commit()
        self.visit()
        health = self.client.get('/watch/sources').json()
        bad = next(s for s in health['sources'] if s['url'].endswith('/missing'))
        self.assertIn('did not load', bad['last_error'])
        ok = next(s for s in health['sources'] if s['url'] == 'https://nexa.ai/pricing')
        self.assertTrue(ok['healthy'] and ok['last_success_at'])

    def test_apify_sources_pause_near_the_monthly_budget(self):
        self.setup_register()
        with self.factory() as db:
            engine.add_spend(db, 4.6)
            src = engine.add_source(db, 1, 1, 'linkedin', 'https://www.linkedin.com/company/nexa')
            db.commit()
            sid = src.id
        asyncio.run(engine.run_visit([sid]))
        with self.factory() as db:
            self.assertIn('reached $4.60 of $5', db.get(WatchSource, sid).last_error)

    def test_brief_week_starts_sunday_night_cairo(self):
        cairo = scheduler.CAIRO
        self.assertEqual(scheduler.brief_week(datetime(2026, 10, 18, 21, 0, tzinfo=cairo)), '2026-10-12')
        self.assertEqual(scheduler.brief_week(datetime(2026, 10, 18, 22, 30, tzinfo=cairo)), '2026-10-19')


@pytest.mark.real_auth
class ClientRole(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)

        def database():
            with self.factory() as db:
                yield db
        app.dependency_overrides[get_db] = database
        with self.factory() as db:
            db.add(User(username='odynza-client', password_hash=hash_password('correct horse battery'), role='client'))
            db.commit()
        self.client = TestClient(app)
        r = self.client.post('/auth/login', json={'username': 'odynza-client', 'password': 'correct horse battery'})
        self.assertEqual(r.status_code, 200, r.text)
        self.csrf = {'X-CSRF-Token': self.client.cookies.get(CSRF_COOKIE)}

    def tearDown(self):
        app.dependency_overrides.pop(get_db, None)
        self.client.close()
        self.engine.dispose()

    def test_client_sees_only_watch_and_cannot_change_the_profile(self):
        self.assertEqual(self.client.get('/content/runs').status_code, 403)
        self.assertEqual(self.client.get('/strategy/radar/plans').status_code, 403)
        self.assertEqual(self.client.get('/watch/client').status_code, 200)
        r = self.client.put('/watch/client', json={'name': 'X', 'website': 'x.com'}, headers=self.csrf)
        self.assertEqual(r.status_code, 403)
        r = self.client.patch('/watch/opportunities/1', json={'status': 'accepted'}, headers=self.csrf)
        self.assertEqual(r.status_code, 404)    # allowed to decide; this one simply does not exist


class MultiClient(ClientRole):
    """Several clients: a client login sees only the client it is linked to, whatever the UI asks for."""

    def test_client_login_is_held_to_its_own_client(self):
        from db.watch_models import WatchAccess, WatchClient
        with self.factory() as db:
            a, b = WatchClient(name='Odynza', website='https://odynza.com'), WatchClient(name='Shop', website='https://shop.eg')
            db.add_all([a, b]); db.commit()
            ca = WatchCompetitor(client_id=a.id, name='Rival A', website='https://a.eg', tier='direct', status='confirmed')
            cb = WatchCompetitor(client_id=b.id, name='Rival B', website='https://b.eg', tier='direct', status='confirmed')
            db.add_all([ca, cb, WatchAccess(client_id=b.id, username='odynza-client')]); db.commit()
            a_id, b_id, ca_id = a.id, b.id, ca.id
        info = self.client.get('/watch/client', headers={'X-Watch-Client': str(a_id)}).json()
        self.assertEqual(info['client']['name'], 'Shop')
        self.assertEqual([c['id'] for c in info['clients']], [b_id])
        names = [c['name'] for c in self.client.get('/watch/competitors', headers={'X-Watch-Client': str(a_id)}).json()]
        self.assertEqual(names, ['Rival B'])
        self.assertEqual(self.client.get(f'/watch/competitors/{ca_id}').status_code, 404)
        r = self.client.post('/watch/clients', json={'name': 'New', 'website': 'https://new.eg'}, headers=self.csrf)
        self.assertEqual(r.status_code, 403)


class Mentions(unittest.TestCase):
    """Web and news mentions through Serper: other sites only, and a result counts once."""

    def serper(self, news, web):
        import httpx

        def handler(request):
            body = {'news': news} if request.url.path == '/news' else {'organic': web}
            return httpx.Response(200, json=body)
        return httpx.AsyncClient(transport=httpx.MockTransport(handler))

    def test_mentions_skip_the_company_site_and_need_a_key(self):
        news = [{'title': 'Nexa raises a round', 'link': 'https://news.example/nexa', 'source': 'Enterprise', 'date': '2 days ago'}]
        web = [{'title': 'Nexa pricing', 'link': 'https://www.nexa.ai/pricing'}, {'title': 'Review', 'link': 'https://blog.example/r'},
               {'title': 'Nexa on Instagram', 'link': 'https://www.instagram.com/nexa/'}]
        with unittest.mock.patch.dict(os.environ, {'SERPER_API_KEY': 'k'}):
            data = asyncio.run(collect.web_mentions('Nexa', 'https://nexa.ai', self.serper(news, web)))
        self.assertEqual([i['url'] for i in data['items']], ['https://news.example/nexa', 'https://blog.example/r'])
        self.assertEqual(data['metrics']['news'], 1)
        with unittest.mock.patch.dict(os.environ, {'SERPER_API_KEY': ''}):
            with self.assertRaises(collect.CollectError):
                asyncio.run(collect.web_mentions('Nexa', 'https://nexa.ai'))

    def test_a_mention_is_a_change_once(self):
        a = {'id': 'https://a.example/1', 'kind': 'news', 'site': 'A', 'title': 'Nexa opens in Alexandria', 'url': 'https://a.example/1'}
        b = {'id': 'https://b.example/2', 'kind': 'web', 'site': 'B', 'title': 'Nexa review', 'url': 'https://b.example/2'}
        first = {'items': [a], 'metrics': {}}
        fields.mention_changes({'items': [], 'metrics': {}}, first)
        second = {'items': [b], 'metrics': {}}
        changes = fields.mention_changes(first, second)
        self.assertEqual(len(changes), 1)
        self.assertIn('Nexa review', changes[0]['after'])
        third = {'items': [a, b], 'metrics': {}}
        self.assertEqual(fields.mention_changes(second, third), [])


class AdsAndPages(unittest.TestCase):
    """Ads are kept only when the watched page ran them; legal pages are never proposed."""

    class FakeApify:
        def __init__(self, rows):
            self.rows = rows

        async def run(self, actor, payload, max_usd, limit=None):
            return self.rows, 0.01

    @staticmethod
    def row(ad_id, page_name, page_id, uri='', active=True, likes=None):
        return {'ad_archive_id': ad_id, 'page_name': page_name, 'page_id': page_id, 'is_active': active,
                'start_date': '2026-10-01', 'publisher_platform': ['facebook'],
                'snapshot': {'page_profile_uri': uri, 'page_like_count': likes, 'body': {'text': f'ad {ad_id}'}}}

    def test_only_the_watched_pages_ads_are_kept(self):
        rows = [self.row('1', 'Botpress', '111', 'https://www.facebook.com/botpress/', likes=15000),
                self.row('2', 'AI Tools Egypt', '999', 'https://www.facebook.com/aitoolseg', likes=90000),
                self.row('3', 'The Book of Eli', '888', 'https://www.facebook.com/thebookofeli37'),
                self.row('4', 'Botpress Inc.', '111')]
        data = asyncio.run(collect.ads('https://www.facebook.com/botpress/', self.FakeApify(rows), 5.0, 'Botpress'))
        self.assertEqual([a['id'] for a in data['items']], ['1', '4'])
        self.assertEqual(data['metrics']['page_likes'], 15000)
        self.assertEqual(data['metrics']['other_pages_dropped'], 2)
        none = asyncio.run(collect.ads('https://www.facebook.com/odynza', self.FakeApify(rows[1:3]), 5.0, 'Odynza'))
        self.assertEqual(none['items'], [])
        self.assertEqual(none['metrics']['live_ads'], 0)

    def test_terms_and_privacy_are_never_proposed_and_the_url_beats_link_text(self):
        html = """<a href="/terms">Terms of Service</a> <a href="/privacy-policy">Privacy</a>
        <a href="/services/crm-erp-ready-systems">Plans and packages</a> <a href="/services">Services</a>
        <a href="/case-studies">Our work</a>"""
        kinds = {p['page_kind']: p['url'] for p in fields.propose_pages(html, 'https://shop.eg', 'adjacent')}
        self.assertEqual(kinds['services'], 'https://shop.eg/services')
        self.assertNotIn('pricing', kinds)
        self.assertNotIn('terms', ' '.join(kinds.values()))
        self.assertEqual(kinds['clients'], 'https://shop.eg/case-studies')


class Pictures(unittest.TestCase):
    """Logos and pictures are kept, but never count as a change."""

    def test_page_logo_and_pictures_are_found(self):
        html = """<html><head><meta property="og:image" content="/share.jpg"></head><body>
        <header><a href="/"><img src="/img/logo.svg" alt="Nexa logo"></a></header>
        <img src="/team.jpg" width="600"><img src="/px.gif" width="1" height="1"><img data-src="https://cdn.x.eg/hero.webp">
        <img src="/icons/arrow.png"></body></html>"""
        out = fields.page_images(html, 'https://nexa.ai/')
        self.assertEqual(out['logo'], 'https://nexa.ai/img/logo.svg')
        self.assertEqual(out['images'], ['https://nexa.ai/share.jpg', 'https://nexa.ai/team.jpg', 'https://cdn.x.eg/hero.webp'])

    def test_site_pictures_are_labelled_from_page_clues_and_kept_with_their_section(self):
        html = """<html><body><header><img src="/brand/logo.png" alt="Nexa"></header>
        <h2>Trusted by leading Egyptian brands</h2><p>Over 200 companies answer faster with Nexa.</p>
        <div class="logos"><img src="/c/bank-misr.svg"><img src="/c/vodafone.svg"><img src="/c/noon.png"><img src="/c/fawry.png"></div>
        <h2>Our technology partners</h2><div><img src="/p/aws-partner-badge.png" alt="AWS partner"><img src="/p/meta.svg">
        <img src="/p/google.svg"><img src="/p/hubspot.svg"></div>
        <h2>See it work</h2><p>The dashboard shows every chat in one place.</p><img src="/shots/dashboard-screenshot.png" width="900">
        <h2>Meet the team</h2><img src="/people/ahmed-founder.jpg" alt="Ahmed, founder"></body></html>"""
        out = fields.page_images(html, 'https://nexa.ai/')
        kinds = {p['url'].rsplit('/', 1)[-1]: p['kind'] for p in out['pictures']}
        self.assertEqual(kinds['logo.png'], 'brand_logo')
        self.assertEqual(kinds['vodafone.svg'], 'client_logo')
        self.assertEqual(kinds['aws-partner-badge.png'], 'partner_logo')
        self.assertEqual(kinds['meta.svg'], 'partner_logo')
        self.assertEqual(kinds['dashboard-screenshot.png'], 'product')
        self.assertEqual(kinds['ahmed-founder.jpg'], 'team')
        named = {p['url'].rsplit('/', 1)[-1]: p['name'] for p in out['pictures']}
        self.assertEqual(named['vodafone.svg'], 'Client logo: vodafone')
        section = next(x for x in out['sections'] if x['heading'].startswith('Trusted'))
        self.assertIn('200 companies', section['text'])
        self.assertEqual(len(section['pictures']), 4)
        self.assertNotIn('https://nexa.ai/c/noon.png', out['images'])   # logos stay out of the cover pictures

    def test_ad_pictures_come_from_image_video_and_card_records(self):
        s = {'images': [{'original_image_url': 'https://scontent/a.jpg', 'resized_image_url': 'https://scontent/a_s.jpg'}],
             'videos': [{'video_hd_url': 'https://video/v.mp4', 'video_preview_image_url': 'https://scontent/v.jpg'}],
             'cards': [{'original_image_url': 'https://scontent/c1.jpg', 'title': 'Card one', 'body': 'Hi', 'cta_text': 'Shop'}]}
        self.assertEqual(collect.ad_images(s), ['https://scontent/a.jpg', 'https://scontent/v.jpg', 'https://scontent/c1.jpg'])
        self.assertEqual(collect.ad_cards(s)[0]['title'], 'Card one')
        self.assertEqual(collect.ad_images({'images': ['https://x/plain.jpg']}), ['https://x/plain.jpg'])

    def test_facebook_photo_pages_are_not_taken_for_pictures(self):
        media = [{'__typename': 'Photo', 'url': 'https://www.facebook.com/photo/?fbid=1&set=a.2',
                  'thumbnail': 'https://scontent.fcai1-1.fna.fbcdn.net/t.jpg',
                  'photo_image': {'uri': 'https://scontent.fcai1-1.fna.fbcdn.net/full.jpg'}},
                 {'url': 'https://www.facebook.com/reel/123'}, 'https://www.facebook.com/Odynza/posts/9']
        self.assertEqual(collect.pictures(media), ['https://scontent.fcai1-1.fna.fbcdn.net/full.jpg'])

    def test_post_page_links_saved_by_older_collectors_are_removed(self):
        from types import SimpleNamespace
        from api.watch import pictures
        snap = SimpleNamespace(metrics={'images': ['https://www.facebook.com/photo/?fbid=1', 'https://cdn.x/a.jpg']},
                               items=[{'url': 'p1', 'images': ['https://www.facebook.com/reel/9/', 'https://scontent/b.jpg']},
                                      {'url': 'p2', 'images': ['https://scontent/c.jpg']}])
        commits = []
        db = SimpleNamespace(query=lambda _m: SimpleNamespace(all=lambda: [snap]), commit=lambda: commits.append(1))
        self.assertEqual(pictures.drop_page_links(db), 1)
        self.assertEqual(snap.metrics['images'], ['https://cdn.x/a.jpg'])
        self.assertEqual([i['images'] for i in snap.items], [['https://scontent/b.jpg'], ['https://scontent/c.jpg']])
        self.assertEqual(pictures.drop_page_links(db), 0)
        self.assertEqual(commits, [1])

    def test_news_results_get_the_articles_picture_and_summary(self):
        page = (b'<html><head><meta property="og:image" content="/img/cover.jpg">'
                b'<meta content="Pluginz opens a Riyadh office and hires 40 engineers." property="og:description">'
                b'<meta property="og:site_name" content="Enterprise"></head></html>')

        async def fake(url, accept='image/*', limit=None, total=35):
            if 'blocked' in url:
                raise HTTPException(502, 'no')
            return page, 'https://news.eg/a/1'
        items = [{'url': 'https://news.eg/a/1', 'snippet': 'Pluginz opens', 'images': []},
                 {'url': 'https://blocked.eg/b', 'snippet': 'kept as is', 'images': []}]
        with unittest.mock.patch.dict(os.environ, {'WATCH_PREVIEWS': '1'}), unittest.mock.patch('api.media.fetch_public', fake):
            asyncio.run(collect.add_previews(items))
        self.assertEqual(items[0]['images'], ['https://news.eg/img/cover.jpg'])
        self.assertIn('Riyadh office', items[0]['summary'])
        self.assertEqual(items[0]['site_name'], 'Enterprise')
        self.assertEqual(items[1], {'url': 'https://blocked.eg/b', 'snippet': 'kept as is', 'images': []})

    def test_page_screenshots_are_real_files_and_only_the_newest_five_are_kept(self):
        import tempfile
        from pathlib import Path
        from api.watch import pictures
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(pictures, 'SHOT_DIR', Path(tmp)):
            keys = [pictures.keep_shot('https://pluginz.co/partners', b'jpeg%d' % n, datetime(2026, 10, n + 1, 9, 30)) for n in range(7)]
            self.assertEqual(keys[-1], 'shot:pluginz-co/partners/2026-10-07_0930.jpg')
            self.assertEqual(len(list(Path(tmp, 'pluginz-co', 'partners').glob('*.jpg'))), 5)
            self.assertEqual(pictures.shot(keys[-1]), b'jpeg6')
            self.assertIsNone(pictures.shot(keys[0]))   # pruned
            self.assertIsNone(pictures.shot('shot:../../secrets/x/2026-10-07_0930.jpg'))
            self.assertEqual(pictures.keep_shot('https://odynza.com', b'x', datetime(2026, 10, 1)), 'shot:odynza-com/home/2026-10-01_0000.jpg')

    def test_pictures_get_a_readable_copy_per_company_and_platform(self):
        import tempfile
        from pathlib import Path
        from api.watch import pictures
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.object(pictures, 'LIBRARY', Path(tmp)):
            rows = pictures.library_entries('PluginZ Solutions', 'facebook', {'avatar': 'https://cdn/a.jpg'},
                                            [{'date': '2026-10-21T09:00:00', 'caption': 'Day 5 of 7: IT Operations.', 'images': ['https://cdn/p1.jpg', 'https://cdn/p2.jpg']}])
            names = [str(f.relative_to(tmp)).replace('\\', '/') for _, f in rows]
            self.assertEqual(names[0], 'pluginz-solutions/facebook/profile-picture')
            self.assertTrue(names[1].startswith('pluginz-solutions/facebook/2026-10-21_day-5-of-7-it-operations_1-'))
            page = pictures.library_entries('Pluginz', 'page', {'pictures': [{'url': 'https://p.co/v.svg', 'name': 'Client logo: vodafone'}]}, [], 'https://pluginz.co/partners')
            self.assertEqual(str(page[0][1].relative_to(tmp)).replace('\\', '/'), 'pluginz/website/partners_client-logo-vodafone_1')

    def test_multi_version_ads_keep_every_version_picture_and_ask_for_metas_own_records(self):
        seen = {}

        class Apify(AdsAndPages.FakeApify):
            async def run(self, actor, payload, max_usd, limit=None):
                seen.update(payload)
                return self.rows, 0.01
        row = AdsAndPages.row('7', 'PluginZ Solutions', '55', 'https://www.facebook.com/PluginZSolutions/')
        row['snapshot'].update({'display_format': 'DCO', 'images': [], 'cards': [
            {'title': 'All your IT', 'original_image_url': 'https://scontent/v1.jpg'},
            {'title': 'Focus on your business', 'resized_image_url': 'https://scontent/v2.jpg'}],
            'extra_images': [{'original_image_url': 'https://scontent/v3.jpg'}]})
        data = asyncio.run(collect.ads('https://www.facebook.com/PluginZSolutions', Apify([row]), 5.0, 'PluginZ'))
        self.assertTrue(seen['raw'])
        self.assertEqual(data['items'][0]['images'], ['https://scontent/v1.jpg', 'https://scontent/v2.jpg', 'https://scontent/v3.jpg'])
        self.assertEqual(len(data['items'][0]['cards']), 2)
        self.assertEqual(data['metrics']['media_keys'], [])
        bare = AdsAndPages.row('8', 'PluginZ Solutions', '55')
        bare['snapshot']['images'] = []
        none = asyncio.run(collect.ads('https://www.facebook.com/PluginZSolutions', Apify([bare]), 5.0, 'PluginZ'))
        self.assertEqual(none['metrics']['media_keys'], ['images'])

    def test_instagram_falls_back_to_apify_when_meta_gives_no_posts(self):
        from unittest.mock import patch

        async def meta(username):
            return {'text': '', 'fields': {}, 'metrics': {'followers': 2}, 'items': [], 'cost': 0.0}
        rows = [{'followersCount': 150, 'latestPosts': [{'id': '1', 'url': 'https://www.instagram.com/p/1', 'type': 'Image',
                                                         'caption': 'Hi', 'likesCount': 4,
                                                         'displayUrl': 'https://scontent.cdninstagram.com/1.jpg'}]}]
        env = {'META_ACCESS_TOKEN': 'token', 'META_IG_USER_ID': '1', 'APIFY_API_TOKEN': 'set'}
        with patch.dict('os.environ', env), patch.object(collect, 'instagram_meta', meta):
            data = asyncio.run(collect.instagram('https://www.instagram.com/odynza', AdsAndPages.FakeApify(rows), 1.0))
        self.assertEqual(data['items'][0]['images'], ['https://scontent.cdninstagram.com/1.jpg'])

    def test_instagram_adds_the_post_and_reel_scrapers_and_keeps_each_post_once(self):
        calls = []

        class Apify:
            async def run(self, actor_id, payload, max_usd, limit=50):
                calls.append((actor_id, payload))
                if 'profile' in actor_id:
                    return [{'followersCount': 900, 'latestPosts': [{'id': '1', 'shortCode': 'A', 'type': 'Image', 'timestamp': '2026-10-20T10:00:00Z',
                                                                   'likesCount': 5, 'displayUrl': 'https://scontent.cdninstagram.com/a.jpg'}]}], 0.01
                if 'post' in actor_id:
                    return [{'id': '1', 'shortCode': 'A', 'type': 'Image', 'timestamp': '2026-10-20T10:00:00Z'},
                            {'id': '2', 'shortCode': 'B', 'type': 'Sidecar', 'timestamp': '2026-09-01T10:00:00Z',
                             'images': ['https://scontent.cdninstagram.com/b1.jpg', 'https://scontent.cdninstagram.com/b2.jpg']}], 0.02
                raise collect.CollectError('Apify answered HTTP 500.')
        with unittest.mock.patch.dict(os.environ, {'META_ACCESS_TOKEN': '', 'META_IG_USER_ID': ''}):
            data = asyncio.run(collect.instagram('https://www.instagram.com/pluginz', Apify(), 0.9))
        self.assertEqual([c[0] for c in calls], ['apify~instagram-profile-scraper', 'apify~instagram-post-scraper', 'apify~instagram-reel-scraper'])
        self.assertEqual(calls[1][1], {'username': ['pluginz'], 'resultsLimit': 24})
        self.assertEqual([p['id'] for p in data['items']], ['1', '2'])
        self.assertEqual(data['items'][1]['url'], 'https://www.instagram.com/p/B/')
        self.assertEqual(data['items'][1]['format'], 'carousel')
        self.assertAlmostEqual(data['cost'], 0.03)
        self.assertIn('reels', data['metrics']['missed'][0])
        with unittest.mock.patch.dict(os.environ, {'WATCH_IG_POSTS': '0', 'WATCH_IG_REELS': '0', 'META_ACCESS_TOKEN': ''}):
            calls.clear()
            asyncio.run(collect.instagram('https://www.instagram.com/pluginz', Apify(), 0.9))
        self.assertEqual(len(calls), 1)

    def test_an_old_post_found_by_a_deeper_scrape_is_not_a_top_post_change(self):
        old = {'metrics': {}, 'items': []}
        new = {'metrics': {'avg_engagement': 10}, 'items': [{'id': '9', 'engagement_total': 500, 'date': '2026-01-01T00:00:00', 'caption': 'old'}]}
        self.assertEqual(fields.social_changes(old, new), [])

    def test_post_pictures_do_not_change_the_hash(self):
        a = collect.post('1', 'https://x/p/1', None, 'image', 'Hi', 3, 1, images=['https://cdn/a.jpg?sig=1', {'url': 'https://cdn/b.jpg'}])
        b = collect.post('1', 'https://x/p/1', None, 'image', 'Hi', 3, 1, images=['https://cdn/a.jpg?sig=2'])
        self.assertEqual(a['images'], ['https://cdn/a.jpg?sig=1', 'https://cdn/b.jpg'])
        self.assertEqual(fields.content_hash('', {}, {}, [a]), fields.content_hash('', {}, {}, [b]))
        self.assertEqual(collect.with_avatar({}, None, {'url': 'https://cdn/logo.png'}), {'avatar': 'https://cdn/logo.png'})
