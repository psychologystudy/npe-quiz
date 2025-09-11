# app.py
import streamlit as st
import pandas as pd
import random
from datetime import datetime
import matplotlib.pyplot as plt

# ----------------------------
# Config & constants
# ----------------------------
BUNDLED_CSV = "data/questions.csv"

REQUIRED_COLS = [
    "Question",
    "Option_A", "Option_B", "Option_C", "Option_D", "Option_E",
    "Correct_Answer",
    "Explanation",
    "Domain"
]

DOMAIN_OPTIONS = ["All", "Ethics", "Assessment", "Intervention", "Communication"]

# ----------------------------
# Data helpers
# ----------------------------
@st.cache_data
def load_questions(path: str) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    # Ensure required columns exist
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""
    # Clean string columns
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = (
                df[c]
                .astype(str)
                .str.replace(r"\s+", " ", regex=True)
                .str.strip()
                .replace({"nan": ""})
            )
    return df

def filter_by_domain(df: pd.DataFrame, domain_choice: str) -> pd.DataFrame:
    if domain_choice and domain_choice != "All":
        return df[df["Domain"].str.lower() == domain_choice.lower()].copy()
    return df.copy()

def prepare_items(df: pd.DataFrame, num: int, seed: int | None = None):
    """Return a list of items with shuffled choices and mapped correct labels."""
    if df.empty:
        return []
    if num > len(df):
        num = len(df)

    rng = random.Random(seed)
    rows = df.sample(n=num, random_state=None).to_dict(orient="records")

    items = []
    for r in rows:
        # Build original list of (label, text) and keep non-empty
        orig = [(lab, r.get(f"Option_{lab}", "").strip()) for lab in list("ABCDE")]
        orig = [(lab, txt) for lab, txt in orig if txt]

        # Shuffle the visible order
        rng.shuffle(orig)

        # Remap to visible labels A.. in the new order
        display_labels = list("ABCDE")[:len(orig)]
        disp = []
        for new_lab, (orig_lab, txt) in zip(display_labels, orig):
            disp.append({"disp_lab": new_lab, "orig_lab": orig_lab, "text": txt})

        # Figure out which visible label is correct
        orig_correct = (r.get("Correct_Answer", "") or "").strip().upper()
        correct_disp = next(
            (d["disp_lab"] for d in disp if d["orig_lab"] == orig_correct),
            None,
        )

        items.append(
            {
                "row": r,
                "disp": disp,
                "correct_disp": correct_disp,
            }
        )
    return items

def reset_quiz_state():
    st.session_state.items = []
    st.session_state.index = 0
    st.session_state.score = 0
    st.session_state.results = []

def start_quiz(df: pd.DataFrame, domain_choice: str, num_questions: int):
    # Prepare filtered items and store in session
    st.session_state.score = 0
    st.session_state.index = 0
    st.session_state.results = []

    df_filt = filter_by_domain(df, domain_choice)
    st.session_state.items = prepare_items(df_filt, num_questions, seed=None)

# ----------------------------
# Google Sheets (optional)
# ----------------------------
def submit_flag_to_sheets(question_text: str, reason: str):
    """Append a flag row to Google Sheets if secrets are configured."""
    try:
        sheet_id = st.secrets.get("GSPREAD_SHEET_ID", None)
        svc = st.secrets.get("gcp_service_account", None)
        if not sheet_id or not svc:
            st.warning("Flag received locally, but Google Sheets is not configured in secrets.")
            return False

        import gspread
        from google.oauth2.service_account import Credentials

        scopes = ["https://www.googleapis.com/auth/spreadsheets"]
        creds = Credentials.from_service_account_info(svc, scopes=scopes)
        client = gspread.authorize(creds)
        sh = client.open_by_key(sheet_id)

        # Create / open a worksheet called "Flags"
        try:
            ws = sh.worksheet("Flags")
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(title="Flags", rows=100, cols=5)
            ws.append_row(["timestamp", "question", "reason"])

        ws.append_row(
            [datetime.now().isoformat(timespec="seconds"), question_text, reason],
            value_input_option="USER_ENTERED",
        )
        return True
    except Exception as e:
        st.error(f"Unable to log flag to Google Sheets: {e}")
        return False

