import argparse
import json
import sqlite3
import time
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URL = "https://github.com/orgs/google/repositories"
DB_FILE = Path(__file__).resolve().parent / "google_repositories.sqlite"


def read_page(session, page):
    time.sleep(1)
    response = session.get(
        URL, params={"q": "sort:name-asc", "page": page}, timeout=30
    )
    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    # 通常のHTMLに含まれる表示用データから、丸められていないスター数を読む。
    embedded = soup.select_one('script[data-target="react-app.embeddedData"]')
    if embedded is None:
        raise ValueError("リポジトリ一覧をHTMLから取得できません")
    listing = json.loads(embedded.get_text())["payload"]["orgReposPageRoute"]
    if listing.get("errorMessage"):
        raise ValueError(listing["errorMessage"])
    visible_names = {
        a.get_text(strip=True) for a in soup.select('h3 a[href^="/google/"]')
    }
    repositories = listing["repositories"]
    if visible_names != {repo["name"] for repo in repositories}:
        raise ValueError("HTML上の一覧と表示用データが一致しません")
    rows = []
    for repo in repositories:
        if repo["owner"].lower() != "google" or not repo["type"].startswith("Public"):
            raise ValueError("Google以外、または非公開のリポジトリが含まれています")
        language = repo["primaryLanguage"]
        stars = repo["starsCount"]
        if type(stars) is not int or stars < 0:
            raise ValueError("スター数が不正です")
        rows.append((repo["name"], language["name"] if language else None, stars))
    return rows, listing["repositoryCount"], listing["pageCount"]


def scrape():
    with requests.Session() as session:
        session.headers["User-Agent"] = "UniversityClassRepositoryScraper/1.0"
        rows, total, pages = read_page(session, 1)
        if total <= 0 or pages <= 0 or not rows:
            raise ValueError("一覧が空です")
        print(f"1/{pages} ページ、{len(rows)}/{total} 件取得", flush=True)
        for page in range(2, pages + 1):
            batch, current_total, current_pages = read_page(session, page)
            if (current_total, current_pages) != (total, pages) or not batch:
                raise ValueError("巡回中に一覧の件数が変わりました。再実行してください")
            rows.extend(batch)
            print(f"{page}/{pages} ページ、{len(rows)}/{total} 件取得", flush=True)
        _, final_total, final_pages = read_page(session, 1)
        if (final_total, final_pages) != (total, pages):
            raise ValueError("巡回中に一覧の件数が変わりました。再実行してください")
    if len(rows) != total or len({name.lower() for name, _, _ in rows}) != total:
        raise ValueError("取得件数が一致しないか、重複があります")
    return rows


def save(rows):
    connection = sqlite3.connect(DB_FILE)
    try:
        with connection:
            cursor = connection.cursor()
            cursor.execute(
                "CREATE TABLE IF NOT EXISTS repositories ("
                "name TEXT PRIMARY KEY COLLATE NOCASE, "
                "language TEXT, stars INTEGER NOT NULL CHECK(stars >= 0))"
            )
            cursor.execute("DELETE FROM repositories")
            cursor.executemany(
                "INSERT INTO repositories (name, language, stars) VALUES (?, ?, ?)",
                rows,
            )
    finally:
        connection.close()


def show():
    if not DB_FILE.exists():
        raise ValueError("DBがありません。まず python main.py を実行してください")
    connection = sqlite3.connect(DB_FILE)
    try:
        cursor = connection.cursor()
        cursor.execute(
            "SELECT name, language, stars FROM repositories ORDER BY name COLLATE NOCASE"
        )
        print("リポジトリ名\t主要な言語\tスター数")
        for name, language, stars in cursor:
            print(f"{name}\t{language or '言語未設定'}\t{stars}")
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--show-only", action="store_true", help="保存済みDBをSELECTで表示")
    args = parser.parse_args()
    try:
        if not args.show_only:
            rows = scrape()
            save(rows)
            print(f"{len(rows)} 件を {DB_FILE.name} に保存しました")
        show()
    except (requests.RequestException, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(1, f"処理を終了しました。{error}\n")


if __name__ == "__main__":
    main()
