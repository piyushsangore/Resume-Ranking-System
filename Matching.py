# Matching.py
"""
Resume parsing adapter and light matching.

- Lazy loads your heavy spaCy resume model (so Flask imports don't crash if transformer
  components are missing).
- Provides parse_resume_bytes(pdf_bytes) -> dict with SKILLS, WORKED_AS, CERTIFICATIONS, PROJECTS, SUMMARY, EDUCATION
- Provides Matching() as a simplified job->resume ranking (returns list/dict or score depending on usage).
"""

import os, re, traceback
from bson.objectid import ObjectId

# Change this path to where your heavy resume model is placed.
RESUME_MODEL_PATH = os.getenv("RESUME_MODEL_PATH", r"assets/ResumeModel/output/model-best")

# Try to import optional MediaWiki helper (if present). If not present, we provide a stub.
try:
    from MediaWiki import get_search_results
except Exception:
    def get_search_results(q):
        return None

# DB placeholders: expecting core.database.db to be available at runtime
resumeFetchedData = None
JOBS = None
try:
    from core.database import db as core_db
    if core_db:
        resumeFetchedData = core_db.resumeFetchedData
        JOBS = core_db.JOBS
except Exception:
    resumeFetchedData = None
    JOBS = None

# Lazy spaCy model
_resume_nlp = None
_resume_nlp_loaded = False
_resume_nlp_error = None

def _try_load_resume_model():
    global _resume_nlp, _resume_nlp_loaded, _resume_nlp_error
    if _resume_nlp_loaded:
        return _resume_nlp is not None
    _resume_nlp_loaded = True
    _resume_nlp = None
    _resume_nlp_error = None
    try:
        import spacy
    except Exception as e:
        _resume_nlp_error = f"spaCy import failed: {e}"
        print("[Matching] spaCy import failed:", _resume_nlp_error)
        return False
    try:
        _resume_nlp = spacy.load(RESUME_MODEL_PATH)
        print("[Matching] Resume spaCy model loaded from:", RESUME_MODEL_PATH)
        return True
    except Exception as e:
        _resume_nlp_error = repr(e)
        print("[Matching] Could not load resume model:", _resume_nlp_error)
        if "Can't find factory for 'transformer'" in str(e) or "transformer" in str(e).lower():
            print("[Matching] Model uses transformer. Install spacy-transformers / transformers / torch (see README).")
        return False

# PDF-to-text extraction using pymupdf (fitz)
def _extract_text_from_pdf_bytes(pdf_bytes):
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        parts = []
        for p in doc:
            parts.append(p.get_text())
        return "\n".join(parts)
    except Exception:
        try:
            return bytes(pdf_bytes).decode("utf-8", errors="ignore")
        except Exception:
            return ""

def _heuristic_extract_skills(text, max_skills=50):
    if not text:
        return []
    parts = re.split(r'\n|,|/|;|•|·|-|—', text)
    skills = []
    seen = set()
    for p in parts:
        s = p.strip()
        if not s or len(s) < 2: continue
        if len(s.split()) > 6: continue
        low = s.lower()
        if low in ("experience", "education", "projects", "certifications", "summary", "skills", "work"): continue
        if low in seen: continue
        seen.add(low)
        skills.append(s)
        if len(skills) >= max_skills: break
    return skills

def _heuristic_extract_experience(text, max_items=10):
    if not text: return []
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    exps = []
    for l in lines:
        if re.search(r'(\d+(\.\d+)?\s*(years?|yrs?|year|yr|months?|mo))', l, re.I) or re.search(r'experience', l, re.I):
            exps.append(l)
        if len(exps) >= max_items: break
    return exps

