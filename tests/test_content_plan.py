"""M2 Content from a Radar plan: slots from the plan rhythm, the pack, drafts and the media buying plan."""
import unittest
from datetime import date
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.watch_models  # noqa: F401
from api.content_plan import plan_slots, slot_days
from api.main import app
from api.strategy_plan import clean
from db.database import Base, ContentItem, ContentRun, StrategyPlan, get_db
from db.watch_models import WatchClient
from tests.test_radar_plans import END, START, plan_body

INPUTS = {'version': 2, 'client_id': 1, 'goal': 'Leads', 'start_date': START, 'end_date': END, 'budget': 20000,
          'budget_total': 59210.53, 'currency': 'EGP', 'paid': ['Meta ads', 'LinkedIn ads'],
          'voices': {'LinkedIn': {'key': 'formal', 'label': 'Formal expert', 'style': 'Clear'},
                     'Instagram': {'key': 'funky', 'label': 'Funky and bold', 'style': 'Playful'},
                     'Facebook': {'key': 'friendly', 'label': 'Friendly guide', 'style': 'Warm'}}}


def saved_plan():
    body = plan_body()
    body['content_plan']['rhythm'] = [{'platform': 'LinkedIn', 'per_week': 2, 'best_slots': ['Tue 10:30']},
                                      {'platform': 'Instagram', 'per_week': 3}, {'platform': 'Facebook', 'per_week': 2}]
    plan, _ = clean(body, INPUTS)
    return plan


