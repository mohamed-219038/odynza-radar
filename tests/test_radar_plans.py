"""M1 Strategy from Radar (plan version 2): defaults, the n8n handoff and pack, the clean-up before saving and the
results report. Isolated database, n8n mocked, no model calls."""
import unittest
from datetime import date, timedelta
from unittest.mock import patch

import httpx
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import db.watch_models  # noqa: F401
from api.main import app
from api.strategy_plan import clean, events_between, months_between
from db.database import Base, StrategyPlan, get_db
from db.watch_models import WatchClient, WatchCompetitor

START, END = '2026-11-01', '2027-01-29'
FORM = {'goal': 'Leads', 'objective': '40 demo requests', 'budget': 20000, 'currency': 'egp', 'start_date': START,
        'end_date': END, 'voices': {'LinkedIn': {'key': 'formal'}, 'Instagram': {'key': 'custom', 'custom': 'Cheeky Cairo slang'}}}


def plan_body():
    return {
        'overview': {'summary': 'Own Arabic-first AI support before rivals do.', 'smart_goal': '40 demos by Jan 29'},
        'competitive_brief': {'landscape': 'Crowded on price.', 'rivals': [{'name': 'Nexa', 'threat': 'high'}],
                              'positioning_map': {'points': [{'company': 'Odynza', 'x': 140, 'y': -5, 'you': True}]}},
        'positioning': {'statement': 'For Egyptian SMEs, Odynza is the AI team that speaks Arabic.',
                        'statement_ar': 'أودينزا', 'pillars': [{'name': 'Arabic first'}],
                        'by_platform': [{'platform': 'LinkedIn', 'line': 'Proof, not promises.'}, {'platform': 'TikTok', 'line': 'x'}]},
        'campaigns': [{'id': 'C1', 'name': 'Ramadan ready', 'start_date': '2026-10-01', 'end_date': '2026-12-15',
                       'budget_percent': 30, 'channels': ['Meta ads', 'Meta ads', 'LinkedIn'], 'visual_prompt': 'Lantern'},
                      {'id': 'C1', 'name': 'Year end', 'start_date': '2026-12-01', 'end_date': '2027-03-01', 'budget_percent': 30}],
        'calendar': [{'date': '2026-11-05', 'title': 'Launch post', 'kind': 'content', 'campaign_id': 'C1'},
                     {'date': '2026-12-25', 'title': 'Made-up holiday', 'kind': 'holiday'},
                     {'date': '2027-05-01', 'title': 'Too late', 'kind': 'content'}],
        'content_plan': {'mix': [{'label': 'Proof', 'percent': 3}, {'label': 'Tips', 'percent': 1}],
                         'rhythm': [{'platform': 'Instagram', 'per_week': 40}]},
        'budget': [{'channel': 'Meta ads', 'percent': 50}, {'channel': 'LinkedIn ads', 'percent': 30},
                   {'channel': 'Contingency', 'percent': 40}],
        'kpis': [{'name': 'Qualified leads', 'target': '40 leads', 'campaign_id': 'C9'},
                 {'name': 'Cost per lead', 'target': 'EGP 400'}],
    }


