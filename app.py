import os
import base64
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
                     id INTEGER PRIMARY KEY AUTOINCREMENT,
                     user_id INTEGER,
                     prompt TEXT,
                     url TEXT,
                     created_time TIMESTAMP DEFAULT (datetime('now', 'localtime'))
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


# ====================================================
# 保存Base64图片到本地并返回URL
# ====================================================
def save_base64_image(base64_data):
    """将Base64图片数据保存到本地，返回本地URL"""
    try:
        # 去除Base64前缀（如：data:image/jpeg;base64,）
        if ',' in base64_data:
            base64_data = base64_data.split(',')[1]

        img_data = base64.b64decode(base64_data)
        os.makedirs("static/image", exist_ok=True)
        filename = f"img_{int(datetime.now().timestamp())}_{os.urandom(4).hex()}.jpg"
        save_path = os.path.join("static", "image", filename)

        with open(save_path, "wb") as f:
            f.write(img_data)

        return f"/static/image/{filename}"
    except Exception as e:
        print(f"保存Base64图片失败: {e}")
        return None


# ====================================================
# 页面路由
# ====================================================

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
        session['user'] = user['username']
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


# ====================================================
# 生成图片（支持图生图 + 自动下载保存）
# ====================================================
@app.route('/api/generate', methods=['POST'])
def generate():
    data = request.json
    prompt = data.get("prompt")
    image_url = data.get("image")  # 图生图时上传的原图URL

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
        "watermark": watermark,
        "image_url": image_url
    }

    print("Ark 请求参数：", json.dumps(payload, ensure_ascii=False, indent=2))

    if image_url:
        payload["image"] = image_url  # 图生图
    try:
        resp = requests.post(url, headers=headers, json=payload)
        result = resp.json()
        print("Ark 响应：", result)

        if "data" in result and len(result["data"]) > 0:
            ark_url = result["data"][0]["url"]

            # 下载图片到 static/image 文件夹
            img_data = requests.get(ark_url).content
            os.makedirs("static/image", exist_ok=True)
            filename = f"img_{int(datetime.now().timestamp())}.jpg"
            save_path = os.path.join("static", "image", filename)
            with open(save_path, "wb") as f:
                f.write(img_data)

            local_url = f"/static/image/{filename}"
            return jsonify({"url": local_url})
        else:
            return jsonify({"error": result.get("error", "未知响应")})
    except Exception as e:
        print("Ark生成失败：", e)
        return jsonify({"error": str(e)}), 500


# ====================================================
# 多图融合功能
# ====================================================
@app.route('/api/generate_multi', methods=['POST'])
def generate_multi():
    data = request.json
    prompt = data.get("prompt")
    images = data.get("images", [])  # 多张图片的Base64数组

    if len(images) < 2:
        return jsonify({"error": "请至少上传两张图片"}), 400

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

    # 直接使用Base64字符串，不保存到本地
    # 注意：火山引擎API要求Base64字符串不带前缀，但我们之前图生图接口是带前缀的，所以这里我们尝试带前缀
    # 如果失败，我们再尝试去掉前缀
    image_list = []
    for img_base64 in images:
        # 如果Base64字符串包含前缀，我们保留它，因为图生图就是这样使用的
        image_list.append(img_base64)

    payload = {
        "guidance_scale": guidance,
        "model": model,
        "prompt": prompt,
        "response_format": "url",
        "seed": seed,
        "size": size,
        "watermark": watermark,
        "image": image_list,  # 多图融合使用image参数，值为Base64字符串数组
        "sequential_image_generation": "disabled"
    }

    print("多图融合 Ark 请求参数：", json.dumps(payload, ensure_ascii=False, indent=2))

    try:
        resp = requests.post(url, headers=headers, json=payload)
        result = resp.json()
        print("多图融合 Ark 响应：", result)

        if "data" in result and len(result["data"]) > 0:
            ark_url = result["data"][0]["url"]

            # 下载图片到 static/image 文件夹
            img_data = requests.get(ark_url).content
            os.makedirs("static/image", exist_ok=True)
            filename = f"multi_img_{int(datetime.now().timestamp())}.jpg"
            save_path = os.path.join("static", "image", filename)
            with open(save_path, "wb") as f:
                f.write(img_data)

            local_url = f"/static/image/{filename}"
            return jsonify({"url": local_url})
        else:
            return jsonify({"error": result.get("error", "未知响应")})
    except Exception as e:
        print("多图融合生成失败：", e)
        return jsonify({"error": str(e)}), 500


# ====================================================
# 保存生成记录
# ====================================================
@app.route('/api/save', methods=['POST'])
def save():
    if 'user_id' not in session:
        return jsonify({"error": "未登录"}), 401
    data = request.json
    prompt = data.get("prompt")
    url = data.get("url")
    image_type = data.get("type", "text2img")  # 默认文生图
    source_image = data.get("source_image")

    local_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db()
    conn.execute(
        "INSERT INTO images(user_id, prompt, url, type, source_image, created_time) VALUES(?,?,?,?,?,?)",
        (session['user_id'], prompt, url, image_type, source_image, local_time)
    )
    conn.commit()
    conn.close()
    return jsonify({"message": "保存成功"})


# ====================================================
# 查询历史记录（支持关键词搜索）
# ====================================================
@app.route('/api/history')
def history():
    if 'user_id' not in session:
        return jsonify([])
    keyword = request.args.get('q', '').strip()
    conn = get_db()
    if keyword:
        rows = conn.execute(
            "SELECT * FROM images WHERE user_id=? AND prompt LIKE ? ORDER BY id DESC",
            (session['user_id'], f"%{keyword}%")
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM images WHERE user_id=? ORDER BY id DESC",
            (session['user_id'],)
        ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


@app.route('/api/delete/<int:image_id>', methods=['DELETE'])
def delete(image_id):
    conn = get_db()
    row = conn.execute("SELECT url FROM images WHERE id=?", (image_id,)).fetchone()
    if row and row["url"].startswith("/static/image/"):
        file_path = row["url"].lstrip("/")
        if os.path.exists(file_path):
            os.remove(file_path)
    conn.execute("DELETE FROM images WHERE id=?", (image_id,))
    conn.commit()
    conn.close()
    return jsonify({"message": "删除成功"})


if __name__ == '__main__':
    init_db()
    app.run(port=5000, debug=True)
