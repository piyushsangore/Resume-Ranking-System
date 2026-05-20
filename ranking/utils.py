# ranking/utils.py
import re
import io
import csv

# Try to import sklearn TF-IDF + cosine_similarity; if unavailable, we'll use a fallback.
_use_sklearn = True
try:
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics.pairwise import cosine_similarity
except Exception:
    _use_sklearn = False

# Use pymupdf (fitz) for text extraction if available; otherwise decode bytes.
def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """
    Extract text from PDF bytes. Returns a string (may be empty).
    """
    if not pdf_bytes:
        return ""
    try:
        import fitz  # pymupdf
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for p in doc:
            parts.append(p.get_text())
        text = "\n".join(parts)
        return text
    except Exception:
        try:
            return bytes(pdf_bytes).decode("utf-8", errors="ignore")
        except Exception:
            return ""

def merge_resume_fields_for_similarity(resume_doc: dict) -> str:
    """
    Merge relevant resume fields into one text blob for JD-resume similarity:
    - SKILLS, WORKED_AS / WORKED AS, CERTIFICATIONS, SUMMARY, EDUCATION, ResumeData (if present).
    Normalizes whitespace and returns a cleaned string.
    """
    parts = []
    # accept multiple possible key names
    keys = [
        "SKILLS", "Skills", "skills",
        "WORKED_AS", "WORKED AS", "Worked As", "worked as",
        "CERTIFICATIONS", "CERTIFICATION", "Certifications",
        "SUMMARY", "Summary", "summary",
        "EDUCATION", "Education", "education",
        "ResumeData", "ResumeDataText", "Resume_Data", "ResumeData", "Resume"
    ]
    seen = set()
    for key in keys:
        val = resume_doc.get(key)
        if not val:
            continue
        if isinstance(val, list):
            txt = " ".join([str(x) for x in val if x])
        else:
            txt = str(val)
        txt = txt.strip()
        if txt and txt.lower() not in seen:
            parts.append(txt)
            seen.add(txt.lower())
    # Also include any plain-text field 'FileData' decoded summary if present
    fd = resume_doc.get("FileData")
    if fd:
        try:
            raw = bytes(fd)
            txt = extract_text_from_pdf_bytes(raw)
            if txt:
                parts.append(txt)
        except Exception:
            pass

    merged = " ".join(parts)
    merged = re.sub(r'\s+', ' ', merged).strip()
    return merged

def _simple_token_overlap_sim(t1: str, t2: str) -> float:
    """
    Very simple similarity fallback: token overlap ratio (0.0-1.0)
    """
    if not t1 or not t2:
        return 0.0
    a = set(re.findall(r'\w+', t1.lower()))
    b = set(re.findall(r'\w+', t2.lower()))
    if not a or not b:
        return 0.0
    inter = a.intersection(b)
    union = a.union(b)
    # return Jaccard-like score
    try:
        return float(len(inter)) / float(len(union))
    except Exception:
        return 0.0

def compute_cosine_similarity(text1: str, text2: str) -> float:
    """
    Compute cosine similarity between two texts (0.0 - 1.0).
    Uses TF-IDF if sklearn available, otherwise a fallback token-overlap score.
    """
    if not text1:
        text1 = ""
    if not text2:
        text2 = ""
    try:
        if _use_sklearn:
            vect = TfidfVectorizer(max_features=2000, stop_words="english")
            tfidf = vect.fit_transform([text1, text2])
            sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
            if sim != sim:  # NaN guard
                return 0.0
            return float(sim)
        else:
            # fallback
            return float(_simple_token_overlap_sim(text1, text2))
    except Exception:
        try:
            return float(_simple_token_overlap_sim(text1, text2))
        except Exception:
            return 0.0

def export_rankings_to_csv(rankings):
    """
    rankings: list of dicts with keys:
      user_id, name, email, final_score, skill_points, exp_points, cert_points, cgpa_points, eq_points
    Returns bytes of CSV (utf-8).
    """
    output = io.StringIO()
    writer = csv.writer(output)
    header = ["rank", "user_id", "name", "email", "final_score", "skill_points", "exp_points", "cert_points", "cgpa_points", "eq_points"]
    writer.writerow(header)
    for i, r in enumerate(rankings, start=1):
        writer.writerow([
            i,
            r.get("user_id", ""),
            r.get("name", ""),
            r.get("email", ""),
            r.get("final_score", ""),
            r.get("skill_points", ""),
            r.get("exp_points", ""),
            r.get("cert_points", ""),
            r.get("cgpa_points", ""),
            r.get("eq_points", "")
        ])
    return output.getvalue().encode("utf-8")







# # ranking/utils.py
# import re
# import io
# import csv
# from typing import Tuple, List
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.metrics.pairwise import cosine_similarity

# # Use pymupdf (fitz) for text extraction
# def extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
#     try:
#         import fitz
#         doc = fitz.open(stream=pdf_bytes, filetype="pdf")
#         parts = []
#         for p in doc:
#             parts.append(p.get_text())
#         return "\n".join(parts)
#     except Exception:
#         try:
#             return bytes(pdf_bytes).decode("utf-8", errors="ignore")
#         except Exception:
#             return ""

