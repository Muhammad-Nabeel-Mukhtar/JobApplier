from flask import Flask, request, jsonify
import requests
import os
from dotenv import load_dotenv

import PyPDF2
import docx
from mongoengine import connect, Document, StringField, ListField

# ---- Load environment variables ----
load_dotenv()
SCRAPINGDOG_API_KEY = os.getenv("SCRAPINGDOG_API_KEY")
MONGO_URI = os.getenv("MONGO_URI")

connect(host=MONGO_URI, alias="default", uuidRepresentation="standard")

app = Flask(__name__)
UPLOAD_FOLDER = 'uploads'
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)

# ---- Utility for resume text extraction and skill parsing ----
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

def simple_skill_extraction(text):
    # Tokenize by words, keep unique lowercase tokens with length >= 4 (basic heuristics)
    import re
    tokens = set(re.findall(r'\b\w{4,}\b', text.lower()))
    # Filter out common stop words (you can expand/remove as needed)
    stopwords = set([
        'about','above','after','again','against','among','because','been','before','being','below',
        'between','both','but','can','could','did','does','doing','down','during','each','few',
        'from','further','have','having','here','into','more','most','other','over','some','such',
        'than','that','their','there','these','they','this','those','under','until','very','with','would'
    ])
    skills = [w for w in tokens if w not in stopwords]
    return skills

# ---- Database Models ----
class User(Document):
    email = StringField(required=True, unique=True)
    password = StringField(required=True)
    role = StringField(default='user')

class Resume(Document):
    filename = StringField(required=True)
    filepath = StringField()
    tag = StringField()
    user_email = StringField()
    skills = ListField(StringField())

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
    skills = simple_skill_extraction(text)
    resume = Resume(
        filename=file.filename,
        filepath=filepath,
        tag=tag,
        user_email=user_email,
        skills=skills
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
    user_email = request.args.get('user_email')
    platform = request.args.get('platform', 'linkedin')
    page = int(request.args.get('page', '1'))
    if not search or not user_email:
        return jsonify({"error": "Missing search or user_email"}), 400

    endpoint_map = {
        'linkedin': 'linkedinjobs',
        'indeed': 'indeedjobs',
        'glassdoor': 'glassdoorjobs',
        'ziprecruiter': 'ziprecruiterjobs'
    }
    endpoint = endpoint_map.get(platform, 'linkedinjobs')
    api_url = f"https://api.scrapingdog.com/{endpoint}?api_key={SCRAPINGDOG_API_KEY}&search={search}&location={location}&page={page}"

    # Get user's latest resume skills
    resume = Resume.objects(user_email=user_email).order_by('-id').first()
    resume_skills = set(str(s).lower() for s in resume.skills) if resume else set()

    try:
        resp = requests.get(api_url)
        data = resp.json()
        # Rank jobs by skills in job fields if resume is uploaded
        for job in data:
            job_fields = [
                job.get('job_position', ''),
                job.get('job_location', ''),
                job.get('company_name', ''),
                job.get('company_profile', ''),
                job.get('job_description', ''),
                job.get('description', ''),
                job.get('job_posting_date', '')
            ]
            job_text = ' '.join([str(f) for f in job_fields if f]).lower()
            match_count = 0
            if resume_skills:
                for skill in resume_skills:
                    if skill in job_text:
                        match_count += 1
            job['match_score'] = match_count
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
