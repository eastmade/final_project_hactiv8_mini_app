# -*- coding: utf-8 -*-
"""
Final Project – Hacktiv8
Minimal but complete: Chat + KB + MCQ + Export
- Works with `google-genai` (new Google AI Python SDK) already in your requirements.
- No database. KB = gabungan teks dari file .txt/.md (atau paste manual).
- PDF optional: kalau PyPDF2 tidak tersedia, akan diabaikan otomatis.

How to run:  streamlit run final_project_min.py
"""

import os
import io
import json
import time
import base64
import datetime as dt
from typing import List, Dict, Tuple

import streamlit as st
from langchain.text_splitter import RecursiveCharacterTextSplitter

# Google AI SDK (google-genai)
try:
    from google import genai
except Exception as e:
    st.stop()

# --- Optional PDF support (tidak wajib untuk lulus). ---
try:
    import PyPDF2  # not in requirements; if missing we'll skip PDF
    _PDF_OK = True
except Exception:
    _PDF_OK = False


# ========= Helpers =========

def get_client(api_key: str):
    """Create Google AI client from google-genai."""
    return genai.Client(api_key=api_key)


def read_text_file(file) -> str:
    data = file.read()
    try:
        return data.decode("utf-8")
    except Exception:
        # best effort
        return data.decode("latin-1", errors="ignore")


def extract_pdf(file) -> str:
    if not _PDF_OK:
        return ""
    try:
        reader = PyPDF2.PdfReader(io.BytesIO(file.read()))
        text = []
        for page in reader.pages:
            text.append(page.extract_text() or "")
        return "\n".join(text)
    except Exception:
        return ""


def build_kb_text(files: List, pasted_text: str) -> str:
    """Gabungkan semua teks dari file + paste area, lalu ringkas jadi ≤ 25k chars."""
    all_texts = []
    if files:
        for f in files:
            name = f.name.lower()
            if name.endswith(".txt") or name.endswith(".md"):
                all_texts.append(read_text_file(f))
            elif name.endswith(".pdf"):
                txt = extract_pdf(f)
                if txt:
                    all_texts.append(txt)
    if pasted_text.strip():
        all_texts.append(pasted_text.strip())

    full = "\n\n".join(t for t in all_texts if t)
    if not full:
        return ""

    # pecah biar lebih teratur, tapi tetap sederhana (tanpa vektor DB)
    splitter = RecursiveCharacterTextSplitter(chunk_size=1200, chunk_overlap=150)
    chunks = splitter.split_text(full)
    # batasi total context (≈ 25k chars) agar aman untuk 1.5-flash
    out = []
    size = 0
    limit = 25000
    for c in chunks:
        if size + len(c) > limit:
            break
        out.append(c)
        size += len(c)
    return "\n\n".join(out)


def ask_model(client, model_id: str, system: str, user: str, temperature: float = 0.3) -> str:
    """Prompt sederhana: system + user -> text."""
    contents = [
        {"role": "user", "parts": [{"text": f"SYSTEM:\n{system}"}]},
        {"role": "user", "parts": [{"text": user}]},
    ]
    try:
        resp = client.models.generate_content(
            model=model_id,
            contents=contents,
            config=genai.types.GenerateContentConfig(temperature=temperature),
        )
        return (getattr(resp, "text", None) or "").strip()
    except Exception as e:
        return f"(Gagal memanggil model: {e})"


def gen_mcq(client, model_id: str, context: str, n: int = 5) -> List[Dict]:
    """Minta model buat MCQ berbentuk JSON sederhana."""
    system = (
        "Anda adalah asisten edukasi. Bangun 5 soal pilihan ganda (MCQ) dari konteks."
        " Jawab dalam Bahasa Indonesia semi-formal."
        " Format output harus JSON list of objects: "
        '[{"q":"...","a":["A","B","C","D"],"key":0}, ...] '
        "di mana 'key' adalah index jawaban benar (0..3). Jangan menambahkan penjelasan di luar JSON."
    )
    user = f"Konteks:\n{context}\n\nBuat {n} soal MCQ seperti spesifikasi di atas."
    raw = ask_model(client, model_id, system, user, temperature=0.2)

    # Ambil JSON dari respons (strip teks non-JSON jika ada)
    try:
        start = raw.find("[")
        end = raw.rfind("]") + 1
        data = json.loads(raw[start:end])
        valid = []
        for item in data:
            if (
                isinstance(item, dict)
                and "q" in item and "a" in item and "key" in item
                and isinstance(item["a"], list) and len(item["a"]) >= 4
            ):
                valid.append({"q": item["q"], "a": item["a"][:4], "key": int(item["key"])})
        return valid[:n]
    except Exception:
        # fallback minimal
        return []


