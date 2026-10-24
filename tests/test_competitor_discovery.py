"""Competitor relevance and geography checks with isolated data and mocked APIs."""
import asyncio
import json
import unittest
import os
os.environ['DISCOVERY_CACHE'] = '0'  # never read or write the real search cache
import httpx
from unittest.mock import patch, AsyncMock
from fastapi import HTTPException


from api.competitors import category_queries, profile_company, shortlist_competitors, rank_matches, verification_queries, fetch_company_page, enrich_official_pages, evidence_excerpts, quote_supported
from api.discovery import DiscoveryRequest, verified_candidates, discover, _cache, _pending, _discover, classify


PROFILE = {'summary': 'Arabic enterprise AI agents', 'market': 'Egypt', 'offerings': [
    {'label': 'Enterprise AI agents', 'search_terms': 'Arabic enterprise AI agents automation',
     'buyer': 'Enterprise operations teams'}], 'sources': []}
HITS = [
    {'source_id': 1, 'url': 'https://vendor.example', 'title': 'Vendor',
     'description': 'Arabic AI agents automate enterprise workflows for operations teams in Egypt.'},
    {'source_id': 2, 'url': 'https://reviews.example/alternatives', 'title': 'API Security alternatives',
     'description': 'Vendor sells Arabic AI agents that automate enterprise workflows.'},
]
CANDIDATE = {'name': 'Vendor', 'website_source_id': 1, 'evidence_source_ids': [1],
    'matched_offering': 'Enterprise AI agents', 'relationship': 'direct',
    'product_source_id': 1, 'product_quote': 'Arabic AI agents automate enterprise workflows',
    'audience_source_id': 1, 'audience_quote': 'enterprise workflows for operations teams',
    'market_source_id': 1, 'market_quote': 'operations teams in Egypt.',
    'customer_overlap': 'Enterprise operations teams'}


def response(data):
    return {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': json.dumps(data)}]}}],
            'usageMetadata': {'totalTokenCount': 100}}


