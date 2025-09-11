# app.py
import streamlit as st
import pandas as pd
import random
from datetime import datetime
import hashlib
import uuid

# Optional Google Sheets (app still runs without these/secrets)
try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:  # pragma: no cover
    gspread = None
    Credentials = None

# ---------- Config ----------
st.set_page_config(page_title="NPE Quiz", page_icon="🧠", layout="centered")

BANK_VERSION = "NPE Bank v1.2 • 2025-09-11"
BUNDLED_CSV = "data/questions.csv"

# REQUIRED columns: Source is now optional/ignored in UI
REQUIRED_COLS = [
    "Question", "Option_A", "Option_B", "Option_C", "Option_D", "Option_E",
    "Correct_Answer", "Explanation", "Domain"
]

# Fixed domains shown to user (case-insensitive match with CSV)
DOMAIN_OPTIONS = ["All", "Ethics", "Assessment", "Interventions", "Communication"]
CANON_DOMAINS = {d.lower(): d for d in DOMAIN_OPTIONS if d != "All"}

# Session id for flag logging
if "session_id" not in st.session_state:
    st.session_state.session_id = uuid.uuid4().hex[:8]

# ---------- Data loading & validation ----------
@st.cache_data
def load_questions(path: str) -> pd.DataFrame:
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        try:
            return pd.read_csv(path, encoding="utf-8")
        except Exception:
            return pd.read_csv(path)

def _canon_domain(val: str) -> str:
    """Map arbitrary domain text to our canonical set; return '' if no match."""
    v = (val or "").strip().lower()
    if not v:
        return ""
    # simple synonyms / fuzzy-ish mapping
    if v.startswith("ethic"):
        return "Ethics"
    if v.startswith("assess"):
        return "Assessment"
    if v.startswith("interven") or v.startswith("treat") or v.startswith("therapy"):
        return "Interventions"
    if v.startswith("comm"):
        return "Communication"
    # if exact match already canonical
    return CANON_DOMAINS.get(v, "")

def clean_and_validate(df: pd.DataFrame):
    """
    - Ensure required columns exist
    - Strip whitespace
    - Replace literal 'nan' strings with ''
    - Validate A–E answer points to a non-empty option
    - Canonicalise Domain to one of {Ethics, Assessment, Interventions, Communication} when possible
    Returns: (df_ok, issues, missing_report_df)
    """
    issues = []

    # Ensure required columns exist
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""

    # Trim whitespace & normalise 'nan'
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
            df[c] = df[c].replace({"nan": ""})

    # Canonicalise Domain (if possible)
    df["Domain"] = df["Domain"].apply(_canon_domain)

    ok_rows = []
    seen_stems = set()

    for i, r in df.iterrows():
        q = r.get("Question", "")
        ca = (r.get("Correct_Answer", "") or "").strip().upper()
        opts = {lab: r.get(f"Option_{lab}", "").strip() for lab in "ABCDE"}

        if not q:
            issues.append((i, "Missing Question"))
            continue

        # Duplicate stem (informational)
        k = q.lower()
        if k in seen_stems:
            issues.append((i, "Duplicate Question stem"))
        else:
            seen_stems.add(k)

        # Correct_Answer must be A–E and exist
        if ca not in list("ABCDE"):
            issues.append((i, "Correct_Answer not in A–E"))
            continue
        if not opts.get(ca):
            issues.append((i, "Correct_Answer points to empty/missing option"))
            continue

        ok_rows.append(i)

    df_ok = df.loc[ok_rows].reset_index(drop=True)

    # Build a small report of missing fields you want to complete
    miss_mask = (df_ok["Explanation"].eq("")) | (df_ok["Domain"].eq(""))
    missing_report = df_ok.loc[miss_mask, ["Question", "Option_A", "Option_B", "Option_C",
                                           "Option_D", "Option_E", "Correct_Answer",
                                           "Explanation", "Domain"]].copy()

    return df_ok, issues, missing_report

# ---------- Google Sheets helpers ----------
@st.cache_resource
def get_flags_worksheet():
    """
    Return a gspread Worksheet for the 'flags' tab, or None if not configured.
    Secrets required:
      GSPREAD_SHEET_ID = "<sheet_id>"
      [gcp_service_account]  # full service account JSON fields
    """
    if gspread is None or Credentials is None:
        return None
    try:
        svc = st.secrets["gcp_service_account"]
        sheet_id = st.secrets["GSPREAD_SHEET_ID"]
    except Exception:
        return None

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(svc, scopes=scopes)
    client = gspread.authorize(creds)
    sh = client.open_by_key(sheet_id)
    try:
        ws = sh.worksheet("flags")
    except gspread.WorksheetNotFound:
        ws = sh.add_worksheet(title="flags", rows=2000, cols=10)
        ws.append_row(["ts", "session_id", "domain", "question_hash", "question"])
    return ws

