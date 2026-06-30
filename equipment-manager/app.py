import base64
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
CATEGORY_FILE = DATA_DIR / "categories.json"
CATEGORY_OPTIONS = ["而댄벂??遺??, "移대찓??, "?꾨몢?대끂", "?ㅽ뿕 ?λ퉬", "湲고?"]
MAX_IMAGE_SIZE = 2 * 1024 * 1024
SAMPLE_ITEMS = [
    {
        "name": "?꾨줈?앺꽣",
        "category": "湲고?",
        "location": "李쎄퀬 A",
        "quantity_total": 2,
        "quantity_available": 2,
        "notes": "HDMI 耳?대툝 ?ы븿",
    },
    {
        "name": "移대찓??,
        "category": "移대찓??,
        "location": "誘몃뵒?댁떎",
        "quantity_total": 3,
        "quantity_available": 3,
        "notes": "諛고꽣由?2媛??ы븿",
    },
    {
        "name": "?쇨컖?",
        "category": "湲고?",
        "location": "李쎄퀬 B",
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


LOAN_STATUS_LABELS = {
    "requested": "????좎껌",
    "borrowed": "???以?,
    "return_requested": "諛섎궔 ?좎껌",
    "returned": "諛섎궔 ?꾨즺",
}


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


def loan_status_label(status):
    return LOAN_STATUS_LABELS.get(status, status)


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


def resolve_department(form):
    grade = form.get("grade", "").strip()
    classroom = form.get("classroom", "").strip()
    if grade and classroom:
        return f"{grade}?숇뀈 {classroom}諛?
    return form.get("department", "").strip()


def normalize_categories(categories):
    seen = set()
    normalized = []
    for category in categories:
        value = str(category).strip()
        if not value or value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def read_image_data(file_storage, current_image=None):
    if not file_storage or not file_storage.filename:
        return current_image

    raw = file_storage.read()
    if not raw:
        return current_image

    if len(raw) > MAX_IMAGE_SIZE:
        flash("?ъ쭊 ?뚯씪? 2MB ?댄븯濡??깅줉??二쇱꽭??", "warning")
        return current_image

    mime_type = file_storage.mimetype or "image/jpeg"
    encoded = base64.b64encode(raw).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


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
                "image_data": "",
                "created_at": now_iso(),
            }
            items.append(row)
        write_json(ITEMS_FILE, items)

    if not LOANS_FILE.exists():
        write_json(LOANS_FILE, [])

    if not CATEGORY_FILE.exists():
        write_json(CATEGORY_FILE, CATEGORY_OPTIONS)

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
                    "image_data": "",
                    "created_at": now_iso(),
                }
            ).execute()
    except Exception:
        # Schema may not exist yet. The app should still start with JSON fallback.
        pass


def normalize_admin_users(raw_users):
    if isinstance(raw_users, dict):
        normalized = []
        for username, password_hash in raw_users.items():
            normalized.append(
                {
                    "username": username,
                    "password_hash": password_hash,
                    "role": "superadmin" if username == "admin" else "subadmin",
                    "created_at": now_iso(),
                }
            )
        return normalized

    if isinstance(raw_users, list):
        normalized = []
        for entry in raw_users:
            username = str(entry.get("username", "")).strip()
            password_hash = str(entry.get("password_hash", "")).strip()
            if not username or not password_hash:
                continue
            normalized.append(
                {
                    "username": username,
                    "password_hash": password_hash,
                    "role": entry.get("role", "subadmin"),
                    "created_at": entry.get("created_at", now_iso()),
                }
            )
        return normalized

    return []


def load_admin_users():
    client = get_supabase_client()
    local_users = normalize_admin_users(read_json(USERS_FILE, {"admin": generate_password_hash("admin1234")}))

    if client:
        try:
            result = client.table("admin_users").select("*").order("username").execute()
            remote_users = normalize_admin_users(result.data or [])
            if remote_users:
                return remote_users
        except Exception:
            return local_users

    return local_users


def save_admin_users(users):
    write_json(USERS_FILE, normalize_admin_users(users))


def find_admin_user(username):
    return next((user for user in load_admin_users() if user["username"] == username), None)


def sync_admin_users_to_local(users):
    save_admin_users(users)


