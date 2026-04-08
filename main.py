import os
import time
import requests
import re
import json # <-- Imported for saving the file
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

app = FastAPI()

class RepoStoryRequest(BaseModel):
    url: str
    total_commits_to_fetch: int = 100 
    deep_dive_limit: int = 20 

def is_wanted_file(file_path):
    ignored_patterns = ['node_modules/', '.env', '.git/', '__pycache__/', 'dist/', 'build/', 'venv/']
    return not any(pattern in file_path for pattern in ignored_patterns)

@app.get("/", response_class=HTMLResponse)
async def serve_frontend():
    with open("index.html", "r") as f:
        return f.read()

@app.post("/api/fetch-repo-story")
async def fetch_repo_story(request: RepoStoryRequest):
    path = urlparse(request.url).path.strip('/')
    parts = path.split('/')
    if len(parts) < 2:
        return {"status": "error", "message": "Invalid GitHub URL format."}
        
    owner, repo = parts[0], parts[1].replace('.git', '')
    
    headers = {'Accept': 'application/vnd.github.v3+json'}
    if GITHUB_TOKEN:
        headers['Authorization'] = f"Bearer {GITHUB_TOKEN}"

    print(f"--- Extracting Story for {owner}/{repo} ---")
    story_data = {
        "repository": f"{owner}/{repo}",
        "context": {},
        "skeleton": [],
        "timeline": []
    }

    # 1. The Context (README)
    readme_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
    readme_headers = headers.copy()
    readme_headers['Accept'] = 'application/vnd.github.v3.raw' 
    readme_resp = requests.get(readme_url, headers=readme_headers)
    story_data["context"]["readme"] = readme_resp.text if readme_resp.status_code == 200 else "No README found."

    # 2. The Skeleton (File Tree)
    repo_url = f"https://api.github.com/repos/{owner}/{repo}"
    repo_resp = requests.get(repo_url, headers=headers)
    if repo_resp.status_code == 200:
        default_branch = repo_resp.json().get('default_branch', 'main')
        story_data["context"]["default_branch"] = default_branch
        
        tree_url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1"
        tree_resp = requests.get(tree_url, headers=headers)
        if tree_resp.status_code == 200:
            tree_data = tree_resp.json().get('tree', [])
            story_data["skeleton"] = [
                {"path": item['path'], "type": item['type']} 
                for item in tree_data if is_wanted_file(item['path'])
            ]

    # 3. The Timeline (Bulk Commits)
    page = 1
    commits_fetched = 0
    bulk_commits = []

    while commits_fetched < request.total_commits_to_fetch:
        commits_url = f"https://api.github.com/repos/{owner}/{repo}/commits?page={page}&per_page=100"
        response = requests.get(commits_url, headers=headers)
        
        if response.status_code != 200:
            break
            
        commits_page = response.json()
        if not commits_page:
            break 
            
        for commit in commits_page:
            if commits_fetched >= request.total_commits_to_fetch:
                break
                
            commit_info = {
                "hash": commit.get("sha"),
                "author": commit.get("commit", {}).get("author", {}).get("name"),
                "date": commit.get("commit", {}).get("author", {}).get("date"),
                "message": commit.get("commit", {}).get("message").split('\n')[0],
                "files_changed": [] 
            }
            bulk_commits.append(commit_info)
            commits_fetched += 1
            
        page += 1

    # 4. The Deep Dive (Selective File Details)
    deep_dive_count = 0
    for commit in bulk_commits:
        if deep_dive_count >= request.deep_dive_limit:
            break
            
        sha = commit["hash"]
        detail_url = f"https://api.github.com/repos/{owner}/{repo}/commits/{sha}"
        detail_response = requests.get(detail_url, headers=headers)
        
        if detail_response.status_code == 200:
            commit_detail = detail_response.json()
            commit["files_changed"] = [file.get("filename") for file in commit_detail.get("files", [])]
            
        deep_dive_count += 1
        # --- THE SAFETY PACER ---
        # 1 request per second = 60 requests per minute. Completely safe.
        time.sleep(1) 

    story_data["timeline"] = bulk_commits
    
    # 5. Save the data to the backend disk
    output_filename = f"{repo}_story.json"
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(story_data, f, indent=4)
    print(f"✅ Data successfully saved to {output_filename}")

    # 6. Return a lightweight summary to the frontend
    return {
        "status": "success", 
        "message": f"Analysis complete! Data saved to backend.",
        "file_created": output_filename,
        "metrics": {
            "skeleton_files_mapped": len(story_data["skeleton"]),
            "total_commits_fetched": len(bulk_commits),
            "deep_dives_performed": deep_dive_count
        }
    }