def append_flag_to_sheet(domain: str, question: str):
    """Append one flag row; returns (ok: bool, message: str)."""
    ws = get_flags_worksheet()
    if ws is None:
        return False, "Google Sheets not configured."
    try:
        qhash = hashlib.sha1((question or "").encode("utf-8")).hexdigest()[:10]
        ws.append_row([
            datetime.now().isoformat(timespec="seconds"),
            st.session_state.get("session_id", ""),
            domain or "",
            qhash,
            question or "",
        ])
        return True, "Saved to Google Sheet."
    except Exception as e:
        return False, f"Append failed: {e}"

def current_flags_sheet_url():
    try:
        sid = st.secrets["GSPREAD_SHEET_ID"]
        return f"https://docs.google.com/spreadsheets/d/{sid}/edit"
    except Exception:
        return None

# ---------- Item preparation ----------
def prepare_items(df: pd.DataFrame, domains: list[str], num: int):
    # Filter by domain(s) (case-insensitive), unless All selected or empty
    if domains and "All" not in [d.title() for d in domains]:
        df = df[df["Domain"].fillna("").str.lower().isin([d.lower() for d in domains])]

    if df.empty:
        return []

    # Clip number of questions to available
    if num > len(df):
        num = len(df)

    rows = df.sample(n=num, random_state=None).to_dict(orient="records")
    items = []

    for r in rows:
        # Collect non-empty options and shuffle
        orig = [(lab, str(r.get(f"Option_{lab}", "")).strip()) for lab in "ABCDE"]
        orig = [(lab, txt) for lab, txt in orig if txt]
        random.shuffle(orig)

        # Map to display labels A.. in new order
        display_labels = list("ABCDE")[:len(orig)]
        disp = []
        for new_lab, (orig_lab, txt) in zip(display_labels, orig):
            disp.append({"disp_lab": new_lab, "orig_lab": orig_lab, "text": txt})

        # Find correct display label via original correct letter
        orig_correct = (r.get("Correct_Answer", "") or "").upper()
        correct_disp = next((d["disp_lab"] for d in disp if d["orig_lab"] == orig_correct), None)

        items.append({
            "row": r,
            "disp": disp,                 # list of dicts {disp_lab, orig_lab, text}
            "correct_disp": correct_disp  # e.g., 'B'
        })
    return items

# ---------- Session helpers ----------
def start_quiz(df: pd.DataFrame):
    st.session_state.score = 0
    st.session_state.index = 0
    st.session_state.results = []
    num = st.session_state.num_questions
    chosen_domains = st.session_state.domain_choice
    st.session_state.items = prepare_items(df, chosen_domains, num)

def restart_quiz():
    st.session_state.items = []
    st.session_state.index = 0
    st.session_state.score = 0
    st.session_state.results = []

# ---------- Review renderer ----------
def render_review(results):
    """Vertical list of Q/A/Explanation with per-item 'Flag inaccurate' buttons."""
    for i, rec in enumerate(results, 1):
        correct = rec["is_correct"] == 1
        tick = "✅" if correct else "❌"

        st.markdown(f"### Q{i}. {rec['question']}")
        st.caption(f"Domain: {rec['domain'] or '—'}")

        if rec["chosen_label"]:
            st.markdown(f"**Your answer {tick}:** {rec['chosen_label']}. {rec['chosen_text']}")
        else:
            st.markdown(f"**Your answer {tick}:** (no answer)")

        st.markdown(
            f"**<span style='background-color:#e6ffe6;padding:2px 6px;border-radius:6px;'>"
            f"Correct: {rec['correct_label']}. {rec['correct_text']}</span>**",
            unsafe_allow_html=True
        )

        if rec.get("explanation"):
            st.markdown(f"**Explanation:** {rec['explanation']}")
        else:
            st.markdown(
                "<span style='color:#888;'>No explanation yet — to improve the bank, add one in data/questions.csv.</span>",
                unsafe_allow_html=True
            )

        cols = st.columns([1, 1, 1, 1])
        with cols[-1]:
            if st.button("Flag inaccurate 🚩", key=f"flag_end_{i}"):
                ok, msg = append_flag_to_sheet(rec["domain"], rec["question"])
                if ok:
                    st.toast("Flag recorded. Thanks!", icon="✅")
                else:
                    st.error(msg)

        st.divider()

