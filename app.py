from flask import Flask, request, render_template_string
import sqlite3
import os
import platform

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "search.db")

# サーバーか自分のパソコンかを自動判別する関数
def detect_environment():
    # Renderなどの本番クラウド環境には特有の環境変数やLinux OSが使われる
    if os.environ.get("RENDER") or os.environ.get("PORT"):
        return "クラウドサーバー (本番公開中)"
    elif platform.system() == "Windows":
        return "ローカルPC (Windows / テスト環境)"
    else:
        return f"その他環境 ({platform.system()})"

HTML = """
<!doctype html>
<html lang="ja">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{% if query %}{{ query }} - {% endif %}openfil</title>
    <style>
        body {
            font-family: "BIZ UDGothic", "Meiryo", "MS Gothic", sans-serif;
            max-width: 720px;
            margin: 0 auto;
            padding: 20px;
            color: #222;
        }
        .top-center {
            text-align: center;
            margin-top: 120px;
        }
        .logo {
            font-size: 42px;
            font-weight: bold;
            letter-spacing: 2px;
            color: #1a73e8;
            text-decoration: none;
        }
        .logo-small {
            font-size: 24px;
            font-weight: bold;
            letter-spacing: 1px;
            color: #1a73e8;
            text-decoration: none;
            margin-right: 15px;
        }
        .search-box {
            margin-top: 20px;
        }
        input[type="text"] {
            width: 70%;
            max-width: 480px;
            padding: 12px 16px;
            font-size: 16px;
            border: 1px solid #dfe1e5;
            border-radius: 24px;
            outline: none;
        }
        input[type="text"]:focus {
            box-shadow: 0 1px 6px rgba(32,33,36,.28);
            border-color: transparent;
        }
        button {
            padding: 11px 20px;
            font-size: 15px;
            background-color: #f8f9fa;
            border: 1px solid #dadce0;
            border-radius: 20px;
            cursor: pointer;
            margin-left: 6px;
        }
        button:hover {
            border-color: #c6c6c6;
            background-color: #f1f3f4;
        }
        .stats {
            color: #70757a;
            font-size: 13px;
            margin-top: 12px;
        }
        .env-badge {
            display: inline-block;
            margin-top: 8px;
            padding: 3px 10px;
            font-size: 11px;
            border-radius: 12px;
            background-color: #f1f3f4;
            color: #5f6368;
        }
        .result {
            margin-top: 24px;
            border-bottom: 1px solid #eee;
            padding-bottom: 14px;
        }
        .result-title {
            font-size: 18px;
            color: #1a0dab;
            text-decoration: none;
        }
        .result-title:hover {
            text-decoration: underline;
        }
        .result-url {
            color: #006621;
            font-size: 13px;
            margin-top: 2px;
            word-break: break-all;
        }
        .snippet {
            color: #4d5156;
            font-size: 14px;
            margin-top: 6px;
            line-height: 1.5;
        }
    </style>
</head>
<body>
    {% if not query %}
        <div class="top-center">
            <a href="/" class="logo">openfil</a>
            <form method="get" class="search-box">
                <input type="text" name="q" placeholder="openfil で検索" autofocus>
                <button type="submit">検索</button>
            </form>
            <div class="stats">インデックス登録数: {{ total_pages }} ページ</div>
            <div class="env-badge">稼働環境: {{ env_name }}</div>
        </div>
    {% else %}
        <div>
            <form method="get" style="display: flex; align-items: center;">
                <a href="/" class="logo-small">openfil</a>
                <input type="text" name="q" value="{{ query }}" placeholder="キーワードを入力">
                <button type="submit">検索</button>
            </form>
        </div>

        <p class="stats">「{{ query }}」の検索結果（上位20件 / 全 {{ total_pages }} ページ中）｜ {{ env_name }}</p>
        {% for title, url, snippet in results %}
            <div class="result">
                <a href="{{ url }}" target="_blank" rel="noopener" class="result-title">{{ title }}</a>
                <div class="result-url">{{ url }}</div>
                <div class="snippet">{{ snippet }}</div>
            </div>
        {% else %}
            <p>「{{ query }}」に一致するページは見つかりませんでした。</p>
        {% endfor %}
    {% endif %}
</body>
</html>
"""

@app.route("/")
def index():
    query = request.args.get("q", "").strip()
    results = []
    total_pages = 0
    env_name = detect_environment()

    if os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        
        cur.execute("SELECT COUNT(*) FROM pages")
        row = cur.fetchone()
        total_pages = row if row else 0

        if query:
            like_q = f"%{query}%"
            cur.execute("""
                SELECT title, url, content
                FROM pages
                WHERE title LIKE ? OR content LIKE ?
                ORDER BY (CASE WHEN title LIKE ? THEN 0 ELSE 1 END)
                LIMIT 20
            """, (like_q, like_q, like_q))
            
            for title, url, content in cur.fetchall():
                idx = content.find(query)
                if idx != -1:
                    start = max(0, idx - 35)
                    end = min(len(content), idx + 95)
                    snippet = "..." + content[start:end] + "..."
                else:
                    snippet = content[:110] + "..."
                results.append((title, url, snippet))

        conn.close()

    return render_template_string(HTML, query=query, results=results, total_pages=total_pages, env_name=env_name)

if __name__ == "__main__":
    app.run()
