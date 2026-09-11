import hashlib
import io
import os
import secrets
import sqlite3
from pathlib import Path
from urllib.parse import urlencode

import altair as alt
import pandas as pd
import requests
import streamlit as st

try:
    from supabase import create_client
except ImportError:
    create_client = None

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "story_submissions.db"
STATUS_ORDER = ["submitted", "accepted", "rejected", "withdrawn"]


def get_secret_value(key, default=""):
    """Read Streamlit Cloud secrets first, then local environment variables."""
    try:
        value = st.secrets.get(key, default)
    except Exception:
        value = default

    if value in (None, ""):
        value = os.getenv(key, default)

    return str(value)


GOOGLE_CLIENT_ID = get_secret_value("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = get_secret_value("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI = get_secret_value("GOOGLE_REDIRECT_URI", "http://localhost:8501")
SUPABASE_URL = get_secret_value("SUPABASE_URL", "")
SUPABASE_KEY = get_secret_value("SUPABASE_SERVICE_ROLE_KEY", "") or get_secret_value("SUPABASE_KEY", "")
SUPABASE_CLIENT = create_client(SUPABASE_URL, SUPABASE_KEY) if create_client and SUPABASE_URL and SUPABASE_KEY else None


def hash_password(password):
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def get_user_by_email(email):
    if SUPABASE_CLIENT:
        response = SUPABASE_CLIENT.table("users").select("id,name,email,password_hash").eq("email", (email or "").strip().lower()).limit(1).execute()
        if not response.data:
            return None
        return response.data[0]

    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT id, name, email, password_hash FROM users WHERE LOWER(email) = LOWER(?)",
        (email or "",),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "name": row[1], "email": row[2], "password_hash": row[3]}


def create_user(name, email, password):
    clean_email = (email or "").strip().lower()
    clean_name = (name or "").strip()
    if not clean_name or not clean_email or not password:
        return False, "Name, email and password are required."
    if "@" not in clean_email:
        return False, "Please enter a valid email address."
    if get_user_by_email(clean_email):
        return False, "An account with this email already exists."

    if SUPABASE_CLIENT:
        SUPABASE_CLIENT.table("users").insert(
            {"name": clean_name, "email": clean_email, "password_hash": hash_password(password)}
        ).execute()
        return True, "User created successfully."

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (clean_name, clean_email, hash_password(password)),
    )
    conn.commit()
    conn.close()
    return True, "User created successfully."


def authenticate_user(email, password):
    user = get_user_by_email(email)
    if not user:
        return None
    if user["password_hash"] != hash_password(password):
        return None
    return user


def create_or_get_google_user(email, name):
    clean_email = (email or "").strip().lower()
    clean_name = (name or "").strip() or "Google User"
    if not clean_email:
        return None
    existing = get_user_by_email(clean_email)
    if existing:
        return existing

    if SUPABASE_CLIENT:
        SUPABASE_CLIENT.table("users").insert(
            {"name": clean_name, "email": clean_email, "password_hash": hash_password(secrets.token_urlsafe(16))}
        ).execute()
        return get_user_by_email(clean_email)

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT INTO users (name, email, password_hash) VALUES (?, ?, ?)",
        (clean_name, clean_email, hash_password(secrets.token_urlsafe(16))),
    )
    conn.commit()
    conn.close()
    return get_user_by_email(clean_email)


