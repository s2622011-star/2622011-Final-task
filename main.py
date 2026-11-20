import json
import sqlite3
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


def get_page(page):
    url = "https://github.com/orgs/google/repositories"
    for attempt in range(3):
        time.sleep(1)
        time.sleep(4)  # アクセス制限に対応するため、さらに4秒待つ
        response = requests.get(
            url, params={"q": "sort:name-asc", "page": page}, timeout=30
        )
        if response.status_code != 429 or attempt == 2:
            break
        wait = 120 * (attempt + 1)
        print(f"アクセス制限のため{wait}秒待ちます", flush=True)
        time.sleep(wait)
    response.raise_for_status()
    html = BeautifulSoup(response.content, "html.parser")
    # HTML内の表示用データを辞書に変換する。スター数を正確な整数で取得できる。
    script = html.find("script", {"data-target": "react-app.embeddedData"})
    if script is None:
        raise ValueError("HTMLから一覧を取得できませんでした")
    data = json.loads(script.get_text())
    return data["payload"]["orgReposPageRoute"]


# 名前順で最初から最後のページまで取得する。
data = get_page(1)
total = data["repositoryCount"]
pages = data["pageCount"]
rows = []
names = set()
if total <= 0 or pages <= 0:
    raise ValueError("一覧が空です")
for page in range(1, pages + 1):
    if page > 1:
        data = get_page(page)
    if data["repositoryCount"] != total or data["pageCount"] != pages:
        raise ValueError("一覧の件数が変わりました。再実行してください")
    for repo in data["repositories"]:
        name = repo["name"]
        if repo["owner"].lower() != "google" or name in names:
            raise ValueError("対象外のリポジトリ、または重複があります")
        names.add(name)
        language = None
        if repo["primaryLanguage"] is not None:
            language = repo["primaryLanguage"]["name"]
        rows.append((name, language, repo["starsCount"]))
    print(f"{page}/{pages} ページ、{len(rows)}/{total} 件取得", flush=True)
if len(rows) != total:
    raise ValueError("全件取得できませんでした")

# 全件の取得に成功したら、SQLiteに保存する。
db_file = Path(__file__).with_name("google_repositories.sqlite")
con = sqlite3.connect(db_file)
try:
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE IF NOT EXISTS repositories "
        "(name TEXT PRIMARY KEY, language TEXT, stars INTEGER)"
    )
    cur.execute("DELETE FROM repositories")
    cur.executemany(
        "INSERT INTO repositories (name, language, stars) VALUES (?, ?, ?)", rows
    )
    con.commit()

    # 保存したデータをSELECT文で取得し、全件表示する。
    cur.execute("SELECT name, language, stars FROM repositories ORDER BY name")
    print("リポジトリ名\t主要な言語\tスター数")
    for name, language, stars in cur:
        print(name, language or "言語未設定", stars, sep="\t")
finally:
    con.close()
