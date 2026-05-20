# app.py
import os
import re
from flask import Flask, request, render_template, redirect, url_for, flash
from dotenv import load_dotenv
from bson.binary import Binary
from bson.objectid import ObjectId
from core.database import init_db
from parser.matching_wrapper import parse_resume_bytes  # existing parser
from ranking.routes import bp as ranking_bp

load_dotenv()

app = Flask(__name__, template_folder="templates", static_folder="static")
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-secret")
app.config["DEBUG"] = os.getenv("FLASK_DEBUG", "False") == "True"

db = init_db()
app.register_blueprint(ranking_bp)

RESUME_COLLECTION = db.resumeFetchedData
JOBS_COLLECTION = db.JOBS
USERS_COLLECTION = db.USERS

EMAIL_RE = re.compile(r"[^@]+@[^@]+\.[^@]+")

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/upload", methods=["GET"])
def upload_form():
    # render a nicer upload form (template below)
    return render_template("upload.html")

@app.route("/upload_resume", methods=["POST"])
def upload_resume():
    # Server-side validation of mandatory fields
    candidate_name = (request.form.get("candidate_name") or "").strip()
    candidate_email = (request.form.get("candidate_email") or "").strip()
    if not candidate_name:
        flash("Please enter your Name.", "danger")
        return redirect(url_for("upload_form"))
    if not candidate_email or not EMAIL_RE.match(candidate_email):
        flash("Please enter a valid Email.", "danger")
        return redirect(url_for("upload_form"))

    file = request.files.get("resume")
    if not file:
        flash("Please upload a PDF resume", "danger")
        return redirect(url_for("upload_form"))

    # optional CGPA and optional user_id
    cgpa_raw = request.form.get("cgpa", "0")
    try:
        cgpa_val = float(cgpa_raw)
    except Exception:
        cgpa_val = 0.0

    user_id = request.form.get("user_id")
    if not user_id:
        # create a demo user if not supplied
        user_doc = {"Name": candidate_name, "Email": candidate_email}
        try:
            res = USERS_COLLECTION.insert_one(user_doc) if USERS_COLLECTION is not None else None
            user_id = str(res.inserted_id) if res else None
        except Exception:
            user_id = f"local-{os.urandom(4).hex()}"

    # read PDF bytes
    pdf_bytes = file.read()

    # parse resume (keeps existing parse logic / heuristics)
    try:
        parsed = parse_resume_bytes(pdf_bytes)
    except Exception as e:
        flash(f"Resume parser error: {e}", "danger")
        return redirect(url_for("upload_form"))

    if not isinstance(parsed, dict):
        parsed = {}

    # overwrite Name and Email with values provided by user (explicit)
    parsed["Name"] = candidate_name
    parsed["Email"] = candidate_email

    parsed["CGPA"] = cgpa_val

    # store UserId as ObjectId when possible
    try:
        parsed["UserId"] = ObjectId(user_id) if user_id and len(user_id) == 24 else user_id
    except Exception:
        parsed["UserId"] = user_id

    parsed["Filename"] = file.filename
    parsed["FileData"] = Binary(pdf_bytes)

    # Insert into DB
    try:
        if RESUME_COLLECTION is not None:
            RESUME_COLLECTION.insert_one(parsed)
            flash("Resume uploaded, parsed and saved to DB successfully", "success")
        else:
            flash("Resume parsed but MongoDB not available. Start DB to persist resumes.", "warning")
    except Exception as e:
        flash(f"Could not save resume to DB: {e}", "warning")

    # Useful server-side logging
    print(f"[upload_resume] saved resume for Name={parsed.get('Name')} Email={parsed.get('Email')} UserId={parsed.get('UserId')}")

    return redirect(url_for("index"))


@app.route("/company", methods=["GET", "POST"])
def company_dashboard():
    if request.method == "POST":
        # Enforce mandatory fields at server side too
        job_profile = (request.form.get("job_profile") or "").strip()
        if not job_profile:
            flash("Job profile is required.", "danger")
            return redirect(url_for("company_dashboard"))

        job_file = request.files.get("job_file")
        jd_bytes = None
        job_doc = {"Job_Profile": job_profile}
        if job_file:
            jd_bytes = job_file.read()
            job_doc["FileData"] = Binary(jd_bytes)

        try:
            if JOBS_COLLECTION is not None:
                JOBS_COLLECTION.insert_one(job_doc)
                flash("Job posted", "success")
            else:
                flash("MongoDB not available — job not saved. Start DB to persist jobs.", "warning")
        except Exception as e:
            flash(f"Could not save job: {e}", "warning")
        return redirect(url_for("company_dashboard"))

    try:
        jobs = list(JOBS_COLLECTION.find({})) if JOBS_COLLECTION is not None else []
    except Exception:
        jobs = []
        flash("Cannot fetch jobs from MongoDB. Start MongoDB or check MONGO_URI.", "warning")
    return render_template("company_dashboard.html", jobs=jobs)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=app.config["DEBUG"])