def get_google_auth_url():
    if not GOOGLE_CLIENT_ID or not GOOGLE_CLIENT_SECRET:
        return None
    state = secrets.token_urlsafe(16)
    st.session_state["google_oauth_state"] = state
    params = {
        "client_id": GOOGLE_CLIENT_ID,
        "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "access_type": "online",
        "prompt": "select_account",
        "state": state,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def handle_google_callback():
    code = st.query_params.get("code")
    if not code:
        return False

    state = st.query_params.get("state")
    if st.session_state.get("google_oauth_state") and state != st.session_state.get("google_oauth_state"):
        st.error("Google login session is invalid. Please try again.")
        return False

    token_response = requests.post(
        "https://oauth2.googleapis.com/token",
        data={
            "code": code,
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "redirect_uri": GOOGLE_REDIRECT_URI,
            "grant_type": "authorization_code",
        },
        timeout=30,
    )
    if token_response.status_code != 200:
        st.error("Google authentication failed while exchanging the auth code.")
        return False

    token_data = token_response.json()
    userinfo_response = requests.get(
        "https://openidconnect.googleapis.com/v1/userinfo",
        headers={"Authorization": f"Bearer {token_data.get('access_token', '')}"},
        timeout=30,
    )
    if userinfo_response.status_code != 200:
        st.error("Google authentication failed while fetching user profile.")
        return False

    user_info = userinfo_response.json()
    user_email = (user_info.get("email") or "").lower()
    user_name = user_info.get("name") or "Google User"
    user = create_or_get_google_user(user_email, user_name)
    if not user:
        st.error("Unable to create or load your Google user profile.")
        return False

    st.session_state["user_email"] = user["email"]
    st.session_state["user_name"] = user["name"]
    st.session_state.pop("google_oauth_state", None)
    st.query_params.clear()
    return True


def render_auth_page():
    st.title("Story Submission Tracker")
    st.caption("Create a writer account or sign in to view your story portfolio.")
    st.markdown("---")

    auth_url = get_google_auth_url()
    if auth_url:
        st.link_button("Continue with Google", auth_url, use_container_width=True)
    else:
        st.warning(
            "Google OAuth is not configured. Add GOOGLE_CLIENT_ID and "
            "GOOGLE_CLIENT_SECRET to .streamlit/secrets.toml, then restart Streamlit. "
            "You can still create a local account below."
        )

    st.markdown("---")
    login_tab, register_tab = st.tabs(["Login", "Register"])

    with login_tab:
        with st.form("login_form"):
            st.subheader("Writer Login")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            login_clicked = st.form_submit_button("Login")
            if login_clicked:
                user = authenticate_user(email, password)
                if user:
                    st.session_state["user_email"] = user["email"]
                    st.session_state["user_name"] = user["name"]
                    st.rerun()
                else:
                    st.error("Invalid email or password.")

    with register_tab:
        with st.form("register_form"):
            st.subheader("Create a New Writer Account")
            name = st.text_input("Full Name")
            email = st.text_input("Email")
            password = st.text_input("Password", type="password")
            confirm_password = st.text_input("Confirm Password", type="password")
            register_clicked = st.form_submit_button("Create Account")
            if register_clicked:
                if not name or not email or not password:
                    st.warning("Please complete all fields.")
                elif password != confirm_password:
                    st.warning("Passwords do not match.")
                else:
                    success, message = create_user(name, email, password)
                    if success:
                        st.success(message)
                        st.session_state["user_email"] = email.strip().lower()
                        st.session_state["user_name"] = name.strip()
                        st.rerun()
                    else:
                        st.error(message)

    st.stop()


def init_db():
    if SUPABASE_CLIENT:
        return

    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS submissions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL DEFAULT '',
            story_name TEXT NOT NULL,
            submitted_to TEXT NOT NULL,
            status TEXT NOT NULL,
            date_of_submission TEXT,
            date_of_response TEXT,
            url_for_story TEXT
        )
        """
    )
    columns = [row[1] for row in conn.execute("PRAGMA table_info(submissions)").fetchall()]
    if "user_email" not in columns:
        conn.execute("ALTER TABLE submissions ADD COLUMN user_email TEXT NOT NULL DEFAULT ''")
    conn.commit()
    conn.close()


def normalize_status(value):
    if value is None or pd.isna(value):
        return "submitted"
    normalized = str(value).strip().lower()
    if normalized == "":
        return "submitted"
    mappings = {
        "accepted": "accepted",
        "accept": "accepted",
        "submitted": "submitted",
        "pending": "submitted",
        "rejected": "rejected",
        "reject": "rejected",
        "withdrawn": "withdrawn",
        "withdraw": "withdrawn",
    }
    return mappings.get(normalized, "submitted")


def clean_text(value):
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def standardize_date(value):
    if value is None or str(value).strip() == "":
        return None
    value_str = str(value).strip()
    try:
        return pd.to_datetime(value_str, errors="raise").strftime("%Y-%m-%d")
    except Exception:
        return None


def safe_date_value(value):
    if value is None or value is pd.NaT or (isinstance(value, float) and pd.isna(value)):
        return None
    if isinstance(value, str):
        value = standardize_date(value)
        if value is None:
            return None
        value = pd.to_datetime(value)
    try:
        return pd.to_datetime(value).date()
    except Exception:
        return None


def load_data(user_email=None):
    if SUPABASE_CLIENT:
        query = SUPABASE_CLIENT.table("submissions").select(
            "id,user_email,story_name,submitted_to,status,date_of_submission,date_of_response,url_for_story"
        )
        if user_email is not None:
            query = query.eq("user_email", (user_email or "").lower())
        response = query.order("date_of_submission", desc=True).order("id", desc=True).execute()
        df = pd.DataFrame(response.data)
        if df.empty:
            return pd.DataFrame(columns=["id", "user_email", "story_name", "submitted_to", "status", "date_of_submission", "date_of_response", "url_for_story"])
        return df

    conn = sqlite3.connect(DB_PATH)
    query = "SELECT id, user_email, story_name, submitted_to, status, date_of_submission, date_of_response, url_for_story FROM submissions"
    params = []
    if user_email is not None:
        query += " WHERE user_email = ?"
        params.append((user_email or "").lower())
    query += " ORDER BY date_of_submission DESC, id DESC"
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    if df.empty:
        return pd.DataFrame(columns=["id", "user_email", "story_name", "submitted_to", "status", "date_of_submission", "date_of_response", "url_for_story"])
    return df


def insert_submission(story_name, submitted_to, status, date_of_submission, date_of_response, url_for_story, user_email=""):
    values = {
        "user_email": (user_email or "").lower(),
        "story_name": clean_text(story_name),
        "submitted_to": clean_text(submitted_to),
        "status": normalize_status(status),
        "date_of_submission": date_of_submission,
        "date_of_response": date_of_response,
        "url_for_story": clean_text(url_for_story) if clean_text(url_for_story) else None,
    }
    if SUPABASE_CLIENT:
        SUPABASE_CLIENT.table("submissions").insert(values).execute()
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        INSERT INTO submissions (user_email, story_name, submitted_to, status, date_of_submission, date_of_response, url_for_story)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            (user_email or "").lower(),
            clean_text(story_name),
            clean_text(submitted_to),
            normalize_status(status),
            date_of_submission,
            date_of_response,
            clean_text(url_for_story) if clean_text(url_for_story) else None,
        ),
    )
    conn.commit()
    conn.close()


def update_submission(submission_id, story_name, submitted_to, status, date_of_submission, date_of_response, url_for_story, user_email=""):
    values = {
        "user_email": (user_email or "").lower(),
        "story_name": clean_text(story_name),
        "submitted_to": clean_text(submitted_to),
        "status": normalize_status(status),
        "date_of_submission": date_of_submission,
        "date_of_response": date_of_response,
        "url_for_story": clean_text(url_for_story) if clean_text(url_for_story) else None,
    }
    if SUPABASE_CLIENT:
        SUPABASE_CLIENT.table("submissions").update(values).eq("id", submission_id).eq("user_email", (user_email or "").lower()).execute()
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        UPDATE submissions
        SET user_email = ?, story_name = ?, submitted_to = ?, status = ?, date_of_submission = ?, date_of_response = ?, url_for_story = ?
        WHERE id = ?
        """,
        (
            (user_email or "").lower(),
            clean_text(story_name),
            clean_text(submitted_to),
            normalize_status(status),
            date_of_submission,
            date_of_response,
            clean_text(url_for_story) if clean_text(url_for_story) else None,
            submission_id,
        ),
    )
    conn.commit()
    conn.close()