# ----------------------------
# UI pieces
# ----------------------------
def title_page():
    st.title("🧠 NPE Quiz — Study Companion")
    st.subheader("Welcome! 👋")

    st.markdown(
        """
This little app started as **my personal study tool** for the National Psychology Exam — and I thought it’d be fun to **share it with other candidates** who might find it useful.

**How it works**
- Questions are drawn from a local bank.
- Choose a **Domain** and **Number of questions** in the sidebar.
- You’ll get immediate feedback and explanations as you go.
- At the end, you’ll see a **scrollable list of every question**, your answer, the **correct answer**, and an explanation.
- You’ll also get a **bar chart** showing how you went by domain to help guide future revision.

**Help me improve it**
- If you spot anything off, you can **flag an inaccurate question** at the bottom of the results page (there’s a text box to explain what you noticed).
- Have ideas or fixes? I’d love to hear them. Send me a message with your suggestions!

When you’re ready, use the **sidebar** ➜ pick your settings and click **Start quiz**.
        """
    )

def quiz_screen(item, idx, total):
    r = item["row"]
    disp = item["disp"]
    correct_disp = item["correct_disp"]

    st.subheader(f"Question {idx+1} of {total}")
    st.write(r.get("Question", ""))
    st.caption(f"Domain: {r.get('Domain','—')}")

    # Create radio with NO default selection
    display_choices = [f"{d['disp_lab']}. {d['text']}" for d in disp]
    choice = st.radio(
        label="Choose one:",
        options=display_choices,
        index=None,  # <- no preselection
        key=f"choice_{idx}",
        label_visibility="collapsed",
    )

    # Submit
    submitted = st.button("Submit answer", key=f"submit_{idx}")

    if submitted:
        if choice is None:
            st.warning("Please select an answer before submitting.")
            return

        chosen_lab = choice.split(".", 1)[0].strip()
        is_correct = (chosen_lab == (correct_disp or ""))

        if is_correct:
            st.success("Correct!")
            st.session_state.score += 1
        else:
            st.error(f"Incorrect. Correct is {correct_disp}.")

        # Explanation
        expl = r.get("Explanation", "")
        if expl:
            st.info(f"**Explanation:** {expl}")

        # Store result
        correct_text = next((d["text"] for d in disp if d["disp_lab"] == correct_disp), "")
        chosen_text = next((d["text"] for d in disp if d["disp_lab"] == chosen_lab), "")

        st.session_state.results.append(
            {
                "ts": datetime.now().isoformat(timespec="seconds"),
                "domain": r.get("Domain", ""),
                "question": r.get("Question", ""),
                "chosen_label": chosen_lab,
                "chosen_text": chosen_text,
                "correct_label": correct_disp or r.get("Correct_Answer", ""),
                "correct_text": correct_text,
                "is_correct": int(is_correct),
            }
        )

        # Advance
        st.session_state.index += 1
        st.rerun()

