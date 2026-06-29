import json
import os
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
ITEMS_FILE = DATA_DIR / "items.json"
LOANS_FILE = DATA_DIR / "loans.json"


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "equipment-manager-secret-key-2026")


def ensure_data_dir():
    DATA_DIR.mkdir(parents=True, exist_ok=True)


def read_json(path: Path, default):
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: Path, data):
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


def initialize_storage():
    ensure_data_dir()

    if not USERS_FILE.exists():
        users = {"admin": generate_password_hash("admin1234")}
        write_json(USERS_FILE, users)

    if not ITEMS_FILE.exists():
        sample_items = [
            {
                "id": 1,
                "name": "프로젝터",
                "category": "영상 장비",
                "asset_no": "PJ-001",
                "location": "창고 A",
                "quantity_total": 2,
                "quantity_available": 2,
                "notes": "HDMI 케이블 포함",
                "created_at": now_iso(),
            },
            {
                "id": 2,
                "name": "카메라",
                "category": "촬영 장비",
                "asset_no": "CM-002",
                "location": "미디어실",
                "quantity_total": 3,
                "quantity_available": 3,
                "notes": "배터리 2개 포함",
                "created_at": now_iso(),
            },
            {
                "id": 3,
                "name": "삼각대",
                "category": "촬영 장비",
                "asset_no": "TR-003",
                "location": "창고 B",
                "quantity_total": 4,
                "quantity_available": 4,
                "notes": "",
                "created_at": now_iso(),
            },
        ]
        write_json(ITEMS_FILE, sample_items)

    if not LOANS_FILE.exists():
        write_json(LOANS_FILE, [])


def load_users():
    return read_json(USERS_FILE, {})


def load_items():
    return read_json(ITEMS_FILE, [])


def save_items(items):
    write_json(ITEMS_FILE, items)


def load_loans():
    return read_json(LOANS_FILE, [])


def save_loans(loans):
    write_json(LOANS_FILE, loans)


def next_id(records):
    return max((record["id"] for record in records), default=0) + 1


def parse_positive_int(value, fallback=0):
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else fallback
    except (TypeError, ValueError):
        return fallback


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def build_dashboard_data():
    items = load_items()
    loans = load_loans()

    query = request.args.get("q", "").strip().lower()
    category = request.args.get("category", "").strip()
    status = request.args.get("status", "").strip()

    filtered_items = []
    for item in items:
        searchable = (
            f"{item['name']} {item['category']} {item['asset_no']} {item['location']}"
        ).lower()
        matches_query = not query or query in searchable
        matches_category = not category or item["category"] == category
        item_status = "available" if item["quantity_available"] > 0 else "unavailable"
        matches_status = not status or item_status == status

        if matches_query and matches_category and matches_status:
            filtered_items.append(item)

    active_loans = [loan for loan in loans if loan["status"] == "borrowed"]
    history = sorted(loans, key=lambda loan: loan["id"], reverse=True)
    categories = sorted({item["category"] for item in items if item["category"]})

    stats = {
        "total_items": len(items),
        "total_stock": sum(item["quantity_total"] for item in items),
        "available_stock": sum(item["quantity_available"] for item in items),
        "borrowed_count": sum(loan["quantity"] for loan in active_loans),
    }

    return {
        "items": filtered_items,
        "all_items": items,
        "active_loans": active_loans,
        "history": history,
        "categories": categories,
        "stats": stats,
        "filters": {"q": query, "category": category, "status": status},
    }


@app.route("/")
def index():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = load_users()

        if username in users and check_password_hash(users[username], password):
            session["username"] = username
            return redirect(url_for("dashboard"))
        error = "아이디 또는 비밀번호가 올바르지 않습니다."

    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.pop("username", None)
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template("dashboard.html", username=session["username"], **build_dashboard_data())


