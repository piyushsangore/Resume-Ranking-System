# parser/matching_wrapper.py
"""
Wrapper to load the project's Matching.py and call parse_resume_bytes(pdf_bytes).
This gives clear, explicit errors when Matching.py fails to import.
"""

import importlib
import traceback

def _import_matching_module():
    try:
        # Matching.py is expected to be at project root (same folder as app.py).
        mod = importlib.import_module("Matching")
        return mod
    except Exception as e:
        tb = traceback.format_exc()
        raise RuntimeError(
            "Failed to import Matching.py. Make sure Matching.py is present in the project root "
            "and that its Python dependencies are installed. Original import error: {}\nTraceback:\n{}".format(e, tb)
        )

_MATCHING = _import_matching_module()

def parse_resume_bytes(pdf_bytes: bytes) -> dict:
    """
    Public API used by app.py: returns a dict with keys:
      SKILLS, WORKED_AS, CERTIFICATIONS, PROJECTS, SUMMARY, EDUCATION, CGPA (if set), Filename, UserId
    """
    # Prefer a function defined in Matching.py if present and not this wrapper.
    if hasattr(_MATCHING, "parse_resume_bytes") and callable(_MATCHING.parse_resume_bytes):
        try:
            return _MATCHING.parse_resume_bytes(pdf_bytes)
        except Exception as e:
            tb = traceback.format_exc()
            raise RuntimeError(f"Matching.parse_resume_bytes() failed: {e}\n{tb}")
    # fallback: check for parse_resume(path)
    if hasattr(_MATCHING, "parse_resume") and callable(_MATCHING.parse_resume):
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
        try:
            tmp.write(pdf_bytes)
            tmp.flush()
            tmp.close()
            res = _MATCHING.parse_resume(tmp.name)
            return res
        finally:
            try:
                os.unlink(tmp.name)
            except Exception:
                pass
    # no parser found
    raise AttributeError("Matching.py found but no parse_resume_bytes or parse_resume function present.")































# # parser/matching_wrapper.py
# """
# Lazy-loading wrapper for the heavy parser (Matching.py) placed in project root.

# Behavior:
#  - Does NOT import Matching at module import time.
#  - When parse_resume_bytes() is called, attempts to import Matching.
#  - If Matching import fails due to missing dependencies (e.g. spaCy), raises a RuntimeError
#    with clear instructions on what to install.
#  - If Matching exposes parse_resume_bytes(bytes) it uses that. Otherwise, if it has parse_resume(path)
#    it writes bytes to a temp file and calls it.
# """

# import importlib
# import tempfile
# import os
# import traceback

# def _import_matching_module():
#     """
#     Try to import Matching module and return it.
#     If import fails, raise a RuntimeError with actionable instructions.
#     """
#     try:
#         mod = importlib.import_module("Matching")
#         return mod
#     except Exception as e:
#         msg = str(e)
#         if "No module named 'spacy'" in msg or ("ModuleNotFoundError" in msg and "spacy" in msg):
#             raise RuntimeError(
#                 "Failed to import Matching.py because spaCy is not installed in this environment.\n"
#                 "Install spaCy in the active venv and the language model required by Matching.py.\n\n"
#                 "Commands (Windows PowerShell):\n"
#                 "    pip install spacy\n"
#                 "    python -m spacy download en_core_web_sm\n\n"
#                 "If Matching.py expects a different model (e.g. en_core_web_trf), open Matching.py and\n"
#                 "check the spacy.load(...) argument and install that model instead.\n\n"
#                 f"Original import error: {e}"
#             )
#         raise RuntimeError(
#             "Failed to import Matching.py. Make sure Matching.py is present in the project root and\n"
#             "that any of its Python dependencies (spaCy, nltk, transformers, etc.) are installed.\n"
#             "Open Matching.py to see the `import` statements and install missing packages.\n\n"
#             f"Original import error: {e}\n\nTraceback:\n{traceback.format_exc()}"
#         )

# def _call_parser_bytes(mod, pdf_bytes):
#     # Try bytes API first
#     if hasattr(mod, "parse_resume_bytes"):
#         return mod.parse_resume_bytes(pdf_bytes)
#     # Try path-based API
#     if hasattr(mod, "parse_resume"):
#         tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
#         try:
#             tmp.write(pdf_bytes)
#             tmp.flush()
#             tmp.close()
#             return mod.parse_resume(tmp.name)
#         finally:
#             try:
#                 os.unlink(tmp.name)
#             except Exception:
#                 pass
#     # No parse API found
#     raise AttributeError("Matching.py found but no parse_resume_bytes(pdf_bytes) or parse_resume(path) function found.")

# def parse_resume_bytes(pdf_bytes):
#     """
#     Public function to parse resume bytes using the heavy parser.
#     This will import Matching.py at call-time and surface clear errors if installation is incomplete.
#     """
#     mod = _import_matching_module()
#     try:
#         result = _call_parser_bytes(mod, pdf_bytes)
#         return result
#     except Exception as e:
#         # If parser raised, include traceback to help debugging
#         raise RuntimeError(f"Matching parser call failed: {e}\n\nTraceback:\n{traceback.format_exc()}")
