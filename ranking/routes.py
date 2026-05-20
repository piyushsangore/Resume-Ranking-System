# ranking/routes.py
from flask import Blueprint, render_template, request, jsonify, make_response, current_app
from bson.objectid import ObjectId
from datetime import datetime
import io, csv, re

bp = Blueprint("ranking", __name__, url_prefix="/ranking")

# Try to import helpers from ranking.utils if available (preferred for better similarity)
try:
    from ranking.utils import (
        merge_resume_fields_for_similarity,
        compute_cosine_similarity,
        extract_text_from_pdf_bytes,
        export_rankings_to_csv,
    )
except Exception:
    merge_resume_fields_for_similarity = None
    compute_cosine_similarity = None
    extract_text_from_pdf_bytes = None
    export_rankings_to_csv = None


def try_get_db():
    """
    Try several methods to obtain a PyMongo database object or an object that
    exposes collection attributes. Returns (db_obj_or_wrapper, note_str).
    """
    # 1) core.database.get_db()
    try:
        from core.database import get_db

        db = get_db()
        if db is not None:
            return db, "from core.database.get_db()"
    except Exception:
        pass

    # 2) current_app attributes
    try:
        if getattr(current_app, "db", None) is not None:
            return current_app.db, "from current_app.db"
        # app may have attached specific collection objects
        has_any = any(
            hasattr(current_app, name)
            for name in ("RESUME_COLLECTION", "JOBS_COLLECTION", "USERS_COLLECTION", "mongo_db")
        )
        if has_any:
            return current_app, "from current_app attributes"
    except Exception:
        pass

    # 3) app module globals
    try:
        import app as main_app

        for name in ("RESUME_COLLECTION", "JOBS_COLLECTION", "USERS_COLLECTION", "db", "mongo_db"):
            if hasattr(main_app, name):
                return main_app, "from app module globals"
    except Exception:
        pass

    # 4) config-based candidate
    try:
        if current_app and getattr(current_app, "config", None):
            db_candidate = (
                current_app.config.get("MONGO_DB")
                or current_app.config.get("DB")
                or current_app.config.get("DATABASE")
            )
            if db_candidate is not None:
                return db_candidate, "from current_app.config"
    except Exception:
        pass

    return None, "not found"


def _find_collection(db, names):
    """
    Given 'db' (PyMongo database or object with attributes), try candidate names
    and return (collection_object_or_None, source_note).
    """
    if db is None:
        return None, None

    # If db is module/app object with attributes like RESUME_COLLECTION etc.
    for n in names:
        try:
            if hasattr(db, n):
                coll = getattr(db, n)
                if coll is not None:
                    return coll, f"attr:{n}"
        except Exception:
            pass

    # If db is a PyMongo database with list_collection_names, search there.
    try:
        if hasattr(db, "list_collection_names"):
            present = set(db.list_collection_names())
            for n in names:
                if n in present:
                    return db[n], f"collection:{n}"
                if n.lower() in present:
                    return db[n.lower()], f"collection:{n.lower()}"
                if n.upper() in present:
                    return db[n.upper()], f"collection:{n.upper()}"
                alt = n.replace("_", "")
                if alt in present:
                    return db[alt], f"collection:{alt}"
    except Exception:
        pass

    return None, None


def _default_export_csv(rankings):
    buf = io.StringIO()
    w = csv.writer(buf)
    header = [
        "rank",
        "user_id",
        "name",
        "email",
        "final_score",
        "skill_points",
        "exp_points",
        "cert_points",
        "cgpa_points",
        "eq_points",
    ]
    w.writerow(header)
    for i, r in enumerate(rankings, start=1):
        w.writerow(
            [
                i,
                r.get("user_id", ""),
                r.get("name", ""),
                r.get("email", ""),
                r.get("final_score", ""),
                r.get("skill_points", ""),
                r.get("exp_points", ""),
                r.get("cert_points", ""),
                r.get("cgpa_points", ""),
                r.get("eq_points", ""),
            ]
        )
    return buf.getvalue().encode("utf-8")


def _parse_experience_years(exp_field):
    if not exp_field:
        return 0.0
    if isinstance(exp_field, list):
        txt = " ".join([str(x) for x in exp_field])
    else:
        txt = str(exp_field)
    m = re.search(r"(\d+(?:\.\d+)?)\s*(years|year|yrs|yr|months|month|mo)", txt, re.I)
    if m:
        val = float(m.group(1))
        if re.search(r"month", m.group(2), re.I):
            return round(val / 12.0, 2)
        return round(val, 2)
    m2 = re.search(r"(\d+(?:\.\d+)?)", txt)
    if m2:
        return float(m2.group(1))
    return 0.0


def _count_experience_entries_from_doc(resume_doc):
    """
    Count experience entries in a resume document. For the simplified rule you
    requested we treat:
      - list fields (e.g. WORKED AS) -> each non-empty element counts as 1
      - string fields -> non-empty string counts as 1
    Returns integer count (0..n).
    """
    keys_to_check = [
        "YEARS OF EXPERIENCE",
        "Years of Experience",
        "WORKED AS",
        "WORKED_AS",
        "Worked_As",
        "WORKEDAS",
        "Experience",
        "EXPERIENCE",
        "WORKED",
        "WORKED_AS_LIST",
    ]
    count = 0
    for key in keys_to_check:
        try:
            val = resume_doc.get(key)
            if val is None:
                continue
            if isinstance(val, (list, tuple)):
                # count only non-empty entries
                for entry in val:
                    try:
                        if str(entry).strip():
                            count += 1
                    except Exception:
                        continue
            else:
                # treat any non-empty string/number as one experience entry
                if isinstance(val, str):
                    if val.strip():
                        count += 1
                else:
                    # for numeric or other truthy values count once
                    try:
                        if val:
                            count += 1
                    except Exception:
                        continue
        except Exception:
            continue
    return count