def make_csv_bytes(rows: List[Dict[str, str]]) -> bytes:
    if not rows:
        return b""
    # CSV manual (tanpa pandas untuk ringan)
    cols = list(rows[0].keys())
    lines = [",".join(cols)]
    for r in rows:
        vals = []
        for c in cols:
            v = str(r.get(c, "")).replace('"', '""')
            if ("," in v) or ("\n" in v):
                vals.append(f'"{v}"')
            else:
                vals.append(v)
        lines.append(",".join(vals))
    return ("\n".join(lines)).encode("utf-8")


# ========= UI =========

st.set_page_config(page_title="Final Project – EduBot", page_icon="🦊", layout="wide")

H8_ORANGE = "#EE6533"
H8_SECOND = "#F3922E"
H8_BLACK = "#252121"
H8_TEXT = "#F5F5F5"
H8_SKY = "#2BA9E0"

st.markdown(
    f"""
    <div style="padding:14px 18px;border-radius:14px;
                background: linear-gradient(90deg,{H8_SECOND}, {H8_ORANGE});
                color:{H8_BLACK}; font-weight:700; font-size:24px;">
        🦊 Hacktiv8 – EduMentor (Final Project)
    </div>
    """,
    unsafe_allow_html=True,
)

with st.sidebar:
    st.subheader("API & Settings")
    api_key = st.text_input("Google AI API Key", type="password")
    temperature = st.slider("Kreativitas (temperature)", 0.0, 1.0, 0.3, 0.05)
    model_id = st.selectbox("Model", ["gemini-1.5-flash", "gemini-1.5-flash-8b"], index=0)
    style = st.selectbox("Gaya asisten", ["Semi-formal", "Santai", "Formal"], index=0)
    domain = st.text_input("Domain topik (opsional)", value="edukasi umum")
    st.caption("Tip: kunci API hanya tersimpan di session.")
    st.divider()
    if st.button("Reset sesi"):
        for k in ("messages", "kb_text", "quiz", "quiz_answers"):
            st.session_state.pop(k, None)
        st.rerun()

# init session states
st.session_state.setdefault("messages", [])
st.session_state.setdefault("kb_text", "")
st.session_state.setdefault("quiz", [])
st.session_state.setdefault("quiz_answers", {})

tab_chat, tab_quiz, tab_export = st.tabs(["💬 Chat", "📝 Quiz", "📦 Export"])

# ---------- CHAT ----------
with tab_chat:
    st.subheader("Conversational Tutor")

    # KB area
    st.markdown("**Knowledge Base (opsional)** – unggah .txt/.md/.pdf atau paste materi:")
    files = st.file_uploader(
        "Drop file di sini", type=["txt", "md", "pdf"],
        accept_multiple_files=True, label_visibility="collapsed"
    )
    pasted = st.text_area("Paste materi (opsional)", height=140, placeholder="Tempel ringkasan/notes di sini…")

    if st.button("Index ke KB"):
        st.session_state.kb_text = build_kb_text(files, pasted)
        if st.session_state.kb_text:
            st.success(f"KB siap. Panjang konteks: {len(st.session_state.kb_text):,} karakter.")
        else:
            st.info("Belum ada teks yang bisa diindeks.")

    # tampilkan history
    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["text"])

    placeholder = "Tanya apa saja… (gunakan KB bila sudah di-index)"
    user_input = st.chat_input(placeholder=placeholder)

    if user_input:
        st.session_state.messages.append({"role": "user", "text": user_input})
        with st.chat_message("user"):
            st.markdown(user_input)

        if not api_key:
            with st.chat_message("assistant"):
                st.error("Masukkan API key di sidebar dulu.")
        else:
            client = get_client(api_key)

            kb = st.session_state.kb_text
            kb_note = f"(KB aktif, {len(kb):,} chars)" if kb else "(KB kosong)"

            system = (
                f"Peran Anda adalah tutor {domain}. Jawab ringkas, jelas, dan edukatif "
                f"dalam Bahasa Indonesia gaya {style.lower()}.\n"
                "Jika konteks KB tersedia, jadikan rujukan utama. Jika tidak relevan, jawab tetap singkat "
                "tanpa mengarang fakta. Tambahkan satu baris *Sumber: KB* atau *Sumber: Umum* di akhir."
            )
            user = f"{kb_note}\n\nKONTEKS KB:\n{kb}\n\nPERTANYAAN PENGGUNA:\n{user_input}"

            with st.chat_message("assistant"):
                with st.spinner("Sedang berpikir…"):
                    answer = ask_model(client, model_id, system, user, temperature)
                st.markdown(answer)
            st.session_state.messages.append({"role": "assistant", "text": answer})

