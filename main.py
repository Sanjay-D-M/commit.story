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
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
import numpy as np

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

# Initialize the embedding model globally for performance
try:
    embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    print("✅ Embedding model loaded successfully")
except Exception as e:
    print(f"⚠️  Could not load embedding model: {e}")
    embedding_model = None

def translate_path_to_english(file_path):
    """Translate file paths to natural language descriptions for semantic matching."""
    path_lower = file_path.lower()

    # Frontend patterns
    if any(pattern in path_lower for pattern in ['src/components', 'components/', 'jsx', 'tsx', 'vue', 'svelte']):
        return "Frontend user interface component"
    elif any(pattern in path_lower for pattern in ['src/pages', 'pages/', 'views/']):
        return "Frontend page or view component"
    elif any(pattern in path_lower for pattern in ['src/hooks', 'hooks/', 'composables']):
        return "Frontend custom hook or composable"
    elif any(pattern in path_lower for pattern in ['src/utils', 'utils/', 'helpers']):
        return "Frontend utility functions"
    elif any(pattern in path_lower for pattern in ['src/styles', 'styles/', 'css', 'scss', 'sass']):
        return "Frontend styling and CSS"
    elif any(pattern in path_lower for pattern in ['public/', 'assets/', 'static/']):
        return "Frontend static assets"

    # Backend patterns
    elif any(pattern in path_lower for pattern in ['backend/', 'server/', 'api/', 'routes']):
        return "Backend API routes and endpoints"
    elif any(pattern in path_lower for pattern in ['models/', 'schemas/', 'entities']):
        return "Backend database models and schemas"
    elif any(pattern in path_lower for pattern in ['controllers/', 'services/', 'business']):
        return "Backend business logic and services"
    elif any(pattern in path_lower for pattern in ['middleware/', 'auth/', 'security']):
        return "Backend authentication and security"
    elif any(pattern in path_lower for pattern in ['config/', 'settings']):
        return "Backend configuration and settings"

    # Database patterns
    elif any(pattern in path_lower for pattern in ['migrations/', 'seeds/', 'fixtures']):
        return "Database schema migrations and seeds"
    elif any(pattern in path_lower for pattern in ['queries/', 'repositories']):
        return "Database queries and data access"

    # DevOps/CI patterns
    elif any(pattern in path_lower for pattern in ['dockerfile', 'docker-compose', 'kubernetes']):
        return "Containerization and deployment configuration"
    elif any(pattern in path_lower for pattern in ['.github/workflows', 'ci/', 'cd/']):
        return "Continuous integration and deployment"
    elif any(pattern in path_lower for pattern in ['package.json', 'requirements.txt', 'pyproject.toml']):
        return "Project dependencies and configuration"
    elif any(pattern in path_lower for pattern in ['readme', 'docs/', 'documentation']):
        return "Project documentation and guides"

    # Testing patterns
    elif any(pattern in path_lower for pattern in ['test/', 'tests/', 'spec/', '__tests__']):
        return "Automated tests and test suites"

    # Default fallback based on file extension
    elif path_lower.endswith(('.py', '.js', '.ts', '.java', '.cpp', '.c', '.go', '.rs')):
        return "Source code implementation"
    elif path_lower.endswith(('.md', '.txt', '.rst')):
        return "Documentation and text files"
    elif path_lower.endswith(('.json', '.yaml', '.yml', '.xml', '.ini', '.cfg')):
        return "Configuration and data files"
    else:
        return "Project file"

def calculate_confidence(commit_message, files_changed):
    """Calculate Say-Do Alignment confidence score (1.0, 0.75, 0.5)."""
    if not embedding_model or not files_changed:
        return 0.5  # Default low confidence if model not available

    try:
        # Convert file paths to English descriptions
        file_descriptions = " ".join([translate_path_to_english(f) for f in files_changed])

        # Embed both the commit message and file descriptions
        msg_vector = embedding_model.encode([commit_message])
        file_vector = embedding_model.encode([file_descriptions])

        # Calculate cosine similarity
        similarity = cosine_similarity(msg_vector, file_vector)[0][0]

        # Apply threshold logic for confidence scores
        if similarity > 0.8:
            return 1.0  # High Confidence - Say matches Do
        elif similarity > 0.4:
            return 0.75  # Partial Confidence - Some alignment
        else:
            return 0.5  # Low Confidence - Mismatch or unclear

    except Exception as e:
        print(f"Error calculating confidence: {e}")
        return 0.5