@bp.route("/compute/<job_id>", methods=["GET"])
def compute_ranking(job_id):
    """
    Compute rankings for a job and render or export them.
    - ?export=1 returns CSV
    - ?as_json=1 returns JSON
    - otherwise render template ranking_results.html (fallback HTML table if missing)
    """
    db, note = try_get_db()
    current_app.logger.debug("ranking.routes: db resolution: %s", note)

    job_names = ["JOBS", "jobs", "Job", "Job_Profile", "job", "Job_Profile", "JOBS_COLLECTION"]
    resume_names = [
        "resumeFetchedData",
        "resumeFetcheddata",
        "resume_fetched_data",
        "RESUME_COLLECTION",
        "resumes",
        "resume",
    ]
    user_names = ["USERS", "users", "USERS_COLLECTION"]

    jobs_coll, jobs_note = _find_collection(db, job_names)
    resumes_coll, resumes_note = _find_collection(db, resume_names)
    users_coll, users_note = _find_collection(db, user_names)

    current_app.logger.debug("jobs_coll:%s resumes_coll:%s users_coll:%s", jobs_note, resumes_note, users_note)

    # Also check db object attributes explicitly where appropriate
    try:
        if jobs_coll is None and hasattr(db, "JOBS_COLLECTION"):
            jobs_coll = getattr(db, "JOBS_COLLECTION")
        if resumes_coll is None and hasattr(db, "RESUME_COLLECTION"):
            resumes_coll = getattr(db, "RESUME_COLLECTION")
        if users_coll is None and hasattr(db, "USERS_COLLECTION"):
            users_coll = getattr(db, "USERS_COLLECTION")
    except Exception:
        pass

    # If no resumes collection discovered, return helpful debug JSON
    if resumes_coll is None:
        collections_list = []
        try:
            if hasattr(db, "list_collection_names"):
                collections_list = db.list_collection_names()
        except Exception:
            pass
        debug = {
            "error": "No resumes collection found by automatic discovery.",
            "tried_resume_names": resume_names,
            "db_discovery_note": note,
            "db_collection_names": collections_list,
            "hint": "If your resumes collection has a different name, update the resume_names list or attach the collection to app globals.",
        }
        current_app.logger.debug("compute_ranking debug: %s", debug)
        return jsonify(debug), 200

    # Load job document
    job_doc = None
    job_title = "Unknown Job"
    job_text = ""
    try:
        if resumes_coll is not None:
            # safe - we will fetch job only if jobs_coll found
            if jobs_coll is not None:
                try:
                    job_doc = jobs_coll.find_one({"_id": ObjectId(job_id)})
                except Exception:
                    job_doc = jobs_coll.find_one({"_id": job_id}) or jobs_coll.find_one({"Job_Profile": job_id})
            if job_doc:
                job_title = job_doc.get("Job_Profile") or job_doc.get("Job_Title") or job_doc.get("job_title") or str(
                    job_doc.get("Job_Profile", "")
                )
                job_text = job_doc.get("Job_Description") or ""
                if not job_text and job_doc.get("FileData") and extract_text_from_pdf_bytes is not None:
                    try:
                        job_text = extract_text_from_pdf_bytes(job_doc.get("FileData"))
                    except Exception:
                        try:
                            job_text = str(job_doc.get("FileData"))[:2000]
                        except Exception:
                            job_text = ""
    except Exception as e:
        current_app.logger.exception("Error fetching job doc: %s", e)
        job_doc = None

    # Collect resumes list
    resumes = []
    try:
        if hasattr(resumes_coll, "find"):
            resumes = list(resumes_coll.find({}))
        else:
            # if resumes_coll isn't a collection, try fallback attribute on db
            try:
                if hasattr(db, "resumeFetchedData"):
                    resumes = list(getattr(db, "resumeFetchedData").find({}))
                else:
                    resumes = []
            except Exception:
                resumes = []
    except Exception as e:
        current_app.logger.exception("Error reading resumes: %s", e)
        resumes = []

    if not resumes:
        # sample collections for debug
        sample = []
        try:
            if hasattr(db, "list_collection_names"):
                names = db.list_collection_names()
                for n in names[:5]:
                    try:
                        docs = list(db[n].find().limit(3))
                        sample.append({"collection": n, "sample_count": len(docs)})
                    except Exception:
                        pass
        except Exception:
            sample = []
        debug = {
            "job_id": job_id,
            "job_title": job_title,
            "rankings": [],
            "notice": "No resumes documents found in discovered resumes collection.",
            "resumes_sample_collections": sample,
        }
        current_app.logger.debug("compute_ranking no resumes: %s", debug)
        return jsonify(debug)

    # Compute scores
    rankings = []
    EQUIV_MAX_POINTS = 5.0
    for resume_doc in resumes:
        try:
            name_val = resume_doc.get("Name") or resume_doc.get("name") or resume_doc.get("NAME") or ""
            email_val = resume_doc.get("Email") or resume_doc.get("email") or ""

            skills = resume_doc.get("SKILLS") or resume_doc.get("skills") or []
            if isinstance(skills, (list, tuple)):
                skill_count = len(skills)
            elif isinstance(skills, str) and skills.strip():
                skill_count = len([s for s in re.split(r"[,;\n\r]+", skills) if s.strip()])
            else:
                skill_count = 0
            skill_points = min(20, int(skill_count))

            certs = resume_doc.get("CERTIFICATIONS") or resume_doc.get("certifications") or []
            if isinstance(certs, (list, tuple)):
                cert_count = len(certs)
            else:
                cert_count = 1 if certs else 0
            cert_points = min(10, int(cert_count) * 5)

            cgpa_raw = resume_doc.get("CGPA") or resume_doc.get("cgpa") or 0
            try:
                cgpa_f = float(cgpa_raw)
            except Exception:
                cgpa_f = 0.0
            cgpa_points = min(25.0, round(cgpa_f * 2.5, 2))

            # -------------------- EXPERIENCE: simplified count * 10 (cap 20) --------------------
            # Count entries across relevant keys and give 10 points per entry with cap 20.
            exp_count = _count_experience_entries_from_doc(resume_doc)
            exp_points = min(20, int(exp_count * 10))

            # -------------------- EQUIVALENCE: use cosine similarity on merged resume text -----------
            merged_resume_text = ""
            try:
                if merge_resume_fields_for_similarity is not None:
                    merged_resume_text = merge_resume_fields_for_similarity(resume_doc) or ""
                else:
                    # fallback merge: skills + summary + education
                    merged_parts = []
                    if isinstance(skills, (list, tuple)):
                        merged_parts.append(" ".join([str(s) for s in skills if s]))
                    else:
                        merged_parts.append(str(skills) if skills else "")
                    merged_parts.append(str(resume_doc.get("SUMMARY", "") or ""))
                    merged_parts.append(str(resume_doc.get("EDUCATION", "") or ""))
                    merged_resume_text = " ".join([p for p in merged_parts if p])
            except Exception:
                merged_resume_text = ""

            eq_sim = 0.0
            try:
                if compute_cosine_similarity is not None and (job_text or job_title) and merged_resume_text:
                    # preferred path: use the provided cosine similarity function
                    eq_sim = compute_cosine_similarity((job_text or job_title), merged_resume_text) or 0.0
                else:
                    # fallback simple token overlap heuristic
                    jtoks = set(t.lower() for t in re.findall(r"\w+", (job_text or job_title) or "") if len(t) > 2)
                    mtoks = set(t.lower() for t in re.findall(r"\w+", merged_resume_text or "") if len(t) > 2)
                    if jtoks and mtoks:
                        eq_sim = len(jtoks.intersection(mtoks)) / float(len(jtoks))
                    else:
                        eq_sim = 0.0
            except Exception:
                eq_sim = 0.0

            eq_points = min(round(float(eq_sim) * float(EQUIV_MAX_POINTS) * 25, 4),25)

            final_score = round(
                (skill_points or 0)
                + (exp_points or 0)
                + (cert_points or 0)
                + (cgpa_points or 0)
                + (eq_points or 0),
                2,
            )

            ranking_item = {
                "user_id": str(resume_doc.get("UserId") or resume_doc.get("_id") or ""),
                "name": name_val or "",
                "email": email_val or "",
                "final_score": final_score,
                "skill_points": skill_points,
                "exp_points": exp_points,
                "cert_points": cert_points,
                "cgpa_points": cgpa_points,
                "eq_points": eq_points,
            }
            rankings.append(ranking_item)
        except Exception:
            current_app.logger.exception("Error scoring resume doc")
            continue

    rankings = sorted(rankings, key=lambda x: x.get("final_score", 0.0), reverse=True)

    # CSV export
    if request.args.get("export") in ("1", "true", "True"):
        try:
            # prefer helper if present
            if export_rankings_to_csv is not None:
                csv_bytes = export_rankings_to_csv(rankings)
            else:
                csv_bytes = _default_export_csv(rankings)
            resp = make_response(csv_bytes)
            resp.headers.set("Content-Type", "text/csv; charset=utf-8")
            resp.headers.set(
                "Content-Disposition",
                f"attachment; filename=rankings_{job_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv",
            )
            return resp
        except Exception:
            current_app.logger.exception("CSV export failed")
            return jsonify({"job_id": job_id, "rankings": rankings})

    if request.args.get("as_json") in ("1", "true", "True"):
        return jsonify({"job_id": job_id, "job_title": job_title, "rankings": rankings})

    # Render template or fallback HTML
    try:
        return render_template("ranking_results.html", job_title=job_title, job=job_doc, job_id=str(job_id), rankings=rankings)
    except Exception as e:
        current_app.logger.debug("ranking_results.html render failed: %s", e)
        # Fallback HTML table so UI remains usable
        rows = []
        for i, r in enumerate(rankings, start=1):
            rows.append(
                f"<tr><td>{i}</td><td>{r.get('name','')}</td><td>{r.get('email','')}</td><td>{r.get('final_score','')}</td>"
                f"<td>{r.get('skill_points','')}</td><td>{r.get('exp_points','')}</td><td>{r.get('cert_points','')}</td>"
                f"<td>{r.get('cgpa_points','')}</td><td>{r.get('eq_points','')}</td></tr>"
            )
        html = f"""
        <html><head><title>Rankings - {job_title}</title>
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap@4.6.2/dist/css/bootstrap.min.css">
        </head><body class="p-4">
        <div class="container">
          <h3>Rankings for job: {job_title}</h3>
          <a class="btn btn-success mb-2" href="?export=1">Export CSV</a>
          <table class="table table-bordered table-striped">
            <thead><tr><th>#</th><th>Name</th><th>Email</th><th>Final Score</th><th>Skill pts</th><th>Exp pts</th><th>Cert pts</th><th>CGPA pts</th><th>Eq pts</th></tr></thead>
            <tbody>{''.join(rows)}</tbody>
          </table>
        </div>
        </body></html>
        """
        return html









