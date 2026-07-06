import os
import re
from flask import Flask, request, render_template, jsonify, send_from_directory

app = Flask(__name__)

# ── 配置 ──────────────────────────────────────────────
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
MAX_FILE_SIZE = 200 * 1024 * 1024  # 单文件上限 200 MB
os.makedirs(UPLOAD_DIR, exist_ok=True)

app.config["MAX_CONTENT_LENGTH"] = MAX_FILE_SIZE * 5


def _sanitize_filename(name: str) -> str:
    """清理文件名：去除危险字符、截断过长名称"""
    if not name:
        raise ValueError("无效的文件名")

    # 取 basename，防止路径穿越 (../../etc/passwd)
    name = os.path.basename(name)

    # 移除 null byte（Werkzeug 已拦截，但双重保险）
    if "\x00" in name:
        raise ValueError("文件名包含非法字符")

    # 移除 Windows/Unix 非法字符: \ / : * ? " < > | 以及控制字符
    name = re.sub(r'[/\\:*?"<>|\x00-\x1f]', '_', name)

    # 去除首尾空格和点号（Windows 会 stripping）
    name = name.strip(" .")

    if not name:
        raise ValueError("无效的文件名")

    # Windows MAX_PATH ≈ 260，留余量截断到 200
    max_len = 200
    if len(name) > max_len:
        base, ext = os.path.splitext(name)
        while len(base) + len(ext) > max_len and base:
            base = base[:-1]
        name = base + ext if base else f"file{ext}"

    return name


def _save_one(f):
    """保存单个文件，返回 (save_name, size)"""
    original = _sanitize_filename(f.filename or "")

    # 防重名：同名自动加序号后缀
    save_name = original
    counter = 1
    base, ext = os.path.splitext(original)
    while os.path.exists(os.path.join(UPLOAD_DIR, save_name)):
        save_name = f"{base}_{counter}{ext}"
        counter += 1

    # 读取内容并检查大小（f.content_length 在 multipart 中始终为 0，不可靠）
    data = f.read()
    if len(data) > MAX_FILE_SIZE:
        raise ValueError(f"文件过大 ({len(data) / 1024 / 1024:.0f}MB > {MAX_FILE_SIZE // 1024 // 1024}MB)")

    filepath = os.path.join(UPLOAD_DIR, save_name)
    with open(filepath, "wb") as dst:
        dst.write(data)

    size = len(data)
    return save_name, size


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/favicon.ico")
def favicon_ico():
    import os
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "favicon.ico", mimetype="image/x-icon")


@app.route("/favicon.png")
def favicon_png():
    import os
    return send_from_directory(os.path.dirname(os.path.abspath(__file__)), "favicon.png", mimetype="image/png")


@app.route("/upload", methods=["POST"])
def upload():
    files = request.files.getlist("file")
    if not files or all(not f.filename for f in files):
        return jsonify(error="没有选择文件"), 400

    results = []
    errors = []
    for f in files:
        try:
            name, size = _save_one(f)
            results.append({"filename": name, "size": size})
        except ValueError as e:
            errors.append(str(e))
        except Exception as e:
            # 捕获文件系统异常（权限、磁盘满等）
            errors.append(f"保存失败: {e}")

    body = {"uploaded": len(results), "files": results}
    if errors:
        body["errors"] = errors
    return jsonify(body)


@app.route("/uploads/<path:filename>")
def download(filename):
    # send_from_directory 已内置路径穿越保护
    return send_from_directory(UPLOAD_DIR, filename)


@app.route("/api/files")
def list_files():
    import time
    files = []
    for name in sorted(os.listdir(UPLOAD_DIR)):
        path = os.path.join(UPLOAD_DIR, name)
        if os.path.isfile(path):
            stat = os.stat(path)
            files.append({
                "name": name,
                "size": stat.st_size,
                "mtime": int(stat.st_mtime),
            })
    return jsonify(files)


# ── 启动 ──────────────────────────────────────────────
if __name__ == "__main__":
    import socket

    port = int(os.environ.get("PORT", 5000))

    # 自动获取本机局域网 IP
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
    except Exception:
        local_ip = "127.0.0.1"
    finally:
        s.close()

    print("=" * 56)
    print("  File-Trans 局域网文件接收服务")
    print("=" * 56)
    print(f"  本机 IP       : {local_ip}")
    print(f"  访问地址      : http://{local_ip}:{port}")
    print(f"  文件大小限制  : {MAX_FILE_SIZE // 1024 // 1024} MB / file")
    print(f"  文件存放目录  : {UPLOAD_DIR}")
    print("=" * 56)

    app.run(host="0.0.0.0", port=port, debug=False)
