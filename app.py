import json
import os
from functools import wraps

import requests
from flask import Flask, render_template, request, redirect, url_for, session, flash, jsonify
from flask_session import Session

APP_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(APP_DIR, "system_config.json")

DEFAULT_CONFIG = {
    "url121": "",
    "VERIFY_TLS": True
}


def load_config():
    if not os.path.exists(CONFIG_PATH):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    for k, v in DEFAULT_CONFIG.items():
        cfg.setdefault(k, v)
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=2)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("token121"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


# -----------------------
# 121 client (matches Scandroid behavior you pasted)
# -----------------------
def login_121(base_url: str, username: str, password: str, verify_tls: bool = True):
    url = f"{base_url.rstrip('/')}/api/users/login"
    payload = {"username": username, "password": password}

    try:
        res = requests.post(url, json=payload, timeout=15, verify=verify_tls)
    except Exception as e:
        raise RuntimeError("Unable to reach login server.") from e

    if res.status_code in (400, 401):
        raise RuntimeError("Incorrect username or password.")
    if res.status_code != 201:
        raise RuntimeError(f"Login failed ({res.status_code}).")

    j = res.json()
    token = j.get("access_token_general")
    if not token:
        raise RuntimeError("Login succeeded but access_token_general was not returned.")

    permissions = j.get("permissions", {}) or {}
    try:
        program_ids = [int(pid) for pid in permissions.keys()]
    except Exception:
        program_ids = list(permissions.keys())

    return token, program_ids


def get_program_121(base_url: str, token: str, program_id: int, verify_tls: bool = True):
    url = f"{base_url.rstrip('/')}/api/programs/{program_id}"
    res = requests.get(
        url,
        cookies={"access_token_general": token},
        timeout=15,
        verify=verify_tls
    )
    if res.status_code != 200:
        raise RuntimeError(f"Unable to load program {program_id} ({res.status_code}).")
    return res.json()


def create_app():
    app = Flask(__name__)
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

    # Server-side sessions
    app.config["SESSION_TYPE"] = "filesystem"
    app.config["SESSION_FILE_DIR"] = os.path.join(APP_DIR, ".flask_session")
    app.config["SESSION_PERMANENT"] = False
    Session(app)

    # -----------------------
    # Config page (url121)
    # -----------------------
    @app.route("/config", methods=["GET", "POST"])
    def config():
        cfg = load_config()
        if request.method == "POST":
            cfg["url121"] = (request.form.get("url121") or "").strip().rstrip("/")
            cfg["VERIFY_TLS"] = (request.form.get("VERIFY_TLS") == "true")
            save_config(cfg)
            flash("Saved configuration.")
            return redirect(url_for("config"))
        return render_template("config.html", cfg=cfg)

    # -----------------------
    # Login page
    # -----------------------
    @app.route("/login", methods=["GET", "POST"])
    def login():
        cfg = load_config()
        base_url = cfg.get("url121")

        if request.method == "POST":
            if not base_url:
                flash("Missing url121. Set it in Config first.")
                return redirect(url_for("config"))

            username = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            token, program_ids = login_121(
                base_url=base_url,
                username=username,
                password=password,
                verify_tls=cfg.get("VERIFY_TLS", True),
            )

            session["token121"] = token
            session["username"] = username
            session["program_ids"] = program_ids
            # default selected program (first accessible)
            if program_ids:
                session["selected_program_id"] = int(program_ids[0])

            return redirect(url_for("index"))

        return render_template("login.html", url121=base_url or "")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    # -----------------------
    # Landing page
    # -----------------------
    @app.route("/")
    @login_required
    def index():
        cfg = load_config()
        return render_template(
            "index.html",
            url121=cfg.get("url121", ""),
            username=session.get("username", "")
        )

    # -----------------------
    # API: list programs (titles for dropdown)
    # -----------------------
    @app.route("/api/programs")
    @login_required
    def api_programs():
        cfg = load_config()
        base_url = cfg["url121"]
        token = session["token121"]
        program_ids = session.get("program_ids", [])

        programs = []
        for pid in program_ids:
            try:
                pdata = get_program_121(
                    base_url=base_url,
                    token=token,
                    program_id=int(pid),
                    verify_tls=cfg.get("VERIFY_TLS", True),
                )
                title_dict = pdata.get("titlePortal", {}) or {}
                title = next(iter(title_dict.values()), f"Program {pid}")
                programs.append({"id": int(pid), "title": title})
            except Exception:
                programs.append({"id": int(pid), "title": f"Program {pid}"})

        programs.sort(key=lambda x: x["title"].lower())
        return jsonify({"programs": programs, "selected_program_id": session.get("selected_program_id")})

    # -----------------------
    # API: set selected program
    # -----------------------
    @app.route("/api/select-program", methods=["POST"])
    @login_required
    def api_select_program():
        pid = request.json.get("program_id")
        try:
            session["selected_program_id"] = int(pid)
        except Exception:
            return jsonify({"ok": False, "error": "Invalid program_id"}), 400
        return jsonify({"ok": True, "selected_program_id": session["selected_program_id"]})

    return app


if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=5000, debug=True)
