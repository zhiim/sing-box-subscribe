import html
from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path
import re
import subprocess
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from urllib.parse import quote
from werkzeug.test import Client
from werkzeug.wrappers import Response

web = importlib.import_module('api.app')


@contextmanager
def test_client():
    yield Client(web.app, Response)


def provider(name):
    return {
        'subscribes': [{
            'url': f'trojan://test-{name}@example.invalid:443?sni=example.invalid#{name}',
            'tag': 'tag_1', 'enabled': True, 'emoji': 0,
            'subgroup': '', 'prefix': '', 'User-Agent': ''
        }],
        'save_config_path': './config.json', 'auto_backup': False,
        'exclude_protocol': 'ssr', 'config_template': '', 'Only-nodes': False
    }


def submitted(command):
    return json.loads(json.loads(command[command.index('--temp_json_data') + 1]))


class RequestPrivacyTests(unittest.TestCase):
    def setUp(self):
        web.app.config['TESTING'] = True

    def post(self, data, template_index='0'):
        with test_client() as client:
            return client.post('/generate_config', data={
                'temp_json_data': json.dumps(data), 'template_index': template_index
            })

    def test_homepage_uses_file_defaults_and_single_form(self):
        with test_client() as client:
            response = client.get('/')
        self.assertEqual(response.status_code, 200)
        page = response.get_data(as_text=True)
        text = re.search(r'<textarea[^>]*name="temp_json_data"[^>]*>(.*?)</textarea>', page, re.S).group(1)
        self.assertEqual(json.loads(html.unescape(text)), json.loads(Path(web.PROVIDERS_PATH).read_text()))
        self.assertIn('id="generate-form" method="POST" action="/generate_config"', page)
        self.assertNotIn('/edit_temp_json', page)
        self.assertNotIn('providers_data', page)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')

    def test_removed_mutation_routes_cannot_save_a_subscription(self):
        with test_client() as client:
            for path in ['/edit_temp_json', '/update_providers', '/clear_temp_json_data']:
                self.assertEqual(client.post(path, data={'temp_json_data': json.dumps(provider('private'))}).status_code, 404)
            self.assertNotIn('test-private', client.get('/').get_data(as_text=True))

    def test_parallel_requests_keep_providers_and_files_separate(self):
        barrier = threading.Barrier(2)
        output_paths = []
        original_env = os.environ.get('TEMP_JSON_DATA')
        inputs = [provider('alice'), provider('bob')]
        def run(command, **kwargs):
            data = submitted(command)
            self.assertEqual(kwargs['stdout'], subprocess.DEVNULL)
            self.assertEqual(kwargs['stderr'], subprocess.DEVNULL)
            self.assertFalse(data['auto_backup'])
            output_paths.append(data['save_config_path'])
            barrier.wait(timeout=5)
            Path(data['save_config_path']).write_text(json.dumps({'url': data['subscribes'][0]['url']}))
        with patch.object(web.subprocess, 'run', side_effect=run):
            with ThreadPoolExecutor(max_workers=2) as pool:
                responses = list(pool.map(self.post, inputs))
        for response, data in zip(responses, inputs):
            self.assertEqual(response.status_code, 200)
            self.assertEqual(json.loads(response.get_data())['url'], data['subscribes'][0]['url'])
            self.assertEqual(response.headers['Cache-Control'], 'no-store')
            self.assertEqual(data['save_config_path'], './config.json')
        self.assertEqual(len(set(output_paths)), 2)
        self.assertTrue(all(not Path(path).parent.exists() for path in output_paths))
        self.assertEqual(os.environ.get('TEMP_JSON_DATA'), original_env)
        with test_client() as client:
            page = client.get('/').get_data(as_text=True)
            self.assertNotIn('test-alice', page)
            self.assertNotIn('test-bob', page)

    def test_client_output_path_is_ignored(self):
        data = provider('private')
        data['save_config_path'] = '/must-not-be-used.json'
        def run(command, **kwargs):
            runtime_data = submitted(command)
            self.assertNotEqual(runtime_data['save_config_path'], data['save_config_path'])
            Path(runtime_data['save_config_path']).write_text('{}')
        with patch.object(web.subprocess, 'run', side_effect=run):
            self.assertEqual(self.post(data).status_code, 200)

    def test_failure_cleans_output_and_does_not_return_subscription(self):
        output_paths = []
        def fail(command, **kwargs):
            output_paths.append(submitted(command)['save_config_path'])
            raise subprocess.CalledProcessError(1, command, stderr='private-subscription-token')
        with patch.object(web.subprocess, 'run', side_effect=fail):
            response = self.post(provider('secret'))
        self.assertEqual(response.status_code, 500)
        self.assertNotIn('private-subscription-token', response.get_data(as_text=True))
        self.assertNotIn('test-secret', response.get_data(as_text=True))
        self.assertFalse(Path(output_paths[0]).parent.exists())

    def test_timeout_cleans_output(self):
        output_paths = []
        def timeout(command, **kwargs):
            output_paths.append(submitted(command)['save_config_path'])
            raise subprocess.TimeoutExpired(command, 60)
        with patch.object(web.subprocess, 'run', side_effect=timeout):
            self.assertEqual(self.post(provider('timeout')).status_code, 504)
        self.assertFalse(Path(output_paths[0]).parent.exists())

    def test_bad_form_does_not_start_conversion(self):
        with patch.object(web.subprocess, 'run') as run:
            with test_client() as client:
                self.assertEqual(client.post('/generate_config').status_code, 400)
                self.assertEqual(client.post('/generate_config', data={'temp_json_data': '{broken'}).status_code, 400)
            for data in [[], {}, {'subscribes': 'not-a-list'}]:
                self.assertEqual(self.post(data).status_code, 400)
            for index in ['invalid', '-1', '999']:
                self.assertEqual(self.post(provider('invalid'), index).status_code, 400)
            run.assert_not_called()

    def test_cli_conversion_with_inline_subscription(self):
        response = self.post(provider('inline'))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        nodes = json.loads(response.get_data())['outbounds']
        node = next(node for node in nodes if node.get('type') == 'trojan')
        self.assertEqual(node['password'], 'test-inline')
        self.assertEqual(node['tag'], 'inline')

    def test_url_conversion_supports_multiple_subscriptions(self):
        uris = '|'.join(provider(name)['subscribes'][0]['url'] for name in ['one', 'two'])
        with test_client() as client:
            response = client.get('/config/' + quote(uris, safe=''))
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True))
        nodes = json.loads(response.get_data())['outbounds']
        self.assertEqual({node['password'] for node in nodes if node.get('type') == 'trojan'}, {'test-one', 'test-two'})

    def test_url_options_preserve_template_and_github_proxy_selection(self):
        calls = []
        def run(command, **kwargs):
            calls.append(command)
            Path(submitted(command)['save_config_path']).write_text('{}')
        uri = provider('options')['subscribes'][0]['url']
        with patch.object(web.subprocess, 'run', side_effect=run):
            with test_client() as client:
                response = client.get('/config/' + quote(uri, safe='') + '?file=1&gh=5&emoji=0')
        self.assertEqual(response.status_code, 200)
        command = calls[0]
        self.assertEqual(command[command.index('--template_index') + 1], '0')
        self.assertEqual(command[command.index('--gh_proxy_index') + 1], '4')
        self.assertEqual(submitted(command)['subscribes'][0]['emoji'], 0)


if __name__ == '__main__':
    unittest.main()