class CompetitorDiscoveryTests(unittest.TestCase):
    def request(self, scope='local_first'):
        return DiscoveryRequest(company_name='Odynza', website='https://odynza.com', context='Egypt',
                                phase='competitors', market_scope=scope)

    def verify(self, candidate, scope='local_first'):
        return verified_candidates({'companies': [candidate]}, HITS, 'competitors', PROFILE, scope)

    def test_queries_cover_business_categories_and_region_not_name_only(self):
        queries = category_queries(self.request(), PROFILE)
        self.assertTrue(any('Arabic enterprise AI agents automation Egypt' in q for q in queries))
        self.assertTrue(any('automation companies platforms alternatives' in q for q in queries))
        self.assertIn('"Odynza" competitors alternatives', queries)
        self.assertLessEqual(len(queries), 7)
        self.assertFalse(any('Arize' in q or 'API security' in q for q in queries))
        self.assertTrue(all('Egypt' in q for q in category_queries(self.request('local_only'), PROFILE)))
        self.assertTrue(all('Egypt' not in q for q in category_queries(self.request('global'), PROFILE)))

    def test_profile_requires_a_real_official_quote(self):
        sources = [{'source_id': 1, 'url': 'https://odynza.com', 'text': HITS[0]['description']}]
        offering = {**PROFILE['offerings'][0], 'source_id': 1, 'quote': CANDIDATE['product_quote']}
        data = {**PROFILE, 'offerings': [offering, {**offering, 'label': 'API security',
                                                   'quote': 'A fabricated API security product'}]}
        with patch('api.competitors.GeminiClient._post', AsyncMock(return_value=response(data))):
            profile, usage = asyncio.run(profile_company(None, self.request(), sources))
        self.assertEqual([o['label'] for o in profile['offerings']], ['Enterprise AI agents'])
        self.assertEqual(usage['totalTokenCount'], 100)

    def test_directory_quote_cannot_prove_official_product_overlap(self):
        candidate = {**CANDIDATE, 'product_source_id': 2,
                     'product_quote': 'Arabic AI agents that automate enterprise workflows'}
        self.assertEqual(self.verify(candidate), [])

    def test_supporting_policy_cannot_become_main_product_and_queries_stay_short(self):
        sources = [{'source_id': 1, 'url': 'https://odynza.com/security', 'text': HITS[0]['description']}]
        offering = {**PROFILE['offerings'][0], 'source_id': 1, 'quote': CANDIDATE['product_quote']}
        with patch('api.competitors.GeminiClient._post', AsyncMock(return_value=response({**PROFILE, 'offerings': [offering]}))):
            profile, _ = asyncio.run(profile_company(None, self.request(), sources))
        self.assertEqual(profile['offerings'], [])
        sources[0]['url'] = 'https://odynza.com/'
        offering['search_terms'] = 'enterprise AI agents workflow automation finance HR operations connectors cloud security hosting'
        with patch('api.competitors.GeminiClient._post', AsyncMock(return_value=response({**PROFILE, 'offerings': [offering]}))):
            profile, _ = asyncio.run(profile_company(None, self.request(), sources))
        self.assertLessEqual(len(profile['offerings'][0]['search_terms'].split()), 8)

    def test_verification_preserves_official_domain_for_ambiguous_company_names(self):
        hits = [{'source_id': 1, 'url': 'https://www.pcs-egypt.com/solutions', 'title': 'PCS', 'description': 'Integration'}]
        queries = verification_queries(['PCS', 'Other Firm'], hits, PROFILE)
        self.assertTrue(all('site:pcs-egypt.com' in q for q in queries[:2]))
        self.assertIn('Arabic enterprise AI agents automation customers', queries[1])
        self.assertEqual(queries[2], '"Other Firm" official company website')

    def test_wrong_quotes_categories_and_source_ids_are_rejected(self):
        for change in ({'product_quote': 'Fabricated advanced security service'}, {'matched_offering': 'API security'},
                       {'product_source_id': '1'}, {'product_source_id': 99}):
            with self.subTest(change=change):
                self.assertEqual(self.verify({**CANDIDATE, **change}), [])

    def test_direct_overlap_needs_audience_proof(self):
        self.assertEqual(self.verify(CANDIDATE)[0]['match_type'], 'direct')
        candidate = self.verify({**CANDIDATE, 'audience_source_id': 0, 'audience_quote': ''})[0]
        self.assertEqual(candidate['match_type'], 'adjacent')
        self.assertIn('needs confirmation', candidate['customer_overlap'])

    def test_classifier_selects_source_excerpts_without_paraphrasing_quotes(self):
        catalog, compact = evidence_excerpts(HITS, PROFILE)
        eid = next(i for i, excerpt in catalog.items() if excerpt['source_id'] == 1)
        selected = {**CANDIDATE, 'product_excerpt_id': eid, 'audience_excerpt_id': eid, 'market_excerpt_id': eid}
        # Even a fabricated model quote is replaced by the actual source excerpt.
        selected['product_quote'] = 'Fabricated evidence which must never reach the user'
        post = AsyncMock(return_value=response({'companies': [selected]}))
        with patch('api.discovery.GeminiClient._post', post):
            candidates, _ = asyncio.run(classify(None, self.request(), HITS, ['Vendor'], PROFILE))
        self.assertEqual(candidates[0]['match_evidence']['product']['quote'], HITS[0]['description'])
        payload = post.await_args.args[-1]
        schema = payload['generationConfig']['responseSchema']['properties']['companies']['items']['properties']
        self.assertEqual(schema['name']['enum'], ['Vendor'])
        self.assertEqual(schema['matched_offering']['enum'], ['Enterprise AI agents'])
        self.assertNotIn('product_quote', schema)
        self.assertIn('product_excerpt_id', schema)
        self.assertEqual(json.loads(payload['contents'][0]['parts'][0]['text'])['search_results'], compact)

    def test_invalid_or_third_party_excerpt_ids_cannot_prove_match(self):
        catalog, _ = evidence_excerpts(HITS, PROFILE)
        directory_id = next(i for i, excerpt in catalog.items() if excerpt['source_id'] == 2)
        for eid in (999, True, '1', directory_id):
            with self.subTest(eid=eid), patch('api.discovery.GeminiClient._post',
                    AsyncMock(return_value=response({'companies': [{**CANDIDATE, 'product_excerpt_id': eid}]}))):
                candidates, _ = asyncio.run(classify(None, self.request(), HITS, ['Vendor'], PROFILE))
            self.assertEqual(candidates, [])

    def test_long_official_content_has_bounded_literal_excerpts(self):
        hit = {**HITS[0], 'description': (HITS[0]['description'] + ' Extra context for enterprise customers') * 80,
               'origin': 'official_page'}
        catalog, compact = evidence_excerpts([hit], PROFILE)
        self.assertLessEqual(len(catalog), 8)
        self.assertTrue(all(quote_supported(e['quote'], hit) for e in catalog.values()))
        self.assertTrue(all(len(e['quote']) <= 240 for e in catalog.values()))

    def test_regional_only_needs_market_evidence_global_does_not(self):
        candidate = {**CANDIDATE, 'market_source_id': 0, 'market_quote': ''}
        self.assertEqual(self.verify(candidate, 'local_only'), [])
        self.assertEqual(self.verify(candidate, 'global')[0]['market_fit'], 'not established')
        self.assertEqual(self.verify(CANDIDATE, 'local_only')[0]['market_fit'], 'regional')

    def test_general_mena_or_arabic_claim_cannot_prove_egypt_presence(self):
        hits = [*HITS, {'source_id': 3, 'url': 'https://vendor.example/regions', 'title': 'Vendor',
                       'description': 'Arabic AI services support government and enterprise buyers in MENA.'}]
        candidate = {**CANDIDATE, 'market_source_id': 3,
                     'market_quote': 'government and enterprise buyers in MENA.'}
        data = {'companies': [candidate]}
        self.assertEqual(verified_candidates(data, hits, 'competitors', PROFILE, 'local_only'), [])
        self.assertEqual(verified_candidates(data, hits, 'competitors', PROFILE, 'local_first')[0]['market_fit'], 'not established')

    def test_public_page_reads_are_bounded_and_do_not_forward_keys_or_cookies(self):
        real_client = httpx.AsyncClient
        requests = []
        def handle(request):
            requests.append(request)
            self.assertEqual(request.headers['host'], 'vendor.example')
            self.assertNotIn('x-goog-api-key', request.headers)
            self.assertNotIn('authorization', request.headers)
            self.assertNotIn('cookie', request.headers)
            html = '<html><title>Vendor AI agents</title><nav>Unrelated navigation</nav><main>' + HITS[0]['description'] * 60 + '</main></html>'
            return httpx.Response(200, headers={'content-type': 'text/html'}, content=html.encode())
        def client(**kwargs):
            self.assertFalse(kwargs['trust_env'])
            return real_client(transport=httpx.MockTransport(handle), **kwargs)
        with patch('api.competitors.public_target', AsyncMock(return_value=(httpx.URL('https://8.8.8.8/'), 'vendor.example'))), \
             patch('api.competitors.httpx.AsyncClient', client):
            page = asyncio.run(fetch_company_page('https://vendor.example/'))
        self.assertEqual(len(requests), 1)
        self.assertEqual(len(page['description']), 2800)
        self.assertNotIn('Unrelated navigation', page['description'])
        self.assertEqual(page['origin'], 'official_page')

    def test_unsafe_or_cross_domain_redirects_and_large_pages_fall_back_to_snippets(self):
        with patch('api.competitors.public_target', AsyncMock(side_effect=HTTPException(400, 'Blocked'))):
            self.assertIsNone(asyncio.run(fetch_company_page('http://localhost/')))
        real_client = httpx.AsyncClient
        for response in (httpx.Response(302, headers={'location': 'http://127.0.0.1/'}),
                         httpx.Response(200, headers={'content-type': 'text/html'}, content=b'x' * (1024 * 1024 + 1))):
            with self.subTest(status=response.status_code), \
                 patch('api.competitors.public_target', AsyncMock(return_value=(httpx.URL('https://8.8.8.8/'), 'vendor.example'))) as resolve, \
                 patch('api.competitors.httpx.AsyncClient', lambda **kw: real_client(transport=httpx.MockTransport(lambda r: response), **kw)):
                self.assertIsNone(asyncio.run(fetch_company_page('https://vendor.example/')))
                self.assertEqual(resolve.await_count, 1)

    def test_enrichment_reads_one_page_per_candidate_preferring_homepage(self):
        hits = [{'source_id': i + 1, 'url': 'https://vendor.example' + path, 'title': 'Vendor', 'description': 'Product'}
                for i, path in enumerate(['/blog/product', '/', '/privacy'])]
        reader = AsyncMock(return_value={'url': 'https://vendor.example/', 'title': 'Vendor', 'description': HITS[0]['description']})
        with patch('api.competitors.fetch_company_page', reader):
            pages = asyncio.run(enrich_official_pages(['Vendor', 'Vendor'], hits))
        self.assertEqual(reader.await_count, 1)
        self.assertEqual(reader.await_args.args[0], 'https://vendor.example/')
        self.assertEqual(pages[0]['source_id'], 4)

    def test_location_ranks_first_then_direct_matches_with_max_five(self):
        rows = [{'name': 'Regional product alternative', 'match_type': 'adjacent', 'market_fit': 'regional'},
                {'name': 'Global direct', 'match_type': 'direct', 'market_fit': 'not established'},
                {'name': 'Regional direct', 'match_type': 'direct', 'market_fit': 'regional'}]
        self.assertEqual([r['name'] for r in rank_matches(rows, 'local_first')],
                         ['Regional direct', 'Regional product alternative', 'Global direct'])
        self.assertEqual(len(rank_matches(rows * 3, 'local_first')), 5)

    def test_official_category_results_can_qualify_without_name_alternatives_article(self):
        data = {'companies': [{'name': 'Vendor', 'evidence_source_ids': [1]},
                              {'name': 'Invented Company', 'evidence_source_ids': [1]}]}
        with patch('api.competitors.GeminiClient._post', AsyncMock(return_value=response(data))):
            names, _ = asyncio.run(shortlist_competitors(None, self.request(), HITS, PROFILE))
        self.assertEqual(names, ['Vendor'])

    def test_empty_results_expire_after_one_minute(self):
        _cache.clear(); _pending.clear()
        fake = AsyncMock(return_value={'candidates': []})
        async def run():
            with patch('api.discovery._discover', fake):
                with patch('api.discovery.time.monotonic', return_value=10):
                    await discover(self.request())
                with patch('api.discovery.time.monotonic', return_value=71):
                    await discover(self.request())
        try:
            asyncio.run(run())
            self.assertEqual(fake.await_count, 2)
        finally:
            _cache.clear(); _pending.clear()

    def test_missing_official_profile_is_searched_before_categories_with_max_three_runs(self):
        sources = [{'source_id': 1, 'url': 'https://odynza.com', 'title': 'Odynza',
                    'description': 'Arabic enterprise AI agents automate workflows for operations teams.'}]
        search = AsyncMock(side_effect=[(sources, 'profile'), (HITS, 'category'), (HITS[:1], 'official')])
        with patch('api.discovery.dotenv_values', return_value={'APIFY_API_TOKEN': 'test', 'COMPETITOR_SEARCH': 'apify'}), \
             patch('api.discovery.gemini_key', return_value='test'), \
             patch('api.discovery.profile_sources', AsyncMock(return_value=[])), \
             patch('api.discovery.profile_company', AsyncMock(return_value=(PROFILE, {}))), \
             patch('api.discovery.shortlist_competitors', AsyncMock(return_value=(['Vendor'], {}))), \
             patch('api.discovery.classify', AsyncMock(return_value=(self.verify(CANDIDATE), {}))), \
             patch('api.discovery.enrich_official_pages', AsyncMock(return_value=[])), \
             patch('api.discovery.web_search', search):
            result = asyncio.run(_discover(self.request()))
        self.assertEqual(result['run_ids'], ['profile', 'category', 'official'])
        self.assertEqual(len(result['candidates']), 1)
        self.assertTrue(all('site:odynza.com' in q for q in search.await_args_list[0].args[1]))


