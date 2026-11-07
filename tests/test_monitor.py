import gzip
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

import os
import requests
import yaml

import main


ROOT = 'https://example.com'
SITEMAP = f'{ROOT}/sitemap.xml'


def urlset(*urls):
    body = ''.join(f'<url><loc>{url}</loc></url>' for url in urls)
    return f'<?xml version="1.0"?><urlset>{body}</urlset>'.encode()


def sitemap_index(*urls):
    body = ''.join(f'<sitemap><loc>{url}</loc></sitemap>' for url in urls)
    return f'<?xml version="1.0"?><sitemapindex>{body}</sitemapindex>'.encode()


class Response:
    def __init__(self, content=b'', status_code=200, headers=None):
        self.content = content
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            error = requests.HTTPError(f'HTTP {self.status_code}')
            error.response = self
            raise error


class ScriptedScraper:
    def __init__(self, scripts):
        self.scripts = scripts
        self.headers = {}
        self.calls = []

    def get(self, url, timeout=None):
        self.calls.append(url)
        script = self.scripts[url]
        item = script.pop(0) if isinstance(script, list) else script
        if isinstance(item, Exception):
            raise item
        return item


class MonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.workdir = Path(self.temp.name)
        self._previous = Path.cwd()
        os.chdir(self.workdir)
        self.now = datetime(2026, 11, 8, 15, 0, 0)
        self.delays = []

    def tearDown(self):
        os.chdir(self._previous)
        self.temp.cleanup()

    def write_config(self, sitemap=None, storage=None, sites=None):
        config = {
            'sites': sites or [{
                'name': 'example',
                'sitemap_urls': [SITEMAP],
                'active': True,
            }],
            'sitemap': {
                'max_depth': 3,
                'max_sitemaps': 500,
                'max_urls': 200000,
                'request_timeout': 10,
                'max_attempts': 3,
            },
            'storage': {'retention_days': 7},
            'feishu': {'webhook_url': ''},
        }
        if sitemap:
            config['sitemap'].update(sitemap)
        if storage:
            config['storage'].update(storage)
        path = self.workdir / 'config.yaml'
        path.write_text(yaml.safe_dump(config), encoding='utf-8')
        return path

    def seed_latest(self, urls):
        latest = self.workdir / 'latest'
        latest.mkdir(exist_ok=True)
        text = '\n'.join(urls)
        (latest / 'example.json').write_text(text, encoding='utf-8')
        return text

    def seed_diff(self, day, text):
        folder = self.workdir / 'diff' / day
        folder.mkdir(parents=True)
        path = folder / 'example.json'
        path.write_text(text, encoding='utf-8')
        return path

    def run_monitor(self, scraper, **config):
        path = self.write_config(**config)
        main.main(
            str(path),
            scraper=scraper,
            sleeper=self.delays.append,
            now=lambda: self.now,
        )

    def latest_text(self):
        return (self.workdir / 'latest' / 'example.json').read_text(encoding='utf-8')

    def test_failed_fetch_keeps_existing_snapshot_and_writes_no_diff(self):
        self.seed_latest([
            'https://example.com/old',
            'https://example.com/kept',
        ])
        scraper = ScriptedScraper({SITEMAP: requests.Timeout('timed out')})

        self.run_monitor(scraper)

        self.assertEqual(
            self.latest_text(),
            'https://example.com/old\nhttps://example.com/kept',
        )
        self.assertFalse((self.workdir / 'diff').exists())
        self.assertEqual(scraper.calls, [SITEMAP, SITEMAP, SITEMAP])
        self.assertEqual(self.delays, [1, 2])

    def test_failed_fetch_does_not_create_a_snapshot(self):
        scraper = ScriptedScraper({SITEMAP: requests.ConnectionError('reset')})

        self.run_monitor(scraper)

        self.assertFalse((self.workdir / 'latest' / 'example.json').exists())
        self.assertFalse((self.workdir / 'diff').exists())

    def test_timeouts_then_success_saves_snapshot_and_only_new_urls(self):
        self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({
            SITEMAP: [
                requests.Timeout('timed out'),
                requests.Timeout('timed out'),
                Response(urlset('https://example.com/old', 'https://example.com/new')),
            ],
        })

        self.run_monitor(scraper)

        self.assertEqual(
            self.latest_text(),
            'https://example.com/old\nhttps://example.com/new',
        )
        diff = (self.workdir / 'diff' / '20261108' / 'example.json').read_text(encoding='utf-8')
        self.assertEqual(diff, 'https://example.com/new\n')
        self.assertEqual(len(scraper.calls), 3)

    def test_retryable_http_status_then_success_honors_retry_after(self):
        scraper = ScriptedScraper({
            SITEMAP: [
                Response(status_code=429, headers={'Retry-After': '7'}),
                Response(urlset('https://example.com/tool')),
            ],
        })

        with self.assertLogs(level='INFO') as captured:
            self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), 'https://example.com/tool')
        self.assertFalse((self.workdir / 'diff').exists())
        self.assertEqual(self.delays, [7])
        self.assertTrue(any('initialized example' in line for line in captured.output))

    def test_retry_after_is_capped(self):
        scraper = ScriptedScraper({
            SITEMAP: [
                Response(status_code=429, headers={'Retry-After': '999'}),
                Response(urlset('https://example.com/tool')),
            ],
        })

        self.run_monitor(scraper)

        self.assertEqual(self.delays, [60])
        self.assertEqual(self.latest_text(), 'https://example.com/tool')

    def test_http_5xx_keeps_snapshot_after_retries(self):
        original = self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({SITEMAP: Response(status_code=503)})

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), original)
        self.assertEqual(len(scraper.calls), 3)
        self.assertEqual(self.delays, [1, 2])
        self.assertFalse((self.workdir / 'diff').exists())

    def test_http_404_is_not_retried_and_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({SITEMAP: Response(status_code=404)})

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), original)
        self.assertEqual(scraper.calls, [SITEMAP])
        self.assertEqual(self.delays, [])

    def test_html_block_page_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({
            SITEMAP: Response(b'<!DOCTYPE html><html><body>blocked</body></html>'),
        })

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), original)
        self.assertEqual(len(scraper.calls), 3)
        self.assertFalse((self.workdir / 'diff').exists())

    def test_broken_xml_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({SITEMAP: Response(b'<urlset><url><loc>')})

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), original)
        self.assertFalse((self.workdir / 'diff').exists())

    def test_one_failed_child_sitemap_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/kept'])
        children = [f'{ROOT}/child-{index}.xml' for index in range(5)]
        scripts = {SITEMAP: Response(sitemap_index(*children))}
        for index, child in enumerate(children):
            if index == 2:
                scripts[child] = requests.Timeout('timed out')
            else:
                scripts[child] = Response(urlset(f'{ROOT}/page-{index}'))
        scraper = ScriptedScraper(scripts)

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), original)
        self.assertNotIn(children[3], scraper.calls)
        self.assertNotIn(children[4], scraper.calls)
        self.assertFalse((self.workdir / 'diff').exists())

    def test_duplicate_locs_after_the_url_cap_stay_complete(self):
        scraper = ScriptedScraper({
            SITEMAP: Response(urlset(
                'https://example.com/a',
                'https://example.com/b',
                'https://example.com/a',
            )),
        })

        self.run_monitor(scraper, sitemap={'max_urls': 2})

        self.assertEqual(self.latest_text(), 'https://example.com/a\nhttps://example.com/b')
        self.assertFalse((self.workdir / 'diff').exists())

    def test_hitting_max_urls_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/kept'])
        scraper = ScriptedScraper({
            SITEMAP: Response(urlset(
                'https://example.com/a',
                'https://example.com/b',
                'https://example.com/c',
            )),
        })

        self.run_monitor(scraper, sitemap={'max_urls': 2})

        self.assertEqual(self.latest_text(), original)
        self.assertFalse((self.workdir / 'diff').exists())

    def test_hitting_max_sitemaps_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/kept'])
        child = f'{ROOT}/child.xml'
        scraper = ScriptedScraper({
            SITEMAP: Response(sitemap_index(child)),
            child: Response(urlset('https://example.com/a')),
        })

        self.run_monitor(scraper, sitemap={'max_sitemaps': 1})

        self.assertEqual(self.latest_text(), original)
        self.assertNotIn(child, scraper.calls)

    def test_hitting_max_depth_keeps_snapshot(self):
        original = self.seed_latest(['https://example.com/kept'])
        child = f'{ROOT}/child.xml'
        scraper = ScriptedScraper({
            SITEMAP: Response(sitemap_index(child)),
            child: Response(urlset('https://example.com/a')),
        })

        self.run_monitor(scraper, sitemap={'max_depth': 0})

        self.assertEqual(self.latest_text(), original)
        self.assertEqual(scraper.calls, [SITEMAP])

    def test_first_complete_crawl_initializes_without_a_diff(self):
        scraper = ScriptedScraper({
            SITEMAP: Response(urlset('https://example.com/a', 'https://example.com/b')),
        })

        with self.assertLogs(level='INFO') as captured:
            self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), 'https://example.com/a\nhttps://example.com/b')
        self.assertFalse((self.workdir / 'diff').exists())
        self.assertTrue(any('initialized example' in line for line in captured.output))

    def test_complete_crawl_records_only_new_urls(self):
        self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({
            SITEMAP: Response(urlset('https://example.com/old', 'https://example.com/new')),
        })

        self.run_monitor(scraper)

        self.assertEqual(
            self.latest_text(),
            'https://example.com/old\nhttps://example.com/new',
        )
        diff = (self.workdir / 'diff' / '20261108' / 'example.json').read_text(encoding='utf-8')
        self.assertEqual(diff, 'https://example.com/new\n')

    def test_repeat_run_with_no_new_urls_leaves_files_unchanged(self):
        latest = self.seed_latest(['https://example.com/old', 'https://example.com/kept'])
        latest_path = self.workdir / 'latest' / 'example.json'
        latest_mtime = latest_path.stat().st_mtime_ns
        diff_path = self.seed_diff(
            '20261108',
            'https://example.com/kept\n--------------------------------\nhttps://example.com/kept\n',
        )
        before = diff_path.read_bytes()
        scraper = ScriptedScraper({
            SITEMAP: Response(urlset('https://example.com/old', 'https://example.com/kept')),
        })

        self.run_monitor(scraper)
        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), latest)
        self.assertEqual(latest_path.stat().st_mtime_ns, latest_mtime)
        self.assertEqual(diff_path.read_bytes(), before)

    def test_same_day_new_url_is_stored_once_and_drops_separator(self):
        self.seed_latest(['https://example.com/old'])
        diff_path = self.seed_diff(
            '20261108',
            'https://example.com/old-new\n--------------------------------\nhttps://example.com/old-new\n',
        )
        scraper = ScriptedScraper({
            SITEMAP: Response(urlset(
                'https://example.com/old',
                'https://example.com/old-new',
                'https://example.com/fresh',
            )),
        })

        self.run_monitor(scraper)

        self.assertEqual(
            diff_path.read_text(encoding='utf-8'),
            'https://example.com/old-new\nhttps://example.com/fresh\n',
        )

    def test_recovered_crawl_does_not_report_the_old_snapshot_as_new(self):
        self.seed_latest([
            'https://example.com/a',
            'https://example.com/b',
            'https://example.com/c',
        ])
        failed = ScriptedScraper({SITEMAP: requests.Timeout('timed out')})
        self.run_monitor(failed)

        recovered = ScriptedScraper({
            SITEMAP: Response(urlset(
                'https://example.com/a',
                'https://example.com/b',
                'https://example.com/c',
                'https://example.com/d',
            )),
        })
        self.run_monitor(recovered)

        diff = (self.workdir / 'diff' / '20261108' / 'example.json').read_text(encoding='utf-8')
        self.assertEqual(diff, 'https://example.com/d\n')

    def test_empty_urlset_keeps_existing_snapshot(self):
        original = self.seed_latest(['https://example.com/old'])
        scraper = ScriptedScraper({SITEMAP: Response(b'<?xml version="1.0"?><urlset></urlset>')})

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), original)
        self.assertFalse((self.workdir / 'diff').exists())

    def test_smaller_complete_sitemap_replaces_snapshot(self):
        self.seed_latest([
            'https://example.com/a',
            'https://example.com/b',
            'https://example.com/c',
        ])
        scraper = ScriptedScraper({SITEMAP: Response(urlset('https://example.com/a'))})

        self.run_monitor(scraper)

        self.assertEqual(self.latest_text(), 'https://example.com/a')
        self.assertFalse((self.workdir / 'diff').exists())

    def test_sitemap_index_gzip_and_text_sitemaps(self):
        child_xml = f'{ROOT}/child.xml'
        child_gz = f'{ROOT}/child.xml.gz'
        child_txt = f'{ROOT}/child.txt'
        scraper = ScriptedScraper({
            SITEMAP: Response(sitemap_index(child_xml, child_gz, child_txt)),
            child_xml: Response(urlset('https://example.com/xml')),
            child_gz: Response(gzip.compress(urlset('https://example.com/gzip'))),
            child_txt: Response(b'https://example.com/text\nnot a url\n'),
        })

        self.run_monitor(scraper)

        self.assertEqual(
            self.latest_text(),
            'https://example.com/xml\nhttps://example.com/gzip\nhttps://example.com/text',
        )
        self.assertFalse((self.workdir / 'diff').exists())

    def test_retention_days_keeps_today_and_previous_days(self):
        self.seed_diff('20261105', 'https://example.com/old\n')
        self.seed_diff('20261106', 'https://example.com/keep\n')
        self.seed_diff('20261108', 'https://example.com/today\n')
        scraper = ScriptedScraper({SITEMAP: Response(urlset('https://example.com/a'))})

        self.run_monitor(scraper, storage={'retention_days': 3})

        names = sorted(path.name for path in (self.workdir / 'diff').iterdir())
        self.assertEqual(names, ['20261106', '20261108'])

    def test_storage_retention_days_is_not_read_from_the_top_level(self):
        self.seed_diff('20261029', 'https://example.com/old\n')
        scraper = ScriptedScraper({SITEMAP: Response(urlset('https://example.com/a'))})
        path = self.workdir / 'config.yaml'
        path.write_text(yaml.safe_dump({
            'retention_days': 1,
            'sites': [{
                'name': 'example',
                'sitemap_urls': [SITEMAP],
                'active': True,
            }],
            'sitemap': {'max_attempts': 1},
            'storage': {'retention_days': 14},
        }), encoding='utf-8')

        main.main(str(path), scraper=scraper, sleeper=self.delays.append, now=lambda: self.now)

        self.assertTrue((self.workdir / 'diff' / '20261029').is_dir())

    def test_invalid_retention_days_deletes_nothing(self):
        folder = self.seed_diff('20260101', 'https://example.com/old\n')
        scraper = ScriptedScraper({SITEMAP: Response(urlset('https://example.com/a'))})

        with self.assertRaises(ValueError):
            self.run_monitor(scraper, storage={'retention_days': 0})

        self.assertTrue(folder.exists())
        self.assertEqual(scraper.calls, [])

    def test_non_integer_retention_days_deletes_nothing(self):
        folder = self.seed_diff('20260101', 'https://example.com/old\n')
        scraper = ScriptedScraper({SITEMAP: Response(urlset('https://example.com/a'))})

        with self.assertRaises(ValueError):
            self.run_monitor(scraper, storage={'retention_days': '7'})

        self.assertTrue(folder.exists())
        self.assertEqual(scraper.calls, [])