def update_admin_password(username, new_password):
    users = load_admin_users()
    target = next((user for user in users if user["username"] == username), None)
    if not target:
        return False

    new_hash = generate_password_hash(new_password)
    target["password_hash"] = new_hash

    client = get_supabase_client()
    if client:
        try:
            client.table("admin_users").update({"password_hash": new_hash}).eq("username", username).execute()
            sync_admin_users_to_local(users)
            return True
        except Exception:
            sync_admin_users_to_local(users)
            flash("admin_users ?뚯씠釉붿씠 ?놁뼱 濡쒖뺄 愿由ъ옄 紐⑸줉?먮쭔 諛섏쁺?덉뒿?덈떎.", "warning")
            return True

    sync_admin_users_to_local(users)
    return True


def create_admin_user(username, password, role="subadmin"):
    normalized_username = username.strip()
    if not normalized_username or not password:
        return False

    users = load_admin_users()
    if any(user["username"] == normalized_username for user in users):
        return False

    new_user = {
        "username": normalized_username,
        "password_hash": generate_password_hash(password),
        "role": role,
        "created_at": now_iso(),
    }
    users.append(new_user)

    client = get_supabase_client()
    if client:
        try:
            client.table("admin_users").insert(new_user).execute()
            sync_admin_users_to_local(users)
            return True
        except Exception:
            sync_admin_users_to_local(users)
            flash("admin_users ?뚯씠釉붿씠 ?놁뼱 濡쒖뺄 愿由ъ옄 紐⑸줉?먮쭔 諛섏쁺?덉뒿?덈떎.", "warning")
            return True

    sync_admin_users_to_local(users)
    return True


def delete_admin_user(username):
    target_username = username.strip()
    users = load_admin_users()
    target = next((user for user in users if user["username"] == target_username), None)
    if not target or target.get("role") == "superadmin":
        return False

    remaining = [user for user in users if user["username"] != target_username]
    client = get_supabase_client()
    if client:
        try:
            client.table("admin_users").delete().eq("username", target_username).execute()
            sync_admin_users_to_local(remaining)
            return True
        except Exception:
            sync_admin_users_to_local(remaining)
            flash("admin_users ?뚯씠釉붿씠 ?놁뼱 濡쒖뺄 愿由ъ옄 紐⑸줉?먯꽌留???젣?덉뒿?덈떎.", "warning")
            return True

    sync_admin_users_to_local(remaining)
    return True


def reset_admin_user_password(username, new_password):
    target_username = username.strip()
    users = load_admin_users()
    target = next((user for user in users if user["username"] == target_username), None)
    if not target or target.get("role") == "superadmin":
        return False

    target["password_hash"] = generate_password_hash(new_password)
    client = get_supabase_client()
    if client:
        try:
            client.table("admin_users").update(
                {"password_hash": target["password_hash"]}
            ).eq("username", target_username).execute()
            sync_admin_users_to_local(users)
            return True
        except Exception:
            sync_admin_users_to_local(users)
            flash("admin_users ?뚯씠釉붿씠 ?놁뼱 濡쒖뺄 愿由ъ옄 紐⑸줉?먮쭔 諛섏쁺?덉뒿?덈떎.", "warning")
            return True

    sync_admin_users_to_local(users)
    return True


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


def load_categories():
    client = get_supabase_client()
    base_categories = read_json(CATEGORY_FILE, CATEGORY_OPTIONS)

    if client:
        try:
            result = client.table("equipment_categories").select("name").order("name").execute()
            remote_categories = [entry["name"] for entry in (result.data or [])]
            return normalize_categories(base_categories + remote_categories)
        except Exception:
            return normalize_categories(base_categories)

    return normalize_categories(base_categories)


def save_categories(categories):
    write_json(CATEGORY_FILE, normalize_categories(categories))


def create_category_record(name):
    category_name = name.strip()
    if not category_name:
        return False

    client = get_supabase_client()
    existing = load_categories()
    if category_name in existing:
        return False

    if client:
        try:
            client.table("equipment_categories").insert(
                {"name": category_name, "created_at": now_iso()}
            ).execute()
            save_categories(existing + [category_name])
            return True
        except Exception:
            save_categories(existing + [category_name])
            flash("遺꾨쪟 ?뚯씠釉붿씠 ?꾩쭅 ?놁뼱 ?꾩떆 紐⑸줉?쇰줈留???ν뻽?듬땲?? ?꾨옒 SQL ?덈궡瑜??곸슜??二쇱꽭??", "warning")
            return True

    save_categories(existing + [category_name])
    return True