# ---------- QUIZ ----------
with tab_quiz:
    st.subheader("Buat Kuis dari KB")
    if not api_key:
        st.info("Masukkan API key di sidebar dulu.")
    elif not st.session_state.kb_text:
        st.info("Index materi ke KB dulu di tab Chat.")
    else:
        col_a, col_b = st.columns([1, 3])
        with col_a:
            if st.button("Generate 5 soal MCQ"):
                client = get_client(api_key)
                with st.spinner("Membuat soal…"):
                    st.session_state.quiz = gen_mcq(client, model_id, st.session_state.kb_text, n=5)
                    st.session_state.quiz_answers = {}
                if st.session_state.quiz:
                    st.success("Soal siap. Jawab di bawah ini.")
                else:
                    st.error("Gagal membuat soal. Coba lagi (atau materi terlalu pendek).")

        quiz = st.session_state.quiz
        if quiz:
            st.divider()
            for i, item in enumerate(quiz, start=1):
                st.markdown(f"**{i}. {item['q']}**")
                key = f"mcq_{i}"
                st.session_state.quiz_answers[key] = st.radio(
                    "Pilih jawaban:", item["a"], key=key, index=None, label_visibility="collapsed"
                )

            if st.button("Kumpulkan Jawaban"):
                rows = []
                benar = 0
                for i, item in enumerate(quiz, start=1):
                    key = f"mcq_{i}"
                    user_ans = st.session_state.quiz_answers.get(key)
                    correct = item["a"][item["key"]]
                    ok = user_ans == correct
                    benar += 1 if ok else 0
                    rows.append({"no": i, "question": item["q"], "answer": user_ans or "", "correct": correct, "is_correct": ok})
                score = int(100 * benar / len(quiz))
                st.success(f"Skor kamu: **{score}**")
                st.json(rows)
                # simpan untuk export
                st.session_state["last_quiz_result"] = {"score": score, "rows": rows, "created_at": dt.datetime.now().isoformat()}

# ---------- EXPORT ----------
with tab_export:
    st.subheader("Export / Import")
    # export chat CSV
    chat_rows = [
        {"ts": dt.datetime.now().isoformat(), "role": m["role"], "text": m["text"]}
        for m in st.session_state.messages
    ]
    chat_csv = make_csv_bytes(chat_rows)
    st.download_button("⬇️ Download Chat CSV", data=chat_csv, file_name="chat_history.csv", mime="text/csv", disabled=(len(chat_rows) == 0))

    # export quiz result CSV (jika ada)
    if "last_quiz_result" in st.session_state:
        qr = st.session_state["last_quiz_result"]
        rows = [{"no": r["no"], "question": r["question"], "user_answer": r["answer"], "correct": r["correct"], "is_correct": r["is_correct"]} for r in qr["rows"]]
        quiz_csv = make_csv_bytes(rows)
        st.download_button("⬇️ Download Quiz CSV", data=quiz_csv, file_name="quiz_result.csv", mime="text/csv")

    # export memory + KB ke JSON
    dump = {
        "messages": st.session_state.messages,
        "kb_text": st.session_state.kb_text,
        "last_quiz_result": st.session_state.get("last_quiz_result"),
    }
    json_bytes = json.dumps(dump, ensure_ascii=False, indent=2).encode("utf-8")
    st.download_button("⬇️ Download Memory+KB (JSON)", data=json_bytes, file_name="memory_kb.json", mime="application/json")

    # import JSON
    up = st.file_uploader("Import Memory+KB (JSON)", type=["json"], key="import_json")
    if up:
        try:
            data = json.loads(up.read().decode("utf-8"))
            st.session_state.messages = data.get("messages", [])
            st.session_state.kb_text = data.get("kb_text", "")
            if data.get("last_quiz_result"):
                st.session_state["last_quiz_result"] = data["last_quiz_result"]
            st.success("Berhasil di-import. Buka tab Chat/Quiz untuk melihat hasilnya.")
        except Exception as e:
            st.error(f"Gagal import JSON: {e}")

st.caption("© Hacktiv8 – Final Project Demo")
