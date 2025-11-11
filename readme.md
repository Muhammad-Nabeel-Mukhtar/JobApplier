text
# Job Aggregation & Resume Matching Backend – NLP Edition

## Overview
This backend API aggregates jobs from LinkedIn, Indeed, Glassdoor, ZipRecruiter via ScrapingDog, enables resume uploads, and uses advanced NLP (spaCy) to extract skills for relevant job matching. Jobs are ranked by how well they match the user's resume.

---

## Directory Structure

App/
├── app.py # Unified backend with NLP matching
├── requirements.txt # Python dependencies
├── .env # Store API secrets (not in version control)
├── Dockerfile # Optional: for Docker deployments
├── Procfile # Optional: for Heroku
├── readme.md # This file
├── uploads/ # Stores uploaded resumes

text

---

## Setup

1. **Install Python requirements:**
pip install -r requirements.txt
python -m spacy download en_core_web_sm



2. **Create `.env` file in root folder:**
SCRAPINGDOG_API_KEY=your_scrapingdog_api_key_here



3. **Run the API locally:**
python app.py



The API will listen on `localhost:5000`.

---

## API Endpoints

### **Authentication**
- `/api/register` [POST]: Register new user  
- `{ "email": "...", "password": "...", "role": "user" }`
- `/api/login` [POST]: Log in user  
- `{ "email": "...", "password": "..." }`

### **Resume Management**
- `/api/resumes` [POST]: Upload a resume (`form-data`, keys: `file`, `tag`)  
- Resumes (PDF/DOCX) parsed with NLP to extract user skills
- `/api/resumes` [GET]: List uploaded resumes with extracted skills

### **Job Search & Matching**
- `/api/jobs` [GET]: Search jobs and get multi-platform aggregation  
- **Query params:**  
 - `search` (required): job keyword  
 - `location` (optional, default: "Pakistan")  
 - `platform` (optional): one of `[all, linkedin, indeed, glassdoor, ziprecruiter]`, default: "all"
- **Returns:**  
 Jobs ranked by `"match_score"`: overlap of extracted resume skills and job details
- **Response example:**
 ```
 [
   {
     "company_name": "...",
     "job_position": "...",
     "job_location": "...",
     "job_link": "...",
     "match_score": 14
   }
 ]
 ```

### **Application Tracking**
- `/api/applications` [POST]: Log a job application  
- `{ "job_id": "...", "resume_id": ..., "user_id": ... }`
- `/api/applications` [GET]: List all application logs for the session

---

## Deployment

- **Heroku:** Use Procfile: `web: python app.py`
- **Docker:**  
FROM python:3.10
WORKDIR /app
COPY . .
RUN pip install --upgrade pip
RUN pip install -r requirements.txt
RUN python -m spacy download en_core_web_sm
EXPOSE 5000
CMD ["python", "app.py"]


- **AWS/Other:** Install `.env`, dependencies, setup writable `uploads/` folder

---

## Features & Notes

- **NLP-based skill extraction:** Uses spaCy to pull noun phrases and lemmatized words from resumes and jobs for best-match recommendations.
- **Multi-platform aggregation:** User can select board or "All" for maximum results.
- **Application logging:** Tracks user submissions internally—actual job applies done on the board using job links.
- **User authentication, resume management and dashboard logic in-memory for MVP. Upgrade to a database for production.

---