def delete_category_record(name):
    category_name = name.strip()
    if not category_name:
        return False

    items = load_items()
    if any(item.get("category") == category_name for item in items):
        flash("?ъ슜 以묒씤 遺꾨쪟????젣?????놁뒿?덈떎.", "warning")
        return False

    client = get_supabase_client()
    categories = [entry for entry in load_categories() if entry != category_name]

    if client:
        try:
            client.table("equipment_categories").delete().eq("name", category_name).execute()
            save_categories(categories)
            return True
        except Exception:
            save_categories(categories)
            flash("遺꾨쪟 ?뚯씠釉붿씠 ?꾩쭅 ?놁뼱 ?꾩떆 紐⑸줉?먯꽌留???젣?덉뒿?덈떎. ?꾨옒 SQL ?덈궡瑜??곸슜??二쇱꽭??", "warning")
            return True

    save_categories(categories)
    return True


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


def load_members():
    client = get_supabase_client()
    if not client:
        return []

    try:
        result = client.table("profiles").select("*").order("created_at", desc=True).execute()
        return result.data or []
    except Exception:
        return []


def create_member_account(full_name, email, phone, password):
    client = get_supabase_client()
    if not client:
        return False, "?뚯썝 湲곕뒫???ъ슜?섎젮硫?Supabase ?ㅼ젙???꾩슂?⑸땲??"

    if find_member_by_email(email):
        return False, "?대? ?ъ슜 以묒씤 ?대찓?쇱엯?덈떎."

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
        return False, "?뚯썝 ?뺣낫瑜???ν븯吏 紐삵뻽?듬땲?? Supabase ?뚯씠釉??ㅼ젙???뺤씤??二쇱꽭??"


def update_member_password(member_id, new_password):
    client = get_supabase_client()
    if not client:
        return False

    try:
        client.table("profiles").update(
            {"password_hash": generate_password_hash(new_password)}
        ).eq("id", member_id).execute()
        return True
    except Exception:
        return False


def delete_member_account(member_id):
    client = get_supabase_client()
    if not client:
        return False

    try:
        client.table("profiles").delete().eq("id", member_id).execute()
        return True
    except Exception:
        return False


def get_member_session():
    return session.get("member_user")


def get_member_loans(member_id, active_only=False):
    loans = load_loans()
    filtered = [loan for loan in loans if loan.get("member_id") == member_id]
    if active_only:
        filtered = [loan for loan in filtered if loan["status"] in {"requested", "borrowed", "return_requested"}]
    return sorted(filtered, key=lambda loan: loan["id"], reverse=True)


def login_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        return view_func(*args, **kwargs)

    return wrapped


def superadmin_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if "username" not in session:
            return redirect(url_for("login"))
        if session.get("admin_role") != "superadmin":
            flash("硫붿씤 愿由ъ옄留??묎렐?????덉뒿?덈떎.", "warning")
            return redirect(url_for("dashboard"))
        return view_func(*args, **kwargs)

    return wrapped