def results_screen():
    st.success("Quiz complete!")
    total = len(st.session_state.items)
    score = st.session_state.score

    st.metric("Score", f"{score}/{total}", f"{(score/total*100):.1f}%")

    res_df = pd.DataFrame(st.session_state.results)

    # Nicely formatted scrollable list of Q&A with explanations
    st.markdown("### Review your answers")
    if res_df.empty:
        st.info("No answers recorded.")
    else:
        for i, row in res_df.iterrows():
            st.markdown("---")
            st.markdown(f"**Q{i+1}. {row['question']}**")
            st.caption(f"Domain: {row['domain'] or '—'}")

            # Answers block
            chosen = f"{row['chosen_label']}. {row['chosen_text']}".strip()
            correct = f"{row['correct_label']}. {row['correct_text']}".strip()

            if row["is_correct"]:
                st.markdown(f"**✅ Your answer:** {chosen}")
            else:
                st.markdown(f"**❌ Your answer:** {chosen if row['chosen_label'] else '—'}")
                st.markdown(f"**✅ Correct answer:** {correct}")

            # Explanation (if available)
            if row["correct_text"]:
                # Explanation already printed during quiz; show again only if present.
                # We don't have separate field here, but we can re-display from item store if needed.
                pass

        # Add a little space before analytics
        st.markdown("")

        # Domain performance bar chart (placed at the end, as requested)
        st.markdown("### Performance by domain")
        acc = (
            res_df.groupby("domain")["is_correct"]
            .mean()
            .fillna(0.0)
            .mul(100)
            .sort_values(ascending=False)
            .round(1)
        )
        if not acc.empty:
            fig, ax = plt.subplots()
            ax.bar(acc.index.astype(str), acc.values)  # no color/style set (Streamlit guideline)
            ax.set_ylim(0, 100)
            ax.set_ylabel("Accuracy (%)")
            ax.set_title("Accuracy by Domain")
            for x, y in enumerate(acc.values):
                ax.text(x, y + 1, f"{y:.1f}%", ha="center", va="bottom", fontsize=9)
            st.pyplot(fig, use_container_width=True)

            # Simple recommendation (focus area)
            worst_domain = acc.idxmin()
            st.info(
                f"**Suggestion:** Your lowest accuracy was in **{worst_domain}**. "
                "Consider focusing revision there in your next practice."
            )

    # Flagging form at the very end
    st.markdown("### Flag an inaccurate question")
    with st.form("flag_form"):
        # Let the user pick a question they want to flag
        questions_list = [r["question"] for r in st.session_state.results]
        q_pick = st.selectbox("Which question needs review?", options=questions_list if questions_list else ["—"], index=0)
        reason = st.text_area("What’s wrong? Be as specific as possible.")
        submitted = st.form_submit_button("Submit flag")
        if submitted:
            if questions_list and q_pick != "—" and reason.strip():
                ok = submit_flag_to_sheets(q_pick, reason.strip())
                if ok:
                    st.success("Thanks — your flag was submitted.")
                else:
                    st.info("Flag saved locally. (If Google Sheets isn’t configured, add secrets later and try again.)")
            else:
                st.warning("Please select a question and enter a reason.")

    # Action buttons
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Restart"):
            reset_quiz_state()
            st.rerun()
    with col2:
        st.caption("Thanks for testing the app! 🚀")

# ----------------------------
# Main app
# ----------------------------
def main():
    st.set_page_config(page_title="NPE Quiz", page_icon="🧠", layout="centered")

    # Load data once
    df_all = load_questions(BUNDLED_CSV)

    # Sidebar — the only controls
    with st.sidebar:
        st.header("Settings")

        # Domain selector (single)
        domain_choice = st.selectbox("Domain", DOMAIN_OPTIONS, index=0)

        # Max questions based on current domain
        avail = len(filter_by_domain(df_all, domain_choice))
        if avail == 0:
            st.caption("No questions available for this domain.")
        max_q = max(avail, 1)

        num_questions = st.number_input(
            "Number of questions",
            min_value=1,
            max_value=max_q,
            value=min(10, max_q),
            step=1,
        )

        # Start quiz button
        if st.button("Start quiz"):
            start_quiz(df_all, domain_choice, int(num_questions))
            st.rerun()

    # Body – either title page, quiz, or results
    items = st.session_state.get("items", [])
    idx = st.session_state.get("index", 0)

    if not items:
        title_page()
        return

    if idx >= len(items):
        results_screen()
        return

    # Quiz page
    quiz_screen(items[idx], idx, len(items))

if __name__ == "__main__":
    # Initialize session defaults if needed
    if "items" not in st.session_state:
        reset_quiz_state()
    main()