def _heuristic_extract_certifications(text, max_items=10):
    if not text: return []
    m = re.search(r'(certificat|certification|certified|certificate)(.*)', text, re.I|re.S)
    certs = []
    if m:
        rest = m.group(2)
        parts = re.split(r'\n|,|;|/|•', rest)
        for p in parts:
            p = p.strip()
            if len(p) > 3:
                certs.append(p)
            if len(certs) >= max_items: break
    if not certs:
        for token in ["AWS", "Azure", "GCP", "PMP", "Oracle", "Cisco", "CCNA", "CCNP", "Google Certified", "Microsoft Certified"]:
            if token.lower() in text.lower():
                certs.append(token)
                if len(certs) >= max_items: break
    return certs

def parse_resume_bytes(pdf_bytes: bytes) -> dict:
    """Unified parse function expected by app."""
    parsed = {"SKILLS": [], "WORKED_AS": [], "CERTIFICATIONS": [], "PROJECTS": [], "SUMMARY": "", "EDUCATION": ""}

    text = _extract_text_from_pdf_bytes(pdf_bytes)
    if not text:
        return parsed

    ok = _try_load_resume_model()
    if ok and _resume_nlp is not None:
        try:
            doc = _resume_nlp(text)
            skills = []
            certs = []
            edu = []
            exps = []
            for ent in getattr(doc, "ents", []):
                lbl = getattr(ent, "label_", "").upper()
                val = ent.text.strip()
                if not val: continue
                if lbl in ("SKILL", "SKILLS", "TECH", "TOOLS", "LANGUAGE", "TECHNOLOGY"):
                    if val.lower() not in [s.lower() for s in skills]:
                        skills.append(val)
                elif lbl in ("CERT", "CERTIFICATION", "CERTIFICATIONS"):
                    if val.lower() not in [c.lower() for c in certs]:
                        certs.append(val)
                elif lbl in ("EDUCATION", "DEGREE", "SCHOOL", "UNIVERSITY"):
                    edu.append(val)
                elif lbl in ("EXPERIENCE", "YEARS", "WORK"):
                    exps.append(val)
            if skills: parsed["SKILLS"] = skills[:50]
            if certs: parsed["CERTIFICATIONS"] = certs[:10]
            if edu: parsed["EDUCATION"] = " ; ".join(edu)[:500]
            if exps: parsed["WORKED_AS"] = exps[:10]
            parsed["SUMMARY"] = " ".join(text.splitlines()[:6])
            # fallback to heuristics for missing
            if not parsed["SKILLS"]:
                parsed["SKILLS"] = _heuristic_extract_skills(text, 50)
            if not parsed["WORKED_AS"]:
                parsed["WORKED_AS"] = _heuristic_extract_experience(text, 10)
            if not parsed["CERTIFICATIONS"]:
                parsed["CERTIFICATIONS"] = _heuristic_extract_certifications(text, 10)
            if not parsed["EDUCATION"]:
                m = re.search(r'(education[:\-\s]*)(.*?)(experience|skills|projects|certificat|$)', text, re.I|re.S)
                if m:
                    parsed["EDUCATION"] = " ".join(m.group(2).splitlines())[:500]
            return parsed
        except Exception as e:
            print("[Matching] Model parse failed; falling back to heuristics:", repr(e))
            traceback.print_exc()

    # heuristics fallback
    parsed["SKILLS"] = _heuristic_extract_skills(text, 50)
    parsed["WORKED_AS"] = _heuristic_extract_experience(text, 10)
    parsed["CERTIFICATIONS"] = _heuristic_extract_certifications(text, 10)
    parsed["SUMMARY"] = (text[:800] + "...") if len(text) > 800 else text
    try:
        m = re.search(r'(education[:\-\s]*)(.*?)(experience|skills|projects|certificat|$)', text, re.I|re.S)
        if m:
            parsed["EDUCATION"] = " ".join(m.group(2).splitlines())[:500]
    except Exception:
        parsed["EDUCATION"] = ""
    return parsed

