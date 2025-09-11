# app.py
import streamlit as st
import pandas as pd
import random
from datetime import datetime
from io import StringIO

# -------------------- Constants --------------------
BUNDLED_CSV = "data/questions.csv"
DOMAINS = ["Ethics", "Assessment", "Intervention", "Communication"]
REQUIRED_COLS = [
    "Question", "Option_A", "Option_B", "Option_C", "Option_D", "Option_E",
    "Correct_Answer", "Explanation", "Domain"
]

# Optional Google Sheets flags (set in Streamlit secrets)
# st.secrets must contain:
#   GSPREAD_SHEET_ID = "<sheet id>"
#   [gcp_service_account] ... full service account JSON values
def append_flag_to_gsheets(payload: dict) -> bool:
    """Append a single flag row to Google Sheets if secrets are present."""
    try:
        if "GSPREAD_SHEET_ID" not in st.secrets:
            return False
        import gspread
        from google.oauth2.service_account import Credentials

        sa_info = dict(st.secrets["gcp_service_account"])
        creds = Credentials.from_service_account_info(
            sa_info,
            scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        gc = gspread.authorize(creds)
        sh = gc.open_by_key(st.secrets["GSPREAD_SHEET_ID"])
        ws = None
        try:
            ws = sh.worksheet("flags")
        except Exception:
            ws = sh.add_worksheet("flags", rows=1000, cols=10)
            ws.append_row(["ts","domain","question","chosen_label","chosen_text","correct_label","correct_text","notes"])
        ws.append_row([
            payload.get("ts",""),
            payload.get("domain",""),
            payload.get("question",""),
            payload.get("chosen_label",""),
            payload.get("chosen_text",""),
            payload.get("correct_label",""),
            payload.get("correct_text",""),
            payload.get("notes",""),
        ])
        return True
    except Exception:
        return False

# -------------------- Data loading & cleaning --------------------
@st.cache_data
def load_questions(path: str) -> pd.DataFrame:
    # robust BOM handling
    try:
        return pd.read_csv(path, encoding="utf-8-sig")
    except UnicodeDecodeError:
        return pd.read_csv(path, encoding="utf-8")

def clean_and_validate(df: pd.DataFrame) -> pd.DataFrame:
    # Ensure required columns exist; normalize whitespace; strip literal "nan"
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = (
                df[c]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace({"nan": ""})
            )
    # Keep rows with a question + valid correct answer pointing to a non-empty option
    ok_rows = []
    for i, r in df.iterrows():
        q = r.get("Question","").strip()
        ca = (r.get("Correct_Answer","") or "").strip().upper()
        if not q or ca not in list("ABCDE"):
            continue
        if not (r.get(f"Option_{ca}","") or "").strip():
            continue
        ok_rows.append(i)
    return df.loc[ok_rows].reset_index(drop=True)

# -------------------- Item prep --------------------
def prepare_items(df: pd.DataFrame, domains_selected: list[str], num: int):
    # domain filter
    if domains_selected and "All" not in domains_selected:
        df = df[df["Domain"].str.lower().isin([d.lower() for d in domains_selected])]

    if df.empty:
        return []

    # sample
    if num > len(df):
        num = len(df)
    rows = df.sample(n=num, random_state=None).to_dict(orient="records")

    items = []
    rng = random.Random()  # no seed => fresh shuffle each run
    for r in rows:
        orig = [(lab, (r.get(f"Option_{lab}", "") or "").strip()) for lab in list("ABCDE")]
        orig = [(lab, txt) for lab, txt in orig if txt]  # drop empties
        rng.shuffle(orig)

        labels = list("ABCDE")[:len(orig)]
        disp = []
        for new_lab, (orig_lab, txt) in zip(labels, orig):
            disp.append({"disp_lab": new_lab, "orig_lab": orig_lab, "text": txt})

        orig_correct = (r.get("Correct_Answer","") or "").upper()
        correct_disp = next((d["disp_lab"] for d in disp if d["orig_lab"] == orig_correct), None)

        items.append({
            "row": r,
            "disp": disp,
            "correct_disp": correct_disp
        })
    return items

# -------------------- Quiz state helpers --------------------
def start_quiz(df: pd.DataFrame):
    st.session_state.score = 0
    st.session_state.index = 0
    st.session_state.results = []
    st.session_state.items = prepare_items(
        df,
        st.session_state.get("domain_choice", ["All"]),
        st.session_state.get("num_questions", 10)
    )

def restart_quiz():
    for k in ["score","index","results","items"]:
        st.session_state.pop(k, None)

# -------------------- App --------------------
def main():
    st.set_page_config(page_title="NPE Quiz", page_icon="🧠", layout="centered")

    # Minimal CSS for nicer cards + highlights
    st.markdown("""
    <style>
      .card { border: 1px solid #eaeaea; padding: 1rem; border-radius: 14px; margin: 0.5rem 0 1rem; background: #fff; }
      .pill { display:inline-block; padding:2px 10px; border-radius:999px; font-size:.8rem; background:#f1f3f5; margin-right:.35rem; }
      .correct { background:#e8f5e9; border-left:4px solid #2e7d32; padding:.6rem .8rem; border-radius:10px; }
      .wrong { background:#ffebee; border-left:4px solid #c62828; padding:.6rem .8rem; border-radius:10px; }
      .muted { color:#6b7280; font-size:.9rem; }
      .option { padding:.25rem .5rem; border-radius:8px; }
    </style>
    """, unsafe_allow_html=True)

    # ---------- Sidebar ----------
    with st.sidebar:
        st.header("⚙️ Quiz Settings")
        st.number_input("Number of questions", min_value=1, max_value=200, value=10, step=1, key="num_questions")

        domain_options = ["All"] + DOMAINS
        st.multiselect(
            "Domains",
            options=domain_options,
            default=["All"],
            key="domain_choice"
        )

        st.button("Start quiz", type="primary", use_container_width=True, on_click=lambda: start_quiz(df_ok))

    # ---------- Load data ----------
    df_raw = load_questions(BUNDLED_CSV)
    df_ok = clean_and_validate(df_raw)

    # ---------- Hero / Welcome ----------
    items = st.session_state.get("items", [])
    idx = st.session_state.get("index", 0)

    st.title("🧠 NPE Quiz")
    if not items:
        st.subheader("Built by a candidate, for candidates")
        st.write(
            "This practice tool helps you prepare for the **National Psychology Examination** with realistic MCQs, "
            "instant feedback, and a full results review at the end."
        )
        with st.expander("Why I created this app"):
            st.markdown(
                "- Focus your time on **high-yield domains** (Ethics, Assessment, Intervention, Communication)\n"
                "- Get **immediate learning** via explanations\n"
                "- Review every question at the end with **clear highlights**\n"
                "- Optionally **flag inaccuracies** so the bank stays high quality"
            )
        st.info("Use the controls in the left sidebar to choose your domains and number of questions, then click **Start quiz**.")
        return

    # ---------- Finished? ----------
    total = len(items)
    if idx >= total:
        score = st.session_state.get("score", 0)
        st.success("All done! 🎉")
        st.metric("Score", f"{score}/{total}", f"{(score/total*100):.1f}%")

        res_df = pd.DataFrame(st.session_state.get("results", []))

        # Detailed per-question review (in order)
        st.markdown("### Review your answers")
        if res_df.empty:
            st.info("No responses captured.")
        else:
            for i, row in res_df.iterrows():
                st.markdown(f"**Q{i+1}. {row['question']}**")
                st.caption(f"Domain: {row.get('domain','—')}")
                # Show chosen + correct
                chosen = f"{row['chosen_label']}. {row['chosen_text']}" if row['chosen_label'] else "(no answer)"
                correct = f"{row['correct_label']}. {row['correct_text']}"
                if row["is_correct"] == 1:
                    st.markdown(f"<div class='correct'><b>Correct</b><br>Answer: {correct}</div>", unsafe_allow_html=True)
                else:
                    st.markdown(
                        f"<div class='wrong'><b>Incorrect</b><br>Your choice: {chosen}<br>Correct: {correct}</div>",
                        unsafe_allow_html=True
                    )
                expl = (row.get("explanation","") or "").strip()
                if expl:
                    st.markdown(f"<div class='card'><span class='muted'>Explanation</span><br>{expl}</div>", unsafe_allow_html=True)
                st.divider()

            # Flag inaccurate questions (end of page)
            st.markdown("### 🏳️ Flag an inaccurate question")
            with st.form("flag_form"):
                # Pick a question to flag
                q_labels = [f"Q{i+1}: {q[:90]}{'…' if len(q)>90 else ''}" for i, q in enumerate(res_df["question"].tolist())]
                q_choice = st.selectbox("Which question?", options=q_labels, index=0)
                notes = st.text_area("What’s wrong or needs fixing? (optional but helpful)")
                submit_flag = st.form_submit_button("Submit flag")
                if submit_flag:
                    k = q_labels.index(q_choice)
                    row = res_df.iloc[k]
                    payload = {
                        "ts": datetime.now().isoformat(timespec="seconds"),
                        "domain": row.get("domain",""),
                        "question": row.get("question",""),
                        "chosen_label": row.get("chosen_label",""),
                        "chosen_text": row.get("chosen_text",""),
                        "correct_label": row.get("correct_label",""),
                        "correct_text": row.get("correct_text",""),
                        "notes": notes or "",
                    }
                    ok = append_flag_to_gsheets(payload)
                    if ok:
                        st.success("Thanks! Your flag has been recorded.")
                    else:
                        st.warning("Flag not sent. If this is your local run, add Google Sheets creds in **Secrets** and try again.")

        # (Moved) Domain breakdown bar chart — at the very end
        if not res_df.empty:
            st.markdown("### 📊 Domain performance")
            # Accuracy per domain
            perf = (
                res_df
                .groupby("domain")["is_correct"]
                .mean()
                .mul(100)
                .round(1)
                .rename("Accuracy %")
                .sort_values(ascending=False)
                .to_frame()
            )
            st.bar_chart(perf)  # simple, nice default bar

            # Recommend focus area (lowest accuracy with >=2 questions if possible)
            counts = res_df.groupby("domain").size().rename("n")
            merged = perf.join(counts, how="inner")
            if not merged.empty:
                # prefer domain with >=2; else min overall
                cand = merged[merged["n"] >= 2]
                focus_row = (cand if not cand.empty else merged).sort_values(by="Accuracy %", ascending=True).head(1)
                focus_domain = focus_row.index[0]
                focus_score = float(focus_row["Accuracy %"].iloc[0])
                st.info(f"**Suggested focus:** {focus_domain} (current accuracy {focus_score:.1f}%).")

        # Restart button
        st.button("Restart", type="secondary", on_click=restart_quiz)
        return

    # ---------- Quiz screen ----------
    item = items[idx]
    r = item["row"]
    disp = item["disp"]
    correct_disp = item["correct_disp"]

    # Progress
    st.progress((idx) / total)
    st.subheader(f"Question {idx+1} of {total}")
    st.markdown(f"<div class='card'>{r['Question']}</div>", unsafe_allow_html=True)
    st.caption(f"Domain: {r.get('Domain','—')}")

    # Choices
    choices = [f"{d['disp_lab']}. {d['text']}" for d in disp]
    choice = st.radio("Choose one:", options=choices, index=None, label_visibility="collapsed")

    # Submit
    submitted = st.button("Submit answer", type="primary", disabled=(choice is None))
    if submitted and choice is not None:
        chosen_lab = choice.split(".", 1)[0].strip()
        is_correct = int(chosen_lab == (correct_disp or ""))

        correct_text = next((d["text"] for d in disp if d["disp_lab"] == correct_disp), "")
        chosen_text = next((d["text"] for d in disp if d["disp_lab"] == chosen_lab), "")

        st.session_state.results.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "domain": r.get("Domain",""),
            "question": r.get("Question",""),
            "chosen_label": chosen_lab,
            "chosen_text": chosen_text,
            "correct_label": correct_disp or r.get("Correct_Answer",""),
            "correct_text": correct_text,
            "explanation": r.get("Explanation",""),
            "is_correct": is_correct
        })
        if is_correct:
            st.session_state.score = st.session_state.get("score", 0) + 1

        st.session_state.index = idx + 1
        st.rerun()

if __name__ == "__main__":
    main()
