import gzip
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from urllib.parse import urlunparse
from xml.etree import ElementTree as ET

import cloudscraper
import requests
import yaml


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

LANGUAGE_CODES = {
    'ar', 'bg', 'cs', 'da', 'de', 'el', 'en', 'en-gb', 'en-us', 'es', 'es-mx',
    'et', 'fi', 'fil', 'fr', 'fr-ca', 'he', 'hi', 'hr', 'hu', 'id', 'it', 'ja', 'ko',
    'lt', 'lv', 'mk', 'ms', 'nl', 'no', 'pl', 'pt', 'pt-br', 'pt-pt', 'ro',
    'ru', 'sk', 'sl', 'sr', 'sv', 'th', 'tr', 'uk', 'vi', 'zh', 'zh-cn', 'zh-tw',
}

LANGUAGE_CODE_ALIASES = {
    'br': 'pt-br',
    'jp': 'ja',
    'ph': 'fil',
    'tw': 'zh-tw',
}

RETRYABLE_STATUS = {429, 500, 502, 503, 504}
MAX_RETRY_DELAY = 60


def load_config(config_path='config.yaml'):
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_sitemap_limits(config):
    sitemap_cfg = config.get('sitemap') or {}

    def read_int(key, default):
        try:
            return int(sitemap_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    max_attempts = read_int('max_attempts', 3)
    if max_attempts < 1:
        max_attempts = 3

    return {
        'max_depth': read_int('max_depth', 3),
        'max_sitemaps': read_int('max_sitemaps', 500),
        'max_urls': read_int('max_urls', 200000),
        'request_timeout': read_int('request_timeout', 10),
        'max_attempts': max_attempts,
    }


def get_retention_days(config):
    storage = config.get('storage') or {}
    if not isinstance(storage, dict):
        raise ValueError('storage config must be a mapping')
    if 'retention_days' not in storage:
        return 7
    value = storage['retention_days']
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f'invalid storage.retention_days: {value!r}')
    return value


def is_http_url(value):
    if not value:
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


def split_language_segment(path):
    segments = [segment for segment in path.split('/') if segment]
    if not segments:
        return None, path or '/'

    first_segment = segments[0].lower()
    first_segment = LANGUAGE_CODE_ALIASES.get(first_segment, first_segment)
    if first_segment not in LANGUAGE_CODES:
        return None, path or '/'

    remaining_segments = segments[1:]
    normalized_path = '/' + '/'.join(remaining_segments) if remaining_segments else '/'
    if path.endswith('/') and normalized_path != '/':
        normalized_path += '/'
    return first_segment, normalized_path


def get_url_identity(url):
    parsed = urlparse(url.strip())
    _, normalized_path = split_language_segment(parsed.path or '/')
    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        normalized_path,
        parsed.params,
        parsed.query,
        '',
    ))


def pick_canonical_url(urls):
    default_urls = []
    english_urls = []

    for url in urls:
        parsed = urlparse(url)
        language_code, _ = split_language_segment(parsed.path or '/')
        if language_code is None:
            default_urls.append(url)
            continue
        if language_code.startswith('en'):
            english_urls.append(url)

    if default_urls:
        return default_urls[0]
    if english_urls:
        return english_urls[0]
    return urls[0]


def collapse_multilingual_urls(urls):
    grouped_urls = {}
    for url in urls:
        identity = get_url_identity(url)
        grouped_urls.setdefault(identity, []).append(url)

    collapsed_urls = []
    filtered_count = 0
    for grouped in grouped_urls.values():
        collapsed_urls.append(pick_canonical_url(grouped))
        filtered_count += len(grouped) - 1
    return collapsed_urls, filtered_count


def is_html_response(content_lower):
    stripped = content_lower.lstrip()
    return (
        stripped.startswith(b'<!doctype html')
        or stripped.startswith(b'<html')
        or (b'<head' in stripped and b'<body' in stripped)
    )


def decode_text_content(content):
    return content.decode('utf-8-sig', errors='replace')


def get_local_name(tag):
    if not tag:
        return ''
    if '}' in tag:
        return tag.rsplit('}', 1)[-1]
    return tag


def get_direct_loc_values(content, parent_tag):
    values = []
    root = ET.fromstring(content)
    for parent in root:
        if get_local_name(parent.tag) != parent_tag:
            continue
        for child in parent:
            if get_local_name(child.tag) != 'loc':
                continue
            value = (child.text or '').strip()
            if is_http_url(value):
                values.append(value)
            break
    return values


def new_crawl_state():
    return {
        'visited_sitemaps': set(),
        'sitemap_count': 0,
        'url_count': 0,
        'seen_urls': set(),
        'complete': True,
    }


def mark_incomplete(state, url, reason):
    state['complete'] = False
    logging.error(
        'Incomplete sitemap %s: %s (urls collected: %s)',
        url,
        reason,
        state['url_count'],
    )


