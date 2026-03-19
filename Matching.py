# Matching.py (improved & robust)
import spacy, fitz, io
from flask import session, request
from database import mongo
from bson.objectid import ObjectId
from MediaWiki import get_search_results
from datetime import datetime

resumeFetchedData = mongo.db.resumeFetchedData
JOBS = mongo.db.JOBS

print("Loading Jd Parser model...")
try:
    jd_model = spacy.load('assets/JdModel/output/model-best')
    print("Jd Parser model loaded")
except Exception as e:
    jd_model = None
    print("Warning: could not load JD spaCy model:", repr(e))

def _extract_text_from_job_doc(job_doc):
    if not job_doc:
        return ""
    # Prefer Job_Description text field if present and non-empty
    jd_text_field = job_doc.get("Job_Description")
    if jd_text_field and isinstance(jd_text_field, str) and jd_text_field.strip():
        return jd_text_field

    # Try binary FileData (may be PDF or text)
    jd_data = job_doc.get("FileData")
    if jd_data:
        try:
            raw = bytes(jd_data)
            # try open as pdf
            try:
                doc = fitz.open(stream=raw, filetype="pdf")
            except Exception:
                doc = fitz.open(stream=raw)
            txt = ""
            for p in doc:
                txt += p.get_text()
            if txt.strip():
                return " ".join(txt.splitlines())
        except Exception:
            # fallback: try decode as utf-8
            try:
                txt = raw.decode('utf-8', errors='ignore')
                if txt.strip():
                    return " ".join(txt.splitlines())
            except Exception:
                return ""
    return ""

def _parse_experience_list(exp_list):
    if not exp_list:
        return []
    parsed = []
    for p in exp_list:
        if not isinstance(p, str): continue
        s = p.lower().replace(",", "")
        nums = [float(t) for t in s.split() if t.replace('.','',1).isdigit()]
        if not nums: continue
        # heuristic: first number is years, if 'month' present convert
        if 'month' in s and ('year' not in s):
            parsed.append(round(nums[0]/12.0, 2))
        elif 'month' in s and 'year' in s and len(nums) >= 2:
            parsed.append(round(nums[0] + nums[1]/12.0, 2))
        else:
            parsed.append(round(nums[0], 2))
    return parsed

def Matching():
    try:
        job_id = request.form.get('job_id')
        if not job_id:
            print("Matching: missing job_id")
            return 0.0
        try:
            job_obj = JOBS.find_one({"_id": ObjectId(job_id)})
        except Exception:
            job_obj = JOBS.find_one({"_id": job_id})
        if not job_obj:
            print("Matching: job not found")
            return 0.0

        # Extract JD text robustly
        text_of_jd = _extract_text_from_job_doc(job_obj)
        print("text_of_jd (preview):", text_of_jd[:200])

        # Run NER on JD if model available
        jd_entities = {}
        if jd_model and text_of_jd.strip():
            try:
                doc_jd = jd_model(text_of_jd)
                for ent in doc_jd.ents:
                    jd_entities.setdefault(ent.label_, []).append(ent.text)
            except Exception as e:
                print("NER failed on JD:", e)

        # Fallbacks
        jd_post = jd_entities.get('JOBPOST') or [job_obj.get('Job_Profile', '')]
        job_description_skills = jd_entities.get('SKILLS') or []
        jd_experience_list = jd_entities.get('EXPERIENCE') or []

        # Resume fields
        try:
            user_objid = ObjectId(session.get('user_id'))
        except:
            user_objid = session.get('user_id')
        resume_doc = resumeFetchedData.find_one({"UserId": user_objid}) or {}
        resume_workedAs = resume_doc.get("WORKED AS") or []
        resume_experience_list = resume_doc.get("YEARS OF EXPERIENCE") or []
        resume_skills = resume_doc.get("SKILLS") or []

        print("resume_workedAs:", resume_workedAs)
        print("resume_experience_list:", resume_experience_list)
        print("resume_skills:", resume_skills)
        print("jd_post:", jd_post)
        print("job_description_skills:", job_description_skills)

        # compute experience numbers
        resume_experience = _parse_experience_list(resume_experience_list)
        jd_experience = _parse_experience_list(jd_experience_list)

        # ---- jdpost similarity (title match) ----
        jd_post_lower = [s.lower() for s in jd_post if isinstance(s, str)]
        jdpost_similarity = 0.0
        experience_similarity = 0.0
        if resume_workedAs and jd_post_lower:
            resume_worked_lower = [s.lower() for s in resume_workedAs if isinstance(s, str)]
            matched = False
            for i, item in enumerate(resume_worked_lower):
                if item in jd_post_lower:
                    matched = True
                    # try experience comparison
                    if resume_experience and jd_experience:
                        try:
                            diff = jd_experience[0] - (resume_experience[i] if i < len(resume_experience) else resume_experience[0])
                            if diff <= 0: experience_similarity = 1.0
                            elif diff <= 1: experience_similarity = 0.7
                            else: experience_similarity = 0.0
                        except:
                            experience_similarity = 0.0
                    break
            jdpost_similarity = 1.0 if matched else 0.0

        jdpost_similarity *= 0.3
        experience_similarity *= 0.2

        # ---- skills similarity (try MediaWiki expansion first, else simple intersection) ----
        skills_similarity = 0.0
        if job_description_skills:
            # try expansion for resume skills
            expanded_resume_skills = []
            for s in resume_skills:
                try:
                    res = get_search_results(f"{s} in technology")
                    if res:
                        if isinstance(res, str): expanded_resume_skills.append(res)
                        else:
                            # join list results to string for easier substring check
                            expanded_resume_skills.append(" ".join([str(x) for x in res]))
                except Exception:
                    continue
            # count matches by substring (robust)
            count = 0
            for jskill in job_description_skills:
                for rskills_text in expanded_resume_skills:
                    if isinstance(rskills_text, str) and jskill.lower() in rskills_text.lower():
                        count += 1
                        break
            # fallback: direct set intersection (lowercased tokens)
            if count == 0:
                s_jd = set([x.lower() for x in job_description_skills if isinstance(x, str)])
                s_res = set([x.lower() for x in resume_skills if isinstance(x, str)])
                if s_jd and s_res:
                    inter = s_jd.intersection(s_res)
                    count = len(inter)
            try:
                skills_similarity = 1 - ((len(job_description_skills) - count) / len(job_description_skills))
                skills_similarity = max(0.0, skills_similarity) * 0.5
            except Exception:
                skills_similarity = 0.0
        else:
            # if JD skills missing, try match resume_skills against JD text keywords
            if resume_skills and text_of_jd:
                s_res = set([x.lower() for x in resume_skills if isinstance(x, str)])
                cnt = sum(1 for w in s_res if w in text_of_jd.lower())
                skills_similarity = (cnt / len(s_res)) * 0.5 if s_res else 0.0
            else:
                skills_similarity = 0.0

        matching = round((jdpost_similarity + experience_similarity + skills_similarity) * 100.0, 2)
        print(f"[Matching] score={matching} (jdpost={jdpost_similarity}, exp={experience_similarity}, skills={skills_similarity})")
        return matching

    except Exception as e:
        print("Matching() error:", repr(e))
        return 0.0