# def merge_resume_fields_for_similarity(resume_doc: dict) -> str:
#     """
#     Merge relevant resume fields into one text blob for JD-resume similarity:
#     - SKILLS, WORKED_AS, CERTIFICATIONS, SUMMARY, EDUCATION, ResumeData (if present).
#     """
#     parts = []
#     for key in ("SKILLS", "WORKED_AS", "CERTIFICATIONS", "SUMMARY", "EDUCATION", "ResumeData"):
#         val = resume_doc.get(key)
#         if isinstance(val, list):
#             parts.append(" ".join([str(x) for x in val]))
#         elif val:
#             parts.append(str(val))
#     merged = " ".join(parts)
#     # simple cleanup
#     merged = re.sub(r'\s+', ' ', merged).strip()
#     return merged

# def compute_cosine_similarity(text1: str, text2: str) -> float:
#     """
#     Compute cosine similarity between two texts (0.0 - 1.0).
#     Uses TF-IDF vectorizer with simple tokenization.
#     """
#     if not text1: text1 = ""
#     if not text2: text2 = ""
#     try:
#         vect = TfidfVectorizer(max_features=2000, stop_words="english")
#         tfidf = vect.fit_transform([text1, text2])
#         sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
#         if sim != sim:  # NaN guard
#             return 0.0
#         return float(sim)
#     except Exception:
#         return 0.0

# def export_rankings_to_csv(rankings: List[dict]) -> bytes:
#     """
#     rankings: list of dicts with keys: user_id, name(optional), email(optional), final_score, skill_points, exp_points, cert_points, cgpa_points, eq_points
#     Returns bytes (utf-8) of CSV.
#     """
#     output = io.StringIO()
#     writer = csv.writer(output)
#     header = ["user_id", "name", "email", "final_score", "skill_points", "exp_points", "cert_points", "cgpa_points", "eq_points"]
#     writer.writerow(header)
#     for r in rankings:
#         row = [
#             r.get("user_id"),
#             r.get("name", ""),
#             r.get("email", ""),
#             r.get("final_score", 0.0),
#             r.get("skill_points", 0.0),
#             r.get("exp_points", 0.0),
#             r.get("cert_points", 0.0),
#             r.get("cgpa_points", 0.0),
#             r.get("eq_points", 0.0)
#         ]
#         writer.writerow(row)
#     return output.getvalue().encode("utf-8")


















# # ranking/utils.py
# import fitz
# import re
# import csv
# import tempfile
# from sklearn.feature_extraction.text import TfidfVectorizer
# from sklearn.metrics.pairwise import cosine_similarity

# def extract_text_from_pdf_bytes(pdf_bytes):
#     if not pdf_bytes:
#         return ""
#     try:
#         data = pdf_bytes if isinstance(pdf_bytes, (bytes,bytearray)) else bytes(pdf_bytes)
#         doc = fitz.open(stream=data, filetype="pdf")
#         text = ""
#         for p in doc:
#             text += p.get_text()
#         return text
#     except Exception:
#         try:
#             return str(pdf_bytes)
#         except:
#             return ""

# def merge_resume_fields_for_similarity(parsed_resume):
#     parts=[]
#     if not parsed_resume:
#         return ""
#     def get_one(*keys):
#         for k in keys:
#             v = parsed_resume.get(k)
#             if v:
#                 return v
#         return None
#     skills = get_one("SKILLS","skills")
#     if skills:
#         if isinstance(skills,(list,tuple)): parts.append(" ".join(map(str,skills)))
#         else: parts.append(str(skills))
#     summary = get_one("SUMMARY","summary")
#     if summary: parts.append(str(summary))
#     exp = get_one("WORKED_AS","EXPERIENCE","experience")
#     if exp:
#         if isinstance(exp,(list,tuple)): parts.append(" ".join(map(str,exp)))
#         else: parts.append(str(exp))
#     projects = get_one("PROJECTS","projects")
#     if projects:
#         if isinstance(projects,(list,tuple)): parts.append(" ".join(map(str,projects)))
#         else: parts.append(str(projects))
#     certs = get_one("CERTIFICATIONS","certifications")
#     if certs:
#         if isinstance(certs,(list,tuple)): parts.append(" ".join(map(str,certs)))
#         else: parts.append(str(certs))
#     edu = get_one("EDUCATION","education")
#     if edu: parts.append(str(edu))
#     return " \n ".join([p for p in parts if p])

# def compute_cosine_similarity(text1, text2):
#     if not text1 or not text2:
#         return 0.0
#     try:
#         vectorizer = TfidfVectorizer(stop_words="english", max_features=5000)
#         tfidf = vectorizer.fit_transform([text1, text2])
#         sim = cosine_similarity(tfidf[0:1], tfidf[1:2])[0][0]
#         return float(max(0.0, min(1.0, sim)))
#     except Exception:
#         s1 = set(re.findall(r"\w+", text1.lower()))
#         s2 = set(re.findall(r"\w+", text2.lower()))
#         if not s1 or not s2: return 0.0
#         return float(len(s1 & s2) / len(s1 | s2))

# def export_rankings_to_csv(rankings_list, filename=None):
#     if filename is None:
#         tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv")
#         filename = tmp.name
#         tmp.close()
#     with open(filename, "w", newline="", encoding="utf-8") as f:
#         w = csv.writer(f)
#         w.writerow(["Rank","Candidate Name","Email","Total Score","Skills Points","Experience Points","Certifications Points","CGPA Points","Equivalence Points","User ID"])
#         for idx, r in enumerate(rankings_list, start=1):
#             pb = r.get("points_breakdown",{})
#             w.writerow([idx, r.get("candidate_name",""), r.get("email",""), r.get("total_score",0),
#                         pb.get("skills",0), pb.get("experience",0), pb.get("certifications",0),
#                         pb.get("cgpa",0), pb.get("equivalence",0), str(r.get("user_id",""))])
#     return filename