def delete_submission(submission_id, user_email=""):
    if SUPABASE_CLIENT:
        SUPABASE_CLIENT.table("submissions").delete().eq("id", submission_id).eq("user_email", (user_email or "").lower()).execute()
        return

    conn = sqlite3.connect(DB_PATH)
    conn.execute("DELETE FROM submissions WHERE id = ?", (submission_id,))
    conn.commit()
    conn.close()


def normalize_header(value):
    return str(value).strip().lower().replace(" ", "").replace("-", "").replace("_", "").replace("(", "").replace(")", "")


def parse_uploaded_file(uploaded_file):
    file_name = uploaded_file.name.lower()
    if file_name.endswith(".csv"):
        df = pd.read_csv(uploaded_file)
    elif file_name.endswith((".xlsx", ".xls")):
        df = pd.read_excel(uploaded_file)
    else:
        raise ValueError("Please upload an Excel (.xlsx/.xls) or CSV file.")

    df = df.copy()
    df.columns = [normalize_header(col) for col in df.columns]

    aliases = {
        "story_name": ["storyname", "storytitle", "title"],
        "submitted_to": ["submittedto", "submittedtoentityname", "entityname", "entity"],
        "status": ["status"],
        "date_of_submission": ["dateofsubmission", "submissiondate", "submitteddate"],
        "date_of_response": ["dateofresponse", "responsedate"],
        "url_for_story": ["urlforthestory", "storyurl", "publishedurl", "url"],
    }

    for target, possible_names in aliases.items():
        matched = next((name for name in possible_names if name in df.columns), None)
        if matched:
            df.rename(columns={matched: target}, inplace=True)

    required = ["story_name", "submitted_to", "status"]
    missing = [field for field in required if field not in df.columns]
    if missing:
        raise ValueError("The uploaded file is missing required columns: Story Name, Submitted to, Status.")

    cleaned_rows = []
    for _, row in df.iterrows():
        story_name = clean_text(row.get("story_name", ""))
        submitted_to = clean_text(row.get("submitted_to", ""))
        if not story_name or not submitted_to:
            continue

        url_for_story_value = clean_text(row.get("url_for_story", ""))

        cleaned_rows.append(
            {
                "story_name": story_name,
                "submitted_to": submitted_to,
                "status": normalize_status(row.get("status", "submitted")),
                "date_of_submission": standardize_date(row.get("date_of_submission")),
                "date_of_response": standardize_date(row.get("date_of_response")),
                "url_for_story": url_for_story_value or None,
            }
        )

    if not cleaned_rows:
        raise ValueError("No valid rows were found in the uploaded file.")

    return pd.DataFrame(cleaned_rows)