class RadarPlans(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        with self.factory() as db:
            db.add(WatchClient(name='Odynza', website='https://odynza.com', audience='Egyptian SMEs'))
            db.add(WatchCompetitor(client_id=1, name='Nexa', website='https://nexa.ai', status='confirmed', tier='direct'))
            db.commit()

        def database():
            with self.factory() as db:
                yield db
        app.dependency_overrides[get_db] = database
        self.env = patch.dict('os.environ', {'N8N_SHARED_TOKEN': 'test-token'})
        self.env.start()
        self.client = TestClient(app, headers={'X-Radar-Token': 'test-token', 'X-CSRF-Token': 'test-csrf'})
        self.calls = []

    def tearDown(self):
        self.env.stop()
        app.dependency_overrides.pop(get_db, None)

    def create(self, **changes):
        calls = self.calls

        async def post(_client, url, json=None, **_kw):
            calls.append((url, json))
            return httpx.Response(200, json={'message': 'Workflow was started'})
        with patch('httpx.AsyncClient.post', post):
            return self.client.post('/strategy/radar/plans', json={**FORM, **changes})

    def test_defaults_suggest_a_voice_per_platform_and_list_the_events(self):
        d = self.client.get('/strategy/radar/defaults').json()
        self.assertEqual({p: v['suggested'] for p, v in d['voices'].items()},
                         {'LinkedIn': 'formal', 'Instagram': 'funky', 'Facebook': 'friendly'})
        self.assertEqual((d['budget'], d['currency']), (20000, 'EGP'))
        self.assertEqual((date.fromisoformat(d['end_date']) - date.fromisoformat(d['start_date'])).days, 89)
        self.assertTrue(all('confirmed' in e for e in d['events']))

    def test_a_plan_starts_the_radar_workflow_with_voices_and_budget(self):
        r = self.create()
        self.assertEqual(r.status_code, 202, r.text)
        url, payload = self.calls[0]
        self.assertTrue(url.endswith('/webhook/radar-strategy'))
        self.assertEqual(set(payload), {'plan_id', 'app_base_url', 'version'})
        with self.factory() as db:
            plan = db.get(StrategyPlan, r.json()['plan_id'])
            voices = plan.inputs['voices']
        self.assertEqual(voices['LinkedIn']['label'], 'Formal expert')
        self.assertEqual((voices['Instagram']['label'], voices['Instagram']['style']), ('Custom voice', 'Cheeky Cairo slang'))
        self.assertEqual(voices['Facebook']['key'], 'friendly')          # not picked: Radar's suggestion
        self.assertEqual(plan.inputs['currency'], 'EGP')
        self.assertAlmostEqual(plan.inputs['budget_total'], 20000 * 90 / 30.4, places=0)
        self.assertEqual(len(self.client.get('/strategy/radar/plans').json()), 1)

    def test_bad_requests_are_refused(self):
        self.assertEqual(self.create(voices={'TikTok': {'key': 'funky'}}).status_code, 422)
        self.assertEqual(self.create(voices={'LinkedIn': {'key': 'custom', 'custom': ''}}).status_code, 422)
        self.assertEqual(self.create(end_date='2026-10-01').status_code, 422)
        self.assertEqual(self.calls, [])

    def test_n8n_reads_the_pack_while_the_plan_runs(self):
        pid = self.create().json()['plan_id']
        pack = self.client.get(f'/strategy/plans/{pid}/pack').json()
        self.assertTrue(pack['ready'])
        self.assertIn('Nexa', pack['rivals'])
        self.assertIn('LinkedIn: Formal expert', pack['voices'])
        self.assertIn('Write Facebook lines in English', pack['voices'])
        self.assertIn('Cairo ICT 2026', pack['events'])
        self.assertNotIn('Ramadan', pack['events'])          # starts after the plan ends
        anon = TestClient(app).get(f'/strategy/plans/{pid}/pack')
        self.assertEqual(anon.status_code, 401)

    def test_the_saved_plan_is_fixed_not_refused(self):
        pid = self.create().json()['plan_id']
        r = self.client.post(f'/strategy/plans/{pid}/result', json={'plan': plan_body(), 'model': 'gemini'})
        self.assertEqual(r.status_code, 200, r.text)
        plan = self.client.get(f'/strategy/radar/plans/{pid}').json()['plan']
        c1, c2 = plan['campaigns']
        self.assertEqual((c1['id'], c2['id']), ('C1', 'C2'))
        self.assertEqual((c1['start_date'], c2['end_date']), (START, END))
        self.assertEqual(c1['channels'], ['Meta ads', 'LinkedIn'])
        self.assertEqual(sum(b['percent'] for b in plan['budget']), 100)
        self.assertAlmostEqual(sum(b['amount'] for b in plan['budget']), plan['budget_total'], places=0)
        self.assertEqual(sum(m['percent'] for m in plan['content_plan']['mix']), 100)
        self.assertEqual(plan['content_plan']['rhythm'][0]['per_week'], 14)
        titles = [e['title'] for e in plan['calendar']]
        self.assertNotIn('Made-up holiday', titles)
        self.assertNotIn('Too late', titles)
        self.assertIn('Black Friday / White Friday', titles)
        ict = next(e for e in plan['calendar'] if e['title'].startswith('Cairo ICT'))
        self.assertTrue(ict['confirmed'])
        self.assertEqual(plan['competitive_brief']['positioning_map']['points'][0]['x'], 100)
        self.assertEqual([p['platform'] for p in plan['positioning']['by_platform']], ['LinkedIn', 'Instagram', 'Facebook'])
        self.assertEqual(plan['kpis'][0]['campaign_id'], '')
        self.assertTrue(plan['notes'])
        self.assertEqual(plan['campaigns'][0]['visual_prompt'], 'Lantern')

    def test_a_plan_without_campaigns_fails_with_the_reason(self):
        pid = self.create().json()['plan_id']
        r = self.client.post(f'/strategy/plans/{pid}/result', json={'plan': {**plan_body(), 'campaigns': []}})
        self.assertEqual(r.status_code, 422)
        detail = self.client.get(f'/strategy/radar/plans/{pid}').json()
        self.assertEqual(detail['status'], 'failed')
        self.assertIn('campaign', detail['validation_errors'][0])

    def test_results_give_wins_misses_and_next_moves(self):
        pid = self.create().json()['plan_id']
        self.client.post(f'/strategy/plans/{pid}/result', json={'plan': plan_body()})
        week = '2026-11-04'   # a Wednesday: saved as its Monday
        self.client.post(f'/strategy/plans/{pid}/results', json={'week_start': week, 'platform': 'Meta ads', 'campaign_id': 'C1',
                                                                  'spend': 4000, 'impressions': 100000, 'clicks': 1200, 'leads': 20})
        r = self.client.post(f'/strategy/plans/{pid}/results', json={'week_start': week, 'platform': 'LinkedIn ads',
                                                                      'spend': 6000, 'impressions': 20000, 'clicks': 60, 'leads': 4})
        rep = r.json()
        self.assertEqual(rep['entries'][0]['week_start'], '2026-11-02')
        self.assertEqual(rep['totals']['leads'], 24)
        self.assertEqual(rep['by_platform']['Meta ads']['cpl'], 200)
        self.assertIn('Move 10 to 20% of the LinkedIn ads budget to Meta ads', rep['next_moves'][0])
        self.assertTrue(any('LinkedIn ads click rate' in m for m in rep['misses']))
        leads = next(k for k in rep['kpis'] if k['name'] == 'Qualified leads')
        self.assertEqual((leads['actual'], leads['state']), (24, 'on track'))   # 24 after a week beats the paced share of 40
        again = self.client.post(f'/strategy/plans/{pid}/results', json={'week_start': week, 'platform': 'Meta ads',
                                                                          'campaign_id': 'C1', 'spend': 1, 'impressions': 10})
        self.assertEqual(len(again.json()['entries']), 2)   # same week, platform and campaign: replaced
        bad = self.client.post(f'/strategy/plans/{pid}/results', json={'week_start': week, 'platform': 'Meta ads',
                                                                        'impressions': 5, 'clicks': 9})
        self.assertEqual(bad.status_code, 422)
        rid = again.json()['entries'][0]['id']
        self.assertEqual(len(self.client.delete(f'/strategy/plans/{pid}/results/{rid}').json()['entries']), 1)


def test_events_and_months():
    names = [e['title'] for e in events_between(date(2027, 2, 1), date(2027, 3, 31))]
    assert 'Ramadan' in names and "Mother's Day (Egypt)" in names
    ramadan = next(e for e in events_between(date(2027, 2, 1), date(2027, 3, 31)) if e['title'] == 'Ramadan')
    assert ramadan['confirmed'] is False
    months = months_between(date(2026, 11, 15), date(2027, 1, 14))
    assert [m['month'] for m in months] == ['2026-11', '2026-12', '2027-01']
    assert abs(sum(m['share'] for m in months) - 1) < 1e-9


def test_clean_keeps_the_period_and_never_trusts_model_sums():
    inputs = {'start_date': START, 'end_date': END, 'budget': 10000, 'budget_total': 30000, 'currency': 'EGP',
              'voices': {'LinkedIn': {'label': 'Formal expert'}}}
    saved, notes = clean({**plan_body(), 'budget': []}, inputs)
    assert [b['percent'] for b in saved['budget']] == [60, 30, 10]
    assert [b['amount'] for b in saved['budget']] == [18000, 9000, 3000]
    assert any('60/30/10' in n for n in notes)
    assert all(START <= e['date'] <= END or e.get('end_date', '') and e['end_date'] >= START for e in saved['calendar'])
    assert saved['positioning']['by_platform'][0]['voice'] == 'Formal expert'

    def test_the_calendar_can_be_edited_and_logos_are_listed(self):
        pid = self.create().json()['plan_id']
        self.assertEqual(self.client.put(f'/strategy/radar/plans/{pid}/calendar', json={'entries': []}).status_code, 409)
        self.client.post(f'/strategy/plans/{pid}/result', json={'plan': plan_body()})
        detail = self.client.get(f'/strategy/radar/plans/{pid}').json()
        self.assertEqual(detail['logos'], {'Odynza': 'client', 'Nexa': 1})
        rows = detail['plan']['calendar']
        entry = {'date': '2026-11-20', 'end_date': '2026-11-20', 'title': 'Webinar with Nexa users', 'kind': 'content',
                 'campaign_id': 'C1', 'note': 'Book the room'}
        r = self.client.put(f'/strategy/radar/plans/{pid}/calendar', json={'entries': rows[1:] + [entry]})
        self.assertEqual(r.status_code, 200, r.text)
        cal = r.json()['plan']['calendar']
        self.assertEqual(len(cal), len(rows))
        mine = next(e for e in cal if e['title'] == 'Webinar with Nexa users')
        self.assertEqual((mine['source'], mine['end_date'], mine['confirmed']), ('you', None, True))
        self.assertEqual([e['date'] for e in cal], sorted(e['date'] for e in cal))
        self.assertIn('calendar_edited', r.json()['plan'])
        for bad in ({**entry, 'date': '2027-05-01', 'end_date': None}, {**entry, 'end_date': '2026-11-01'},
                    {**entry, 'campaign_id': 'C9'}, {**entry, 'kind': 'party'}):
            self.assertEqual(self.client.put(f'/strategy/radar/plans/{pid}/calendar', json={'entries': [bad]}).status_code, 422, bad)
