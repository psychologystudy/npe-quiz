# app.py
import streamlit as st
import pandas as pd
import random
from datetime import datetime

BUNDLED_CSV = "data/questions.csv"

REQUIRED_COLS = [
    "Question","Option_A","Option_B","Option_C","Option_D","Option_E",
    "Correct_Answer","Explanation","Domain","Source"
]

# ----------------- Data loading & validation -----------------
@st.cache_data
def load_questions(path: str) -> pd.DataFrame:
    return pd.read_csv(path, encoding="utf-8-sig")

def clean_and_validate(df: pd.DataFrame):
    issues = []
    for c in REQUIRED_COLS:
        if c not in df.columns:
            df[c] = ""
    for c in df.columns:
        if df[c].dtype == object:
            df[c] = df[c].astype(str).str.replace(r"\s+", " ", regex=True).str.strip()
            df[c] = df[c].replace({"nan": ""})

    ok_rows, seen = [], set()
    for i, r in df.iterrows():
        q = r.get("Question","")
        ca = (r.get("Correct_Answer","") or "").strip().upper()
        opts = {lab: r.get(f"Option_{lab}","").strip() for lab in "ABCDE"}
        if not q:
            issues.append((i, "Missing Question")); continue
        key = q.lower()
        if key in seen:
            issues.append((i, "Duplicate Question stem"))
        else:
            seen.add(key)
        if ca not in list("ABCDE"):
            issues.append((i, "Correct_Answer not in A–E")); continue
        if not opts.get(ca, ""):
            issues.append((i, "Correct_Answer points to empty/missing option")); continue
        ok_rows.append(i)

    df_ok = df.loc[ok_rows].reset_index(drop=True)

    mask_legacy = df_ok.applymap(lambda x: isinstance(x, str) and "WISC-IV" in x).any(axis=1)
    for idx in df_ok.index[mask_legacy]:
        issues.append((idx, "Found 'WISC-IV' (consider WISC-V)"))
    return df_ok, issues

# ----------------- Item preparation -----------------
def build_items(rows, seed=None):
    rng = random.Random(seed)
    items = []
    for r in rows:
        orig = [(lab, r.get(f"Option_{lab}", "").strip()) for lab in "ABCDE"]
        orig = [(lab, txt) for lab, txt in orig if txt]
        rng.shuffle(orig)
        display_labels = list("ABCDE")[:len(orig)]
        disp = []
        for new_lab, (orig_lab, txt) in zip(display_labels, orig):
            disp.append({"disp_lab": new_lab, "orig_lab": orig_lab, "text": txt})
        orig_correct = (r.get("Correct_Answer", "") or "").upper()
        correct_disp = next((d["disp_lab"] for d in disp if d["orig_lab"] == orig_correct), None)
        items.append({"row": r, "disp": disp, "correct_disp": correct_disp})
    return items

def prepare_items(df: pd.DataFrame, domain_choice: str, num: int, seed: int | None):
    if domain_choice and domain_choice.lower() != "all":
        df = df[df["Domain"].str.lower() == domain_choice.lower()]
    if df.empty:
        return []
    if num > len(df):
        num = len(df)
    rows = df.sample(n=num, random_state=None).to_dict(orient="records")
    return build_items(rows, seed)

# ----------------- Session helpers -----------------
def start_quiz(df: pd.DataFrame):
    st.session_state.score = 0
    st.session_state.index = 0
    st.session_state.results = []            # list of dict rows (order = asked)
    st.session_state.flagged_inaccurate = set()  # set of (domain, question, source)
    seed = None  # simple & non-seeded for now
    domain_choice = st.session_state.get("domain_choice", "All")
    num = st.session_state.get("num_questions", 10)
    st.session_state.items = prepare_items(df, domain_choice, num, seed)

def restart_quiz():
    st.session_state.items = []
    st.session_state.index = 0
    st.session_state.score = 0
    st.session_state.results = []
    st.session_state.flagged_inaccurate = set()

# ----------------- Review rendering -----------------
def render_review(results):
    """Vertical scrollable list of Q/A/Explanation with per-item flag buttons."""
    for i, rec in enumerate(results, 1):
        correct = rec["is_correct"] == 1
        tick = "✅" if correct else "❌"
        st.markdown(f"### Q{i}. {rec['question']}")
        st.caption(f"Domain: {rec['domain'] or '—'}  |  Source: {rec['source'] or '—'}")
        st.markdown(
            f"**Your answer {tick}:** {rec['chosen_label']}. {rec['chosen_text']}" if rec["chosen_label"] else
            f"**Your answer {tick}:** (no answer)"
        )
        st.markdown(
            f"**<span style='background-color:#e6ffe6;padding:2px 6px;border-radius:6px;'>"
            f"Correct: {rec['correct_label']}. {rec['correct_text']}</span>**",
            unsafe_allow_html=True
        )
        if rec.get("explanation"):
            st.markdown(f"**Explanation:** {rec['explanation']}")
        # Flag inaccurate here
        cols = st.columns([1, 1, 1, 1])
        with cols[-1]:
            flag_key = f"flag_end_{i}"
            if st.button("Flag inaccurate 🚩", key=flag_key):
                st.session_state.flagged_inaccurate.add(
                    (rec["domain"], rec["question"], rec["source"])
                )
                st.toast("Flagged. Thanks for helping keep the bank clean!", icon="✅")
        st.divider()