# # ranking/routes.py
# """
# Ranking blueprint: compute rankings for a job, render HTML or export CSV.

# How it helps:
# - Robustly finds your Mongo collections by trying several common import paths.
# - compute_ranking endpoint = GET /ranking/compute/<job_id>
# - Alias endpoint 'compute_ranking_for_job' is registered so older templates using
#   url_for('ranking.compute_ranking_for_job', job_id=...) will work.
# - If templates 'ranking_results.html' or 'ranking_list.html' are missing, returns JSON.
# """

# from flask import Blueprint, request, render_template, jsonify, make_response, current_app
# from bson.objectid import ObjectId
# from datetime import datetime
# import re, io, csv

# bp = Blueprint("ranking", __name__, url_prefix="/ranking")

# # Try to find mongo collections from various possible modules (app, database, core.database)
# RESUME_COLLECTION = None
# JOBS_COLLECTION = None
# USERS_COLLECTION = None

# def _init_collections():
#     global RESUME_COLLECTION, JOBS_COLLECTION, USERS_COLLECTION
#     if RESUME_COLLECTION is not None and JOBS_COLLECTION is not None:
#         return

#     # Try common import locations used in this project
#     try:
#         # your old app used "from database import mongo" and mongo.init_app(app)
#         from database import mongo
#         db = mongo.db
#         RESUME_COLLECTION = db.resumeFetchedData
#         JOBS_COLLECTION = db.JOBS
#         # USERS may or may not exist
#         try:
#             USERS_COLLECTION = db.IRS_USERS
#         except Exception:
#             USERS_COLLECTION = None
#         current_app.logger.debug("ranking.routes: using database.mongo")
#         return
#     except Exception:
#         pass

