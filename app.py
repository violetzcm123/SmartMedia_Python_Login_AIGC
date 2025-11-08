import requests
from flask import Flask, request, jsonify, render_template, redirect, url_for, session
from flask_cors import CORS
from volcengine.visual.VisualService import VisualService
import sqlite3, json
from datetime import datetime

app = Flask(__name__)
app.secret_key = 'smartmedia_secret_key'
CORS(app)


def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     username
                     TEXT
                     UNIQUE,
                     password
                     TEXT
                 )''')
    c.execute('''CREATE TABLE IF NOT EXISTS images
                 (
                     id
                     INTEGER
                     PRIMARY
                     KEY
                     AUTOINCREMENT,
                     user_id
                     INTEGER,
                     prompt
                     TEXT,
                     url
                     TEXT,
                     created_time
                     TIMESTAMP
                     DEFAULT
                     (datetime('now', 'localtime'))
                 )''')
    conn.commit()
    conn.close()


# ====================================================
# 🔹 从 TXT 文件读取 Ark 配置信息
# ====================================================
def get_ark_config():
    conf = {}
    with open("volc_config.txt", "r", encoding="utf-8") as f:
        for line in f:
            if "=" in line:
                key, val = line.strip().split("=", 1)
                conf[key.strip()] = val.strip()
    return conf


@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('home'))
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        data = request.form
        username, password = data['username'], data['password']
        conn = get_db()
        try:
            conn.execute("INSERT INTO users(username, password) VALUES(?,?)", (username, password))
            conn.commit()
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            return render_template('register.html', error='用户名已存在')
        finally:
            conn.close()
    return render_template('register.html')


@app.route('/login', methods=['POST'])
def login():
    username, password = request.form['username'], request.form['password']
    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE username=? AND password=?", (username, password)).fetchone()
    conn.close()
    if user:
        session['user_id'] = user['id']
        return redirect(url_for('home'))
    else:
        return render_template('login.html', error='用户名或密码错误')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))


@app.route('/home')
def home():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('index.html')

@app.route('/history')
def history_page():
    if 'user_id' not in session:
        return redirect(url_for('index'))
    return render_template('history.html')


@app.route('/api/generate', methods=['POST'])
def generate():
    data = request.json
    prompt = data.get("prompt")

    conf = get_ark_config()
    api_key = conf.get("ARK_API_KEY")
    model = conf.get("ARK_MODEL", "doubao-seedream-4-0-250828")
    size = conf.get("ARK_SIZE", "1024x1024")
    guidance = float(conf.get("ARK_GUIDANCE", 2.5))
    seed = int(conf.get("ARK_SEED", 42))
    watermark = conf.get("ARK_WATERMARK", "True").lower() == "true"

    url = "https://ark.cn-beijing.volces.com/api/v3/images/generations"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    payload = {
        "guidance_scale": guidance,
        "model": model,
        "prompt": prompt,
        "response_format": "url",
        "seed": seed,
        "size": size,
        "watermark": watermark
    }

    try:
        resp = requests.post(url, headers=headers, json=payload)
        result = resp.json()
        print(" Ark 响应：", result)

        if "data" in result and len(result["data"]) > 0:
            img_url = result["data"][0]["url"]
            return jsonify({"url": img_url})
        else:
            return jsonify({"error": result.get("error", "未知响应")})
    except Exception as e:
        print(" Ark生成失败：", e)
        return jsonify({"error": str(e)}), 500




@app.route('/api/save', methods=['POST'])
def save():
    if 'user_id' not in session:
        return jsonify({"error": "未登录"}), 401
    data = request.json
    local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute("INSERT INTO images(user_id, prompt, url,created_time) VALUES(?,?,?,?)",
                 (session['user_id'], data['prompt'], data['url'],local_time))
    conn.commit()
    conn.close()
    return jsonify({"message": "保存成功"})



@app.route('/api/history')
def history():
    if 'user_id' not in session:
        return jsonify([])
    conn = get_db()
    rows = conn.execute("SELECT * FROM images WHERE user_id=? ORDER BY id DESC",
                        (session['user_id'],)).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/delete/<int:image_id>', methods=['DELETE'])
def delete(image_id):
    conn = get_db()
    conn.execute("DELETE FROM images WHERE id=?", (image_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "删除成功"})


if __name__ == '__main__':
    init_db()
    app.run(port=5000, debug=True)