# ----------------- App -----------------
def main():
    st.set_page_config(page_title="NPE Quiz", page_icon="🧠", layout="centered")
    st.title("NPE Quiz")

    # Sidebar (minimal controls)
    with st.sidebar:
        st.header("Setup")
        fixed_domains = ["All", "Ethics", "Assessment", "Interventions", "Communication"]
        st.selectbox("Domain", options=fixed_domains, index=0, key="domain_choice")
        st.number_input("Number of questions", min_value=1, max_value=200, value=10, step=1, key="num_questions")

        # Load data & start
        df_raw = load_questions(BUNDLED_CSV)
        df, _ = clean_and_validate(df_raw)
        st.button("Start quiz", on_click=start_quiz, args=(df,))

    # Landing page
    items = st.session_state.get("items", [])
    idx = st.session_state.get("index", 0)

    if not items:
        st.markdown(
            """
### Why I built this NPE Quiz
Preparing for the National Psychology Exam is as much about **pattern recognition** and **testcraft** as it is about content.
I created this app to make revision **active and immediate**:

- Focused practice by domain (**Ethics, Assessment, Interventions, Communication**)
- **Immediate feedback** while you work (with quick correctness toasts)
- A final review page with **every question, answer, and explanation** in order
- A simple way to **flag questionable items** so the bank stays clean

Choose your **Domain** and **Number of questions** from the sidebar, then press **Start quiz**.
            """
        )
        return

    total = len(items)

    # Completed?
    if idx >= total:
        st.success("Quiz complete!")
        st.metric("Score", f"{st.session_state.score}/{total}", f"{(st.session_state.score/total*100):.1f}%")

        st.subheader("Review your answers")
        render_review(st.session_state.results)

        # Show flagged inaccurate summary
        st.subheader("Flagged inaccurate questions")
        flagged = list(st.session_state.get("flagged_inaccurate", set()))
        if flagged:
            flagged_df = pd.DataFrame(flagged, columns=["Domain","Question","Source"])
            st.dataframe(flagged_df.drop_duplicates(), use_container_width=True, hide_index=True)
        else:
            st.write("No questions flagged.")

        st.divider()
        if st.button("Restart"):
            restart_quiz()
            st.rerun()
        return

    # ----------------- Quiz screen -----------------
    item = items[idx]
    r = item["row"]
    disp = item["disp"]
    correct_disp = item["correct_disp"]

    st.subheader(f"Question {idx+1} of {total}")
    st.write(r["Question"])
    st.caption(f"Domain: {r.get('Domain','') or '—'}  |  Source: {r.get('Source','') or '—'}")

    display_choices = [f"{d['disp_lab']}. {d['text']}" for d in disp]

    prev_choice_key = f"q_{idx}"
    current_value = st.session_state.get(prev_choice_key, None)

    # Radio with NO default selection (index=None). If your Streamlit build doesn't allow this,
    # we can fall back to a small placeholder shim—but try this first.
    choice = st.radio(
        "Choose one:",
        options=display_choices,
        index=None if current_value is None else display_choices.index(current_value),
        label_visibility="collapsed",
        key=prev_choice_key
    )

    # Submit -> record -> toast -> NEXT immediately
    submitted = st.button("Submit answer", disabled=(choice is None), key=f"submit_{idx}")
    if submitted:
        chosen_lab = (choice or "").split(".", 1)[0].strip()
        is_correct = int(chosen_lab == (correct_disp or ""))

        if is_correct:
            st.toast("Correct!", icon="✅")
            st.session_state.score += 1
        else:
            st.toast(f"Incorrect. Correct is {correct_disp or '(not set)'}", icon="⚠️")

        correct_text = next((d["text"] for d in disp if d["disp_lab"] == correct_disp), "")
        chosen_text = next((d["text"] for d in disp if d["disp_lab"] == chosen_lab), "")
        expl = r.get("Explanation","")

        st.session_state.results.append({
            "ts": datetime.now().isoformat(timespec="seconds"),
            "domain": r.get("Domain",""),
            "source": r.get("Source",""),
            "question": r.get("Question",""),
            "chosen_label": chosen_lab,
            "chosen_text": chosen_text,
            "correct_label": correct_disp or r.get("Correct_Answer",""),
            "correct_text": correct_text,
            "is_correct": is_correct,
            "explanation": expl,
        })

        # Advance immediately
        st.session_state.index += 1
        # Clean per-question state
        if prev_choice_key in st.session_state:
            del st.session_state[prev_choice_key]
        st.rerun()

if __name__ == "__main__":
    main()