#     try:
#         # maybe app exposes mongo or collections directly
#         import app as main_app
#         if hasattr(main_app, "mongo"):
#             db = main_app.mongo.db
#             RESUME_COLLECTION = db.resumeFetchedData
#             JOBS_COLLECTION = db.JOBS
#             USERS_COLLECTION = getattr(db, "IRS_USERS", None)
#             current_app.logger.debug("ranking.routes: using app.mongo")
#             return
#     except Exception:
#         pass

#     try:
#         # some code used core.database.db or similar
#         from core.database import db as core_db
#         RESUME_COLLECTION = getattr(core_db, "resumeFetchedData", None)
#         JOBS_COLLECTION = getattr(core_db, "JOBS", None)
#         USERS_COLLECTION = getattr(core_db, "USERS", None)
#         current_app.logger.debug("ranking.routes: using core.database.db")
#         return
#     except Exception:
#         pass

#     # Last fallback: leave them None and code will handle
#     current_app.logger.debug("ranking.routes: could not auto-detect DB collections; RESUME_COLLECTION remains None")

# # small helper: parse years from typical resume fields
# def _parse_experience_years(exp_field):
#     if not exp_field:
#         return 0.0
#     if isinstance(exp_field, list):
#         txt = " ".join([str(x) for x in exp_field])
#     else:
#         txt = str(exp_field)
#     m = re.search(r'(\d+(?:\.\d+)?)\s*(years|year|yrs|yr|months|month|mo)', txt, re.I)
#     if m:
#         val = float(m.group(1))
#         if re.search(r'month', m.group(2), re.I):
#             return round(val / 12.0, 2)
#         return round(val, 2)
#     # fallback any number
#     m2 = re.search(r'(\d+(?:\.\d+)?)', txt)
#     if m2:
#         try:
#             return float(m2.group(1))
#         except:
#             return 0.0
#     return 0.0

# # fallback CSV exporter (if your ranking.utils is not available)
# def _default_export_csv(rankings):
#     buf = io.StringIO()
#     w = csv.writer(buf)
#     header = ["rank", "user_id", "name", "email", "final_score", "skill_points", "exp_points", "cert_points", "cgpa_points", "eq_points"]
#     w.writerow(header)
#     for i, r in enumerate(rankings, start=1):
#         w.writerow([
#             i,
#             r.get("user_id", ""),
#             r.get("name", ""),
#             r.get("email", ""),
#             r.get("final_score", ""),
#             r.get("skill_points", ""),
#             r.get("exp_points", ""),
#             r.get("cert_points", ""),
#             r.get("cgpa_points", ""),
#             r.get("eq_points", ""),
#         ])
#     return buf.getvalue().encode("utf-8")

# # try to import optional helpers from ranking.utils if present
# try:
#     from ranking.utils import merge_resume_fields_for_similarity, compute_cosine_similarity, export_rankings_to_csv
# except Exception:
#     merge_resume_fields_for_similarity = None
#     compute_cosine_similarity = None
#     export_rankings_to_csv = None

# # Main endpoint: compute ranking for a job id
# @bp.route("/compute/<job_id>", methods=["GET"])
# def compute_ranking(job_id):
#     """
#     Compute rankings for <job_id>.
#     - ?export=1 returns CSV
#     - ?as_json=1 returns raw JSON
#     - Otherwise renders HTML template. It will try these template names in order:
#         'ranking_results.html' (preferred), 'ranking_list.html' (older), else returns JSON.
#     """
#     # ensure collections available
#     try:
#         _init_collections()
#     except Exception:
#         current_app.logger.exception("Failed to init collections")

#     jobs_coll = globals().get("JOBS_COLLECTION")
#     resumes_coll = globals().get("RESUME_COLLECTION")
#     users_coll = globals().get("USERS_COLLECTION")

