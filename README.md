# 🚀 Intelligent Resume Screening & Ranking System

An AI-powered web application that automates **resume screening and candidate ranking** using Natural Language Processing (NLP), semantic similarity, and a customizable weighted scoring framework.

---

## 📌 Overview

Modern recruitment systems struggle with handling large volumes of applications efficiently. Traditional Applicant Tracking Systems (ATS) rely heavily on **keyword matching**, often ignoring contextual relevance and candidate competency.

This project introduces an **Intelligent Resume Screening System** that:

* Extracts structured information from resumes using NLP
* Evaluates candidates semantically against job descriptions
* Applies a customizable weighted scoring model
* Generates transparent and explainable rankings

📄 Based on research: *“Intelligent Applicant Screening and Ranking with Custom Weighted Scoring”* 

---

## 🎯 Key Features

### 🧠 AI-Based Resume Analysis

* NLP-powered resume parsing using **spaCy (NER)**
* Extracts:

  * Skills
  * Experience
  * Certifications
  * CGPA
  * Projects

### 🔍 Semantic Matching

* TF-IDF + Cosine Similarity
* Matches **meaning**, not just keywords
* Handles:

  * Synonyms
  * Contextual relationships

### ⚖️ Custom Weighted Scoring

Flexible evaluation model:

| Parameter      | Description                        |
| -------------- | ---------------------------------- |
| Skills         | Technical & domain skill relevance |
| Experience     | Work experience & relevance        |
| CGPA           | Academic performance               |
| Certifications | Professional credentials           |
| Projects       | Practical exposure                 |
| Job Similarity | Semantic alignment with JD         |

✔ Recruiters can adjust weights dynamically

---

## 🏗️ System Architecture

The system follows a **modular pipeline architecture**:

* Resume Input → Preprocessing → NLP Parsing
* Job Description Modeling
* Semantic Similarity Computation
* Weighted Scoring Engine
* Ranking & Comparison Output

📌 End-to-end pipeline ensures:

* Accuracy
* Transparency
* Scalability

---

## ⚙️ Methodology

### 1️⃣ Resume Preprocessing

* PDF → Text conversion
* Cleaning (stopwords, formatting, noise removal)
* Tokenization & normalization

### 2️⃣ NLP-Based Parsing

* Custom **Named Entity Recognition (NER)**
* Extracts structured candidate attributes

### 3️⃣ Job Profile Modeling

* Converts job description into structured format:

  * Skills
  * Experience requirements
  * Certifications

### 4️⃣ Semantic Similarity

* TF-IDF vectorization
* Cosine similarity computation

### 5️⃣ Weighted Scoring

Final score computed as:

```
Final Score = Σ (Weight × Feature Score)
```

### 6️⃣ Ranking & Comparison

* Candidates sorted by score
* Resume-to-resume comparison supported

---

## 🖥️ Tech Stack

### 🔹 Backend

* Python
* Flask

### 🔹 NLP & ML

* spaCy (NER)
* Scikit-learn
* TF-IDF
* Cosine Similarity

### 🔹 Frontend

* HTML5
* CSS3
* JavaScript

### 🔹 Database

* MongoDB Atlas

---

## 📊 Results & Performance

* ⏱️ **90% reduction in screening time**
* 📈 Processes **50 resumes in <5 minutes**
* 🎯 Improved accuracy vs keyword-based ATS
* 🔍 Transparent scoring increases recruiter trust

✔ System aligns closely with human evaluation
✔ Reduces bias and inconsistency

---

## 📸 Key Outputs

### 📊 Ranking Dashboard

* Displays sorted candidates
* Shows final scores

### 📈 Score Breakdown

* Skill score
* Experience score
* Certification score
* Similarity score

### 📄 Export Feature

* CSV export for HR teams

---

## 📁 Project Structure

```id="projstruct1"
Resume-Ranking-System/
│
├── app.py
├── Matching.py
├── Job_post.py
├── database.py
├── requirements.txt
│
├── templates/
├── static/
│   ├── css/
│   ├── images/
│   ├── uploaded_resumes/
│   └── Job_Description/
│
├── testdata/
├── .gitignore
└── README.md
```

---

## 🚀 How to Run

```bash
git clone https://github.com/piyushsangore/Resume-Ranking-System.git
cd Resume-Ranking-System
pip install -r requirements.txt
python app.py
```

Open:

```
http://127.0.0.1:5000/
```

---

## 🔒 Security & Best Practices

* Sensitive files excluded using `.gitignore`
* No API keys or credentials exposed
* Scalable architecture for deployment

---

## 🔮 Future Scope

* 🤖 Transformer-based models (BERT)
* 🌍 Multilingual resume support
* 📱 Mobile interface for recruiters
* 📊 Advanced HR analytics dashboard
* ⚖️ Bias detection & fairness analysis

---

## 🎓 Acknowledgment

Developed under the guidance of
**Prof. Shubhangi Kamble**
Vishwakarma Institute of Technology, Pune

---

## 👨‍💻 Author

* Piyush Sangore

---

## ⭐ Support

If you found this project useful:

⭐ Star the repository
📢 Share with others
💼 Add it to your portfolio

---
