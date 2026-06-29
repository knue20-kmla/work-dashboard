import json
import os
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

try:
    from supabase import Client, create_client
except ImportError:  # pragma: no cover
    Client = None
    create_client = None


BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
USERS_FILE = DATA_DIR / "users.json"
ITEMS_FILE = DATA_DIR / "items.json"
LOANS_FILE = DATA_DIR / "loans.json"
CATEGORY_OPTIONS = ["컴퓨터 부품", "카메라", "아두이노", "실험 장비", "기타"]
SAMPLE_ITEMS = [
    {
        "name": "프로젝터",
        "category": "기타",
        "location": "창고 A",
        "quantity_total": 2,
        "quantity_available": 2,
        "notes": "HDMI 케이블 포함",
    },
    {
        "name": "카메라",
        "category": "카메라",
        "location": "미디어실",
        "quantity_total": 3,
        "quantity_available": 3,
        "notes": "배터리 2개 포함",
    },
    {
        "name": "삼각대",
        "category": "기타",
        "location": "창고 B",
        "quantity_total": 4,
        "quantity_available": 4,
        "notes": "",
    },
]


app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "equipment-manager-secret-key-2026")


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def today_str():
    return datetime.now().strftime("%Y-%m-%d")


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


def next_id(records):
    return max((record["id"] for record in records), default=0) + 1


def parse_positive_int(value, fallback=0):
    try:
        parsed = int(value)
        return parsed if parsed >= 0 else fallback
    except (TypeError, ValueError):
        return fallback


def parse_date_or_today(value):
    return value.strip() if value and value.strip() else today_str()


def generate_asset_no(items, year=None):
    target_year = str(year or datetime.now().year)
    used_numbers = []

    for item in items:
        asset_no = str(item.get("asset_no", ""))
        if not asset_no.startswith(f"{target_year}-"):
            continue
        try:
            used_numbers.append(int(asset_no.split("-", 1)[1]))
        except (IndexError, ValueError):
            continue

    next_number = max(used_numbers, default=0) + 1
    return f"{target_year}-{next_number:03d}"


def resolve_category(form):
    selected = form.get("category", "").strip()
    custom = form.get("category_custom", "").strip()
    return custom or selected


def supabase_enabled():
    return all(
        [
            create_client,
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY"),
        ]
    )


def get_supabase_client():
    if not supabase_enabled():
        return None
    return create_client(os.getenv("SUPABASE_URL"), os.getenv("SUPABASE_SERVICE_ROLE_KEY"))


def initialize_storage():
    ensure_data_dir()

    if not USERS_FILE.exists():
        users = {"admin": generate_password_hash("admin1234")}
        write_json(USERS_FILE, users)

    if not ITEMS_FILE.exists():
        items = []
        for index, item in enumerate(SAMPLE_ITEMS, start=1):
            row = {
                "id": index,
                **item,
                "asset_no": generate_asset_no(items),
                "created_at": now_iso(),
            }
            items.append(row)
        write_json(ITEMS_FILE, items)

    if not LOANS_FILE.exists():
        write_json(LOANS_FILE, [])

    seed_supabase()


def seed_supabase():
    client = get_supabase_client()
    if not client:
        return

    try:
        result = client.table("equipment_items").select("id", count="exact").limit(1).execute()
        if getattr(result, "count", 0):
            return

        for item in SAMPLE_ITEMS:
            existing_items = load_items()
            client.table("equipment_items").insert(
                {
                    **item,
                    "asset_no": generate_asset_no(existing_items),
                    "created_at": now_iso(),
                }
            ).execute()
    except Exception:
        # Schema may not exist yet. The app should still start with JSON fallback.
        pass


def load_admin_users():
    return read_json(USERS_FILE, {})


def load_items():
    client = get_supabase_client()
    if not client:
        return read_json(ITEMS_FILE, [])

    try:
        result = client.table("equipment_items").select("*").order("id").execute()
        return result.data or []
    except Exception:
        return read_json(ITEMS_FILE, [])


def save_items(items):
    write_json(ITEMS_FILE, items)


def load_loans():
    client = get_supabase_client()
    if not client:
        return read_json(LOANS_FILE, [])

    try:
        result = client.table("equipment_loans").select("*").order("id").execute()
        return result.data or []
    except Exception:
        return read_json(LOANS_FILE, [])


def save_loans(loans):
    write_json(LOANS_FILE, loans)