#     # fetch job doc
#     job_doc = None
#     job_title = "Unknown Job"
#     job_text = ""
#     if jobs_coll is not None:
#         try:
#             try:
#                 job_doc = jobs_coll.find_one({"_id": ObjectId(job_id)})
#             except Exception:
#                 job_doc = jobs_coll.find_one({"_id": job_id})
#         except Exception:
#             job_doc = None

#     if job_doc:
#         # safe extraction of job title and any JD text
#         job_title = job_doc.get("Job_Profile") or job_doc.get("Job_Profile".upper()) or str(job_doc.get("Job_Profile", "Unknown Job"))
#         jd_text = job_doc.get("Job_Description") or ""
#         if not jd_text and job_doc.get("FileData"):
#             # try to extract some text if ranking.utils has extractor
#             try:
#                 from ranking.utils import extract_text_from_pdf_bytes
#                 jd_text = extract_text_from_pdf_bytes(job_doc.get("FileData"))
#             except Exception:
#                 try:
#                     jd_text = str(job_doc.get("FileData"))[:2000]
#                 except Exception:
#                     jd_text = ""
#         job_text = jd_text or job_title

#     # collect resume docs
#     resumes = []
#     if resumes_coll is not None:
#         try:
#             resumes = list(resumes_coll.find({}))
#         except Exception:
#             resumes = []
#     else:
#         resumes = []

#     rankings = []
#     for resume_doc in resumes:
#         try:
#             # robust name/email extraction from stored resume doc
#             name_val = resume_doc.get("Name") or resume_doc.get("name") or resume_doc.get("NAME") or ""
#             email_val = resume_doc.get("Email") or resume_doc.get("email") or resume_doc.get("EMAIL") or ""
#             # try USERS collection if name/email missing and Users collection available
#             if (not name_val or not email_val) and users_coll is not None:
#                 try:
#                     # resume_doc may have 'UserId' stored as ObjectId or string
#                     uid = resume_doc.get("UserId") or resume_doc.get("user_id") or resume_doc.get("UserId")
#                     if uid:
#                         try:
#                             udoc = users_coll.find_one({"_id": ObjectId(uid)})
#                         except Exception:
#                             udoc = users_coll.find_one({"_id": uid})
#                         if udoc:
#                             name_val = name_val or udoc.get("Name") or udoc.get("name")
#                             email_val = email_val or udoc.get("Email") or udoc.get("email")
#                 except Exception:
#                     pass

#             # skill points: count of SKILLS list (cap at 20)
#             skills = resume_doc.get("SKILLS") or resume_doc.get("skills") or []
#             if isinstance(skills, (list, tuple)):
#                 skill_count = len(skills)
#             elif isinstance(skills, str) and skills.strip():
#                 # try comma-split
#                 skill_count = len([s for s in re.split(r'[,\n;]', skills) if s.strip()])
#             else:
#                 skill_count = 0
#             skill_points = min(20, int(skill_count))

#             # cert points
#             certs = resume_doc.get("CERTIFICATIONS") or resume_doc.get("certifications") or []
#             if isinstance(certs, (list, tuple)):
#                 cert_count = len(certs)
#             elif isinstance(certs, str) and certs.strip():
#                 cert_count = 1
#             else:
#                 cert_count = 0
#             cert_points = min(10, int(cert_count))

#             # cgpa points (assume CGPA out of 10 scaled to 25)
#             cgpa_raw = resume_doc.get("CGPA") or resume_doc.get("cgpa") or resume_doc.get("Cgpa") or 0
#             try:
#                 cgpa_f = float(cgpa_raw)
#             except Exception:
#                 cgpa_f = 0.0
#             cgpa_points = min(25.0, round(cgpa_f * 2.5, 2))

#             # experience points
#             exp_field = resume_doc.get("YEARS OF EXPERIENCE") or resume_doc.get("Years of Experience") or resume_doc.get("WORKED AS") or resume_doc.get("Experience") or ""
#             exp_years = _parse_experience_years(exp_field)
#             if exp_years <= 0:
#                 exp_points = 0
#             elif exp_years >= 5:
#                 exp_points = 20
#             else:
#                 exp_points = round((exp_years / 5.0) * 20.0, 2)

#             # eq_points: similarity between JD and resume merged text
#             merged_text = ""
#             if merge_resume_fields_for_similarity is not None:
#                 try:
#                     merged_text = merge_resume_fields_for_similarity(resume_doc)
#                 except Exception:
#                     merged_text = " ".join([str(skills if isinstance(skills, (list,tuple)) else skills), str(resume_doc.get("SUMMARY","") or ""), str(resume_doc.get("EDUCATION","") or "")])
#             else:
#                 merged_text = " ".join([str(skills if isinstance(skills, (list,tuple)) else skills), str(resume_doc.get("SUMMARY","") or ""), str(resume_doc.get("EDUCATION","") or "")])

#             sim = 0.0
#             if compute_cosine_similarity is not None:
#                 try:
#                     sim = compute_cosine_similarity(job_text or job_title, merged_text)
#                 except Exception:
#                     sim = 0.0
#             else:
#                 # fallback simple token overlap heuristic
#                 try:
#                     jtoks = set([t.lower() for t in re.findall(r'\w+', job_text) if len(t) > 2])
#                     mtoks = set([t.lower() for t in re.findall(r'\w+', merged_text) if len(t) > 2])
#                     if jtoks and mtoks:
#                         sim = len(jtoks.intersection(mtoks)) / float(len(jtoks))
#                     else:
#                         sim = 0.0
#                 except Exception:
#                     sim = 0.0

