# Story Submission Tracker

A mobile-friendly application for tracking story submissions for a writer. It supports status tracking, Excel/CSV import, Excel export, and a color-coded dashboard.

## Features
- Add and update story submissions
- Track the following fields:
  - Story Name
  - Submitted to (Entity Name)
  - Status (submitted, accepted, rejected, withdrawn)
  - Date of Submission
  - Date of Response
  - URL for the Story
- Dashboard summary by submission status and entity
- Search and filter by story name and status
- Upload existing submissions from Excel or CSV
- Export the current dataset into Excel
- Responsive layout for phone and desktop browsing

## Local run
1. Create a virtual environment:
   python -m venv .venv
2. Activate it:
   - Windows: .venv\Scripts\activate
   - macOS/Linux: source .venv/bin/activate
3. Install dependencies:
   pip install -r requirements.txt
4. Create a local secret file if you want Google login enabled:
   - Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml`
   - Fill in your Google OAuth values
5. Start the app:
   streamlit run app.py

## Streamlit Community Cloud deployment
1. Push this repository to GitHub
2. In Streamlit Cloud, create a new app and connect the GitHub repo
3. Set the app entrypoint to `app.py`
4. Add the following secrets in the Streamlit Cloud UI:

   ```toml
   GOOGLE_CLIENT_ID = "<your-google-client-id>.apps.googleusercontent.com"
   GOOGLE_CLIENT_SECRET = "<your-google-client-secret>"
   GOOGLE_REDIRECT_URI = "https://<your-app-name>.streamlit.app"
   ```

5. In Google Cloud Console, add this redirect URI exactly:
   `https://<your-app-name>.streamlit.app`

6. Deploy the app and sign in with Google or a local account

## Google OAuth setup
1. Create a project in Google Cloud Console
2. Enable the Google Identity / OAuth APIs
3. Create OAuth 2.0 Client ID credentials
4. Add the redirect URI for your deployment target
5. Copy the client ID and client secret into Streamlit Cloud secrets

> For local testing, use `http://localhost:8501` as the redirect URI.

## Data persistence
The app stores records in a SQLite database at `data/story_submissions.db`.
