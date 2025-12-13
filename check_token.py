import os
import pathlib
import urllib.request
import urllib.error


def read_token_from_env(path):
    p = pathlib.Path(path)
    if not p.exists():
        return None
    raw = p.read_text().strip()
    if '=' in raw:
        return raw.split('=', 1)[1].strip()
    return raw


def mask(s):
    if not s:
        return '<none>'
    return (s[:6] + '...' + s[-6:]) if len(s) > 12 else ('*' * len(s))


def main():
    env_path = r'c:\Users\herna\Desktop\HootBot\.env'
    token = read_token_from_env(env_path)
    print('Local .env token present:', bool(token))
    if token:
        print('Masked token:', mask(token), 'length=', len(token))
    else:
        print('No token found in .env; aborting check')
        return

    url = 'https://discord.com/api/v10/users/@me'
    req = urllib.request.Request(url, headers={
        'Authorization': f'Bot {token}',
        'User-Agent': 'HootBot-TokenCheck/1.0'
    })
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print('HTTP status:', resp.status)
            # Don't print the body; just success
    except urllib.error.HTTPError as e:
        print('HTTPError:', e.code, getattr(e, 'reason', ''))
    except Exception as e:
        print('Error during request:', repr(e))


if __name__ == '__main__':
    main()