#             eq_points = round(sim * 5.0, 4)

#             # final score (weights are simple sum so UI numbers match expected ranges)
#             final_score = round((skill_points * 1.0) + (exp_points * 1.0) + (cert_points * 1.0) + (cgpa_points * 1.0) + (eq_points * 1.0), 2)

#             ranking_item = {
#                 "user_id": str(resume_doc.get("UserId") or resume_doc.get("_id") or ""),
#                 "name": name_val or "",
#                 "email": email_val or "",
#                 "final_score": final_score,
#                 "skill_points": skill_points,
#                 "exp_points": exp_points,
#                 "cert_points": cert_points,
#                 "cgpa_points": cgpa_points,
#                 "eq_points": eq_points,
#             }
#             rankings.append(ranking_item)
#         except Exception as e:
#             current_app.logger.exception("Error scoring resume: %s", e)
#             continue

#     # sort descending by final_score
#     rankings = sorted(rankings, key=lambda x: x.get("final_score", 0.0), reverse=True)

#     # if export CSV requested
#     if request.args.get("export") in ("1", "true", "True"):
#         try:
#             if export_rankings_to_csv is not None:
#                 csv_bytes = export_rankings_to_csv(rankings)
#             else:
#                 csv_bytes = _default_export_csv(rankings)
#             resp = make_response(csv_bytes)
#             resp.headers.set("Content-Type", "text/csv; charset=utf-8")
#             resp.headers.set("Content-Disposition", f"attachment; filename=rankings_{job_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv")
#             return resp
#         except Exception:
#             return jsonify({"job_id": job_id, "rankings": rankings})

#     # JSON debug mode
#     if request.args.get("as_json") in ("1", "true", "True"):
#         return jsonify({"job_id": job_id, "job_title": job_title, "rankings": rankings})

#     # Try rendering HTML templates you may already have. Prefer 'ranking_results.html' or 'ranking_list.html'
#     try:
#         # prefer "ranking_results.html" (I saw that file in your project)
#         return render_template("ranking_results.html", job_title=job_title, job=job_doc, rankings=rankings)
#     except Exception as e1:
#         current_app.logger.debug("ranking_results.html render failed: %s", e1)
#         try:
#             return render_template("ranking_list.html", job_title=job_title, job=job_doc, rankings=rankings)
#         except Exception as e2:
#             current_app.logger.exception("Both ranking templates failed: %s | %s", e1, e2)
#             # fallback JSON so UI doesn't break
#             return jsonify({"job_id": job_id, "job_title": job_title, "rankings": rankings})

# # register alias endpoint name so older templates using compute_ranking_for_job won't break
# # This maps the same URL to a second endpoint name: 'ranking.compute_ranking_for_job'
# # (Blueprint name 'ranking' will prefix the endpoint).
# bp.add_url_rule("/compute/<job_id>", endpoint="compute_ranking_for_job", view_func=compute_ranking, methods=["GET"])








# # paste this function in ranking/routes.py (replace the existing compute_ranking)
# from flask import render_template, request, make_response, jsonify, current_app
# from bson.objectid import ObjectId
# from datetime import datetime
# import io, csv, re

# # Attempt to import helpers (optional)
# try:
#     from ranking.utils import merge_resume_fields_for_similarity, compute_cosine_similarity, export_rankings_to_csv
# except Exception:
#     merge_resume_fields_for_similarity = None
#     compute_cosine_similarity = None
#     export_rankings_to_csv = None

# def _parse_experience_years(exp_field):
#     """Return a float representing years of experience parsed from various resume fields."""
#     if not exp_field:
#         return 0.0
#     # if list, join
#     if isinstance(exp_field, list):
#         txt = " ".join([str(x) for x in exp_field])
#     else:
#         txt = str(exp_field)
#     # find numbers followed by year(s)/yr/month
#     m = re.search(r'(\d+(?:\.\d+)?)\s*(years|year|yrs|yrs\.|yr|months|month|mo)', txt, re.I)
#     if m:
#         val = float(m.group(1))
#         if re.search(r'month', m.group(2), re.I):
#             return round(val / 12.0, 2)
#         return round(val, 2)
#     # fallback: any number
#     m2 = re.search(r'(\d+(?:\.\d+)?)', txt)
#     if m2:
#         return float(m2.group(1))
#     return 0.0

# def _default_export_csv(rankings):
#     """Simple CSV exporter used if ranking.utils.export_rankings_to_csv is unavailable."""
#     buf = io.StringIO()
#     w = csv.writer(buf)
#     header = ["rank", "user_id", "name", "email", "final_score", "skill_points", "exp_points", "cert_points", "cgpa_points", "eq_points"]
#     w.writerow(header)
#     for i, r in enumerate(rankings, start=1):
#         w.writerow([
#             i,
#             r.get("user_id", ""),
#             r.get("name", ""),
#             r.get("email", ""),
#             r.get("final_score", ""),
#             r.get("skill_points", ""),
#             r.get("exp_points", ""),
#             r.get("cert_points", ""),
#             r.get("cgpa_points", ""),
#             r.get("eq_points", ""),
#         ])
#     return buf.getvalue().encode("utf-8")

# @bp.route("/compute/<job_id>", methods=["GET"])
# def compute_ranking(job_id):
#     """
#     Compute rankings for a job and render a table or export CSV.
#     Usage:
#       GET /ranking/compute/<job_id>              -> renders HTML (template 'rankings.html')
#       GET /ranking/compute/<job_id>?export=1     -> returns CSV file
#       GET /ranking/compute/<job_id>?as_json=1    -> returns JSON (for debugging)
#     This function is intentionally conservative and focuses on ensuring `name` and `email`
#     are present in the output for display + CSV.
#     """
#     # collections expected to be defined at module level:
#     # RESUME_COLLECTION, JOBS_COLLECTION, USERS_COLLECTION
#     try:
#         jobs_coll = globals().get("JOBS_COLLECTION")
#         resumes_coll = globals().get("RESUME_COLLECTION")
#     except Exception:
#         jobs_coll = None
#         resumes_coll = None

