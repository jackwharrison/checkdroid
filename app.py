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

REQUIRED_PERMISSIONS = [
    "registration:attribute.update",
    "registration:attribute:financial.update",
    "registration:personal.update",
    "registration:status:markAsValidated.update",
]


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
    """
    Try to log in to the 121 API.

    Returns: (token, program_ids, error_message)
      - token: access_token_general on success, else None
      - program_ids: list[int] of programs that have ALL REQUIRED_PERMISSIONS
      - error_message: None on success, or a human-readable string
    """
    if not base_url:
        return None, [], "System not configured: url121 is missing."

    login_url = f"{base_url.rstrip('/')}/api/users/login"
    payload = {"username": username, "password": password}

    try:
        res = requests.post(login_url, json=payload, timeout=15, verify=verify_tls)
    except Exception:
        return None, [], "Unable to reach login server. Please try again later."

    # Wrong email/password
    if res.status_code in (400, 401):
        return None, [], "Invalid email or password. Double-check your credentials and try again."

    # Any non-success status
    if res.status_code != 201:
        return None, [], f"Login failed ({res.status_code}). Please contact support."

    # 201 – success, now enforce program permissions
    data = res.json()
    token = data.get("access_token_general")
    permissions_by_program = data.get("permissions", {}) or {}

    allowed_program_ids: list[int] = []

    for pid_str, perm_list in permissions_by_program.items():
        # Ensure perm_list is a list
        perms = perm_list or []
        if all(req in perms for req in REQUIRED_PERMISSIONS):
            try:
                allowed_program_ids.append(int(pid_str))
            except ValueError:
                # Ignore any weird non-int keys
                continue

    if not allowed_program_ids:
        # User logged in, but has no programs with the full permission set
        msg = (
            "You do not have access to any programs with validation permissions in CheckDroid. "
            "Please contact your 121 system administrator."
        )
        return None, [], msg

    return token, allowed_program_ids, None

def fetch_new_registrations_121(base_url: str, token: str, program_id: int, verify_tls: bool = True):
    """
    Fetch all registrations for a program from 121 and return only those
    with status == 'new'. Handles pagination of the /registrations endpoint.
    """
    base_url = base_url.rstrip("/")
    page = 1
    limit = 100  # or 20 if you want default
    all_new: list[dict] = []

    while True:
        params = {
            "page": page,
            "limit": limit,
            "sortBy": "id:ASC",
        }
        url = f"{base_url}/api/programs/{program_id}/registrations"

        res = requests.get(
            url,
            params=params,
            cookies={"access_token_general": token},
            timeout=20,
            verify=verify_tls,
        )

        if res.status_code != 200:
            raise RuntimeError(f"121 registrations returned {res.status_code} (page {page}).")

        payload = res.json()
        data = payload.get("data", []) or []
        meta = payload.get("meta", {}) or {}

        # Filter by status == "new"
        for reg in data:
            if str(reg.get("status", "")).lower() == "new":
                all_new.append(reg)

        total_pages = meta.get("totalPages", 1)
        current_page = meta.get("currentPage", page)

        if current_page >= total_pages:
            break

        page += 1

    return all_new

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
        error = None
        email_value = ""

        if request.method == "POST":
            email_value = (request.form.get("username") or "").strip()
            password = request.form.get("password") or ""

            # Basic e-mail validation before calling 121
            if not email_value or "@" not in email_value:
                error = "Please enter a valid e-mail address."
            elif not password:
                error = "Password is required."
            else:
                config = load_config()
                base_url = config.get("url121")
                verify_tls = config.get("VERIFY_TLS", True)

                token, program_ids, api_error = login_121(
                    base_url=base_url,
                    username=email_value,
                    password=password,
                    verify_tls=verify_tls,
                )

                if api_error:
                    # Show nice red banner, not a 500
                    error = api_error
                else:
                    # Success – store session and go to landing page
                    session["token121"] = token          # <-- key matches login_required/api_programs
                    session["username"] = email_value
                    session["program_ids"] = program_ids
                    return redirect(url_for("index"))    # <-- send to landing page "/"

        return render_template("login.html", error=error, email=email_value)

    @app.route("/api/registrations")
    @login_required
    def api_registrations():
        cfg = load_config()
        base_url = cfg["url121"]
        verify_tls = cfg.get("VERIFY_TLS", True)

        token = session["token121"]
        program_id = request.args.get("program_id", type=int)

        if not program_id:
            return jsonify({"error": "Missing program_id"}), 400

        # Ensure user is allowed to see this program
        allowed_programs = session.get("program_ids", [])
        if program_id not in allowed_programs:
            return jsonify({"error": "Not allowed for this program"}), 403

        try:
            new_regs = fetch_new_registrations_121(
                base_url=base_url,
                token=token,
                program_id=program_id,
                verify_tls=verify_tls,
            )
        except Exception as e:
            print("Error fetching registrations:", e)
            return jsonify({"error": "Failed to fetch registrations from 121"}), 502

        # Return full objects (all fields), but ensure programId is present + correct
        full_records = []
        for r in new_regs:
            reg = dict(r)  # shallow copy to avoid mutating original
            reg["programId"] = reg.get("programId", program_id)
            full_records.append(reg)

        return jsonify({
            "program_id": program_id,
            "count": len(full_records),
            "registrations": full_records,
        })

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
