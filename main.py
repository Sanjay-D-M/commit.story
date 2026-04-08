import json
import os
import re
import requests
from collections import Counter
from datetime import datetime
from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from urllib.parse import urlparse

load_dotenv()
GITHUB_TOKEN = os.getenv("GITHUB_ACCESS_TOKEN")

RUNS_DIR = "runs"
os.makedirs(RUNS_DIR, exist_ok=True)

print("Booting AI Model for Semantic Noise Removal...")
model = SentenceTransformer('all-MiniLM-L6-v2')

app = FastAPI()

class AnalyzeRequest(BaseModel):
    url: str
    user_type: str = "tech"   # 'tech' or 'non-tech'
    limit: int = 100


# --- Helpers ---

def detect_frameworks(tree_paths):
    stack = set()
    for path in tree_paths:
        p = path.lower()
        if 'package.json' in p:                             stack.add('Node.js')
        if 'requirements.txt' in p or p.endswith('.py'):   stack.add('Python')
        if p.endswith('.go'):                               stack.add('Go')
        if p.endswith('.rs'):                               stack.add('Rust')
        if p.endswith('.tsx') or p.endswith('.jsx'):        stack.add('React')
        if p.endswith('.java'):                             stack.add('Java')
        if p.endswith('.rb'):                               stack.add('Ruby')
        if p.endswith(('.cpp', '.cc')):                     stack.add('C++')
        if 'dockerfile' in p or 'docker-compose' in p:     stack.add('Docker')
        if p.endswith('.sql') or 'prisma' in p:             stack.add('SQL / Database')
        if '.github' in p and '.yml' in p:                 stack.add('GitHub Actions')
        if p.endswith(('.tf', '.tfvars')):                  stack.add('Terraform')
    return sorted(stack) if stack else ['Generic / Unknown']


def get_architectural_layer(files):
    if not files:
        return 'Other'
    scores = {'Frontend': 0, 'Backend': 0, 'Database': 0}
    for f in files:
        fl = f.lower()
        if any(x in fl for x in ['.html', '.css', '.jsx', '.tsx', '.vue', 'assets', 'public']):
            scores['Frontend'] += 1
        elif any(x in fl for x in ['.sql', '.db', 'prisma', 'migrations', 'schema']):
            scores['Database'] += 1
        elif any(x in fl for x in ['.py', '.js', '.ts', '.go', '.rs', 'api', 'server', 'models']):
            scores['Backend'] += 1
    best = max(scores, key=scores.get)
    return best if scores[best] > 0 else 'Other'


def generate_insights(commits):
    total = len(commits)
    if total == 0:
        return {}
    author_counts = Counter(c['author'] for c in commits)
    leaderboard = [{'name': a, 'commit_count': c} for a, c in author_counts.most_common()]
    return {
        'total': total,
        'leaderboard': leaderboard,
        'top_contributor': leaderboard[0]['name'] if leaderboard else 'N/A',
    }


def compute_confidence(vec, seen_vecs, raw_msg):
    """Score 0.0–1.0: uniqueness × message descriptiveness."""
    # Uniqueness: inverse of max cosine similarity to any recent commit
    if seen_vecs:
        sims = [float(cosine_similarity([vec], [sv])[0][0]) for sv in seen_vecs[-20:]]
        max_sim = max(sims)
        uniqueness = max(0.0, 1.0 - max_sim)
    else:
        uniqueness = 1.0  # first commit ever
    # Quality: more descriptive words = higher quality
    quality = min(1.0, len(raw_msg.split()) / 8.0)
    return round(min(1.0, 0.55 * uniqueness + 0.45 * quality), 2)