def member_required(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if not get_member_session():
            flash("??ъ? 諛섎궔? ?쇰컲 ?ъ슜??濡쒓렇?????댁슜?????덉뒿?덈떎.", "warning")
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

    pending_borrow_requests = [loan for loan in loans if loan["status"] == "requested"]
    pending_return_requests = [loan for loan in loans if loan["status"] == "return_requested"]
    active_loans = [loan for loan in loans if loan["status"] in {"borrowed", "return_requested"}]
    history = sorted(loans, key=lambda loan: loan["id"], reverse=True)
    categories = normalize_categories(load_categories() + [item["category"] for item in items if item["category"]])

    stats = {
        "total_items": len(items),
        "total_stock": sum(item["quantity_total"] for item in items),
        "available_stock": sum(item["quantity_available"] for item in items),
        "borrowed_count": sum(loan["quantity"] for loan in active_loans),
    }

    return {
        "items": filtered_items,
        "all_items": items,
        "pending_borrow_requests": sorted(pending_borrow_requests, key=lambda loan: loan["id"], reverse=True),
        "pending_return_requests": sorted(pending_return_requests, key=lambda loan: loan["id"], reverse=True),
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
        "image_data": read_image_data(request.files.get("image_file"), current_image=""),
    }

    if not item["name"]:
        return False

    client = get_supabase_client()
    if client:
        try:
            client.table("equipment_items").insert({**item, "created_at": now_iso()}).execute()
            return True
        except Exception:
            fallback_item = {key: value for key, value in item.items() if key != "image_data"}
            client.table("equipment_items").insert({**fallback_item, "created_at": now_iso()}).execute()
            flash("?ъ쭊 ??μ슜 而щ읆???꾩쭅 ?놁뼱 ?ъ쭊 ?놁씠 ?깅줉?덉뒿?덈떎. ?꾨옒 SQL ?덈궡瑜??곸슜??二쇱꽭??", "warning")
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
        if loan["status"] in {"borrowed", "return_requested"} and loan["item_id"] == item_id
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
        "image_data": read_image_data(request.files.get("image_file"), current_image=item.get("image_data", "")),
    }

    if request.form.get("remove_image") == "1":
        payload["image_data"] = ""

    client = get_supabase_client()
    if client:
        try:
            client.table("equipment_items").update(payload).eq("id", item_id).execute()
            return True
        except Exception:
            fallback_payload = {key: value for key, value in payload.items() if key != "image_data"}
            client.table("equipment_items").update(fallback_payload).eq("id", item_id).execute()
            flash("?ъ쭊 ??μ슜 而щ읆???꾩쭅 ?놁뼱 ?ъ쭊 蹂寃??놁씠 ??ν뻽?듬땲?? ?꾨옒 SQL ?덈궡瑜??곸슜??二쇱꽭??", "warning")
            return True

    item.update(payload)
    save_items(items)
    return True


def delete_item_record(item_id):
    items = load_items()
    loans = load_loans()

    has_active_loan = any(
        loan
        for loan in loans
        if loan["item_id"] == item_id and loan["status"] in {"requested", "borrowed", "return_requested"}
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
    if not item:
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
        "department": resolve_department(request.form),
        "purpose": request.form.get("purpose", "").strip(),
        "quantity": quantity,
        "borrowed_at": parse_date_or_today(request.form.get("borrowed_at", "")),
        "due_at": request.form.get("due_at", "").strip(),
        "returned_at": "",
        "status": "requested" if member else "borrowed",
        "notes": request.form.get("notes", "").strip(),
        "created_by": actor,
        "member_id": member_id,
    }

    client = get_supabase_client()
    if client:
        try:
            if not member:
                if quantity > item["quantity_available"]:
                    return False
                client.table("equipment_items").update(
                    {"quantity_available": item["quantity_available"] - quantity}
                ).eq("id", item_id).execute()
            client.table("equipment_loans").insert(loan).execute()
            return True
        except Exception:
            flash("????깅줉 以??ㅻ쪟媛 諛쒖깮?덉뒿?덈떎. ?낅젰媛믪씠??Supabase ?뚯씠釉?援ъ“瑜??뺤씤??二쇱꽭??", "error")
            return False

    loan["id"] = next_id(loans)
    if not member:
        if quantity > item["quantity_available"]:
            return False
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

    returned_at = parse_date_or_today(request.form.get("returned_at", ""))

    client = get_supabase_client()
    if client:
        try:
            client.table("equipment_loans").update(
                {"status": "return_requested", "returned_at": returned_at}
            ).eq("id", target_loan_id).execute()
            return True
        except Exception:
            flash("諛섎궔 泥섎━ 以??ㅻ쪟媛 諛쒖깮?덉뒿?덈떎. Supabase ?뚯씠釉?援ъ“瑜??뺤씤??二쇱꽭??", "error")
            return False

    loan["status"] = "return_requested"
    loan["returned_at"] = returned_at
    save_loans(loans)
    return True


def approve_loan_request(loan_id):
    items = load_items()
    loans = load_loans()

    loan = next((entry for entry in loans if entry["id"] == loan_id), None)
    if not loan or loan["status"] != "requested":
        return False

    item = next((entry for entry in items if entry["id"] == loan["item_id"]), None)
    if not item or loan["quantity"] > item["quantity_available"]:
        return False

    client = get_supabase_client()
    if client:
        try:
            client.table("equipment_items").update(
                {"quantity_available": item["quantity_available"] - loan["quantity"]}
            ).eq("id", item["id"]).execute()
            client.table("equipment_loans").update({"status": "borrowed"}).eq("id", loan_id).execute()
            return True
        except Exception:
            flash("????뱀씤 泥섎━ 以??ㅻ쪟媛 諛쒖깮?덉뒿?덈떎.", "error")
            return False

    item["quantity_available"] -= loan["quantity"]
    loan["status"] = "borrowed"
    save_items(items)
    save_loans(loans)
    return True