def Matching():
    """
    Optional lightweight matching implementation — returns list of results for a job id POSTed via request.form['job_id'].
    This is a safe fallback if the original repo matching is not usable.
    """
    try:
        from flask import request
        job_id = request.form.get("job_id")
        if not job_id:
            return []
        if not JOBS or not resumeFetchedData:
            print("[Matching] DB not configured.")
            return []
        try:
            job_obj = JOBS.find_one({"_id": ObjectId(job_id)})
        except Exception:
            job_obj = JOBS.find_one({"_id": job_id})
        if not job_obj:
            return []
        jd_text = job_obj.get("Job_Description") or ""
        if not jd_text and job_obj.get("FileData"):
            jd_text = _extract_text_from_pdf_bytes(bytes(job_obj.get("FileData")))
        # create simple token set
        jd_tokens = set(re.findall(r"\b[A-Za-z0-9\+\#\.\-]{2,20}\b", jd_text.lower()))
        results = []
        for r in resumeFetchedData.find({}):
            skills = [s.lower() for s in (r.get("SKILLS") or [])]
            inter = set(skills).intersection(jd_tokens)
            skill_percent = (len(inter) / max(1, len(jd_tokens))) * 50.0 if jd_tokens else 0.0
            cgpa_val = float(r.get("CGPA", 0)) if r.get("CGPA") else 0.0
            cgpa_score = min(25.0, cgpa_val * 2.5)
            exp_score = 0.0
            exp_list = r.get("YEARS OF EXPERIENCE") or []
            if exp_list:
                nm = re.findall(r"(\d+(\.\d+)?)", " ".join(exp_list))
                if nm:
                    years = float(nm[0][0])
                    exp_score = min(25.0, (years / 5.0) * 25.0)
            total = round(skill_percent + cgpa_score + exp_score, 2)
            results.append({"user_id": r.get("UserId"), "score": total, "skill_points": round(skill_percent,2), "cgpa_points": round(cgpa_score,2), "exp_points": round(exp_score,2)})
        return sorted(results, key=lambda x: x["score"], reverse=True)
    except Exception as e:
        print("[Matching] error:", e)
        traceback.print_exc()
        return []
































# # Matching.py (improved & robust)
# import spacy, fitz, io
# from flask import session, request
# from bson.objectid import ObjectId
# from MediaWiki import get_search_results
# from datetime import datetime
# import re
# import tempfile

# # Use Atlas DB from core.database.db
# resumeFetchedData = None
# JOBS = None
# try:
#     from core.database import db as core_db
#     if core_db:
#         resumeFetchedData = core_db.resumeFetchedData
#         JOBS = core_db.JOBS
# except Exception:
#     resumeFetchedData = None
#     JOBS = None

# print("Loading Jd Parser model...")
# try:
#     jd_model = spacy.load('assets/JdModel/output/model-best')
#     print("Jd Parser model loaded")
# except Exception as e:
#     jd_model = None
#     print("Warning: could not load JD spaCy model:", repr(e))

# def _extract_text_from_job_doc(job_doc):
#     if not job_doc:
#         return ""
#     # Prefer Job_Description text field if present and non-empty
#     jd_text_field = job_doc.get("Job_Description")
#     if jd_text_field and isinstance(jd_text_field, str) and jd_text_field.strip():
#         return jd_text_field

#     # Try binary FileData (may be PDF or text)
#     jd_data = job_doc.get("FileData")
#     if jd_data:
#         try:
#             raw = bytes(jd_data)
#             # try open as pdf
#             try:
#                 doc = fitz.open(stream=raw, filetype="pdf")
#             except Exception:
#                 doc = fitz.open(stream=raw)
#             txt = ""
#             for p in doc:
#                 txt += p.get_text()
#             if txt.strip():
#                 return " ".join(txt.splitlines())
#         except Exception:
#             # fallback: try decode as utf-8
#             try:
#                 txt = raw.decode('utf-8', errors='ignore')
#                 if txt.strip():
#                     return " ".join(txt.splitlines())
#             except Exception:
#                 return ""
#     return ""

