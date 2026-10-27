import base64
import io
import os
import re
import sqlite3
from datetime import datetime
from urllib.parse import urlparse

import qrcode
from flask import (
    Flask,
    abort,
    g,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)
from PIL import Image

THEMES = {"terminal", "win98"}
HEX_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")
MAX_CONTENT = 1000
MAX_LABEL = 80
MIN_SIZE = 100
MAX_SIZE = 600
MAX_HISTORY = 50

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 128 * 1024


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(os.path.join(app.instance_path, "qr_studio.db"))
        g.db.row_factory = sqlite3.Row
    return g.db


@app.teardown_appcontext
def close_db(exception):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    os.makedirs(app.instance_path, exist_ok=True)
    db = get_db()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS qr_codes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            label       TEXT,
            content     TEXT NOT NULL,
            foreground  TEXT NOT NULL,
            background  TEXT NOT NULL,
            size        INTEGER NOT NULL,
            created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_qr_codes_created
            ON qr_codes (created_at DESC, id DESC);
        """
    )
    db.commit()


def render_qr_png(content, foreground, background, size):
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=1,
        border=4,
    )
    qr.add_data(content)
    qr.make(fit=True)
    modules = qr.make_image(fill_color=foreground, back_color=background).convert("RGB")

    box = max(1, size // modules.width)
    scaled = modules.resize((modules.width * box, modules.height * box), Image.NEAREST)

    canvas = Image.new("RGB", (size, size), background)
    left = (size - scaled.width) // 2
    top = (size - scaled.height) // 2
    canvas.paste(scaled, (left, top))

    buffer = io.BytesIO()
    canvas.save(buffer, format="PNG")
    return buffer.getvalue()


def validate_url(content):
    if "://" not in content:
        return None
    parsed = urlparse(content)
    if parsed.scheme.lower() not in ("http", "https"):
        return "Only http and https links can be encoded as URLs."
    if not parsed.netloc:
        return "That link is missing a domain."
    return None


def parse_payload(data):
    content = str(data.get("content") or "").strip()
    if not content:
        return None, "Content is required."
    if len(content) > MAX_CONTENT:
        return None, f"Content is limited to {MAX_CONTENT} characters."

    label = str(data.get("label") or "").strip()
    if len(label) > MAX_LABEL:
        return None, f"Labels are limited to {MAX_LABEL} characters."

    foreground = str(data.get("foreground") or "#000000").strip()
    background = str(data.get("background") or "#ffffff").strip()
    if not HEX_COLOR.match(foreground) or not HEX_COLOR.match(background):
        return None, "Colors must be hex values like #1a1408."

    try:
        size = int(data.get("size", 300))
    except (TypeError, ValueError):
        return None, "Size must be a whole number."
    if not MIN_SIZE <= size <= MAX_SIZE:
        return None, f"Size must be between {MIN_SIZE} and {MAX_SIZE} px."

    url_error = validate_url(content)
    if url_error:
        return None, url_error

    return {
        "content": content,
        "label": label,
        "foreground": foreground,
        "background": background,
        "size": size,
    }, None


def get_qr_or_404(qr_id):
    row = get_db().execute(
        "SELECT * FROM qr_codes WHERE id = ?", (qr_id,)
    ).fetchone()
    if row is None:
        abort(404)
    return row


@app.context_processor
def inject_theme():
    theme = request.cookies.get("theme", "terminal")
    if theme not in THEMES:
        theme = "terminal"
    return {
        "theme": theme,
        "other_theme": "win98" if theme == "terminal" else "terminal",
    }


@app.template_filter("dt")
def format_datetime(value):
    try:
        stamp = datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
    except (TypeError, ValueError):
        return value or ""
    return stamp.strftime("%b %d, %Y at %H:%M UTC")


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/api/generate")
def api_generate():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({"error": "Send a JSON object."}), 400

    payload, error = parse_payload(data)
    if error:
        return jsonify({"error": error}), 400

    try:
        png = render_qr_png(
            payload["content"],
            payload["foreground"],
            payload["background"],
            payload["size"],
        )
    except (qrcode.exceptions.DataOverflowError, ValueError):
        return jsonify({"error": "That content is too long for one QR code."}), 400

    try:
        db = get_db()
        existing = db.execute(
            """
            SELECT id FROM qr_codes
            WHERE content = ? AND foreground = ? AND background = ? AND size = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (
                payload["content"],
                payload["foreground"],
                payload["background"],
                payload["size"],
            ),
        ).fetchone()

        if existing is not None:
            qr_id = existing["id"]
            db.execute(
                "UPDATE qr_codes SET label = ?, created_at = CURRENT_TIMESTAMP WHERE id = ?",
                (payload["label"], qr_id),
            )
        else:
            cursor = db.execute(
                """
                INSERT INTO qr_codes (label, content, foreground, background, size)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    payload["label"],
                    payload["content"],
                    payload["foreground"],
                    payload["background"],
                    payload["size"],
                ),
            )
            qr_id = cursor.lastrowid
            db.execute(
                """
                DELETE FROM qr_codes
                WHERE id NOT IN (
                    SELECT id FROM qr_codes
                    ORDER BY created_at DESC, id DESC
                    LIMIT ?
                )
                """,
                (MAX_HISTORY,),
            )
        db.commit()
    except sqlite3.Error:
        app.logger.exception("Could not save QR code")
        return jsonify({"error": "Could not save this QR code."}), 500

    image = base64.b64encode(png).decode("ascii")
    return jsonify(
        {
            "id": qr_id,
            "image": f"data:image/png;base64,{image}",
            "content": payload["content"],
            "label": payload["label"],
            "foreground": payload["foreground"],
            "background": payload["background"],
            "size": payload["size"],
        }
    )


@app.get("/qr/<int:qr_id>.png")
def qr_image(qr_id):
    row = get_qr_or_404(qr_id)
    png = render_qr_png(
        row["content"], row["foreground"], row["background"], row["size"]
    )
    return send_file(io.BytesIO(png), mimetype="image/png", max_age=300)


@app.get("/download/<int:qr_id>")
def download(qr_id):
    row = get_qr_or_404(qr_id)
    png = render_qr_png(
        row["content"], row["foreground"], row["background"], row["size"]
    )
    return send_file(
        io.BytesIO(png),
        mimetype="image/png",
        as_attachment=True,
        download_name=f"qr-{qr_id:04d}.png",
    )


@app.get("/history")
def history():
    entries = get_db().execute(
        "SELECT * FROM qr_codes ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return render_template("history.html", entries=entries)


@app.post("/history/<int:qr_id>/delete")
def delete(qr_id):
    db = get_db()
    cursor = db.execute("DELETE FROM qr_codes WHERE id = ?", (qr_id,))
    db.commit()
    if cursor.rowcount == 0:
        abort(404)
    return redirect(url_for("history"))


@app.post("/settings")
def settings():
    theme = request.form.get("theme", "")
    if theme not in THEMES:
        abort(400)

    next_url = request.form.get("next") or url_for("index")
    if next_url not in {url_for("index"), url_for("history")}:
        next_url = url_for("index")

    response = redirect(next_url)
    response.set_cookie(
        "theme", theme, max_age=60 * 60 * 24 * 365, samesite="Lax", httponly=False
    )
    return response


with app.app_context():
    init_db()


if __name__ == "__main__":
    app.run(debug=True)
