import requests
import gzip
import sqlite3
import os
import re
import platform
from urllib.parse import urlparse
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "search.db")
LOG_PATH = os.path.join(BASE_DIR, "log.txt")
MAX_LOG_ENTRIES = 30

# 環境に応じて目標件数を自動切り替え（PCなら250件、サーバーなら1000件）
def get_target_config():
    if os.environ.get("GITHUB_ACTIONS") or os.environ.get("RENDER") or os.environ.get("PORT") or platform.system() != "Windows":
        return 1000, "サーバー環境 (1,000件モード)"
    else:
        return 250, "ローカルPC環境 (250件モード)"

TARGET_COUNT, ENV_MODE_NAME = get_target_config()

log_lines = []

def write_log(message):
    print(message)
    log_lines.append(message)

# 日本語ページ判定（ひらがな・カタカナが一定以上含まれ、スパム単語を含まないかチェック）
NG_WORDS = ["无修正", "在线播放", "毛片", "黄色片", "成人一级", "免費看", "中文字幕", "パイズリ", "フェラチオ", "人妻", "巨乳", "AV作品"]

def is_clean_japanese(title, text):
    combined = title + " " + text
    # NGワードが含まれていたら除外
    for ng in NG_WORDS:
        if ng in combined:
            return False
    # ひらがな・カタカナが合計5文字以上含まれていること（中国語サイトの誤混入を防止）
    kana_matches = re.findall(r'[\u3040-\u309F\u30A0-\u30FF]', combined)
    return len(kana_matches) >= 5

def is_target_domain(url):
    try:
        host = urlparse(url).netloc.lower()
        return host.endswith((".jp", ".com", ".org", ".net"))
    except Exception:
        return False

existing_blocks = []
next_run_num = 1

if os.path.exists(LOG_PATH):
    try:
        with open(LOG_PATH, "r", encoding="utf-8") as f:
            old_content = f.read().strip()
        if old_content:
            raw_blocks = old_content.split("========================================")
            for b in raw_blocks:
                b_clean = b.strip()
                if b_clean:
                    existing_blocks.append("========================================\n" + b_clean)
            found_nums = re.findall(r'\[実行 #(\d+)\]', old_content)
            if found_nums:
                next_run_num = max(int(n) for n in found_nums) + 1
    except Exception:
        pass

write_log("========================================")
write_log(f"=== [実行 #{next_run_num}] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
write_log(f"実行モード: {ENV_MODE_NAME}")

# 古い search.db を削除
for suffix in ["", "-journal", "-wal", "-shm"]:
    target_file = DB_PATH + suffix
    if os.path.exists(target_file):
        try:
            os.remove(target_file)
            write_log(f"古いデータベースを削除しました: {os.path.basename(target_file)}")
        except Exception as e:
            write_log(f"削除失敗: {e}")

conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()
cur.execute("""
    CREATE TABLE IF NOT EXISTS pages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        url TEXT UNIQUE,
        title TEXT,
        content TEXT
    )
""")
conn.commit()

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; openfil/1.0)"}
LATEST_ID = "CC-MAIN-2026-43"

try:
    write_log(f"使用アーカイブ: {LATEST_ID}")
    wet_paths_url = "https://" + f"data.commoncrawl.org/crawl-data/{LATEST_ID}/wet.paths.gz"
    write_log("データファイル一覧を取得中...")
    paths_res = requests.get(wet_paths_url, headers=HEADERS, timeout=20)
    paths_res.raise_for_status()
    wet_paths = gzip.decompress(paths_res.content).decode("utf-8").strip().split("\n")

    total_saved = 0
    # 1つのファイルで1000件に届かない場合に備え、最大5ファイルまで順番に巡回
    for wet_rel_path in wet_paths[:5]:
        if total_saved >= TARGET_COUNT:
            break

        wet_rel_path = wet_rel_path.strip()
        wet_file_url = "https://" + "data.commoncrawl.org/" + wet_rel_path
        write_log(f"ストリーミング受信開始: {wet_rel_path}")

        with requests.get(wet_file_url, headers=HEADERS, stream=True, timeout=30) as res:
            res.raise_for_status()
            with gzip.open(res.raw, "rt", encoding="utf-8", errors="ignore") as f:
                current_url = ""
                in_body = False
                body_lines = []

                for line in f:
                    if line.startswith("WARC/1.0"):
                        if current_url and body_lines and is_target_domain(current_url):
                            title = body_lines.pop(0).strip()[:120] or current_url
                            full_text = " ".join(body_lines).strip()
                            if len(full_text) > 50 and is_clean_japanese(title, full_text):
                                content = full_text[:800]
                                cur.execute(
                                    "INSERT OR IGNORE INTO pages (url, title, content) VALUES (?, ?, ?)",
                                    (current_url, title, content)
                                )
                                if cur.rowcount > 0:
                                    conn.commit()
                                    total_saved += 1
                                    write_log(f"[{total_saved}/{TARGET_COUNT}] 保存: {title} ({current_url})")

                                    if total_saved >= TARGET_COUNT:
                                        write_log("目標件数に達したため受信を終了します。")
                                        break

                        current_url = ""
                        in_body = False
                        body_lines = []

                    elif not in_body:
                        if line.startswith("WARC-Target-URI:"):
                            current_url = line.split(":", 1).pop().strip()
                        elif line.strip() == "" and current_url:
                            in_body = True
                    else:
                        clean_line = line.strip()
                        if clean_line:
                            body_lines.append(clean_line)

    cur.execute("VACUUM")
    write_log(f"\n完了！合計 {total_saved} 件の日本語ページを保存しました。")
    write_log(f"データベース保存先: {DB_PATH}")

except Exception as e:
    write_log(f"\n予期せぬエラーで終了しました: {e}")

finally:
    conn.close()
    write_log(f"=== [実行 #{next_run_num}] 終了: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} ===")
    
    existing_blocks.append("\n".join(log_lines))
    kept_blocks = existing_blocks[-MAX_LOG_ENTRIES:]
    
    with open(LOG_PATH, "w", encoding="utf-8") as f:
        f.write("\n\n".join(kept_blocks) + "\n")
    print(f"ログを更新しました（保持件数: {len(kept_blocks)}/{MAX_LOG_ENTRIES}回分）: {LOG_PATH}")