# def _parse_experience_list(exp_list):
#     if not exp_list:
#         return []
#     parsed = []
#     for p in exp_list:
#         if not isinstance(p, str): continue
#         s = p.lower().replace(",", "")
#         nums = [float(t) for t in s.split() if t.replace('.','',1).isdigit()]
#         if not nums: continue
#         # heuristic: first number is years, if 'month' present convert
#         if 'month' in s and ('year' not in s):
#             parsed.append(round(nums[0]/12.0, 2))
#         elif 'month' in s and 'year' in s and len(nums) >= 2:
#             parsed.append(round(nums[0] + nums[1]/12.0, 2))
#         else:
#             parsed.append(round(nums[0], 2))
#     return parsed

# def Matching():
#     try:
#         job_id = request.form.get('job_id')
#         if not job_id:
#             print("Matching: missing job_id")
#             return 0.0
#         try:
#             job_obj = JOBS.find_one({"_id": ObjectId(job_id)})
#         except Exception:
#             job_obj = JOBS.find_one({"_id": job_id})
#         if not job_obj:
#             print("Matching: job not found")
#             return 0.0

#         # Extract JD text robustly
#         text_of_jd = _extract_text_from_job_doc(job_obj)
#         print("text_of_jd (preview):", text_of_jd[:200])

#         # Run NER on JD if model available
#         jd_entities = {}
#         if jd_model and text_of_jd.strip():
#             try:
#                 doc_jd = jd_model(text_of_jd)
#                 for ent in doc_jd.ents:
#                     jd_entities.setdefault(ent.label_, []).append(ent.text)
#             except Exception as e:
#                 print("NER failed on JD:", e)

#         # Fallbacks
#         jd_post = jd_entities.get('JOBPOST') or [job_obj.get('Job_Profile', '')]
#         job_description_skills = jd_entities.get('SKILLS') or []
#         jd_experience_list = jd_entities.get('EXPERIENCE') or []

#         # Resume fields
#         try:
#             user_objid = ObjectId(session.get('user_id'))
#         except:
#             user_objid = session.get('user_id')
#         resume_doc = resumeFetchedData.find_one({"UserId": user_objid}) or {}
#         resume_workedAs = resume_doc.get("WORKED AS") or []
#         resume_experience_list = resume_doc.get("YEARS OF EXPERIENCE") or []
#         resume_skills = resume_doc.get("SKILLS") or []

#         print("resume_workedAs:", resume_workedAs)
#         print("resume_experience_list:", resume_experience_list)
#         print("resume_skills:", resume_skills)
#         print("jd_post:", jd_post)
#         print("job_description_skills:", job_description_skills)

#         # compute experience numbers
#         resume_experience = _parse_experience_list(resume_experience_list)
#         jd_experience = _parse_experience_list(jd_experience_list)

#         # ---- jdpost similarity (title match) ----
#         jd_post_lower = [s.lower() for s in jd_post if isinstance(s, str)]
#         jdpost_similarity = 0.0
#         experience_similarity = 0.0
#         if resume_workedAs and jd_post_lower:
#             resume_worked_lower = [s.lower() for s in resume_workedAs if isinstance(s, str)]
#             matched = False
#             for i, item in enumerate(resume_worked_lower):
#                 if item in jd_post_lower:
#                     matched = True
#                     # try experience comparison
#                     if resume_experience and jd_experience:
#                         try:
#                             diff = jd_experience[0] - (resume_experience[i] if i < len(resume_experience) else resume_experience[0])
#                             if diff <= 0: experience_similarity = 1.0
#                             elif diff <= 1: experience_similarity = 0.7
#                             else: experience_similarity = 0.0
#                         except:
#                             experience_similarity = 0.0
#                     break
#             jdpost_similarity = 1.0 if matched else 0.0

#         jdpost_similarity *= 0.3
#         experience_similarity *= 0.2