OWN_PAGES = [{'source_id': 1, 'url': 'https://odynza.com', 'title': 'Odynza', 'text': 'Arabic enterprise AI agents. ' * 30}]


class FastCompetitorSearchTests(unittest.TestCase):
    """Default search: Gemini + Google Search grounding, verified on each competitor's own homepage."""
    def request(self, scope='local_first'):
        return DiscoveryRequest(company_name='Odynza', website='https://odynza.com', context='Egypt',
                                phase='competitors', market_scope=scope)

    def test_grounded_suggestions_are_cleaned(self):
        from api.competitors import grounded_competitors
        data = {'companies': [
            {'name': 'Vendor', 'website': 'vendor.example/products', 'relationship': 'direct', 'reason': 'same buyers'},
            {'name': 'Vendor again', 'website': 'https://www.vendor.example', 'reason': 'duplicate domain'},
            {'name': 'Odynza Labs', 'website': 'https://labs.odynza.com', 'reason': 'own subsidiary'},
            {'name': 'Directory', 'website': 'https://www.g2.com/x', 'reason': 'directory'},
            {'name': 'Odynza', 'website': 'https://odynza.net', 'reason': 'itself'},
            {'name': 'No site', 'website': 'not a url'},
        ]}
        body = response(data)
        body['candidates'][0]['content']['parts'][0]['text'] = 'Here you go:\n```json\n' + json.dumps(data) + '\n```'
        body['candidates'][0]['groundingMetadata'] = {'webSearchQueries': ['enterprise AI agents Egypt companies']}
        post = AsyncMock(return_value=body)
        with patch('api.competitors.GeminiClient._post', post):
            found, usage, searched = asyncio.run(grounded_competitors(None, self.request(), PROFILE))
        self.assertEqual(found, [{'name': 'Vendor', 'website': 'https://vendor.example/', 'relationship': 'direct', 'reason': 'same buyers'}])
        self.assertEqual(searched, ['enterprise AI agents Egypt companies'])
        payload = post.await_args.args[2]
        self.assertEqual(payload['tools'], [{'google_search': {}}])
        self.assertNotIn('responseSchema', payload['generationConfig'])

    def test_unusable_grounded_answer_raises(self):
        from api.competitors import grounded_competitors
        from api.gemini import GeminiError
        body = {'candidates': [{'finishReason': 'STOP', 'content': {'parts': [{'text': 'no json here'}]}}]}
        with patch('api.competitors.GeminiClient._post', AsyncMock(return_value=body)):
            with self.assertRaises(GeminiError):
                asyncio.run(grounded_competitors(None, self.request(), PROFILE))

    def test_social_links_from_homepage(self):
        from bs4 import BeautifulSoup
        from api.competitors import social_links
        html = ('<a href="https://www.facebook.com/sharer.php?u=x">share</a><a href="https://facebook.com/vendor?ref=1">fb</a>'
                '<a href="https://instagram.com/p/abc">post</a><a href="https://www.instagram.com/vendor/">ig</a>'
                '<a href="https://www.linkedin.com/in/person">person</a><a href="https://linkedin.com/company/vendor/">li</a>')
        self.assertEqual(social_links(BeautifulSoup(html, 'lxml'), 'https://vendor.example/'),
                         {'facebook': 'https://facebook.com/vendor/', 'instagram': 'https://www.instagram.com/vendor/',
                          'linkedin': 'https://linkedin.com/company/vendor/'})

    def fast_run(self, env, grounded):
        page = {'url': 'https://vendor.example/', 'title': 'Vendor', 'origin': 'official_page',
                'description': 'Arabic AI agents automate enterprise workflows for operations teams in Egypt.',
                'social': {'linkedin': 'https://www.linkedin.com/company/vendor/', 'facebook': 'https://www.facebook.com/vendor'}}
        candidate = {**CANDIDATE}
        verified = verified_candidates({'companies': [candidate]}, [{**page, 'source_id': 1}], 'competitors', PROFILE, 'local_first')
        search = AsyncMock(side_effect=[(HITS, 'category'), (HITS[:1], 'official')])
        with patch('api.discovery.dotenv_values', return_value=env), \
             patch('api.discovery.gemini_key', return_value='test'), \
             patch('api.discovery.profile_sources', AsyncMock(return_value=OWN_PAGES)), \
             patch('api.discovery.fetch_company_page', AsyncMock(return_value=None)), \
             patch('api.discovery.profile_company', AsyncMock(return_value=(PROFILE, {}))), \
             patch('api.discovery.grounded_competitors', grounded), \
             patch('api.competitors.fetch_company_page', AsyncMock(return_value=page)), \
             patch('api.discovery.shortlist_competitors', AsyncMock(return_value=(['Vendor'], {}))), \
             patch('api.discovery.classify', AsyncMock(return_value=(verified, {}))) as classify_mock, \
             patch('api.discovery.enrich_official_pages', AsyncMock(return_value=[])), \
             patch('api.discovery.web_search', search):
            result = asyncio.run(_discover(self.request()))
        return result, search, classify_mock

    def test_fast_path_needs_no_apify_runs(self):
        grounded = AsyncMock(return_value=([{'name': 'Vendor', 'website': 'https://vendor.example/'}], {'totalTokenCount': 5}, ['q']))
        result, search, classify_mock = self.fast_run({}, grounded)
        self.assertEqual(search.await_count, 0)
        self.assertEqual(result['run_ids'], [])
        self.assertEqual(result['queries'], ['q'])
        self.assertEqual([c['name'] for c in result['candidates']], ['Vendor'])
        self.assertEqual(result['candidates'][0]['linkedin'], 'https://www.linkedin.com/company/vendor/')
        self.assertEqual(result['candidates'][0]['facebook'], 'https://www.facebook.com/vendor')
        self.assertEqual(classify_mock.await_args.kwargs['allowed_names'], ['Vendor'])

    def test_fast_path_failure_falls_back_to_apify(self):
        from api.gemini import GeminiError
        grounded = AsyncMock(side_effect=GeminiError('generateContent: model does not support search'))
        result, search, _ = self.fast_run({'APIFY_API_TOKEN': 'test'}, grounded)
        self.assertEqual(result['run_ids'], ['category', 'official'])
        self.assertIn('Fast search was unavailable', result['notice'])

    def test_fast_path_without_apify_token_reports_the_error(self):
        from api.gemini import GeminiError
        grounded = AsyncMock(side_effect=GeminiError('quota'))
        with self.assertRaises(GeminiError):
            self.fast_run({}, grounded)