def approve_return_request(loan_id):
    items = load_items()
    loans = load_loans()

    loan = next((entry for entry in loans if entry["id"] == loan_id), None)
    if not loan or loan["status"] != "return_requested":
        return False

    item = next((entry for entry in items if entry["id"] == loan["item_id"]), None)
    if not item:
        return False

    client = get_supabase_client()
    if client:
        try:
            client.table("equipment_items").update(
                {"quantity_available": min(item["quantity_total"], item["quantity_available"] + loan["quantity"])}
            ).eq("id", item["id"]).execute()
            client.table("equipment_loans").update({"status": "returned"}).eq("id", loan_id).execute()
            return True
        except Exception:
            flash("諛섎궔 ?뱀씤 泥섎━ 以??ㅻ쪟媛 諛쒖깮?덉뒿?덈떎.", "error")
            return False

    item["quantity_available"] = min(
        item["quantity_total"], item["quantity_available"] + loan["quantity"]
    )
    loan["status"] = "returned"
    save_items(items)
    save_loans(loans)
    return True


@app.context_processor
def inject_globals():
    return {
        "member_user": get_member_session(),
        "supabase_ready": supabase_enabled(),
        "category_options": load_categories(),
        "loan_status_label": loan_status_label,
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
        admin_user = find_admin_user(username)

        if admin_user and check_password_hash(admin_user["password_hash"], password):
            session["username"] = admin_user["username"]
            session["admin_role"] = admin_user.get("role", "subadmin")
            return redirect(url_for("dashboard"))
        error = "?꾩씠???먮뒗 鍮꾨?踰덊샇媛 ?щ컮瑜댁? ?딆뒿?덈떎."

    return render_template("login.html", error=error)


@app.route("/member/login", methods=["GET", "POST"])
def member_login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        member = find_member_by_email(email)
        if not member or not check_password_hash(member["password_hash"], password):
            flash("?대찓???먮뒗 鍮꾨?踰덊샇媛 ?щ컮瑜댁? ?딆뒿?덈떎.", "error")
            return render_template("member_auth.html", mode="login")

        session["member_user"] = {
            "id": member["id"],
            "email": member["email"],
            "full_name": member["full_name"],
            "phone": member.get("phone", ""),
        }
        flash("?쇰컲 ?ъ슜??濡쒓렇?몄씠 ?꾨즺?섏뿀?듬땲??", "success")
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
            flash("?대쫫, ?대찓?? 鍮꾨?踰덊샇???꾩닔?낅땲??", "error")
            return render_template("member_auth.html", mode="signup")

        if password != password_confirm:
            flash("鍮꾨?踰덊샇 ?뺤씤???쇱튂?섏? ?딆뒿?덈떎.", "error")
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
        flash("?뚯썝媛?낆씠 ?꾨즺?섏뿀?듬땲??", "success")
        return redirect(url_for("index"))

    return render_template("member_auth.html", mode="signup")


@app.route("/member/logout")
def member_logout():
    session.pop("member_user", None)
    flash("?쇰컲 ?ъ슜??濡쒓렇?꾩썐???꾨즺?섏뿀?듬땲??", "success")
    return redirect(url_for("index"))


@app.route("/logout")
def logout():
    session.pop("username", None)
    session.pop("admin_role", None)
    return redirect(url_for("login"))


@app.route("/dashboard")
@login_required
def dashboard():
    return render_template(
        "dashboard.html",
        username=session["username"],
        admin_role=session.get("admin_role", "subadmin"),
        admin_users=load_admin_users(),
        members=load_members(),
        **build_dashboard_data(),
    )


@app.route("/items", methods=["POST"])
@login_required
def create_item():
    create_item_record()
    return redirect(url_for("dashboard"))


@app.route("/admin/password", methods=["POST"])
@superadmin_required
def change_admin_password():
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")

    current_admin = find_admin_user(session["username"])
    if not current_admin or not check_password_hash(current_admin["password_hash"], current_password):
        flash("?꾩옱 鍮꾨?踰덊샇媛 ?щ컮瑜댁? ?딆뒿?덈떎.", "error")
        return redirect(url_for("dashboard"))

    if not new_password or new_password != new_password_confirm:
        flash("??鍮꾨?踰덊샇 ?뺤씤???쇱튂?섏? ?딆뒿?덈떎.", "error")
        return redirect(url_for("dashboard"))

    if update_admin_password(session["username"], new_password):
        flash("硫붿씤 愿由ъ옄 鍮꾨?踰덊샇瑜?蹂寃쏀뻽?듬땲??", "success")
    else:
        flash("鍮꾨?踰덊샇 蹂寃쎌뿉 ?ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/admin/subadmins", methods=["POST"])
@superadmin_required
def create_subadmin():
    username = request.form.get("subadmin_username", "").strip()
    password = request.form.get("subadmin_password", "")
    password_confirm = request.form.get("subadmin_password_confirm", "")

    if not username or not password:
        flash("?꾩씠?붿? 鍮꾨?踰덊샇瑜??낅젰??二쇱꽭??", "error")
        return redirect(url_for("dashboard"))

    if password != password_confirm:
        flash("?쒕툕愿由ъ옄 鍮꾨?踰덊샇 ?뺤씤???쇱튂?섏? ?딆뒿?덈떎.", "error")
        return redirect(url_for("dashboard"))

    if create_admin_user(username, password, role="subadmin"):
        flash("?쒕툕愿由ъ옄瑜?異붽??덉뒿?덈떎.", "success")
    else:
        flash("?대? 議댁옱?섎뒗 愿由ъ옄 ?꾩씠?붿씠嫄곕굹 ?앹꽦???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/admin/subadmins/reset-password", methods=["POST"])
@superadmin_required
def reset_subadmin_password():
    username = request.form.get("subadmin_username", "").strip()
    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")

    if not username or not new_password or new_password != new_password_confirm:
        flash("?쒕툕愿由ъ옄 鍮꾨?踰덊샇 ?뺤씤???쇱튂?섏? ?딆뒿?덈떎.", "error")
        return redirect(url_for("dashboard"))

    if reset_admin_user_password(username, new_password):
        flash("?쒕툕愿由ъ옄 鍮꾨?踰덊샇瑜??ъ꽕?뺥뻽?듬땲??", "success")
    else:
        flash("?쒕툕愿由ъ옄 鍮꾨?踰덊샇 ?ъ꽕?뺤뿉 ?ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/admin/subadmins/delete", methods=["POST"])
@superadmin_required
def delete_subadmin():
    username = request.form.get("subadmin_username", "").strip()
    if delete_admin_user(username):
        flash("?쒕툕愿由ъ옄瑜???젣?덉뒿?덈떎.", "success")
    else:
        flash("?쒕툕愿由ъ옄 ??젣???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/admin/members/reset-password", methods=["POST"])
@superadmin_required
def reset_member_password():
    member_id = parse_positive_int(request.form.get("member_id"))
    new_password = request.form.get("new_password", "")
    new_password_confirm = request.form.get("new_password_confirm", "")

    if not member_id or not new_password or new_password != new_password_confirm:
        flash("?뚯썝 鍮꾨?踰덊샇 ?뺤씤???쇱튂?섏? ?딆뒿?덈떎.", "error")
        return redirect(url_for("dashboard"))

    if update_member_password(member_id, new_password):
        flash("?뚯썝 鍮꾨?踰덊샇瑜??ъ꽕?뺥뻽?듬땲??", "success")
    else:
        flash("?뚯썝 鍮꾨?踰덊샇 ?ъ꽕?뺤뿉 ?ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/admin/members/delete", methods=["POST"])
@superadmin_required
def delete_member():
    member_id = parse_positive_int(request.form.get("member_id"))
    if not member_id:
        flash("??젣???뚯썝???뺤씤??二쇱꽭??", "error")
        return redirect(url_for("dashboard"))

    if delete_member_account(member_id):
        flash("?뚯썝????젣?덉뒿?덈떎.", "success")
    else:
        flash("?뚯썝 ??젣???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/categories", methods=["POST"])
@login_required
def create_category():
    create_category_record(request.form.get("category_name", ""))
    return redirect(url_for("dashboard"))


@app.route("/categories/delete", methods=["POST"])
@login_required
def delete_category():
    delete_category_record(request.form.get("category_name", ""))
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
    if not create_loan_record(session["username"]):
        flash("????깅줉???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/return", methods=["POST"])
@login_required
def return_loan(loan_id):
    if not complete_return(loan_id=loan_id):
        flash("諛섎궔 泥섎━???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/approve", methods=["POST"])
@login_required
def approve_loan(loan_id):
    if approve_loan_request(loan_id):
        flash("????좎껌???뱀씤?덉뒿?덈떎.", "success")
    else:
        flash("????좎껌 ?뱀씤???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/loans/<int:loan_id>/approve-return", methods=["POST"])
@login_required
def approve_return(loan_id):
    if approve_return_request(loan_id):
        flash("諛섎궔 ?좎껌???뱀씤?덉뒿?덈떎.", "success")
    else:
        flash("諛섎궔 ?좎껌 ?뱀씤???ㅽ뙣?덉뒿?덈떎.", "error")
    return redirect(url_for("dashboard"))


@app.route("/loans/approve-batch", methods=["POST"])
@login_required
def approve_loans_batch():
    loan_ids = [parse_positive_int(value) for value in request.form.getlist("loan_ids")]
    loan_ids = [loan_id for loan_id in loan_ids if loan_id]

    if not loan_ids:
        flash("승인할 대여 신청을 선택해 주세요.", "warning")
        return redirect(url_for("dashboard"))

    success_count = 0
    for loan_id in loan_ids:
        if approve_loan_request(loan_id):
            success_count += 1

    if success_count:
        flash(f"{success_count}건의 대여 신청을 승인했습니다.", "success")
    else:
        flash("대여 신청 승인에 실패했습니다.", "error")
    return redirect(url_for("dashboard"))


@app.route("/loans/approve-return-batch", methods=["POST"])
@login_required
def approve_returns_batch():
    loan_ids = [parse_positive_int(value) for value in request.form.getlist("loan_ids")]
    loan_ids = [loan_id for loan_id in loan_ids if loan_id]

    if not loan_ids:
        flash("승인할 반납 신청을 선택해 주세요.", "warning")
        return redirect(url_for("dashboard"))

    success_count = 0
    for loan_id in loan_ids:
        if approve_return_request(loan_id):
            success_count += 1

    if success_count:
        flash(f"{success_count}건의 반납 신청을 승인했습니다.", "success")
    else:
        flash("반납 신청 승인에 실패했습니다.", "error")
    return redirect(url_for("dashboard"))


@app.route("/borrow", methods=["POST"])
@member_required
def public_borrow():
    member = find_member_by_id(get_member_session()["id"])
    if not member:
        session.pop("member_user", None)
        flash("?뚯썝 ?뺣낫瑜??ㅼ떆 ?뺤씤??二쇱꽭?? ?ㅼ떆 濡쒓렇?명빐 二쇱꽭??", "error")
        return redirect(url_for("member_login"))

    if create_loan_record("member", member=member):
        flash("????좎껌???깅줉?섏뿀?듬땲??", "success")
    return redirect(url_for("index"))


@app.route("/return", methods=["POST"])
@member_required
def public_return():
    member_id = get_member_session()["id"]
    loan_ids = [parse_positive_int(value) for value in request.form.getlist("loan_ids")]
    loan_ids = [loan_id for loan_id in loan_ids if loan_id]

    if not loan_ids:
        single_loan_id = parse_positive_int(request.form.get("loan_id"))
        if single_loan_id:
            loan_ids = [single_loan_id]

    if not loan_ids:
        flash("반납 신청할 항목을 선택해 주세요.", "warning")
        return redirect(url_for("index"))

    success_count = 0
    for loan_id in loan_ids:
        if complete_return(loan_id=loan_id, member_id=member_id):
            success_count += 1

    if success_count:
        flash(f"{success_count}건의 반납 신청이 접수되었습니다.", "success")
    else:
        flash("반납 신청 처리에 실패했습니다.", "error")
    return redirect(url_for("index"))


@app.route("/api/items")
@login_required
def api_items():
    return jsonify(load_items())


initialize_storage()


if __name__ == "__main__":
    app.run(debug=True, port=5010)