def find_member_by_email(email):
    client = get_supabase_client()
    if not client:
        return None

    try:
        result = (
            client.table("profiles")
            .select("*")
            .eq("email", email.lower())
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception:
        return None


def find_member_by_id(member_id):
    client = get_supabase_client()
    if not client:
        return None

    try:
        result = client.table("profiles").select("*").eq("id", member_id).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception:
        return None


def create_member_account(full_name, email, phone, password):
    client = get_supabase_client()
    if not client:
        return False, "회원 기능을 사용하려면 Supabase 설정이 필요합니다."

    if find_member_by_email(email):
        return False, "이미 사용 중인 이메일입니다."

    try:
        result = (
            client.table("profiles")
            .insert(
                {
                    "full_name": full_name.strip(),
                    "email": email.strip().lower(),
                    "phone": phone.strip(),
                    "password_hash": generate_password_hash(password),
                    "created_at": now_iso(),
                }
            )
            .execute()
        )
        return True, result.data[0]
    except Exception:
        return False, "회원 정보를 저장하지 못했습니다. Supabase 테이블 설정을 확인해 주세요."


def get_member_session():
    return session.get("member_user")


def get_member_loans(member_id, active_only=False):
    loans = load_loans()
    filtered = [loan for loan in loans if loan.get("member_id") == member_id]
    if active_only:
        filtered = [loan for loan in filtered if loan["status"] == "borrowed"]
    return sorted(filtered, key=lambda loan: loan["id"], reverse=True)


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def member_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not get_member_session():
            flash("대여와 반납은 일반 사용자 로그인 후 이용할 수 있습니다.", "warning")
            return redirect(url_for("member_login"))
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


def create_item_record():
    items = load_items()

    quantity_total = max(parse_positive_int(request.form.get("quantity_total"), 1), 1)

    item = {
        "name": request.form.get("name", "").strip(),
        "category": resolve_category(request.form),
        "asset_no": generate_asset_no(items),
        "location": request.form.get("location", "").strip(),
        "quantity_total": quantity_total,
        "quantity_available": quantity_total,
        "notes": request.form.get("notes", "").strip(),
    }

    if not item["name"]:
        return False

    client = get_supabase_client()
    if client:
        client.table("equipment_items").insert({**item, "created_at": now_iso()}).execute()
        return True

    item["id"] = next_id(items)
    item["created_at"] = now_iso()
    items.append(item)
    save_items(items)
    return True


def update_item_record(item_id):
    items = load_items()
    loans = load_loans()
    item = next((entry for entry in items if entry["id"] == item_id), None)
    if not item:
        return False

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
    quantity_available = max(min(requested_available, quantity_total - borrowed_quantity), 0)

    payload = {
        "name": request.form.get("name", "").strip() or item["name"],
        "category": resolve_category(request.form),
        "asset_no": item["asset_no"],
        "location": request.form.get("location", "").strip(),
        "quantity_total": quantity_total,
        "quantity_available": quantity_available,
        "notes": request.form.get("notes", "").strip(),
    }

    client = get_supabase_client()
    if client:
        client.table("equipment_items").update(payload).eq("id", item_id).execute()
        return True

    item.update(payload)
    save_items(items)
    return True


def delete_item_record(item_id):
    items = load_items()
    loans = load_loans()

    has_active_loan = any(
        loan for loan in loans if loan["item_id"] == item_id and loan["status"] == "borrowed"
    )
    if has_active_loan:
        return False

    client = get_supabase_client()
    if client:
        client.table("equipment_items").delete().eq("id", item_id).execute()
        return True

    items = [item for item in items if item["id"] != item_id]
    save_items(items)
    return True


def create_loan_record(actor, member=None):
    items = load_items()
    loans = load_loans()

    item_id = parse_positive_int(request.form.get("item_id"))
    quantity = max(parse_positive_int(request.form.get("quantity"), 1), 1)
    item = next((entry for entry in items if entry["id"] == item_id), None)
    if not item or quantity > item["quantity_available"]:
        return False

    if member:
        borrower = member["full_name"]
        phone = member.get("phone", "")
        member_id = member["id"]
    else:
        borrower = request.form.get("borrower", "").strip()
        phone = request.form.get("phone", "").strip()
        member_id = None

    if not borrower:
        return False

    loan = {
        "item_id": item_id,
        "item_name": item["name"],
        "borrower": borrower,
        "phone": phone,
        "class_name": request.form.get("class_name", "").strip(),
        "team_name": request.form.get("team_name", "").strip(),
        "department": request.form.get("department", "").strip(),
        "purpose": request.form.get("purpose", "").strip(),
        "quantity": quantity,
        "borrowed_at": parse_date_or_today(request.form.get("borrowed_at", "")),
        "due_at": request.form.get("due_at", "").strip(),
        "returned_at": "",
        "status": "borrowed",
        "notes": request.form.get("notes", "").strip(),
        "created_by": actor,
        "member_id": member_id,
    }

    client = get_supabase_client()
    if client:
        client.table("equipment_items").update(
            {"quantity_available": item["quantity_available"] - quantity}
        ).eq("id", item_id).execute()
        client.table("equipment_loans").insert(loan).execute()
        return True

    loan["id"] = next_id(loans)
    item["quantity_available"] -= quantity
    loans.append(loan)
    save_items(items)
    save_loans(loans)
    return True


def complete_return(loan_id=None, member_id=None):
    items = load_items()
    loans = load_loans()

    target_loan_id = loan_id if loan_id is not None else parse_positive_int(request.form.get("loan_id"))
    loan = next((entry for entry in loans if entry["id"] == target_loan_id), None)
    if not loan or loan["status"] != "borrowed":
        return False

    if member_id is not None and loan.get("member_id") != member_id:
        return False

    item = next((entry for entry in items if entry["id"] == loan["item_id"]), None)
    if not item:
        return False

    returned_at = parse_date_or_today(request.form.get("returned_at", ""))

    client = get_supabase_client()
    if client:
        client.table("equipment_items").update(
            {"quantity_available": min(item["quantity_total"], item["quantity_available"] + loan["quantity"])}
        ).eq("id", item["id"]).execute()
        client.table("equipment_loans").update(
            {"status": "returned", "returned_at": returned_at}
        ).eq("id", target_loan_id).execute()
        return True

    item["quantity_available"] = min(
        item["quantity_total"], item["quantity_available"] + loan["quantity"]
    )
    loan["status"] = "returned"
    loan["returned_at"] = returned_at
    save_items(items)
    save_loans(loans)
    return True


@app.context_processor
def inject_globals():
    return {
        "member_user": get_member_session(),
        "supabase_ready": supabase_enabled(),
        "category_options": CATEGORY_OPTIONS,
    }


@app.route("/")
def index():
    data = build_dashboard_data()
    member = get_member_session()
    member_loans = get_member_loans(member["id"], active_only=True) if member else []
    return render_template("public.html", member_loans=member_loans, **data)


@app.route("/admin")
def admin():
    if "username" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        users = load_admin_users()

        if username in users and check_password_hash(users[username], password):
            session["username"] = username
            return redirect(url_for("dashboard"))
        error = "아이디 또는 비밀번호가 올바르지 않습니다."

    return render_template("login.html", error=error)


@app.route("/member/login", methods=["GET", "POST"])
def member_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        member = find_member_by_email(email)
        if not member or not check_password_hash(member["password_hash"], password):
            flash("이메일 또는 비밀번호가 올바르지 않습니다.", "error")
            return render_template("member_auth.html", mode="login")

        session["member_user"] = {
            "id": member["id"],
            "email": member["email"],
            "full_name": member["full_name"],
            "phone": member.get("phone", ""),
        }
        flash("일반 사용자 로그인이 완료되었습니다.", "success")
        return redirect(url_for("index"))

    return render_template("member_auth.html", mode="login")


@app.route("/member/signup", methods=["GET", "POST"])
def member_signup():
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        phone = request.form.get("phone", "").strip()
        password = request.form.get("password", "")
        password_confirm = request.form.get("password_confirm", "")

        if not full_name or not email or not password:
            flash("이름, 이메일, 비밀번호는 필수입니다.", "error")
            return render_template("member_auth.html", mode="signup")

        if password != password_confirm:
            flash("비밀번호 확인이 일치하지 않습니다.", "error")
            return render_template("member_auth.html", mode="signup")

        ok, payload = create_member_account(full_name, email, phone, password)
        if not ok:
            flash(payload, "error")
            return render_template("member_auth.html", mode="signup")

        session["member_user"] = {
            "id": payload["id"],
            "email": payload["email"],
            "full_name": payload["full_name"],
            "phone": payload.get("phone", ""),
        }
        flash("회원가입이 완료되었습니다.", "success")
        return redirect(url_for("index"))

    return render_template("member_auth.html", mode="signup")


@app.route("/member/logout")
def member_logout():
    session.pop("member_user", None)
    flash("일반 사용자 로그아웃이 완료되었습니다.", "success")
    return redirect(url_for("index"))


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
    create_item_record()
    return redirect(url_for("dashboard"))


@app.route("/items/<int:item_id>/update", methods=["POST"])
@login_required
def update_item(item_id):
    update_item_record(item_id)
    return redirect(url_for("dashboard"))


@app.route("/items/<int:item_id>/delete", methods=["POST"])
@login_required
def delete_item(item_id):
    delete_item_record(item_id)
    return redirect(url_for("dashboard"))


@app.route("/loans", methods=["POST"])
@login_required
def create_loan():
    create_loan_record(session["username"])
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
@login_required
def return_loan(loan_id):
    complete_return(loan_id=loan_id)
    return redirect(url_for("dashboard"))


@app.route("/borrow", methods=["POST"])
@member_required
def public_borrow():
    member = find_member_by_id(get_member_session()["id"])
    if not member:
        session.pop("member_user", None)
        flash("회원 정보를 다시 확인해 주세요. 다시 로그인해 주세요.", "error")
        return redirect(url_for("member_login"))

    create_loan_record("member", member=member)
    flash("대여 신청이 등록되었습니다.", "success")
    return redirect(url_for("index"))


@app.route("/return", methods=["POST"])
@member_required
def public_return():
    complete_return(member_id=get_member_session()["id"])
    flash("반납 처리가 완료되었습니다.", "success")
    return redirect(url_for("index"))


@app.route("/api/items")
@login_required
def api_items():
    return jsonify(load_items())


initialize_storage()


if __name__ == "__main__":
    app.run(debug=True, port=5010)