#         # ---- skills similarity (try MediaWiki expansion first, else simple intersection) ----
#         skills_similarity = 0.0
#         if job_description_skills:
#             # try expansion for resume skills
#             expanded_resume_skills = []
#             for s in resume_skills:
#                 try:
#                     res = get_search_results(f"{s} in technology")
#                     if res:
#                         if isinstance(res, str): expanded_resume_skills.append(res)
#                         else:
#                             # join list results to string for easier substring check
#                             expanded_resume_skills.append(" ".join([str(x) for x in res]))
#                 except Exception:
#                     continue
#             # count matches by substring (robust)
#             count = 0
#             for jskill in job_description_skills:
#                 for rskills_text in expanded_resume_skills:
#                     if isinstance(rskills_text, str) and jskill.lower() in rskills_text.lower():
#                         count += 1
#                         break
#             # fallback: direct set intersection (lowercased tokens)
#             if count == 0:
#                 s_jd = set([x.lower() for x in job_description_skills if isinstance(x, str)])
#                 s_res = set([x.lower() for x in resume_skills if isinstance(x, str)])
#                 if s_jd and s_res:
#                     inter = s_jd.intersection(s_res)
#                     count = len(inter)
#             try:
#                 skills_similarity = 1 - ((len(job_description_skills) - count) / len(job_description_skills))
#                 skills_similarity = max(0.0, skills_similarity) * 0.5
#             except Exception:
#                 skills_similarity = 0.0
#         else:
#             # if JD skills missing, try match resume_skills against JD text keywords
#             if resume_skills and text_of_jd:
#                 s_res = set([x.lower() for x in resume_skills if isinstance(x, str)])
#                 cnt = sum(1 for w in s_res if w in text_of_jd.lower())
#                 skills_similarity = (cnt / len(s_res)) * 0.5 if s_res else 0.0
#             else:
#                 skills_similarity = 0.0

#         matching = round((jdpost_similarity + experience_similarity + skills_similarity) * 100.0, 2)
#         print(f"[Matching] score={matching} (jdpost={jdpost_similarity}, exp={experience_similarity}, skills={skills_similarity})")
#         return matching

#     except Exception as e:
#         print("Matching() error:", repr(e))
#         return 0.0

# # ------------------------
# # Resume parser adapter for app compatibility
# # ------------------------

# from ranking.utils import extract_text_from_pdf_bytes  # uses pymupdf
# try:
#     import spacy as _spacy
# except Exception:
#     _spacy = None

# def _heuristic_extract_skills(text, max_skills=50):
#     if not text:
#         return []
#     parts = re.split(r'\n|,|/|;|•|•| - | — ', text)
#     skills = []
#     seen = set()
#     for p in parts:
#         s = p.strip()
#         if not s or len(s) < 2:
#             continue
#         if len(s.split()) > 6:
#             continue
#         low = s.lower()
#         if low in ("experience", "education", "projects", "certifications", "summary", "skills", "work"):
#             continue
#         if low in seen:
#             continue
#         seen.add(low)
#         skills.append(s)
#         if len(skills) >= max_skills:
#             break
#     return skills

# def _heuristic_extract_experience(text, max_items=10):
#     if not text:
#         return []
#     lines = [l.strip() for l in text.splitlines() if l.strip()]
#     exps = []
#     for l in lines:
#         if re.search(r'(\d+(\.\d+)?\s*(years?|yrs?|year|yr|months?|mo))', l, re.I) or re.search(r'experience', l, re.I):
#             exps.append(l)
#         if len(exps) >= max_items:
#             break
#     return exps

