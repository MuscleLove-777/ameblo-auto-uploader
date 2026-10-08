"""LINE delivery adapter; credentials stay in environment and are never logged."""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
import sys
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--outcome', choices=['auth_failed', 'unconfirmed', 'completed'], required=True)
    parser.add_argument('--attempt', choices=['1', '2', '3'], default='1')
    args = parser.parse_args(argv)
    if not os.environ.get('LINE_CHANNEL_TOKEN') or not os.environ.get('LINE_USER_ID'):
        print('::warning::LINE notification is not configured; message was not sent.')
        return 2
    messages = {
        'auth_failed': 'Cookie の期限確認に失敗し、投稿処理を停止しました。認証更新が必要です。',
        'unconfirmed': '投稿処理の正常完了を確認できません。再実行前に公開結果と台帳を照合してください。',
        'completed': '投稿スクリプトが正常終了しました。公開記事と台帳で投稿結果を確認してください。',
    }
    now = datetime.now(timezone(timedelta(hours=9))).strftime('%Y-%m-%d %H:%M JST')
    text = messages[args.outcome] + '\n時刻: ' + now
    if args.outcome == 'completed':
        text += '\n試行: ' + args.attempt
    repository = os.environ.get('GITHUB_REPOSITORY', '')
    run_id = os.environ.get('GITHUB_RUN_ID', '')
    if repository and run_id:
        text += '\nログ: https://github.com/' + repository + '/actions/runs/' + run_id
    payload = {'to': os.environ['LINE_USER_ID'], 'messages': [{'type': 'text', 'text': text}]}
    headers = {'Content-Type': 'application/json', 'Authorization': os.environ['LINE_CHANNEL_TOKEN']}
    headers['Authorization'] = 'Bearer ' + headers['Authorization']
    request = Request('https://api.line.me/v2/bot/message/push',
                      data=json.dumps(payload, ensure_ascii=False).encode('utf-8'),
                      headers=headers, method='POST')
    try:
        with urlopen(request, timeout=30) as response:
            if response.status != 200:
                print('::warning::LINE did not accept the notification; message was not confirmed.')
                return 3
    except (HTTPError, URLError, TimeoutError, OSError):
        print('::warning::LINE request failed; message was not confirmed. Check notification configuration.')
        return 3
    print('LINE accepted the notification request.')
    return 0


if __name__ == '__main__':
    sys.exit(main())