def cluster_commits_by_architecture(commits):
    """Group commits by architectural components using K-Means clustering."""
    if not embedding_model or not commits:
        return {}

    try:
        # Extract commit messages and create embeddings
        messages = [commit.get('message', '') for commit in commits if commit.get('message')]
        if not messages:
            return {}

        embeddings = embedding_model.encode(messages)

        # Use K-Means to cluster into architectural groups
        # We'll use 4 clusters: Frontend, Backend, Database, DevOps
        n_clusters = min(4, len(messages))
        kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
        clusters = kmeans.fit_predict(embeddings)

        # Group commits by cluster
        architecture_groups = {
            'frontend': [],
            'backend': [],
            'database': [],
            'devops': []
        }

        cluster_names = ['frontend', 'backend', 'database', 'devops']

        for i, commit in enumerate(commits):
            if i < len(clusters):
                cluster_name = cluster_names[clusters[i] % len(cluster_names)]
                architecture_groups[cluster_name].append(commit)

        return architecture_groups

    except Exception as e:
        print(f"Error clustering commits: {e}")
        return {}

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
    
    # 6. Say-Do Alignment Analysis (NEW FEATURE)
    print("🔍 Analyzing Say-Do Alignment...")
    alignment_insights = {
        "confidence_distribution": {"high": 0, "medium": 0, "low": 0},
        "developer_scores": {},
        "architecture_clusters": {},
        "problematic_commits": []
    }
    
    for commit in bulk_commits:
        if commit.get("files_changed"):
            confidence = calculate_confidence(commit["message"], commit["files_changed"])
            commit["alignment_confidence"] = confidence
            
            # Update distribution
            if confidence == 1.0:
                alignment_insights["confidence_distribution"]["high"] += 1
            elif confidence == 0.75:
                alignment_insights["confidence_distribution"]["medium"] += 1
            else:
                alignment_insights["confidence_distribution"]["low"] += 1
                alignment_insights["problematic_commits"].append({
                    "hash": commit["hash"],
                    "message": commit["message"],
                    "confidence": confidence,
                    "files_changed": commit["files_changed"]
                })
            
            # Track developer scores
            author = commit.get("author", "Unknown")
            if author not in alignment_insights["developer_scores"]:
                alignment_insights["developer_scores"][author] = {
                    "total_commits": 0, "avg_confidence": 0.0, "high_count": 0
                }
            
            dev_stats = alignment_insights["developer_scores"][author]
            dev_stats["total_commits"] += 1
            dev_stats["avg_confidence"] = (
                (dev_stats["avg_confidence"] * (dev_stats["total_commits"] - 1)) + confidence
            ) / dev_stats["total_commits"]
            if confidence == 1.0:
                dev_stats["high_count"] += 1
    
    # Calculate architecture clusters
    alignment_insights["architecture_clusters"] = cluster_commits_by_architecture(bulk_commits)
    
    story_data["alignment_insights"] = alignment_insights
    
    # 7. Save the data to the backend disk
    output_filename = f"{repo}_story.json"
    with open(output_filename, 'w', encoding='utf-8') as f:
        json.dump(story_data, f, indent=4)
    print(f"✅ Data successfully saved to {output_filename}")
    print(f"📊 Say-Do Alignment: {alignment_insights['confidence_distribution']['high']} high, {alignment_insights['confidence_distribution']['medium']} medium, {alignment_insights['confidence_distribution']['low']} low confidence commits")

    # 8. Return a lightweight summary to the frontend
    return {
        "status": "success", 
        "message": f"Analysis complete! Data saved to backend.",
        "file_created": output_filename,
        "metrics": {
            "skeleton_files_mapped": len(story_data["skeleton"]),
            "total_commits_fetched": len(bulk_commits),
            "deep_dives_performed": deep_dive_count,
            "alignment_analysis": {
                "high_confidence_commits": alignment_insights["confidence_distribution"]["high"],
                "medium_confidence_commits": alignment_insights["confidence_distribution"]["medium"],
                "low_confidence_commits": alignment_insights["confidence_distribution"]["low"],
                "problematic_commits_count": len(alignment_insights["problematic_commits"])
            }
        }
    }