# def _heuristic_extract_certifications(text, max_items=10):
#     if not text:
#         return []
#     m = re.search(r'(certificat|certification|certified|certificate)(.*)', text, re.I|re.S)
#     certs = []
#     if m:
#         rest = m.group(2)
#         parts = re.split(r'\n|,|;|/|•', rest)
#         for p in parts:
#             p = p.strip()
#             if len(p) > 3:
#                 certs.append(p)
#             if len(certs) >= max_items:
#                 break
#     if not certs:
#         for token in ["AWS", "Azure", "GCP", "PMP", "Oracle", "Cisco", "CCNA", "CCNP", "Google Certified", "Microsoft Certified"]:
#             if token.lower() in text.lower():
#                 certs.append(token)
#                 if len(certs) >= max_items:
#                     break
#     return certs

# def parse_resume_bytes(pdf_bytes):
#     """
#     Unified parse function expected by the app.
#     Returns a dict with keys:
#       SKILLS (list), WORKED_AS (list), CERTIFICATIONS (list), PROJECTS (list), SUMMARY (string), EDUCATION (string)
#     """
#     # If Matching.py already had a different parser exposed (unlikely here), prefer it:
#     try:
#         existing = globals().get("parse_resume_bytes")
#         if existing and existing is not parse_resume_bytes:
#             return existing(pdf_bytes)
#     except Exception:
#         pass

#     # Extract text
#     text = ""
#     try:
#         text = extract_text_from_pdf_bytes(pdf_bytes)
#     except Exception:
#         try:
#             text = bytes(pdf_bytes).decode('utf-8', errors='ignore')
#         except Exception:
#             text = ""

#     parsed = {"SKILLS": [], "WORKED_AS": [], "CERTIFICATIONS": [], "PROJECTS": [], "SUMMARY": "", "EDUCATION": ""}

#     if not text:
#         return parsed

#     # Try spaCy if available
#     nlp = None
#     if _spacy is not None:
#         try:
#             try:
#                 nlp = _spacy.load("en_core_web_sm")
#             except Exception:
#                 if jd_model is not None:
#                     nlp = jd_model
#         except Exception:
#             nlp = None

#     if nlp:
#         try:
#             doc = nlp(text)
#             skills = []
#             certs = []
#             edu = []
#             exps = []
#             for ent in doc.ents:
#                 lbl = ent.label_.upper()
#                 val = ent.text.strip()
#                 if lbl in ("SKILL", "TECH", "TOOLS", "LANGUAGE", "NORP", "ORG"):
#                     if val.lower() not in [s.lower() for s in skills]:
#                         skills.append(val)
#                 if lbl in ("CERT", "CERTIFICATION"):
#                     if val.lower() not in [c.lower() for c in certs]:
#                         certs.append(val)
#                 if lbl in ("EDUCATION","DEGREE","SCHOOL"):
#                     edu.append(val)
#                 if lbl in ("EXPERIENCE","YEARS"):
#                     exps.append(val)
#             if skills:
#                 parsed["SKILLS"] = skills[:50]
#             if certs:
#                 parsed["CERTIFICATIONS"] = certs[:10]
#             if edu:
#                 parsed["EDUCATION"] = " ; ".join(edu)
#             if exps:
#                 parsed["WORKED_AS"] = exps[:10]
#             parsed["SUMMARY"] = " ".join(text.splitlines()[:6])
#             return parsed
#         except Exception:
#             pass

#     # Heuristic fallback
#     parsed["SKILLS"] = _heuristic_extract_skills(text, max_skills=50)
#     parsed["WORKED_AS"] = _heuristic_extract_experience(text, max_items=10)
#     parsed["CERTIFICATIONS"] = _heuristic_extract_certifications(text, max_items=10)
#     parsed["PROJECTS"] = []
#     parsed["SUMMARY"] = (text[:800] + "...") if len(text) > 800 else text
#     try:
#         m = re.search(r'(education[:\-\s]*)(.*?)(experience|skills|projects|certificat|$)', text, re.I|re.S)
#         if m:
#             edu_text = m.group(2)
#             parsed["EDUCATION"] = " ".join(edu_text.splitlines())[:500]
#     except Exception:
#         parsed["EDUCATION"] = ""
#     return parsed