# ---------- App ----------
def main():
    st.title("NPE Quiz 🧠")

    # Sidebar (only the 3 controls)
    with st.sidebar:
        st.header("Settings")
        st.number_input("Number of questions", min_value=1, max_value=500, value=10, step=1, key="num_questions")
        st.multiselect(
            "Domain(s)",
            options=DOMAIN_OPTIONS,
            default=["All"],
            key="domain_choice",
            help="Choose 'All' or filter by specific domain(s)."
        )

        df_raw = load_questions(BUNDLED_CSV)
        df, issues, missing_report = clean_and_validate(df_raw)

        st.button("Start quiz", type="primary", on_click=start_quiz, args=(df,))

        # Admin audit: find items missing Explanation or Domain
        with st.expander("Admin: Data audit (missing Explanation/Domain)"):
            n_missing = len(missing_report)
            if n_missing == 0:
                st.success("No missing Explanation/Domain ✅")
            else:
                st.warning(f"{n_missing} item(s) missing Explanation and/or Domain.")
                st.download_button(
                    "Download missing-items CSV",
                    data=missing_report.to_csv(index=False).encode("utf-8-sig"),
                    file_name="missing_explanations_or_domains.csv",
                    mime="text/csv"
                )
            # Optional: show where flags go
            url = current_flags_sheet_url()
            if url:
                st.caption(f"Flags destination: [Google Sheet]({url})")

    # Get current items/index
    items = st.session_state.get("items", [])
    idx = st.session_state.get("index", 0)

    # Landing page
    if not items:
        st.markdown(
            """
            ### Welcome to the NPE Quiz App

            I built this to **study for the National Psychology Exam** and to share a practical,
            feedback-driven way to revise. It uses a structured question bank with clear
            explanations and shows your results at the end so you can **learn by doing**.

            **How it works**
            1. Pick the number of questions and (optionally) a domain filter in the sidebar.
            2. Click **Start quiz**.
            3. Answer each question. Your choice is checked immediately and the next item loads.
            4. At the end, see a **scrollable list** of every question with the **correct answer highlighted** and explanations.
            5. If you spot any errors, use **“Flag inaccurate”** to send it to my review list.

            _Tip: This is an independent study aid — always cross-check with official guidelines and texts._
            """
        )
        st.caption(BANK_VERSION)
        return

    total = len(items)
    # Finished? -> Summary page
    if idx >= total:
        st.success("Quiz complete!")
        st.metric("Score", f"{st.session_state.score}/{total}", f"{(st.session_state.score/total*100):.1f}%")

        # Domain performance bar chart & recommendation
        res_df = pd.DataFrame(st.session_state.results)
        if not res_df.empty:
            by_dom = (
                res_df.groupby("domain", dropna=False)["is_correct"]
                .agg(["count", "mean"])
                .rename(columns={"count": "N", "mean": "Accuracy"})
                .reset_index()
            )
            by_dom["Accuracy %"] = (by_dom["Accuracy"] * 100).round(1)

            # Chart (only domains that are labeled)
            ch_df = by_dom[by_dom["domain"].fillna("") != ""].set_index("domain")[["Accuracy %"]]
            if not ch_df.empty:
                st.subheader("Performance by Domain")
                st.bar_chart(ch_df)  # simple Streamlit chart

                # Recommend weakest focus area (prefer domains with N>=3; else any)
                cand = by_dom[by_dom["N"] >= 3]
                if cand.empty:
                    cand = by_dom
                if not cand.empty:
                    weakest = cand.sort_values(["Accuracy", "N"], ascending=[True, False]).iloc[0]
                    st.info(
                        f"**Focus suggestion:** {weakest['domain'] or 'General'} "
                        f"({weakest['Accuracy %']}% correct across {int(weakest['N'])} items). "
                        "Consider reviewing this area before your next quiz."
                    )

        # Review section (vertical list)
        if st.session_state.get("results"):
            render_review(st.session_state.results)

        # Restart
        if st.button("Restart"):
            restart_quiz()
            st.rerun()

        st.caption(BANK_VERSION)
        return

    # Quiz screen
    item = items[idx]
    r = item["row"]
    disp = item["disp"]
    correct_disp = item["correct_disp"]

    st.subheader(f"Question {idx+1} of {total}")
    st.write(r.get("Question", ""))
    st.caption(f"Domain: {r.get('Domain', '') or '—'}")

    # Radio with no default selection (index=None)
    display_choices = [f"{d['disp_lab']}. {d['text']}" for d in disp]
    choice = st.radio(
        "Choose one:",
        options=display_choices,
        index=None,
        label_visibility="collapsed",
        key=f"q_{idx}"
    )

    submitted = st.button("Submit answer", type="primary", key=f"submit_{idx}")

    if submitted:
        if not choice:
            st.warning("Please select an answer before submitting.")
            return

        chosen_lab = choice.split(".", 1)[0].strip()
        is_correct = (chosen_lab == (correct_disp or ""))

        # Toast result then advance
        if is_correct:
            st.toast("Correct!", icon="✅")
            st.session_state.score += 1
        else:
            st.toast(f"Incorrect. Correct is {correct_disp or '(not set)'}", icon="❌")

        correct_text = next((d["text"] for d in disp if d["disp_lab"] == correct_disp), "")
        chosen_text = next((d["text"] for d in disp if d["disp_lab"] == chosen_lab), "")
        st.session_state.results.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "domain": r.get("Domain", ""),
            "question": r.get("Question", ""),
            "chosen_label": chosen_lab,
            "chosen_text": chosen_text,
            "correct_label": correct_disp or r.get("Correct_Answer", ""),
            "correct_text": correct_text,
            "explanation": r.get("Explanation", ""),
            "is_correct": int(is_correct),
        })

        st.session_state.index += 1
        st.rerun()

    st.caption(BANK_VERSION)


if __name__ == "__main__":
    main()
