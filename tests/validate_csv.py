import sys, pandas as pd

path = sys.argv[1] if len(sys.argv) > 1 else "data/questions.csv"
df = pd.read_csv(path, encoding="utf-8-sig")

required = ["Question","Option_A","Option_B","Option_C","Option_D","Option_E","Correct_Answer","Explanation","Domain","Source"]
for c in required:
    if c not in df.columns:
        print(f"[ERROR] Missing column: {c}")
        sys.exit(1)

errors = 0
seen = set()
for i, r in df.iterrows():
    q = str(r.get("Question","")).strip()
    ca = str(r.get("Correct_Answer","")).strip().upper()
    if not q:
        print(f"[ERROR] Row {i}: empty Question")
        errors += 1
        continue
    if q.lower() in seen:
        print(f"[WARN] Row {i}: duplicate Question")
    else:
        seen.add(q.lower())
    if ca not in list("ABCDE"):
        print(f"[ERROR] Row {i}: Correct_Answer not A–E: {ca}")
        errors += 1
    else:
        opt = str(r.get(f"Option_{ca}","")).strip()
        if not opt:
            print(f"[ERROR] Row {i}: Correct_Answer points to empty Option_{ca}")
            errors += 1

print("Done with", "errors." if errors else "no blocking errors.")
sys.exit(1 if errors else 0)
