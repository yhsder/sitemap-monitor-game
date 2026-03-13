import gzip
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

import cloudscraper
import requests
import yaml


logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


def load_config(config_path='config.yaml'):
    with open(config_path, encoding='utf-8') as f:
        return yaml.safe_load(f)


def get_sitemap_limits(config):
    sitemap_cfg = config.get('sitemap', {})

    def read_int(key, default):
        try:
            return int(sitemap_cfg.get(key, default))
        except (TypeError, ValueError):
            return default

    return {
        'max_depth': read_int('max_depth', 3),
        'max_sitemaps': read_int('max_sitemaps', 500),
        'max_urls': read_int('max_urls', 200000),
        'request_timeout': read_int('request_timeout', 10),
    }


def is_http_url(value):
    if not value:
        return False
    try:
        parsed = urlparse(value.strip())
    except ValueError:
        return False
    return parsed.scheme in ('http', 'https') and bool(parsed.netloc)


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


def fetch_sitemap_content(url, scraper, timeout, max_attempts=3):
    last_error = None
    for attempt in range(1, max_attempts + 1):
        response = scraper.get(url, timeout=timeout)
        response.raise_for_status()

        content = response.content
        if content[:2] == b'\x1f\x8b':
            try:
                content = gzip.decompress(content)
            except OSError:
                logging.warning("Failed to decompress gzip sitemap: %s", url)

        if is_html_response(content.lower()):
            content_type = response.headers.get('content-type', 'unknown')
            last_error = f"Skip {url}: received HTML instead of sitemap (content-type={content_type})"
            logging.warning(
                "Unexpected HTML response for %s on attempt %s/%s",
                url,
                attempt,
                max_attempts,
            )
            if attempt < max_attempts:
                time.sleep(attempt)
                continue
            break

        return response, content

    raise ValueError(last_error or f"Skip {url}: invalid sitemap response")


def process_sitemap(url, scraper, limits, state, depth=0):
    if state['sitemap_count'] >= limits['max_sitemaps']:
        logging.warning("Max sitemaps reached, skip %s", url)
        return []
    if url in state['visited_sitemaps']:
        return []

    state['visited_sitemaps'].add(url)
    state['sitemap_count'] += 1

    try:
        response, content = fetch_sitemap_content(url, scraper, limits['request_timeout'])
        content_lower = content.lower()

        if b'<sitemapindex' in content_lower:
            if depth >= limits['max_depth']:
                logging.warning("Max sitemap depth reached at %s", url)
                return []
            sitemap_urls = parse_sitemapindex(content)
            all_urls = []
            for sitemap_url in sitemap_urls:
                if state['sitemap_count'] >= limits['max_sitemaps']:
                    logging.warning("Max sitemaps reached, stop expanding")
                    break
                if state['url_count'] >= limits['max_urls']:
                    logging.warning("Max urls reached, stop expanding")
                    break
                all_urls.extend(process_sitemap(sitemap_url, scraper, limits, state, depth + 1))
            return all_urls

        if b'<urlset' in content_lower:
            urls = parse_xml(content)
        else:
            stripped = content_lower.lstrip()
            if stripped.startswith(b'<'):
                logging.warning(
                    "Skip unsupported sitemap markup from %s (content-type=%s)",
                    url,
                    response.headers.get('content-type', 'unknown'),
                )
                return []

            urls = parse_txt(decode_text_content(content))
            if not urls:
                logging.warning(
                    "Skip invalid plain-text sitemap from %s (content-type=%s)",
                    url,
                    response.headers.get('content-type', 'unknown'),
                )
                return []

        return collect_urls(urls, limits, state)
    except requests.RequestException as e:
        logging.error("Error processing %s: %s", url, str(e))
        return []
    except ValueError as e:
        logging.warning(str(e))
        return []
    except Exception as e:
        logging.error("Unexpected error processing %s: %s", url, str(e))
        return []


def parse_xml(content):
    return get_direct_loc_values(content, 'url')


def parse_txt(content):
    return [line.strip() for line in content.splitlines() if is_http_url(line.strip())]


def parse_sitemapindex(content):
    return get_direct_loc_values(content, 'sitemap')


def collect_urls(urls, limits, state):
    results = []
    for url in urls:
        if not is_http_url(url):
            continue
        if state['url_count'] >= limits['max_urls']:
            logging.warning("Max urls reached, stop collecting")
            break
        if url in state['seen_urls']:
            continue
        state['seen_urls'].add(url)
        state['url_count'] += 1
        results.append(url)
    return results


def save_latest(site_name, new_urls):
    latest_dir = Path('latest')
    latest_dir.mkdir(parents=True, exist_ok=True)

    latest_file = latest_dir / f'{site_name}.json'
    with open(latest_file, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_urls))


def save_diff(site_name, new_urls):
    today = datetime.now().strftime('%Y%m%d')
    date_dir = Path('diff') / today
    date_dir.mkdir(parents=True, exist_ok=True)

    file_path = date_dir / f'{site_name}.json'
    mode = 'a' if file_path.exists() else 'w'
    with open(file_path, mode, encoding='utf-8') as f:
        if mode == 'a':
            f.write('\n--------------------------------\n')
        f.write('\n'.join(new_urls) + '\n')


def compare_data(site_name, new_urls):
    latest_file = Path('latest') / f'{site_name}.json'
    if not latest_file.exists():
        return []

    with open(latest_file, encoding='utf-8') as f:
        last_urls = {url for url in f.read().splitlines() if is_http_url(url)}

    return [url for url in new_urls if url not in last_urls]


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


def main(config_path='config.yaml'):
    config = load_config(config_path)
    limits = get_sitemap_limits(config)
    scraper = cloudscraper.create_scraper()
    scraper.headers.update({
        'Accept': 'application/xml,text/xml;q=0.9,text/plain;q=0.8,*/*;q=0.1'
    })

    for site in config['sites']:
        if not site['active']:
            continue

        logging.info("Processing site: %s", site['name'])
        state = {
            'visited_sitemaps': set(),
            'sitemap_count': 0,
            'url_count': 0,
            'seen_urls': set(),
        }
        all_urls = []
        for sitemap_url in site['sitemap_urls']:
            urls = process_sitemap(sitemap_url, scraper, limits, state)
            all_urls.extend(urls)

        unique_urls = [url for url in {url: None for url in all_urls}.keys() if is_http_url(url)]
        new_urls = compare_data(site['name'], unique_urls)

        save_latest(site['name'], unique_urls)
        if new_urls:
            save_diff(site['name'], new_urls)
            send_feishu_notification(new_urls, config, site['name'])

        cleanup_old_data(site['name'], config)


def cleanup_old_data(site_name, config):
    data_dir = Path('diff')
    if not data_dir.exists():
        return

    retention_days = config.get('retention_days', 7)
    cutoff = datetime.now() - timedelta(days=retention_days)

    for date_dir in data_dir.glob('*'):
        if not date_dir.is_dir():
            continue

        try:
            dir_date = datetime.strptime(date_dir.name, '%Y%m%d')
            if dir_date < cutoff:
                for f in date_dir.glob('*.json'):
                    f.unlink()
                date_dir.rmdir()
                logging.info("Removed expired directory: %s", date_dir.name)
        except ValueError:
            continue
        except Exception as e:
            logging.error("Failed to remove expired directory %s: %s", date_dir.name, str(e))


if __name__ == '__main__':
    main()