def get_status_colors():
    return {
        "submitted": "#f7d7a5",
        "accepted": "#b9f2c7",
        "rejected": "#f7b7b7",
        "withdrawn": "#bfd7ff",
    }


def get_existing_story_names(user_email=None):
    data = load_data(user_email)
    if data.empty:
        return []
    return sorted({str(value).strip() for value in data["story_name"].dropna() if str(value).strip()})


def get_existing_entities(user_email=None):
    data = load_data(user_email)
    if data.empty:
        return []
    return sorted({str(value).strip() for value in data["submitted_to"].dropna() if str(value).strip()})


st.set_page_config(page_title="Story Submission Tracker", layout="wide")

CSS = """
<style>
    .main { padding-top: 1rem; }
    .block-container { padding-top: 1rem; }
    .metric-card {
        background: #f3f4f6;
        border-radius: 12px;
        padding: 1rem;
        margin-bottom: 0.75rem;
        min-height: 128px;
        border: 1px solid rgba(148,163,184,0.35);
        color: #111827;
    }
    .status-pill {
        display: inline-block;
        padding: 0.32rem 0.7rem;
        border-radius: 999px;
        font-size: 0.8rem;
        font-weight: 700;
        color: #111827;
    }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)

init_db()

if "user_email" not in st.session_state:
    st.session_state["user_email"] = None

if "user_name" not in st.session_state:
    st.session_state["user_name"] = "Writer"

if not st.session_state.get("user_email"):
    if handle_google_callback():
        pass
    if not st.session_state.get("user_email"):
        render_auth_page()

user_email = st.session_state.get("user_email")
user_name = st.session_state.get("user_name")

st.title("Story Submission Tracker")
st.caption(f"Portfolio for {user_name}.")

with st.sidebar:
    st.subheader("Writer")
    st.write(user_name)
    st.write(user_email)
    if st.button("Logout"):
        st.session_state.pop("user_email", None)
        st.session_state.pop("user_name", None)
        st.session_state.pop("google_oauth_state", None)
        st.rerun()

    st.markdown("---")
    st.header("Filters")
    search_term = st.text_input("Search by story name")
    status_filter = st.selectbox("Status filter", ["all", *STATUS_ORDER])

    st.markdown("---")
    st.header("Template")
    template_path = BASE_DIR / "upload_template.csv"
    if template_path.exists():
        template_bytes = template_path.read_bytes()
        st.download_button(
            label="Download upload template",
            data=template_bytes,
            file_name="upload_template.csv",
            mime="text/csv",
        )

    st.markdown("---")
    st.header("Import data")
    uploaded_file = st.file_uploader("Upload Excel / CSV", type=["xlsx", "xls", "csv"])
    if uploaded_file is not None:
        try:
            imported_df = parse_uploaded_file(uploaded_file)
            replace_existing = st.checkbox("Replace existing records", value=False)
            if st.button("Import file"):
                if replace_existing:
                    if SUPABASE_CLIENT:
                        SUPABASE_CLIENT.table("submissions").delete().eq("user_email", (user_email or "").lower()).execute()
                    else:
                        conn = sqlite3.connect(DB_PATH)
                        conn.execute("DELETE FROM submissions WHERE user_email = ?", ((user_email or "").lower(),))
                        conn.commit()
                        conn.close()

                for _, row in imported_df.iterrows():
                    insert_submission(
                        row["story_name"],
                        row["submitted_to"],
                        row["status"],
                        row["date_of_submission"],
                        row["date_of_response"],
                        row["url_for_story"],
                        user_email=user_email,
                    )
                st.success(f"Imported {len(imported_df)} rows.")
                st.rerun()
        except Exception as exc:
            st.error(f"Import failed: {exc}")

    st.markdown("---")
    st.header("Export data")
    export_df = load_data(user_email)
    if not export_df.empty:
        export_buffer = io.BytesIO()
        with pd.ExcelWriter(export_buffer, engine="openpyxl") as writer:
            export_df[["story_name", "submitted_to", "status", "date_of_submission", "date_of_response", "url_for_story"]].to_excel(writer, index=False, sheet_name="Submissions")
        st.download_button(
            label="Download Excel",
            data=export_buffer.getvalue(),
            file_name=f"{user_email.split('@')[0]}_story_submissions.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    else:
        st.info("No data to export yet.")


df = load_data(user_email)
if not df.empty:
    df["status"] = df["status"].apply(normalize_status)
    if search_term:
        df = df[df["story_name"].str.contains(search_term, case=False, na=False)]
    if status_filter != "all":
        df = df[df["status"] == status_filter]
else:
    df = pd.DataFrame(columns=["id", "story_name", "submitted_to", "status", "date_of_submission", "date_of_response", "url_for_story"])

summary = {item: int((df["status"] == item).sum()) if not df.empty else 0 for item in STATUS_ORDER}
summary["total"] = int(len(df))

col1, col2, col3, col4 = st.columns(4)
metrics = [
    ("Total submissions", summary["total"], col1),
    ("Submitted", summary["submitted"], col2),
    ("Accepted", summary["accepted"], col3),
    ("Rejected", summary["rejected"], col4),
]
for label, value, container in metrics:
    with container:
        st.markdown(f'<div class="metric-card"><h4>{label}</h4><h2>{value}</h2></div>', unsafe_allow_html=True)

status_chart_df = pd.DataFrame({"status": STATUS_ORDER, "count": [summary.get(status, 0) for status in STATUS_ORDER]})
status_chart_df = status_chart_df[status_chart_df["count"] > 0].copy()
status_chart_df["color"] = status_chart_df["status"].map(get_status_colors())
if not status_chart_df.empty:
    st.subheader("Status overview")
    chart = alt.Chart(status_chart_df).mark_bar().encode(
        x=alt.X("status:N", sort=STATUS_ORDER, title="Status"),
        y=alt.Y("count:Q", title="Count"),
        color=alt.Color(
            "status:N",
            scale=alt.Scale(domain=STATUS_ORDER, range=[get_status_colors()[status] for status in STATUS_ORDER]),
            legend=None,
        ),
    )
    st.altair_chart(chart, use_container_width=True)

entity_counts = df.groupby("submitted_to").size().reset_index(name="count") if not df.empty else pd.DataFrame(columns=["submitted_to", "count"])
if not entity_counts.empty:
    st.subheader("Submissions by entity")
    entity_chart = alt.Chart(entity_counts).mark_bar(color="#2563eb").encode(
        x=alt.X("submitted_to:N", sort="-y", title="Entity"),
        y=alt.Y("count:Q", title="Count"),
    )
    st.altair_chart(entity_chart, use_container_width=True)

st.markdown("---")

with st.form("new_submission_form", clear_on_submit=True):
    st.subheader("Add a submission")
    existing_story_names = get_existing_story_names(user_email)
    existing_entities = get_existing_entities(user_email)

    story_new_option = "Type a new story name..."
    entity_new_option = "Type a new entity name..."
    story_options = [story_new_option] + existing_story_names
    entity_options = [entity_new_option] + existing_entities

    if st.session_state.get("reset_submission_form"):
        st.session_state.pop("story_name_select", None)
        st.session_state.pop("entity_name_select", None)
        st.session_state.pop("new_story_name", None)
        st.session_state.pop("new_entity_name", None)
        st.session_state["reset_submission_form"] = False

    col_a, col_b = st.columns(2)
    with col_a:
        story_selection = st.selectbox("Story Name", options=story_options, index=0, key="story_name_select")
        if story_selection == story_new_option:
            story_name = st.text_input("New Story Name", key="new_story_name", placeholder="Enter a new story title")
        else:
            story_name = story_selection

        entity_selection = st.selectbox("Submitted to (Entity Name)", options=entity_options, index=0, key="entity_name_select")
        if entity_selection == entity_new_option:
            submitted_to = st.text_input("New Entity Name", key="new_entity_name", placeholder="Enter a new entity name")
        else:
            submitted_to = entity_selection

        status = st.selectbox("Status", ["submitted", "accepted", "rejected", "withdrawn"])
    with col_b:
        date_of_submission = st.date_input("Date of Submission")
        date_of_response = st.date_input("Date of Response", value=None)
        url_for_story = st.text_input("URL for the Story (if accepted and published)")

    if st.form_submit_button("Save submission"):
        if not story_name.strip() or not submitted_to.strip():
            st.warning("Story name and entity name are required.")
        else:
            insert_submission(
                story_name,
                submitted_to,
                status,
                date_of_submission.isoformat() if date_of_submission else None,
                date_of_response.isoformat() if date_of_response else None,
                url_for_story,
                user_email=user_email,
            )
            st.session_state["reset_submission_form"] = True
            st.success("Submission saved. The form will refresh to a clean state.")
            st.rerun()

st.markdown("---")

if df.empty:
    st.info("No submissions match the current filters yet. Add your first record using the form above.")
else:
    st.subheader("Submission list")
    display_df = df[["id", "story_name", "submitted_to", "status", "date_of_submission", "date_of_response", "url_for_story"]].copy()
    colors = get_status_colors()
    display_df["status_badge"] = display_df["status"].apply(lambda x: f'<span class="status-pill" style="background:{colors.get(x, "#334155")}">{x.title()}</span>')
    st.dataframe(
        display_df[["story_name", "submitted_to", "status_badge", "date_of_submission", "date_of_response", "url_for_story"]],
        use_container_width=True,
        hide_index=True,
    )

    st.subheader("Edit or delete a record")
    selected_id = st.selectbox(
        "Choose a record",
        options=df["id"].tolist(),
        format_func=lambda x: f"{x} - {df.loc[df['id'] == x, 'story_name'].iloc[0]} | {df.loc[df['id'] == x, 'submitted_to'].iloc[0]}",
    )
    selected_row = df[df["id"] == selected_id].iloc[0]

    with st.form("edit_submission_form"):
        story_name_edit = st.text_input("Story Name", value=selected_row["story_name"])
        submitted_to_edit = st.text_input("Submitted to (Entity Name)", value=selected_row["submitted_to"])
        status_edit = st.selectbox("Status", ["submitted", "accepted", "rejected", "withdrawn"], index=STATUS_ORDER.index(selected_row["status"]))

        date_of_submission_edit = st.date_input(
            "Date of Submission",
            value=safe_date_value(selected_row["date_of_submission"]),
        )
        date_of_response_edit = st.date_input(
            "Date of Response",
            value=safe_date_value(selected_row["date_of_response"]),
        )
        url_for_story_edit = st.text_input("URL for the Story", value=selected_row["url_for_story"] or "")

        col_update, col_delete = st.columns(2)
        with col_update:
            update_clicked = st.form_submit_button("Update record")
        with col_delete:
            delete_clicked = st.form_submit_button("Delete record")

        if update_clicked:
            update_submission(
                selected_id,
                story_name_edit,
                submitted_to_edit,
                status_edit,
                date_of_submission_edit.isoformat() if date_of_submission_edit else None,
                date_of_response_edit.isoformat() if date_of_response_edit else None,
                url_for_story_edit,
                user_email=user_email,
            )
            st.success("Record updated.")
            st.rerun()

        if delete_clicked:
            delete_submission(selected_id, user_email=user_email)
            st.success("Record deleted.")
            st.rerun()

st.markdown("---")
st.subheader("Workflow board")
status_colors = get_status_colors()
board_columns = st.columns(len(STATUS_ORDER))
for idx, status in enumerate(STATUS_ORDER):
    with board_columns[idx]:
        status_rows = df[df["status"] == status].copy() if not df.empty else pd.DataFrame(columns=["id", "story_name", "submitted_to", "status", "date_of_submission", "date_of_response", "url_for_story"])
        card_color = status_colors.get(status, "#e5e7eb")
        st.markdown(f'<div style="background:{card_color};padding:0.8rem;border-radius:12px;color:#111827;font-weight:700;text-align:center;margin-bottom:0.8rem;">{status.title()}</div>', unsafe_allow_html=True)
        if status_rows.empty:
            st.markdown('<div style="border:1px dashed rgba(15,23,42,0.25); border-radius:10px; padding:0.8rem; color:#374151; text-align:center; background:#f8fafc;">No stories</div>', unsafe_allow_html=True)
        else:
            for _, row in status_rows.iterrows():
                url = row.get("url_for_story") or ""
                story_url_html = f'<div><a href="{url}" target="_blank" style="color:#111827; font-weight:600;">Open story URL</a></div>' if url else ""
                date_text = row.get("date_of_submission")
                response_text = row.get("date_of_response")
                st.markdown(
                    f"""
                    <div style="background:#ffffff; border:1px solid rgba(148,163,184,0.2); border-left:8px solid {card_color}; border-radius:12px; padding:0.9rem; margin-bottom:0.8rem; color:#111827; box-shadow:0 1px 2px rgba(15,23,42,0.08);">
                        <div style="font-size:1.1rem; font-weight:700; margin-bottom:0.4rem; color:#111827;">{row['story_name']}</div>
                        <div style="color:#374151; margin-bottom:0.2rem;">{row['submitted_to']}</div>
                        <div style="font-size:0.8rem; color:#374151; margin-bottom:0.2rem;">Submitted: {date_text if date_text else '—'}</div>
                        <div style="font-size:0.8rem; color:#374151; margin-bottom:0.3rem;">Response: {response_text if response_text else '—'}</div>
                        {story_url_html}
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