#     # fetch job doc
#     job_doc = None
#     job_title = "Unknown Job"
#     job_text = ""
#     try:
#         if jobs_coll is not None:
#             try:
#                 job_doc = jobs_coll.find_one({"_id": ObjectId(job_id)})
#             except Exception:
#                 job_doc = jobs_coll.find_one({"_id": job_id})
#         if job_doc:
#             job_title = job_doc.get("Job_Profile") or job_doc.get("Job_Profile".upper()) or str(job_doc.get("Job_Profile",""))
#             # attempt to extract job text (file data or Job_Description)
#             jd_text = job_doc.get("Job_Description") or ""
#             if not jd_text and job_doc.get("FileData"):
#                 try:
#                     # if you have ranking.utils.extract_text_from_pdf_bytes, prefer that
#                     from ranking.utils import extract_text_from_pdf_bytes
#                     jd_text = extract_text_from_pdf_bytes(job_doc.get("FileData"))
#                 except Exception:
#                     try:
#                         jd_text = str(job_doc.get("FileData"))[:2000]
#                     except Exception:
#                         jd_text = ""
#             job_text = jd_text or job_title
#     except Exception:
#         job_doc = None

#     # collect resumes
#     resumes = []
#     try:
#         if resumes_coll is not None:
#             # fetch all resume docs - you may filter if needed
#             resumes = list(resumes_coll.find({}))
#         else:
#             resumes = []
#     except Exception:
#         resumes = []

#     rankings = []
#     # compute scores conservatively
#     for resume_doc in resumes:
#         try:
#             # extract name/email robustly
#             name_val = resume_doc.get("Name") or resume_doc.get("name") or resume_doc.get("NAME") or ""
#             email_val = resume_doc.get("Email") or resume_doc.get("email") or resume_doc.get("EMAIL") or ""

#             # skill points: number of skills (cap at 20)
#             skills = resume_doc.get("SKILLS") or resume_doc.get("skills") or []
#             skill_count = len(skills) if isinstance(skills, (list, tuple)) else (len(str(skills).split(",")) if skills else 0)
#             skill_points = min(20, int(skill_count))

#             # cert points: number of certifications (cap at 10)
#             certs = resume_doc.get("CERTIFICATIONS") or resume_doc.get("certifications") or []
#             cert_count = len(certs) if isinstance(certs, (list, tuple)) else (1 if certs else 0)
#             cert_points = min(10, int(cert_count))

#             # cgpa points: if CGPA stored, scale to max 25 (assumes CGPA out of 10)
#             cgpa_raw = resume_doc.get("CGPA") or resume_doc.get("cgpa") or 0
#             try:
#                 cgpa_f = float(cgpa_raw)
#             except Exception:
#                 cgpa_f = 0.0
#             cgpa_points = min(25.0, round(cgpa_f * 2.5, 2))   # 10 => 25 points

#             # exp points: parse YEARS OF EXPERIENCE or WORKED AS fields
#             exp_field = resume_doc.get("YEARS OF EXPERIENCE") or resume_doc.get("Years of Experience") or resume_doc.get("WORKED AS") or resume_doc.get("Experience") or ""
#             exp_years = _parse_experience_years(exp_field)
#             # simple mapping: 0 yrs -> 0, >=5 -> 20, else linear
#             if exp_years <= 0:
#                 exp_points = 0
#             elif exp_years >= 5:
#                 exp_points = 20
#             else:
#                 exp_points = round((exp_years / 5.0) * 20.0, 2)

#             # eq_points: text similarity between JD and merged resume text (0..~5)
#             merged_text = ""
#             if merge_resume_fields_for_similarity is not None:
#                 try:
#                     merged_text = merge_resume_fields_for_similarity(resume_doc)
#                 except Exception:
#                     merged_text = " ".join([
#                         " ".join(skills) if isinstance(skills, (list,tuple)) else str(skills),
#                         str(resume_doc.get("SUMMARY", "") or ""),
#                         str(resume_doc.get("EDUCATION", "") or "")
#                     ])
#             else:
#                 merged_text = " ".join([
#                     " ".join(skills) if isinstance(skills, (list,tuple)) else str(skills),
#                     str(resume_doc.get("SUMMARY", "") or ""),
#                     str(resume_doc.get("EDUCATION", "") or "")
#                 ])

#             sim = 0.0
#             if compute_cosine_similarity is not None:
#                 try:
#                     sim = compute_cosine_similarity(job_text or job_title, merged_text)
#                 except Exception:
#                     sim = 0.0
#             else:
#                 # fallback: tiny heuristic — fraction of job words present in merged_text
#                 try:
#                     jtoks = set([t.lower() for t in re.findall(r'\w+', job_text) if len(t) > 2])
#                     mtoks = set([t.lower() for t in re.findall(r'\w+', merged_text) if len(t) > 2])
#                     if jtoks and mtoks:
#                         sim = len(jtoks.intersection(mtoks)) / float(len(jtoks))
#                         if sim != sim: sim = 0.0
#                     else:
#                         sim = 0.0
#                 except Exception:
#                     sim = 0.0

#             eq_points = round(sim * 5.0, 4)  # scale to approx 0..5 region

