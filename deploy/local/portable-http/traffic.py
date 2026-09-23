"""Bounded real HTTP load; reports responses, never writes metrics or incidents."""

import argparse
import time
import urllib.error
import urllib.request
from collections import Counter

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8082/work')
    parser.add_argument('--seconds', type=int, default=360)
    args = parser.parse_args()
    if not 1 <= args.seconds <= 1800:
        parser.error('seconds must be between 1 and 1800')
    counts: Counter[int] = Counter()
    end = time.monotonic() + args.seconds
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    while time.monotonic() < end:
        try:
            with opener.open(args.url, timeout=2) as response:
                response.read()
                counts[response.status] += 1
        except urllib.error.HTTPError as error:
            with error:
                error.read()
                counts[error.code] += 1
        time.sleep(0.2)
    print(dict(counts))
