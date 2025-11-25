from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv

import PyPDF2
import docx
import re
import csv
import spacy
from spacy.lang.en.stop_words import STOP_WORDS
from mongoengine import connect, Document, StringField, ListField

# ---- Load environment variables ----
load_dotenv()
SCRAPINGDOG_API_KEY = os.getenv("SCRAPINGDOG_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")
nlp = spacy.load("en_core_web_sm")

connect(host=MONGO_URI, alias="default", uuidRepresentation="standard")

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ---- Load the master skills set ----
def load_skills(filepath="techset_list.csv"):
    skillset = set()
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            for row in csv.reader(f):
                skill = row[0].strip().lower()
                if skill:
                    skillset.add(skill)
    except Exception:
        pass
    return skillset

SKILLS = load_skills()

# ---- Utility Functions ----
def extract_text_from_pdf(file_path):
    text = ""
    try:
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
    except Exception:
        pass
    return text

def extract_text_from_docx(file_path):
    text = ""
    try:
        doc = docx.Document(file_path)
        text = " ".join([para.text for para in doc.paragraphs])
    except Exception:
        pass
    return text

def extract_job_skills(text):
    found_skills = set()
    text_lower = text.lower()
    # Check for each skill as a whole word/phrase
    for skill in SKILLS:
        skill_regex = r"\b" + re.escape(skill) + r"\b"
        if re.search(skill_regex, text_lower):
            found_skills.add(skill)
    return sorted(found_skills)

# ---- Database Models ----
class User(Document):
    email = StringField(required=True, unique=True)
    password = StringField(required=True)
    role = StringField(default='user')

class Resume(Document):
    filename = StringField(required=True)
    filepath = StringField()
    tag = StringField()
    skills = ListField(StringField())
    user_email = StringField()

class Application(Document):
    job_id = StringField()
    resume_id = StringField()
    user_email = StringField()
    status = StringField(default='submitted')

# ---- API Endpoints ----
@app.route('/api/register', methods=['POST'])
def register():
    email = request.json.get('email')
    password = request.json.get('password')
    role = request.json.get('role', 'user')
    if not email or not password:
        return jsonify({"error": "email and password required"}), 400
    if User.objects(email=email).first():
        return jsonify({"error": "email already in use"}), 409
    user = User(email=email, password=password, role=role)
    user.save()
    return jsonify({"msg": "User registered", "user": {"email": user.email, "role": user.role}}), 201

@app.route('/api/login', methods=['POST'])
def login():
    email = request.json.get('email')
    password = request.json.get('password')
    user = User.objects(email=email, password=password).first()
    if user:
        return jsonify({"msg": "Login successful", "user": {"email": user.email, "role": user.role}}), 200
    else:
        return jsonify({"error": "Invalid credentials"}), 401

@app.route('/api/resumes', methods=['POST'])
def upload_resume():
    if 'file' not in request.files or 'user_email' not in request.form:
        return jsonify({'error': 'Missing file or user_email'}), 400
    file = request.files['file']
    tag = request.form.get('tag', 'General')
    user_email = request.form['user_email']
    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    text = ""
    if file.filename.lower().endswith('.pdf'):
        text = extract_text_from_pdf(filepath)
    elif file.filename.lower().endswith('.docx'):
        text = extract_text_from_docx(filepath)

    skills = extract_job_skills(text)

    resume = Resume(
        filename=file.filename,
        filepath=filepath,
        tag=tag,
        skills=skills,
        user_email=user_email
    )
    resume.save()
    return jsonify({'msg': 'Resume uploaded', 'resume': {
        "id": str(resume.id), "filename": resume.filename, "skills": resume.skills, "tag": resume.tag
    }}), 201

@app.route('/api/resumes', methods=['GET'])
def list_resumes():
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Missing user_email'}), 400
    resumes = Resume.objects(user_email=user_email)
    return jsonify([{
        "id": str(r.id),
        "filename": r.filename,
        "tag": r.tag,
        "skills": r.skills
    } for r in resumes])

@app.route('/api/jobs', methods=['GET'])
def get_jobs():
    search = request.args.get('search')
    location = request.args.get('location', 'Pakistan')
    platform = request.args.get('platform', 'all').lower()
    user_email = request.args.get('user_email')
    page = int(request.args.get('page', '1'))  # for pagination (if your scraper supports)
    if not search or not user_email:
        return jsonify({"error": "Missing search or user_email"}), 400

    endpoint_map = {
        'linkedin': 'linkedinjobs',
        'indeed': 'indeedjobs',
        'glassdoor': 'glassdoorjobs',
        'ziprecruiter': 'ziprecruiterjobs'
    }

    # Resume skills
    resume = Resume.objects(user_email=user_email).order_by('-id').first()
    resume_skills = set(resume.skills) if resume else set()
    # User's search skills
    search_skills = set(extract_job_skills(search))
    full_match_set = resume_skills | search_skills

    def calc_match(job):
        job_fields = [
            job.get('job_position', ''),
            job.get('job_location', ''),
            job.get('company_name', ''),
            job.get('company_profile', ''),
            job.get('job_description', ''),
            job.get('description', ''),
            job.get('job_posting_date', '')
        ]
        job_text = ' '.join([str(f) for f in job_fields if f])
        job_skills = set(extract_job_skills(job_text))
        # Match combines explicit job field skills with all extracted/known
        return len(full_match_set & job_skills)

    result = []
    if platform == 'all' or platform not in endpoint_map:
        for plat, endpoint in endpoint_map.items():
            api_url = f"https://api.scrapingdog.com/{endpoint}?api_key={SCRAPINGDOG_API_KEY}&search={search}&location={location}&page={page}"
            try:
                resp = requests.get(api_url)
                data = resp.json()
                if isinstance(data, list):
                    for job in data:
                        job['match_score'] = calc_match(job)
                        result.append(job)
            except Exception:
                continue
        result = sorted(result, key=lambda x: x.get('match_score', 0), reverse=True)
        return jsonify(result)
    else:
        endpoint = endpoint_map[platform]
        api_url = f"https://api.scrapingdog.com/{endpoint}?api_key={SCRAPINGDOG_API_KEY}&search={search}&location={location}&page={page}"
        try:
            resp = requests.get(api_url)
            data = resp.json()
            if isinstance(data, list):
                for job in data:
                    job['match_score'] = calc_match(job)
                data = sorted(data, key=lambda x: x.get('match_score', 0), reverse=True)
            return jsonify(data)
        except Exception as e:
            return jsonify({"error": str(e)}), 502

@app.route('/api/applications', methods=['POST'])
def apply_to_job():
    job_id = request.json.get('job_id')
    resume_id = request.json.get('resume_id')
    user_email = request.json.get('user_email')
    if not job_id or not resume_id or not user_email:
        return jsonify({"error": "job_id, resume_id, user_email required"}), 400
    application = Application(
        job_id=job_id,
        resume_id=resume_id,
        user_email=user_email,
        status="submitted"
    )
    application.save()
    return jsonify({"msg": "Application submitted", "application": {
        "id": str(application.id), "job_id": job_id, "resume_id": resume_id, "user_email": user_email
    }}), 201

@app.route('/api/applications', methods=['GET'])
def get_applications():
    user_email = request.args.get('user_email')
    if not user_email:
        return jsonify({'error': 'Missing user_email'}), 400
    apps = Application.objects(user_email=user_email)
    return jsonify([{
        "id": str(a.id),
        "job_id": a.job_id,
        "resume_id": a.resume_id,
        "status": a.status
    } for a in apps])

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