def retry_delay(attempt, response=None):
    if response is not None and response.status_code == 429:
        raw = response.headers.get('Retry-After')
        if raw is not None:
            try:
                seconds = int(str(raw).strip())
            except ValueError:
                seconds = None
            if seconds is not None and seconds >= 0:
                return min(seconds, MAX_RETRY_DELAY)
    return min(2 ** (attempt - 1), MAX_RETRY_DELAY)


def fetch_sitemap_content(url, scraper, timeout, max_attempts=3, sleeper=time.sleep):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        try:
            response = scraper.get(url, timeout=timeout)
        except requests.RequestException as exc:
            last_error = f'{exc.__class__.__name__}: {exc}'
            logging.warning(
                'Request failed for %s on attempt %s/%s: %s',
                url,
                attempt,
                max_attempts,
                last_error,
            )
            if attempt >= max_attempts:
                break
            sleeper(retry_delay(attempt))
            continue

        if response.status_code in RETRYABLE_STATUS:
            last_error = f'HTTP {response.status_code}'
            logging.warning(
                'Retryable HTTP %s for %s on attempt %s/%s',
                response.status_code,
                url,
                attempt,
                max_attempts,
            )
            if attempt >= max_attempts:
                break
            sleeper(retry_delay(attempt, response))
            continue

        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise requests.HTTPError(f'HTTP {response.status_code} for {url}') from exc

        content = response.content
        if content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except OSError as exc:
                raise ValueError(f'Failed to decompress gzip sitemap: {url}') from exc

        if is_html_response(content.lower()):
            content_type = response.headers.get('content-type', 'unknown')
            last_error = f'HTML response (content-type={content_type})'
            logging.warning(
                'Unexpected HTML response for %s on attempt %s/%s',
                url,
                attempt,
                max_attempts,
            )
            if attempt >= max_attempts:
                break
            sleeper(retry_delay(attempt))
            continue

        return response, content

    raise ValueError(last_error or f'invalid sitemap response for {url}')


def process_sitemap(url, scraper, limits, state, depth=0, sleeper=time.sleep):
    if url in state['visited_sitemaps']:
        return []
    if state['sitemap_count'] >= limits['max_sitemaps']:
        mark_incomplete(state, url, 'max_sitemaps reached')
        return []

    state['visited_sitemaps'].add(url)
    state['sitemap_count'] += 1

    try:
        response, content = fetch_sitemap_content(
            url,
            scraper,
            limits['request_timeout'],
            limits['max_attempts'],
            sleeper,
        )
        content_lower = content.lower()

        if b'<sitemapindex' in content_lower:
            if depth >= limits['max_depth']:
                mark_incomplete(state, url, 'max_depth reached')
                return []
            sitemap_urls = parse_sitemapindex(content)
            all_urls = []
            for sitemap_url in sitemap_urls:
                if state['url_count'] >= limits['max_urls']:
                    mark_incomplete(state, sitemap_url, 'max_urls reached')
                    break
                all_urls.extend(process_sitemap(
                    sitemap_url, scraper, limits, state, depth + 1, sleeper,
                ))
                if not state['complete']:
                    break
            return all_urls

        if b'<urlset' in content_lower:
            urls = parse_xml(content)
        else:
            stripped = content_lower.lstrip()
            if stripped.startswith(b'<'):
                mark_incomplete(state, url, 'unsupported sitemap markup')
                return []
            urls = parse_txt(decode_text_content(content))
            if not urls:
                mark_incomplete(state, url, 'invalid plain-text sitemap')
                return []

        return collect_urls(urls, limits, state, url)
    except Exception as exc:
        mark_incomplete(state, url, str(exc))
        return []


def parse_xml(content):
    return get_direct_loc_values(content, 'url')


def parse_txt(content):
    return [line.strip() for line in content.splitlines() if is_http_url(line.strip())]


def parse_sitemapindex(content):
    return get_direct_loc_values(content, 'sitemap')


def collect_urls(urls, limits, state, sitemap_url):
    results = []
    for url in urls:
        if not is_http_url(url) or url in state['seen_urls']:
            continue
        if state['url_count'] >= limits['max_urls']:
            mark_incomplete(state, sitemap_url, 'max_urls reached')
            break
        state['seen_urls'].add(url)
        state['url_count'] += 1
        results.append(url)
    return results


def write_text_atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f'.{path.name}.tmp')
    temporary.write_text(text, encoding='utf-8')
    temporary.replace(path)


def read_stored_urls(path):
    if not path.exists():
        return []
    urls = []
    seen = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        value = line.strip()
        if not is_http_url(value) or value in seen:
            continue
        seen.add(value)
        urls.append(value)
    return urls