class FastIdentifyTests(unittest.TestCase):
    """Step 1 (find the company itself) also uses Google Search grounding instead of an Apify run."""
    def request(self):
        return DiscoveryRequest(company_name='Odynza', context='Egypt', phase='identify')

    def test_grounded_identify_cleans_suggestions(self):
        from api.competitors import grounded_identify
        data = {'companies': [
            {'name': 'Odynza', 'website': 'odynza.com', 'facebook': 'https://www.facebook.com/sharer.php?u=x',
             'instagram': 'https://www.instagram.com/odynza/', 'linkedin': 'https://www.linkedin.com/in/person'},
            {'name': 'Odynza on LinkedIn', 'website': 'https://www.linkedin.com/company/odynza'},
            {'name': 'Odynza duplicate', 'website': 'https://www.odynza.com/about'},
        ]}
        with patch('api.competitors.GeminiClient._post', AsyncMock(return_value=response(data))):
            found, _, _ = asyncio.run(grounded_identify(None, self.request()))
        self.assertEqual(found, [{'name': 'Odynza', 'website': 'https://odynza.com/', 'description': '',
                                  'facebook': '', 'instagram': 'https://www.instagram.com/odynza/', 'linkedin': ''}])

    def identify(self, env, grounded):
        pages = {'https://odynza.com/': {'url': 'https://odynza.com/', 'title': 'Odynza | Real estate', 'origin': 'official_page',
                                         'description': 'Odynza builds marketing tools for real estate developers in Egypt.',
                                         'social': {'linkedin': 'https://www.linkedin.com/company/odynza/'}}}
        reader = AsyncMock(side_effect=lambda url, **kw: pages.get(url))
        apify_hits = [{'source_id': 1, 'url': 'https://odynza.com/', 'title': 'Odynza', 'description': 'Official site'}]
        search = AsyncMock(return_value=(apify_hits, 'identify-run'))
        with patch('api.discovery.dotenv_values', return_value=env), \
             patch('api.discovery.gemini_key', return_value='test'), \
             patch('api.discovery.grounded_identify', grounded), \
             patch('api.competitors.fetch_company_page', reader), \
             patch('api.discovery.classify', AsyncMock(return_value=([], {}))), \
             patch('api.discovery.web_search', search):
            return asyncio.run(_discover(self.request())), search

    def test_identify_needs_no_apify_and_checks_homepages(self):
        grounded = AsyncMock(return_value=([
            {'name': 'Odynza Travel', 'website': 'https://odynza-travel.example/', 'description': 'Travel agency',
             'facebook': '', 'instagram': '', 'linkedin': ''},
            {'name': 'Odynza', 'website': 'https://odynza.com/', 'description': 'Real estate marketing',
             'facebook': 'https://www.facebook.com/odynza', 'instagram': '', 'linkedin': 'https://www.linkedin.com/company/other/'},
        ], {}, ['Odynza Egypt official website']))
        result, search = self.identify({}, grounded)
        self.assertEqual(search.await_count, 0)
        self.assertEqual([c['name'] for c in result['candidates']], ['Odynza', 'Odynza Travel'])
        first = result['candidates'][0]
        self.assertEqual(first['linkedin'], 'https://www.linkedin.com/company/odynza/')  # homepage link wins
        self.assertEqual(first['facebook'], 'https://www.facebook.com/odynza')
        self.assertEqual(first['sources'][0]['url'], 'https://odynza.com/')
        self.assertEqual(result['candidates'][1]['sources'], [])
        self.assertIn('google_ai_search', result['timings'])
        self.assertEqual(result['queries'], ['Odynza Egypt official website'])

    def test_homepage_that_does_not_mention_the_company_is_dropped(self):
        grounded = AsyncMock(return_value=([{'name': 'Zebracorp', 'website': 'https://odynza.com/', 'description': '',
                                             'facebook': '', 'instagram': '', 'linkedin': ''}], {}, []))
        result, _ = self.identify({}, grounded)
        self.assertEqual(result['candidates'], [])

    def test_identify_falls_back_to_apify(self):
        from api.gemini import GeminiError
        result, search = self.identify({'APIFY_API_TOKEN': 'test'}, AsyncMock(side_effect=GeminiError('no search tool')))
        self.assertEqual(search.await_count, 1)
        self.assertIn('Fast search was unavailable', result['notice'])
        self.assertIn('apify_search', result['timings'])