def save_run(run_dir, result, vector_log, raw_github_data=None):
    """Persist analysis result and full vector log to the runs/ folder."""
    os.makedirs(run_dir, exist_ok=True)
    with open(os.path.join(run_dir, "analysis.json"), "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, default=str)
    with open(os.path.join(run_dir, "vector_log.json"), "w", encoding="utf-8") as f:
        json.dump(vector_log, f, indent=2, default=str)
    
    if raw_github_data:
        with open(os.path.join(run_dir, "raw_github_data.json"), "w", encoding="utf-8") as f:
            json.dump(raw_github_data, f, indent=2, default=str)
            
    print(f"[Run saved] → {run_dir}")


# --- Routes ---

@app.get('/', response_class=HTMLResponse)
async def serve_frontend():
    with open('index.html', 'r', encoding='utf-8') as f:
        return f.read()


@app.post('/api/analyze')
async def execute_pipeline(request: AnalyzeRequest):
    try:
        path = urlparse(request.url).path.strip('/')
        parts = path.split('/')
        if len(parts) < 2:
            return {'status': 'error', 'message': 'Invalid GitHub URL. Expected https://github.com/owner/repo'}

        owner, repo = parts[0], parts[1].replace('.git', '')
        headers = {'Authorization': f'Bearer {GITHUB_TOKEN}'} if GITHUB_TOKEN else {}

        # 1. REPO META
        repo_info = requests.get(f'https://api.github.com/repos/{owner}/{repo}', headers=headers).json()
        if 'message' in repo_info:
            return {'status': 'error', 'message': repo_info['message']}

        default_branch = repo_info.get('default_branch', 'main')
        stars        = repo_info.get('stargazers_count', 0)
        forks        = repo_info.get('forks_count', 0)
        description  = repo_info.get('description', '')

        # 2. FILE TREE
        tree_resp = requests.get(
            f'https://api.github.com/repos/{owner}/{repo}/git/trees/{default_branch}?recursive=1',
            headers=headers
        ).json()
        ignore = ['node_modules/', '.git/', 'venv/', 'dist/', 'build/', '__pycache__/']
        clean_tree = [
            item['path'] for item in tree_resp.get('tree', [])
            if item['type'] == 'blob' and not any(ig in item['path'] for ig in ignore)
        ]
        tech_stack = detect_frameworks(clean_tree)

        # 3. BULK COMMITS
        commits_raw = requests.get(
            f'https://api.github.com/repos/{owner}/{repo}/commits?per_page=100',
            headers=headers
        ).json()
        if not isinstance(commits_raw, list):
            return {'status': 'error', 'message': 'Could not fetch commits.'}

        raw_count = len(commits_raw[:request.limit])

        # 4. AI NOISE REMOVAL — Semantic Deduplication + Confidence Scoring
        meaningful  = []
        seen_vecs   = []
        vector_log  = []   # saved to disk: full vectors + similarity breakdown

        for commit in commits_raw[:request.limit]:
            raw_msg = commit['commit']['message'].split('\n')[0]
            author  = commit['commit']['author']['name']
            date    = commit['commit']['author']['date']
            sha     = commit['sha']

            clean_msg = re.sub(
                r'^(fix|feat|chore|update|merge|bump|wip)[\(:]?\s*', '',
                raw_msg, flags=re.IGNORECASE
            ).strip()
            if not clean_msg:
                continue

            vec  = model.encode([clean_msg])[0]
            sims = [float(cosine_similarity([vec], [sv])[0][0]) for sv in seen_vecs[-20:]]
            max_sim     = max(sims) if sims else 0.0
            is_duplicate = max_sim > 0.85

            if not is_duplicate:
                confidence = compute_confidence(vec, seen_vecs, raw_msg)
                meaningful.append({
                    'hash':       sha[:7],
                    'author':     author,
                    'message':    raw_msg,
                    'date':       date,
                    'confidence': confidence,
                })
                vector_log.append({
                    'hash':                    sha[:7],
                    'message':                 raw_msg,
                    'was_duplicate':           False,
                    'max_similarity_to_prior': round(max_sim, 4),
                    'all_similarities':        [round(s, 4) for s in sims],
                    'confidence':              confidence,
                    'vector_384d':             vec.tolist(),
                })
                seen_vecs.append(vec)
            else:
                vector_log.append({
                    'hash':                    sha[:7],
                    'message':                 raw_msg,
                    'was_duplicate':           True,
                    'max_similarity_to_prior': round(max_sim, 4),
                    'all_similarities':        [round(s, 4) for s in sims],
                    'confidence':              None,
                    'vector_384d':             vec.tolist(),
                })

        noise_filtered = raw_count - len(meaningful)
        noise_pct = round(noise_filtered / raw_count * 100, 1) if raw_count else 0
        insights = generate_insights(meaningful)

        # 5. PERSONA ROUTING
        repo_meta = {
            'name': repo, 'owner': owner,
            'stars': stars, 'forks': forks, 'description': description,
        }

        if request.user_type == 'non-tech':
            top = insights.get('top_contributor', 'the team')
            story = (
                f"This project — **{repo}** — is powered by {', '.join(tech_stack[:3])}. "
                f"After removing {noise_filtered} repetitive or noisy commits using AI, "
                f"the team has shipped {len(meaningful)} distinct, meaningful contributions. "
                f"The primary driver of development is **{top}**, and the project has earned "
                f"{stars:,} ⭐ stars and {forks:,} forks on GitHub."
            )
            return {
                'status':    'success',
                'persona':   'non-tech',
                'repo_meta': repo_meta,
                'summary': {
                    'core_technologies':        tech_stack,
                    'total_meaningful_updates': len(meaningful),
                    'top_contributors':         [d['name'] for d in insights.get('leaderboard', [])[:3]],
                },
                'story': story,
            }
        else:
            result = {
                'status':    'success',
                'persona':   'tech',
                'repo_meta': repo_meta,
                'analytics': {
                    'total_files':        len(clean_tree),
                    'frameworks':         tech_stack,
                    'raw_commits':        raw_count,
                    'noise_filtered':     noise_filtered,
                    'meaningful_commits': len(meaningful),
                    'noise_pct':          noise_pct,
                },
                'leaderboard':    insights.get('leaderboard', []),
                'file_structure': clean_tree[:50],
                'clean_ledger':   meaningful[:50],
            }

        # 6. PERSIST RUN TO DISK
        ts = datetime.utcnow().strftime("%Y-%m-%d_%H-%M-%S")
        run_id  = f"{ts}_{owner}_{repo}"
        run_dir = os.path.join(RUNS_DIR, run_id)
        
        raw_github_data = {
            "repo_info": repo_info,
            "tree_resp": tree_resp,
            "commits_raw": commits_raw
        }
        
        save_run(run_dir, result, vector_log, raw_github_data)

        return result

    except Exception as e:
        return {'status': 'error', 'message': str(e)}


@app.get('/api/runs')
async def list_runs():
    """Return metadata for all saved analysis runs."""
    runs = []
    if os.path.exists(RUNS_DIR):
        for run_id in sorted(os.listdir(RUNS_DIR), reverse=True):
            analysis_path = os.path.join(RUNS_DIR, run_id, "analysis.json")
            if not os.path.exists(analysis_path):
                continue
            with open(analysis_path, encoding="utf-8") as f:
                data = json.load(f)
            rm  = data.get("repo_meta", {})
            an  = data.get("analytics", {})
            sm  = data.get("summary",   {})
            runs.append({
                "run_id":             run_id,
                "repo":               f"{rm.get('owner','?')}/{rm.get('name','?')}",
                "timestamp":          run_id[:19].replace("_", " "),
                "persona":            data.get("persona", "tech"),
                "meaningful_commits": an.get("meaningful_commits", sm.get("total_meaningful_updates", 0)),
                "noise_filtered":     an.get("noise_filtered", 0),
                "stars":              rm.get("stars", 0),
            })
    return {"status": "success", "runs": runs}