def save_latest(site_name, new_urls):
    latest_file = Path('latest') / f'{site_name}.json'
    text = '\n'.join(new_urls)
    if latest_file.exists() and latest_file.read_text(encoding='utf-8') == text:
        return
    write_text_atomic(latest_file, text)


def save_diff(site_name, new_urls, today):
    file_path = Path('diff') / today / f'{site_name}.json'
    existing = read_stored_urls(file_path)
    seen = set(existing)
    added = [url for url in new_urls if is_http_url(url) and url not in seen]
    if not added:
        return
    write_text_atomic(file_path, '\n'.join(existing + added) + '\n')


def compare_data(site_name, new_urls):
    latest_file = Path('latest') / f'{site_name}.json'
    if not latest_file.exists():
        return []

    last_urls = read_stored_urls(latest_file)
    last_identities = {get_url_identity(url) for url in last_urls}
    return [url for url in new_urls if get_url_identity(url) not in last_identities]


def send_feishu_notification(new_urls, config, site_name):
    if not new_urls:
        return

    feishu_cfg = config.get('feishu', {})
    webhook_url = feishu_cfg.get('webhook_url')
    if not webhook_url:
        return

    message = {
        "msg_type": "interactive",
        "card": {
            "header": {
                "title": {"tag": "plain_text", "content": f"{site_name} 游戏上新通知"},
                "template": "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": f"**今日新增 {len(new_urls)} 款游戏**\n\n" + "\n".join(
                            f"- {url}" for url in new_urls[:10]
                        ),
                    },
                }
            ],
        },
    }

    for attempt in range(3):
        try:
            resp = requests.post(webhook_url, json=message, timeout=10)
            resp.raise_for_status()
            logging.info("Feishu notification sent for %s", site_name)
            return
        except requests.RequestException as e:
            logging.error("Failed to send Feishu notification: %s", str(e))
            if attempt < 2:
                logging.info("Retrying Feishu notification...")


def snapshot_path(site_name):
    return Path('latest') / f'{site_name}.json'


def main(config_path='config.yaml', scraper=None, sleeper=None, now=None):
    config = load_config(config_path)
    retention_days = get_retention_days(config)
    limits = get_sitemap_limits(config)
    sleeper = sleeper or time.sleep
    now = now or datetime.now
    if scraper is None:
        scraper = cloudscraper.create_scraper()
        scraper.headers.update({
            'Accept': 'application/xml,text/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1'
        })

    for site in config['sites']:
        if not site['active']:
            continue

        current = now()
        today = current.strftime('%Y%m%d')
        logging.info("Processing site: %s", site['name'])
        state = new_crawl_state()
        all_urls = []
        for sitemap_url in site['sitemap_urls']:
            all_urls.extend(process_sitemap(
                sitemap_url, scraper, limits, state, sleeper=sleeper,
            ))
            if not state['complete']:
                break

        if not state['complete']:
            logging.error(
                'Incomplete crawl for %s: collected %s urls; snapshot kept',
                site['name'],
                state['url_count'],
            )
            cleanup_old_data(retention_days, current.date())
            continue

        unique_urls = [url for url in {url: None for url in all_urls}.keys() if is_http_url(url)]
        unique_urls, filtered_count = collapse_multilingual_urls(unique_urls)
        if filtered_count:
            logging.info(
                "Collapsed %s multilingual URLs for %s",
                filtered_count,
                site['name'],
            )

        latest_file = snapshot_path(site['name'])
        if not unique_urls and latest_file.exists():
            logging.warning('Empty crawl for %s kept existing snapshot', site['name'])
            cleanup_old_data(retention_days, current.date())
            continue

        if not latest_file.exists():
            save_latest(site['name'], unique_urls)
            logging.info('initialized %s', site['name'])
            cleanup_old_data(retention_days, current.date())
            continue

        new_urls = compare_data(site['name'], unique_urls)
        save_latest(site['name'], unique_urls)
        if new_urls:
            save_diff(site['name'], new_urls, today)
            send_feishu_notification(new_urls, config, site['name'])

        cleanup_old_data(retention_days, current.date())


def cleanup_old_data(retention_days, today):
    data_dir = Path('diff')
    if not data_dir.exists():
        return

    earliest = today - timedelta(days=retention_days - 1)
    for date_dir in data_dir.glob('*'):
        if not date_dir.is_dir():
            continue

        try:
            dir_date = datetime.strptime(date_dir.name, '%Y%m%d').date()
            if dir_date < earliest:
                for expired in date_dir.glob('*.json'):
                    expired.unlink()
                date_dir.rmdir()
                logging.info("Removed expired directory: %s", date_dir.name)
        except ValueError:
            continue
        except Exception as e:
            logging.error("Failed to remove expired directory %s: %s", date_dir.name, str(e))


if __name__ == '__main__':
    main()