#             # final score: weighted sum similar to what UI expects (adjust weights as safe)
#             final_score = round((skill_points * 1.0) + (exp_points * 1.0) + (cert_points * 1.0) + (cgpa_points * 1.0) + (eq_points * 1.0), 2)

#             ranking_item = {
#                 "user_id": str(resume_doc.get("UserId") or resume_doc.get("_id") or ""),
#                 "name": name_val or "",
#                 "email": email_val or "",
#                 "final_score": final_score,
#                 "skill_points": skill_points,
#                 "exp_points": exp_points,
#                 "cert_points": cert_points,
#                 "cgpa_points": cgpa_points,
#                 "eq_points": eq_points,
#                 # include raw resume doc if you need for debug/template (optional)
#                 # "resume_doc": resume_doc
#             }
#             rankings.append(ranking_item)
#         except Exception as e:
#             # skip problematic resume but log
#             current_app.logger.exception("Error computing score for resume: %s", e)
#             continue

#     # sort descending
#     rankings = sorted(rankings, key=lambda x: x.get("final_score", 0.0), reverse=True)

#     # If export requested -> return CSV
#     if request.args.get("export") in ("1", "true", "True"):
#         try:
#             if export_rankings_to_csv is not None:
#                 csv_bytes = export_rankings_to_csv(rankings)
#             else:
#                 csv_bytes = _default_export_csv(rankings)
#             resp = make_response(csv_bytes)
#             resp.headers.set("Content-Type", "text/csv; charset=utf-8")
#             resp.headers.set("Content-Disposition", f"attachment; filename=rankings_{job_id}_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}.csv")
#             return resp
#         except Exception:
#             # fallback JSON on failure
#             return jsonify({"job_id": job_id, "rankings": rankings})

#     # JSON handy debug mode
#     if request.args.get("as_json") in ("1", "true", "True"):
#         return jsonify({"job_id": job_id, "rankings": rankings})

#     # Render HTML page. Keep same variable names the templates expect:
#     # The template in your project previously displayed job title and the rankings list.
#     # If your template file name is different from 'rankings.html', update below.
#     try:
#         return render_template("rankings.html", job_title=job_title, job=job_doc, rankings=rankings)
#     except Exception:
#         # If template name is different in your project, try the older 'ranking_list.html' fallback:
#         try:
#             return render_template("ranking_list.html", job_title=job_title, job=job_doc, rankings=rankings)
#         except Exception as e:
#             # Last resort: return JSON for debugging
#             current_app.logger.exception("Template render failed: %s", e)
#             return jsonify({"job_id": job_id, "job_title": job_title, "rankings": rankings})




























# # ranking/routes.py
# from flask import Blueprint, render_template, send_file
# from bson.objectid import ObjectId
# from core.database import get_db
# from ranking.utils import extract_text_from_pdf_bytes, merge_resume_fields_for_similarity, compute_cosine_similarity, export_rankings_to_csv
# from ranking.scoring import compute_resume_score

# bp = Blueprint("ranking", __name__, url_prefix="/ranking")

# # fetch DB object (init_db in app.py has validated the connection)
# db = get_db()
# RESUME_COLLECTION = db.resumeFetchedData
# JOBS_COLLECTION = db.JOBS
# USERS_COLLECTION = db.USERS

# @bp.route("/compute/<job_id>", methods=["GET"])
# def compute_ranking_for_job(job_id):
#     job = JOBS_COLLECTION.find_one({"_id": ObjectId(job_id)})
#     if not job:
#         return "Job not found", 404
#     jd_bytes = job.get("FileData")
#     job_text = extract_text_from_pdf_bytes(jd_bytes) if jd_bytes else job.get("JobDescriptionText","") or job.get("Job_Description","")
#     candidates_cursor = RESUME_COLLECTION.find({})
#     rankings=[]
#     for cand in candidates_cursor:
#         user_id = cand.get("UserId")
#         user_doc = USERS_COLLECTION.find_one({"_id": ObjectId(user_id)}) if user_id and isinstance(user_id, ObjectId) else {}
#         candidate_name = user_doc.get("Name") if user_doc else cand.get("Name","Unknown")
#         email = user_doc.get("Email") if user_doc else cand.get("Email","")
#         resume_blob = merge_resume_fields_for_similarity(cand)
#         sim = compute_cosine_similarity(job_text, resume_blob)
#         cgpa_val = cand.get("CGPA") or cand.get("cgpa") or 0.0
#         score_obj = compute_resume_score(cand, cgpa_val, sim)
#         rankings.append({"candidate_name": candidate_name, "email": email, "user_id": user_id,
#                          "similarity": round(sim,4), "total_score": score_obj["total_score"],
#                          "points_breakdown": score_obj["points_breakdown"], "resume_id": str(cand.get("_id"))})
#     rankings_sorted = sorted(rankings, key=lambda x: x["total_score"], reverse=True)
#     JOBS_COLLECTION.update_one({"_id": ObjectId(job_id)}, {"$set": {"last_ranking": rankings_sorted}})
#     return render_template("ranking_results.html", job=job, rankings=rankings_sorted)

# @bp.route("/export/<job_id>", methods=["GET"])
# def export_rankings(job_id):
#     job = JOBS_COLLECTION.find_one({"_id": ObjectId(job_id)})
#     if not job:
#         return "Job not found", 404
#     last = job.get("last_ranking")
#     if not last:
#         return compute_ranking_for_job(job_id)
#     csv_path = export_rankings_to_csv(last)
#     return send_file(csv_path, as_attachment=True, download_name=f"ranking_{job_id}.csv")
