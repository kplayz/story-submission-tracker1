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
4. Start the app:
   streamlit run app.py

## Hugging Face Spaces deployment
1. Create a new Hugging Face Space
2. Select Python and Streamlit
3. Connect this repository or upload the files directly
4. Keep the app entrypoint as `app.py`
5. Deploy with the included `requirements.txt`

## Data persistence
The app stores records in a SQLite database at `data/story_submissions.db`.
