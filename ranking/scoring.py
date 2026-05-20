# ranking/scoring.py
def compute_resume_score(parsed_resume, cgpa_value, equivalence_similarity):
    # Skills: 1 pt per skill, max 20
    skills_field = parsed_resume.get("SKILLS") or parsed_resume.get("skills") or []
    num_skills = len(skills_field) if isinstance(skills_field,(list,tuple)) else (1 if skills_field else 0)
    skills_points = min(num_skills,20) * 1

    # Experience entries: 10 pts per entry, max 20
    exp_field = parsed_resume.get("WORKED_AS") or parsed_resume.get("EXPERIENCE") or parsed_resume.get("experience") or []
    num_exp = len(exp_field) if isinstance(exp_field,(list,tuple)) else (1 if exp_field else 0)
    experience_points = min(num_exp * 10, 20)

    # Certifications: 5 pts each, max 10
    cert_field = parsed_resume.get("CERTIFICATIONS") or parsed_resume.get("certifications") or parsed_resume.get("certificate") or []
    num_certs = len(cert_field) if isinstance(cert_field,(list,tuple)) else (1 if cert_field else 0)
    certification_points = min(num_certs * 5, 10)

    # CGPA: 2.5 * cgpa (cap 25)
    try:
        cgpa = float(cgpa_value)
    except Exception:
        cgpa = 0.0
    cgpa_points = min(2.5 * cgpa, 25)

    # Equivalence: similarity 0..1 mapped to 25
    try:
        eq = float(equivalence_similarity)
    except Exception:
        eq = 0.0
    eq = max(0.0, min(1.0, eq))
    equivalence_points = eq * 25

    total = skills_points + experience_points + certification_points + cgpa_points + equivalence_points
    total = round(total, 2)
    breakdown = {"skills": round(skills_points,2), "experience": round(experience_points,2),
                 "certifications": round(certification_points,2), "cgpa": round(cgpa_points,2),
                 "equivalence": round(equivalence_points,2)}
    return {"total_score": total, "points_breakdown": breakdown}