class SerperSearchTests(unittest.TestCase):
    """Serper + Gemini search, rule-based cleanup, parallel verification and streaming."""
    def request(self, scope='local_first', phase='competitors'):
        return DiscoveryRequest(company_name='Odynza', website='https://odynza.com', context='Egypt',
                                phase=phase, market_scope=scope)

    def test_competitor_searches_add_arabic_and_country(self):
        from api.search_pipeline import competitor_searches
        profile = {**PROFILE, 'offerings': [{**PROFILE['offerings'][0], 'search_terms_ar': 'وكلاء ذكاء اصطناعي للشركات'}]}
        searches = competitor_searches(self.request(), profile)
        self.assertIn({'q': 'Arabic enterprise AI agents automation companies Egypt', 'gl': 'eg'}, searches)
        self.assertIn({'q': 'شركات وكلاء ذكاء اصطناعي للشركات في مصر', 'gl': 'eg', 'hl': 'ar'}, searches)
        self.assertIn({'q': 'Arabic enterprise AI agents automation alternatives'}, searches)
        self.assertLessEqual(len(searches), 8)
        worldwide = competitor_searches(self.request('global'), profile)
        self.assertFalse(any('gl' in s for s in worldwide))

    def test_cleanup_drops_directories_news_articles_and_own_company(self):
        from api.search_pipeline import rank_competitor_candidates
        def hit(url, title):
            return {'url': url, 'title': title, 'description': ''}
        appearances = [
            (0, 0, hit('https://www.vendor.example/', 'Vendor | Arabic AI agents for enterprises')),
            (1, 2, hit('https://vendor.example/pricing', 'Pricing - Vendor')),
            (0, 1, hit('https://www.g2.com/categories/ai-agents', 'Best AI agents')),
            (0, 3, hit('https://techcrunch.com/2026/ai', 'Funding news')),
            (0, 4, hit('https://blog.example/top-10-ai-companies-egypt', 'Top 10 AI companies in Egypt')),
            (0, 5, hit('https://odynza.com/about', 'About Odynza')),
            (0, 6, hit('https://odynzalabs.example/', 'Odynza Labs')),
            (1, 0, hit('https://other.example/', 'Other Co - AI workflow automation')),
        ]
        grounded = [{'name': 'Third Co', 'website': 'https://third.example/', 'reason': 'Same buyers'}]
        found = rank_competitor_candidates(appearances, grounded, self.request(), 10)
        self.assertEqual([f['website'] for f in found], ['https://www.vendor.example/', 'https://other.example/', 'https://third.example/'])
        self.assertEqual(found[0]['name'], 'Vendor')
        self.assertEqual(found[1]['name'], 'Other Co')
        self.assertEqual(found[2]['found_by'], ['Google AI search'])

    def test_identify_candidates_need_the_name_and_collect_socials(self):
        from api.search_pipeline import identify_candidates
        appearances = [(0, 0, {'url': 'https://odynza.com/', 'title': 'Odynza | Marketing AI', 'description': 'Odynza home'}),
                       (0, 1, {'url': 'https://unrelated.example/', 'title': 'Something else', 'description': ''}),
                       (2, 0, {'url': 'https://www.linkedin.com/company/odynza/', 'title': 'Odynza | LinkedIn', 'description': ''}),
                       (2, 1, {'url': 'https://www.facebook.com/someoneelse', 'title': 'Someone', 'description': ''})]
        found, socials = identify_candidates(appearances, [], 'Odynza')
        self.assertEqual([f['website'] for f in found], ['https://odynza.com/'])
        self.assertEqual(found[0]['name'], 'Odynza')
        self.assertEqual(socials, {'linkedin': 'https://www.linkedin.com/company/odynza/'})

    def test_serper_runs_queries_together_and_reports_a_bad_key(self):
        from api.search_pipeline import serper_search
        from api.gemini import GeminiError
        seen = []
        def handler(request):
            body = json.loads(request.content)
            seen.append((request.headers['X-API-KEY'], body['q'], body['num']))
            return httpx.Response(200, json={'organic': [{'link': 'https://vendor.example/', 'title': 'Vendor', 'snippet': 'AI'},
                                                         {'link': 'javascript:alert(1)', 'title': 'bad'}]})
        async def run(transport, key='k'):
            async with httpx.AsyncClient(transport=transport) as client:
                return await serper_search(client, key, [{'q': 'one'}, {'q': 'two', 'gl': 'eg'}])
        appearances = asyncio.run(run(httpx.MockTransport(handler)))
        self.assertEqual(sorted(seen), [('k', 'one', 10), ('k', 'two', 10)])
        self.assertEqual([(i, r, h['url']) for i, r, h in appearances], [(0, 0, 'https://vendor.example/'), (1, 0, 'https://vendor.example/')])
        with self.assertRaises(GeminiError):
            asyncio.run(run(httpx.MockTransport(lambda r: httpx.Response(401))))

    def serper_run(self, appearances, grounded, classify_fn, emit=None, cached_profile=None):
        from api.search_pipeline import PROFILE_TTL
        def page(url):
            name = url.split('//')[1].split('.')[0].title()
            return {'url': url, 'title': name, 'origin': 'official_page', 'description': f'{name} sells Arabic AI agents in Egypt.', 'social': {}}
        events = []
        async def collect(event):
            events.append(event)
        profile_call = AsyncMock(return_value=(PROFILE, {}))
        with patch('api.discovery.dotenv_values', return_value={'SERPER_API_KEY': 'k'}), \
             patch('api.discovery.gemini_key', return_value='test'), \
             patch('api.discovery.profile_sources', AsyncMock(return_value=OWN_PAGES)), \
             patch('api.discovery.profile_company', profile_call), \
             patch('api.discovery.cache_get', AsyncMock(side_effect=lambda key, ttl: cached_profile if ttl == PROFILE_TTL else None)), \
             patch('api.discovery.cache_put', AsyncMock()), \
             patch('api.discovery.run_serper', AsyncMock(return_value=appearances)), \
             patch('api.discovery.grounded_competitors', grounded), \
             patch('api.competitors.fetch_company_page', AsyncMock(side_effect=lambda url, **kw: page(url))), \
             patch('api.discovery.classify', AsyncMock(side_effect=classify_fn)), \
             patch('api.discovery.web_search', AsyncMock()) as apify:
            result = asyncio.run(_discover(self.request(), collect))
        return result, events, apify, profile_call

    @staticmethod
    def verify_all(_llm, _request, pages, allowed_names=None, profile=None):
        return [{'name': p['candidate'], 'website': p['url'], 'match_type': 'direct', 'market_fit': 'regional',
                 'facebook': '', 'instagram': '', 'linkedin': '', 'sources': []} for p in pages], {'totalTokenCount': 10}

    def test_serper_path_verifies_in_parallel_batches_and_streams_progress(self):
        from api.gemini import GeminiError
        appearances = [(0, i, {'url': f'https://vendor{i}.example/', 'title': f'Vendor{i} | AI agents', 'description': ''}) for i in range(5)]
        grounded = AsyncMock(side_effect=GeminiError('no google search on this model'))
        result, events, apify, _ = self.serper_run(appearances, grounded, self.verify_all)
        self.assertEqual(apify.await_count, 0)
        self.assertEqual(len(result['candidates']), 5)
        self.assertEqual(result['mode'], 'auto')
        self.assertEqual(result['serper_queries'], len(result['queries']) + 15)  # + one profile search per missing social link
        self.assertIn('Google AI search (Gemini) was unavailable', result['notice'])
        self.assertIn('check_matches', result['timings'])
        partial = [e for e in events if e['type'] == 'partial']
        self.assertEqual(len(partial), 1)  # 5 pages = 2 batches; progress after the first
        self.assertEqual(partial[0]['checking'], len(partial[0]['candidates']) and 5 - len(partial[0]['candidates']))
        self.assertTrue(any(e['type'] == 'stage' for e in events))

    def test_saved_profile_skips_the_profile_step(self):
        appearances = [(0, 0, {'url': 'https://vendor.example/', 'title': 'Vendor', 'description': ''})]
        grounded = AsyncMock(return_value=([], {}, []))
        result, _, _, profile_call = self.serper_run(appearances, grounded, self.verify_all, cached_profile=PROFILE)
        self.assertEqual(profile_call.await_count, 0)
        self.assertTrue(result['profile_cached'])
        self.assertEqual([c['name'] for c in result['candidates']], ['Vendor'])

    def test_social_profiles_are_found_with_site_searches(self):
        from api.discovery import find_socials
        candidates = [{'name': 'Vendor', 'website': 'https://vendor.example/', 'facebook': 'https://facebook.com/vendor',
                       'instagram': '', 'linkedin': ''}]
        rows = [(1, 0, {'url': 'https://www.instagram.com/p/123/', 'title': 'Vendor post', 'description': ''}),
                (1, 1, {'url': 'https://www.instagram.com/vendor.eg/', 'title': 'Vendor (@vendor.eg)', 'description': ''}),
                (0, 0, {'url': 'https://www.linkedin.com/company/someone-else/', 'title': 'Someone Else', 'description': ''}),
                (0, 1, {'url': 'https://eg.linkedin.com/company/vendor', 'title': 'Vendor | LinkedIn', 'description': ''})]
        serper = AsyncMock(return_value=rows)
        with patch('api.discovery.run_serper', serper):
            count = asyncio.run(find_socials('k', candidates))
        self.assertEqual(count, 3)  # the suggested Facebook page is not on their website, so it is checked too
        self.assertEqual([s['q'] for s in serper.await_args.args[1]],
                         ['site:linkedin.com/company "Vendor"', 'site:instagram.com "Vendor"', 'site:facebook.com "Vendor"'])
        self.assertEqual(candidates[0]['instagram'], 'https://www.instagram.com/vendor.eg/')
        self.assertIn('linkedin.com/company/vendor', candidates[0]['linkedin'])
        self.assertEqual(candidates[0]['facebook'], 'https://facebook.com/vendor')
        self.assertEqual(candidates[0]['social_checks']['facebook'], 'unconfirmed')
        self.assertEqual(asyncio.run(find_socials('', candidates)), 0)

    def test_stream_endpoint_sends_progress_then_result(self):
        from fastapi.testclient import TestClient
        from api.main import app
        async def fake(request, emit):
            await emit({'type': 'stage', 'message': 'Searching'})
            return {'candidates': [{'name': 'Vendor'}], 'seconds': 1.0}
        with patch('api.routers.discovery.discover', fake):
            response = TestClient(app).post('/discover/stream', json={'company_name': 'Odynza'})
        lines = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual([l['type'] for l in lines], ['stage', 'result'])
        self.assertEqual(lines[1]['data']['candidates'][0]['name'], 'Vendor')