@app.route("/items", methods=["POST"])
@login_required
def create_item():
    items = load_items()

    quantity_total = max(parse_positive_int(request.form.get("quantity_total"), 1), 1)
    quantity_available = min(
        parse_positive_int(request.form.get("quantity_available"), quantity_total),
        quantity_total,
    )

    item = {
        "id": next_id(items),
        "name": request.form.get("name", "").strip(),
        "category": request.form.get("category", "").strip(),
        "asset_no": request.form.get("asset_no", "").strip(),
        "location": request.form.get("location", "").strip(),
        "quantity_total": quantity_total,
        "quantity_available": quantity_available,
        "notes": request.form.get("notes", "").strip(),
        "created_at": now_iso(),
    }

    if not item["name"]:
        return redirect(url_for("dashboard"))

    items.append(item)
    save_items(items)
    return redirect(url_for("dashboard"))


@app.route("/items/<int:item_id>/update", methods=["POST"])
@login_required
def update_item(item_id):
    items = load_items()
    loans = load_loans()
    item = next((entry for entry in items if entry["id"] == item_id), None)

    if not item:
        return redirect(url_for("dashboard"))

    borrowed_quantity = sum(
        loan["quantity"]
        for loan in loans
        if loan["status"] == "borrowed" and loan["item_id"] == item_id
    )

    quantity_total = max(
        parse_positive_int(request.form.get("quantity_total"), item["quantity_total"]),
        borrowed_quantity,
        1,
    )
    requested_available = parse_positive_int(
        request.form.get("quantity_available"), item["quantity_available"]
    )
    quantity_available = min(requested_available, quantity_total - borrowed_quantity)
    quantity_available = max(quantity_available, 0)

    item.update(
        {
            "name": request.form.get("name", "").strip() or item["name"],
            "category": request.form.get("category", "").strip(),
            "asset_no": request.form.get("asset_no", "").strip(),
            "location": request.form.get("location", "").strip(),
            "quantity_total": quantity_total,
            "quantity_available": quantity_available,
            "notes": request.form.get("notes", "").strip(),
        }
    )

    save_items(items)
    return redirect(url_for("dashboard"))


@app.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    items = load_items()
    loans = load_loans()

    has_active_loan = any(
        loan for loan in loans if loan["item_id"] == item_id and loan["status"] == "borrowed"
    )
    if has_active_loan:
        return redirect(url_for("dashboard"))

    items = [item for item in items if item["id"] != item_id]
    save_items(items)
    return redirect(url_for("dashboard"))


@app.route("/loans", methods=["POST"])
@login_required
def create_loan():
    items = load_items()
    loans = load_loans()

    item_id = parse_positive_int(request.form.get("item_id"))
    quantity = max(parse_positive_int(request.form.get("quantity"), 1), 1)
    item = next((entry for entry in items if entry["id"] == item_id), None)

    if not item or quantity > item["quantity_available"]:
        return redirect(url_for("dashboard"))

    borrower = request.form.get("borrower", "").strip()
    if not borrower:
        return redirect(url_for("dashboard"))

    loan = {
        "id": next_id(loans),
        "item_id": item_id,
        "item_name": item["name"],
        "borrower": borrower,
        "phone": request.form.get("phone", "").strip(),
        "class_name": request.form.get("class_name", "").strip(),
        "team_name": request.form.get("team_name", "").strip(),
        "department": request.form.get("department", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "quantity": quantity,
        "borrowed_at": request.form.get("borrowed_at") or today_str(),
        "due_at": request.form.get("due_at", "").strip(),
        "returned_at": "",
        "status": "borrowed",
        "notes": request.form.get("notes", "").strip(),
        "created_by": session["username"],
    }

    item["quantity_available"] -= quantity
    loans.append(loan)
    save_items(items)
    save_loans(loans)
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
@login_required
def return_loan(loan_id):
    items = load_items()
    loans = load_loans()

    loan = next((entry for entry in loans if entry["id"] == loan_id), None)
    if not loan or loan["status"] != "borrowed":
        return redirect(url_for("dashboard"))

    item = next((entry for entry in items if entry["id"] == loan["item_id"]), None)
    if item:
        item["quantity_available"] = min(
            item["quantity_total"], item["quantity_available"] + loan["quantity"]
        )

    loan["status"] = "returned"
    loan["returned_at"] = request.form.get("returned_at") or today_str()

    save_items(items)
    save_loans(loans)
    return redirect(url_for("dashboard"))


@app.route("/api/items")
@login_required
def api_items():
    return jsonify(load_items())


initialize_storage()


if __name__ == "__main__":
    app.run(debug=True, port=5010)
