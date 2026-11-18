#!/usr/bin/env python3
"""每日更新 data.json：比特幣價格（Coinbase，失敗改用 CoinGecko）＋ BBC 商業新聞。
任何一部分失敗，都保留舊資料並記下原因與最後成功時間。"""
import json, os, sys, time, datetime, email.utils
import urllib.request, urllib.error
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urlunsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, 'data.json')
FORCE_FAIL = os.environ.get('FORCE_FAIL', '')  # 測試用：price / news / price,news


def fetch_text(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0 market-dashboard'})
    try:
        with urllib.request.urlopen(req, timeout=25) as r:
            return r.read().decode('utf-8')
    except urllib.error.HTTPError as e:
        raise RuntimeError('來源回應 HTTP %d' % e.code)
    except Exception as e:
        raise RuntimeError('無法連線（%s）' % str(e)[:60])


def price_coinbase():
    s = json.loads(fetch_text('https://api.exchange.coinbase.com/products/BTC-USD/stats'))
    c = json.loads(fetch_text('https://api.exchange.coinbase.com/products/BTC-USD/candles?granularity=86400'))
    last, op = float(s['last']), float(s['open'])
    if not (last > 0 and op > 0 and isinstance(c, list) and len(c) >= 20):
        raise RuntimeError('回傳格式不符')
    hist = [[int(x[0]) * 1000, round(x[4])] for x in reversed(c[:31])]
    hist[-1][1] = round(last)
    return 'Coinbase', {'usd': last, 'change': round((last / op - 1) * 100, 2), 'asOf': int(time.time() * 1000)}, hist


def price_coingecko():
    a = json.loads(fetch_text('https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=usd&include_24hr_change=true&include_last_updated_at=true'))['bitcoin']
    b = json.loads(fetch_text('https://api.coingecko.com/api/v3/coins/bitcoin/market_chart?vs_currency=usd&days=30&interval=daily'))['prices']
    if len(b) < 20:
        raise RuntimeError('回傳格式不符')
    return 'CoinGecko', {'usd': a['usd'], 'change': round(a['usd_24h_change'], 2), 'asOf': a['last_updated_at'] * 1000}, [[int(t), round(v)] for t, v in b]


def get_price():
    if 'price' in FORCE_FAIL:
        raise RuntimeError('（測試）故意讓價格更新失敗')
    errs = []
    for name, fn in (('Coinbase', price_coinbase), ('CoinGecko', price_coingecko)):
        try:
            return fn()
        except (RuntimeError, KeyError, ValueError, TypeError) as e:
            errs.append('%s：%s' % (name, e if isinstance(e, RuntimeError) else '回傳格式不符'))
    raise RuntimeError('；'.join(errs))


def get_news():
    if 'news' in FORCE_FAIL:
        raise RuntimeError('（測試）故意讓新聞更新失敗')
    try:
        ch = ET.fromstring(fetch_text('https://feeds.bbci.co.uk/news/business/rss.xml')).find('channel')
        items = []
        for it in ch.findall('item'):
            p = urlsplit(it.findtext('link').strip())
            items.append({
                'title': ' '.join(it.findtext('title').split()),
                'url': urlunsplit((p.scheme, p.netloc, p.path, '', '')),
                'source': 'BBC News',
                'at': int(email.utils.parsedate_to_datetime(it.findtext('pubDate')).timestamp() * 1000),
            })
    except (ET.ParseError, AttributeError, TypeError):
        raise RuntimeError('回傳格式不符')
    seen, uniq = set(), []
    for r in sorted(items, key=lambda r: r['at'], reverse=True):
        if r['url'] not in seen:
            seen.add(r['url'])
            uniq.append(r)
    if not uniq:
        raise RuntimeError('RSS 裡沒有任何新聞')
    return uniq[:6]


def main():
    try:
        prev = json.load(open(OUT, encoding='utf-8'))
    except (OSError, ValueError):
        prev = {}
    now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    d = {
        'attemptedAt': now,
        'price': prev.get('price'), 'history': prev.get('history', []), 'priceSource': prev.get('priceSource', ''),
        'priceStatus': 'ok', 'priceError': '', 'priceFetchedAt': prev.get('priceFetchedAt'),
        'news': prev.get('news', []),
        'newsStatus': 'ok', 'newsError': '', 'newsFetchedAt': prev.get('newsFetchedAt'),
    }
    try:
        d['priceSource'], d['price'], d['history'] = get_price()
        d['priceFetchedAt'] = now
    except RuntimeError as e:
        d['priceStatus'], d['priceError'] = 'failed', str(e)
    try:
        d['news'] = get_news()
        d['newsFetchedAt'] = now
    except RuntimeError as e:
        d['newsStatus'], d['newsError'] = 'failed', str(e)
    with open(OUT, 'w', encoding='utf-8') as f:
        json.dump(d, f, ensure_ascii=False, indent=1)
    print('價格：%s %s｜新聞：%s %s' % (d['priceStatus'], d['priceError'], d['newsStatus'], d['newsError']))
    # 兩者都失敗時讓排程顯示紅燈，方便發現；資料檔仍已寫入（保留舊資料）
    if d['priceStatus'] != 'ok' and d['newsStatus'] != 'ok':
        sys.exit(1)


main()
