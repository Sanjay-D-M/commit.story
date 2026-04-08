# Repository Story Extractor

A FastAPI web application that extracts and visualizes the development story of GitHub repositories. It fetches repository metadata, file structures, commit history, and detailed file change information.

## Features

- **Repository Context**: Extracts README and default branch information
- **File Skeleton**: Maps the complete directory structure of the repository
- **Commit Timeline**: Fetches commit history with author, date, and message information
- **Deep Dive Analysis**: Detailed file change information for selected commits
- **API Rate Limiting**: Built-in safety pacing to respect GitHub API limits
- **GitHub Token Support**: Optional personal access token for higher rate limits

## Project Structure

```
.
├── main.py                      # FastAPI application and API endpoints
├── github_commit_fetcher.py     # GitHub API interaction utilities
├── index.html                   # Frontend user interface
├── requirements.txt             # Python dependencies
├── .env                         # Environment variables (not in git)
└── README.md                    # This file
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/hackathon-dev-tools.git
cd hackathon-dev-tools
```

2. Create a virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up environment variables (optional):
```bash
cp .env.example .env
# Edit .env and add your GITHUB_ACCESS_TOKEN
```

## Usage

1. Start the FastAPI server:
```bash
uvicorn main:app --reload
```

2. Open your browser and navigate to:
```
http://localhost:8000
```

3. Enter a GitHub repository URL (e.g., `https://github.com/facebook/react`)

4. Click "Start Extraction Pipeline" and wait for analysis to complete

The extracted data will be saved as a JSON file on the server with the following structure:
- `repository`: Repository identifier
- `context`: README and branch information
- `skeleton`: File tree structure
- `timeline`: Commit history with file changes

## Configuration

Environment variables in `.env`:
- `GITHUB_ACCESS_TOKEN`: Optional GitHub personal access token for increased rate limits

## API Endpoints

- **GET `/`**: Serves the frontend HTML page
- **POST `/api/fetch-repo-story`**: Main extraction endpoint

### Request Body
```json
{
  "url": "https://github.com/owner/repo",
  "total_commits_to_fetch": 100,
  "deep_dive_limit": 20
}
```

### Response
```json
{
  "status": "success",
  "file_created": "repo_story.json",
  "metrics": {
    "skeleton_files_mapped": 150,
    "total_commits_fetched": 100,
    "deep_dives_performed": 20
  }
}
```

## Rate Limiting

The application includes automatic rate limiting:
- 1 request per second during deep dive analysis (~3000 requests/hour)
- Stays well within GitHub API limits (5000 requests/hour with token)

## Requirements

- Python 3.8+
- FastAPI
- Uvicorn
- Requests
- python-dotenv

## License

MIT

## Author

Created for Hackathon Dev Tools project