class ContentRadar(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(WatchClient(name='Odynza', website='https://odynza.com', claims=['Arabic-first support']))
            db.add(StrategyPlan(id='a' * 8 + '-1111-2222-3333-' + 'b' * 12, session_id='', company_id='watch:1',
                                company_name='Odynza', status='completed', inputs=INPUTS, plan=saved_plan()))
            db.commit()
        self.pid = 'a' * 8 + '-1111-2222-3333-' + 'b' * 12

        def database():
            with self.factory() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.env = patch.dict('os.environ', {'N8N_SHARED_TOKEN': 'test-token', 'CLOUDFLARE_ACCOUNT_ID': '',
                                             'CLOUDFLARE_API_TOKEN': '', 'IMAGE_PROVIDER': 'gemini'})
        self.env.start()
        self.client = TestClient(app, headers={'X-Radar-Token': 'test-token'})
        self.calls = []

    def tearDown(self):
        self.env.stop()
        app.dependency_overrides.pop(get_db, None)

    def start(self, **body):
        calls = self.calls

        async def post(_client, url, json=None, **_kw):
            calls.append((url, json))
            return httpx.Response(200, json={})
        with patch('httpx.AsyncClient.post', post):
            return self.client.post('/content/runs', json={'plan_id': self.pid, 'platforms': ['LinkedIn', 'Instagram', 'Facebook'],
                                                           'start_date': '2026-11-08', 'weeks': 1, 'stories_per_week': 2,
                                                           'reels_per_month': 1, **body})

    def test_defaults_come_from_the_plan_rhythm(self):
        d = self.client.get(f'/content/plans/{self.pid}/defaults').json()
        self.assertEqual((d['version'], d['rhythm'], d['media_buying']), (2, {'LinkedIn': 2, 'Instagram': 3, 'Facebook': 2}, True))
        self.assertEqual(set(d['paid_budget']), {'Meta ads', 'LinkedIn ads'})

    def test_slots_use_best_days_reels_and_stories(self):
        days = slot_days(date(2026, 11, 8), 1, 2, ['Tue 10:30'])
        self.assertEqual([d.weekday() for d in days], [6, 1])   # Sunday from the defaults, Tuesday from the plan
        slots = plan_slots(saved_plan(), ['LinkedIn', 'Instagram'], date(2026, 11, 8), 1, {}, 1, 2)
        li = [s for s in slots if s['platform'] == 'LinkedIn']
        self.assertEqual(next(s['time'] for s in li if date.fromisoformat(s['date']).weekday() == 1), '10:30')
        formats = [s['format'] for s in slots if s['platform'] == 'Instagram']
        self.assertEqual((formats.count('reel'), formats.count('story')), (1, 2))
        self.assertTrue(any('Cairo ICT' in s['plan_action'] for s in slots))

    def test_batch_round_trip_with_media_buying(self):
        r = self.start()
        self.assertEqual(r.status_code, 202, r.text)
        self.assertTrue(self.calls[0][0].endswith('/radar-content'))
        rid = r.json()['run_id']
        pack = self.client.get(f'/content/runs/{rid}/pack').json()
        self.assertIn('Funky and bold', pack['voice']['Instagram'])
        self.assertIn('Egyptian Arabic', pack['voice']['Facebook'])
        self.assertIn('Arabic-first support', pack['proof'])
        self.assertIn('Meta ads', pack['media_buying'])
        self.assertTrue(pack['make_media_buying'])
        with self.factory() as db:
            from db.database import ContentRun
            story = next(x['slot_id'] for x in db.get(ContentRun, rid).inputs['slots'] if x['format'] == 'story')
        posts = [{'slot_id': story, 'text': 'جرب أودينزا', 'slides': [{'headline': 'إطار 1', 'body': 'poll'}]},
                 {'slot_id': 'li-2026-11-08', 'text': 'Proof, not promises.', 'hashtags': ['ai']}]
        buying = {'summary': 'Meta for leads, LinkedIn for decision makers.', 'campaigns': [
            {'platform': 'Meta', 'name': 'Leads', 'campaign_id': 'C1', 'budget_percent': 70, 'ad_sets': [
                {'name': 'Cairo SMEs', 'budget_percent': 3, 'ads': [{'name': 'A', 'draft_slot_id': story}]},
                {'name': 'Retarget', 'budget_percent': 1, 'ads': [{'name': 'B', 'draft_slot_id': 'nope'}]}]},
            {'platform': 'Meta ads', 'name': 'Awareness', 'budget_percent': 30},
            {'platform': 'TikTok ads', 'name': 'Not allowed'}],
            'checklist': ['Book the shoot']}
        r = self.client.post(f'/content/runs/{rid}/result', json={'posts': posts, 'media_buying': buying})
        self.assertEqual(r.status_code, 200, r.text)
        run = self.client.get(f'/content/runs/{rid}').json()
        st = next(i for i in run['items'] if i['format'] == 'story')
        self.assertEqual(st['aspect'], '9:16')
        mb = run['media_buying']
        self.assertEqual([c['name'] for c in mb['campaigns']], ['Leads', 'Awareness'])
        leads = mb['campaigns'][0]
        self.assertEqual(leads['start_date'], START)          # campaign C1 starts before the plan; kept inside it
        self.assertAlmostEqual(leads['amount'], mb['budget']['Meta ads'] * 0.7, places=1)
        self.assertEqual([a['budget_percent'] for a in leads['ad_sets']], [75, 25])
        self.assertEqual(leads['ad_sets'][1]['ads'][0]['draft_slot_id'], '')
        self.assertIn('Book the shoot', mb['checklist'])
        self.assertTrue(mb['benchmarks'])
        with self.factory() as db:
            self.assertEqual(db.query(ContentItem).count(), 2)

    def test_run_again_copies_the_settings_and_delete_removes_the_batch(self):
        first = self.start()
        self.assertEqual(first.status_code, 202, first.text)
        rid = first.json()['run_id']
        calls = self.calls

        async def post(_client, url, json=None, **_kw):
            calls.append((url, json))
            return httpx.Response(200, json={})
        class Later(date):
            @classmethod
            def today(cls):
                return date(2026, 11, 20)   # the old start date is now in the past
        with patch('httpx.AsyncClient.post', post), patch('api.routers.content.date', Later):
            again = self.client.post(f'/content/runs/{rid}/again')
        self.assertEqual(again.status_code, 202, again.text)
        new = again.json()['run_id']
        self.assertNotEqual(new, rid)
        with self.factory() as db:
            old, fresh = db.get(ContentRun, rid), db.get(ContentRun, new)
            self.assertEqual(fresh.plan_id, old.plan_id)
            self.assertEqual(fresh.inputs['platforms'], old.inputs['platforms'])
            self.assertEqual(fresh.inputs['stories_per_week'], 2)
            self.assertNotEqual(fresh.inputs.get('start_date'), '2026-11-08')
        self.assertEqual(self.client.delete(f'/content/runs/{rid}').status_code, 200)
        self.assertEqual(self.client.get(f'/content/runs/{rid}').status_code, 404)
        self.assertEqual(self.client.post('/content/runs/nope/again').status_code, 404)