if __name__ == '__main__':
    unittest.main()


class AccuracyTests(unittest.TestCase):
    """Same-name profiles of other businesses, post links, duplicate websites and oversized rivals."""
    PAGE = {'url': 'https://odynza.com/', 'title': 'Odynza | Applied AI Engineering',
            'description': 'We develop AI agents, secure infrastructure and deep integrations for enterprises. '
                           'Cognitive infrastructure, agent ecosystems and workflow automation.'}

    def test_same_name_page_about_another_business_is_removed(self):
        from api.discovery import find_socials
        c = {'name': 'Odynza', 'website': 'https://odynza.com/', 'description': 'Applied AI engineering company',
             'facebook': 'https://www.facebook.com/p/Odynza-Egypt-61577890784776/', 'instagram': '', 'linkedin': ''}
        rows = [(2, 0, {'url': 'https://www.facebook.com/p/Odynza-Egypt-61577890784776/', 'title': 'Odynza Egypt',
                        'description': 'Odynza Egypt. Hurghada tours, Red Sea excursions, dolphin house trips and snorkeling adventures.'}),
                (0, 0, {'url': 'https://eg.linkedin.com/company/odynza', 'title': 'Odynza | LinkedIn',
                        'description': 'Odynza builds AI agents and secure infrastructure for enterprises in Egypt.'}),
                (1, 0, {'url': 'https://www.instagram.com/odynza/', 'title': 'Odynza (@odynza)',
                        'description': 'Applied AI engineering. Agents for enterprise workflows.'})]
        with patch('api.discovery.run_serper', AsyncMock(return_value=rows)):
            asyncio.run(find_socials('k', [c], pages=[self.PAGE]))
        self.assertEqual(c['facebook'], '')
        self.assertEqual(c['social_rejected'][0]['channel'], 'facebook')
        self.assertIn('different business', c['social_rejected'][0]['reason'])
        self.assertIn('Hurghada', c['social_rejected'][0]['reason'])
        self.assertIn('linkedin.com/company/odynza', c['linkedin'])
        self.assertEqual(c['instagram'], 'https://www.instagram.com/odynza/')
        self.assertEqual(c['social_checks'], {'linkedin': 'matched', 'instagram': 'matched'})

    def test_profile_links_only_never_posts_or_videos(self):
        from api.competitors import official_social
        self.assertEqual(official_social('facebook', 'https://www.facebook.com/entopyltd/videos/applied-aimp4/587443843646377/'),
                         'https://www.facebook.com/entopyltd/')
        self.assertEqual(official_social('facebook', 'https://www.facebook.com/reel/922265827307749/'), '')
        self.assertEqual(official_social('facebook', 'https://web.facebook.com/p/Odynza-Egypt-61577890784776/?ref=x'),
                         'https://www.facebook.com/p/Odynza-Egypt-61577890784776/')
        self.assertEqual(official_social('facebook', 'https://www.facebook.com/profile.php?id=123&sk=about'),
                         'https://www.facebook.com/profile.php?id=123')
        self.assertEqual(official_social('instagram', 'https://www.instagram.com/vendor/reels/'), 'https://www.instagram.com/vendor/')
        self.assertEqual(official_social('linkedin', 'https://eg.linkedin.com/company/vendor/posts/?x=1'),
                         'https://www.linkedin.com/company/vendor/')

    def test_profile_handle_must_carry_the_company_name(self):
        from api.social_check import handle_matches
        self.assertFalse(handle_matches('instagram', 'https://www.instagram.com/uiowa.appliedai/', 'Applied AI', 'https://applied-ai.com/'))
        self.assertFalse(handle_matches('linkedin', 'https://www.linkedin.com/company/10786831/', 'Applied AI', 'https://applied-ai.com/'))
        self.assertFalse(handle_matches('facebook', 'https://www.facebook.com/entopyltd/', 'Applied AI', 'https://applied-ai.com/'))
        self.assertTrue(handle_matches('linkedin', 'https://www.linkedin.com/company/boston-consulting-group/', 'BCG', 'https://www.bcg.com/'))
        self.assertTrue(handle_matches('facebook', 'https://www.facebook.com/p/Odynza-Egypt-61577890784776/', 'Odynza', 'https://odynza.com/'))
        self.assertTrue(handle_matches('instagram', 'https://www.instagram.com/alshohab.alalya.eg/', 'Alshohab Eg', 'https://alshohab-eg.com/'))

    def test_two_websites_with_the_same_profiles_are_one_company(self):
        from api.discovery import merge_same_company
        merged = merge_same_company([
            {'name': 'Odynza', 'website': 'https://odynza.com/', 'linkedin': 'https://www.linkedin.com/company/odynza/', 'facebook': '', 'instagram': ''},
            {'name': 'Odynza', 'website': 'https://www.odynza.tech/', 'linkedin': 'https://www.linkedin.com/company/odynza/',
             'facebook': '', 'instagram': 'https://www.instagram.com/odynza/'},
            {'name': 'Odynza Travel', 'website': 'https://odynza-travel.example/', 'linkedin': '', 'facebook': '', 'instagram': ''}])
        self.assertEqual([m['website'] for m in merged], ['https://odynza.com/', 'https://odynza-travel.example/'])
        self.assertEqual(merged[0]['other_websites'], ['https://www.odynza.tech/'])
        self.assertEqual(merged[0]['instagram'], 'https://www.instagram.com/odynza/')

    def test_global_consultancy_is_dropped_locally_and_ranked_last_worldwide(self):
        from api.competitors import rank_matches
        profile = {**PROFILE, 'business_model': 'software_product', 'scale': 'startup_or_small'}
        rows = lambda: [
            {'name': 'BCG', 'match_type': 'direct', 'market_fit': 'not established', 'business_model': 'consulting', 'scale': 'large_or_global'},
            {'name': 'Local AI', 'match_type': 'adjacent', 'market_fit': 'regional', 'business_model': 'software_product', 'scale': 'startup_or_small'},
            {'name': 'Agency', 'match_type': 'adjacent', 'market_fit': 'regional', 'business_model': 'tech_services', 'scale': 'mid_size'}]
        self.assertEqual([c['name'] for c in rank_matches(rows(), 'local_first', profile)], ['Local AI', 'Agency'])
        ranked = rank_matches(rows(), 'global', profile)
        self.assertEqual(ranked[-1]['name'], 'BCG')
        self.assertIn('consulting firm', ranked[-1]['fit_note'])
        self.assertIn('Much larger', ranked[-1]['fit_note'])

    def test_short_domain_names_are_acronyms(self):
        from api.search_pipeline import name_from_title
        self.assertEqual(name_from_title('Boston Consulting Group', 'bcg.com'), 'BCG')
        self.assertEqual(name_from_title('Paymob | Online payments', 'paymob.com'), 'Paymob')

    def test_country_domain_proves_the_market_and_local_results_are_read_first(self):
        from api.competitors import local_site
        from api.search_pipeline import rank_competitor_candidates
        self.assertTrue(local_site('https://www.vendor.com.eg/', 'Egypt'))
        self.assertFalse(local_site('https://vendor.com/', 'Egypt'))
        def hit(url, title):
            return {'url': url, 'title': title, 'description': ''}
        searches = [{'q': 'AI agents companies Egypt', 'gl': 'eg'}, {'q': 'AI agents companies'}]
        appearances = [(1, 0, hit('https://global.example/', 'Global | AI agents')),
                       (0, 1, hit('https://local.example/', 'Local | AI agents')),
                       (1, 1, hit('https://other.com.eg/', 'Other | AI agents'))]
        found = rank_competitor_candidates(appearances, [], DiscoveryRequest(company_name='Odynza', website='https://odynza.com', context='Egypt', phase='competitors'), 5, searches, 'Egypt')
        self.assertEqual([f['name'] for f in found], ['Other', 'Local', 'Global'])
        worldwide = rank_competitor_candidates(appearances, [], DiscoveryRequest(company_name='Odynza', website='https://odynza.com', context='Egypt', phase='competitors', market_scope='global'), 5, searches, 'Egypt')
        self.assertEqual(worldwide[0]['name'], 'Global')

    def test_ranking_is_numbered_and_explained(self):
        from api.competitors import rank_matches
        profile = {**PROFILE, 'business_model': 'software_product', 'scale': 'startup_or_small', 'market': 'Egypt'}
        ranked = rank_matches([
            {'name': 'Big', 'match_type': 'direct', 'market_fit': 'regional', 'business_model': 'consulting', 'scale': 'large_or_global'},
            {'name': 'Near', 'match_type': 'direct', 'market_fit': 'regional', 'business_model': 'software_product', 'scale': 'startup_or_small'}],
            'local_first', profile)
        self.assertEqual([(c['rank'], c['name']) for c in ranked], [(1, 'Near'), (2, 'Big')])
        self.assertEqual(ranked[0]['rank_reason'], 'Serves Egypt; same kind of product for the same buyers.')
        self.assertIn('placed lower', ranked[1]['rank_reason'])
