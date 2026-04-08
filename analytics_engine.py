import json
import re
import numpy as np
import chromadb
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.cluster import KMeans
from collections import Counter

print("Loading AI Model...")
model = SentenceTransformer('all-MiniLM-L6-v2')
chroma_client = chromadb.PersistentClient(path="./repo_vectordb")

try:
    chroma_client.delete_collection("universal_repo_data")
except:
    pass
collection = chroma_client.create_collection(name="universal_repo_data")

# --- UPGRADE 1: Universal Taxonomy ---
def get_universal_file_context(file_path):
    f = file_path.lower()
    
    # Cloud & DevOps
    if any(x in f for x in ['dockerfile', 'docker-compose', '.k8s', 'terraform', '.tf', '.yml', '.yaml', '.github/workflows']): return "Cloud Infrastructure and CI/CD Pipeline"
    # Configuration & Deps
    if any(x in f for x in ['package.json', 'cargo.toml', 'go.mod', 'requirements.txt', '.env', 'pom.xml', 'build.gradle']): return "Project Configuration and Dependencies"
    # Database
    if f.endswith(('.sql', '.db', '.sqlite', '.prisma')) or 'migrations' in f: return "Database Schema and Migrations"
    # Frontend / UI
    if f.endswith(('.html', '.css', '.scss', '.jsx', '.tsx', '.vue', '.svelte', '.jinja')): return "Frontend User Interface component"
    # Visual Assets
    if f.endswith(('.png', '.svg', '.ico', '.jpg', '.jpeg', '.webp', '.gif', '.ttf', '.woff')): return "Visual Asset or Font"
    # Mobile Apps
    if f.endswith(('.swift', '.kt', '.dart', '.java')) and ('android' in f or 'ios' in f or 'lib' in f): return "Mobile Application Logic"
    # Backend / Systems / Core Logic
    if f.endswith(('.js', '.ts', '.py', '.go', '.rs', '.cpp', '.c', '.h', '.cs', '.rb', '.php', '.java')): return "Core Application Logic and Backend Systems"
    # Docs
    if f.endswith(('.md', '.txt', '.rst')) or 'license' in f: return "Documentation"
    
    return "Source code"

def translate_files_to_english(files):
    if not files: return "No files were modified."
    descriptions = []
    for f in files:
        file_name = f.split('/')[-1]
        folders = " ".join(f.split('/')[:-1]).replace('_', ' ').replace('-', ' ')
        context = get_universal_file_context(f)
        descriptions.append(f"{context} specifically {file_name} in {folders}")
    return " ".join(set(descriptions))

# --- UPGRADE 2: Identity Resolution ---
def normalize_author(author_string):
    """Merges Martinmimi, martinmimi, wmartinmimi, etc."""
    clean = re.sub(r'[^a-zA-Z]', '', author_string).lower()
    # Handle the specific 'w' prefix typo in your dataset
    if clean.startswith('w') and len(clean) > 5 and clean[1:] in ['martinmimi', 'martinmmimi']:
        return "martinmimi"
    if 'martinmimi' in clean or 'martinmmimi' in clean:
        return "martinmimi"
    return author_string.strip()

def process_repository(json_filepath):
    with open(json_filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    timeline = data.get("timeline", [])
    if not timeline: return

    analyzed_commits = []
    all_commit_vectors = []

    print(f"Analyzing {len(timeline)} commits using Universal Pipeline...")
    
    for commit in timeline:
        raw_msg = commit.get("message", "").strip()
        files = commit.get("files_changed", [])
        author = normalize_author(commit.get("author", "Unknown"))
        
        clean_msg = re.sub(r'^(fix|feat|chore|docs|style|refactor|test|merge|init)[\(:]?\s*', '', raw_msg, flags=re.IGNORECASE).strip()
        if not clean_msg: clean_msg = raw_msg 
            
        confidence = 0.5 
        file_desc = translate_files_to_english(files)
        
        # --- UPGRADE 3: Heuristic Fast-Tracking ---
        msg_lower = raw_msg.lower()
        is_docs_update = any(kw in msg_lower for kw in ['doc', 'readme', 'typo', 'license'])
        only_docs_changed = all(f.endswith('.md') or f.endswith('.txt') for f in files) if files else False
        
        is_config_update = any(kw in msg_lower for kw in ['bump', 'version', 'deps', 'dependency', 'ignore', 'config'])
        only_configs_changed = all(get_universal_file_context(f) == "Project Configuration and Dependencies" for f in files) if files else False

        # Bypass AI math if the commit explicitly matches human structural rules
        if (is_docs_update and only_docs_changed) or (is_config_update and only_configs_changed):
            confidence = 1.0
            msg_vector = model.encode([clean_msg]) # Still need the vector for clustering
        elif clean_msg and files:
            # Otherwise, use the advanced AI similarity math
            msg_vector = model.encode([clean_msg])
            file_vector = model.encode([file_desc])
            
            sim_score = cosine_similarity(msg_vector, file_vector)[0][0]
            
            msg_words = set(re.findall(r'\b[a-z]{3,}\b', clean_msg.lower()))
            file_string = " ".join(files).lower()
            file_words = set(re.findall(r'\b[a-z]{3,}\b', file_string.replace('.', ' '))) 
            
            meaningful_matches = msg_words.intersection(file_words)
            if meaningful_matches:
                sim_score += (0.15 * len(meaningful_matches)) 
            
            if sim_score >= 0.30: confidence = 1.0     
            elif sim_score >= 0.15: confidence = 0.75  
            else: confidence = 0.5                     
        else:
            msg_vector = model.encode([clean_msg])

        all_commit_vectors.append(msg_vector[0])

        # --- UPGRADE 4: The Rich Document ---
        # This is what ChromaDB will search against. It includes the files!
        rich_document = f"Commit Message: {raw_msg}. Actions taken: {file_desc}"

        analyzed_commits.append({
            "hash": commit.get("hash"),
            "author": author,
            "raw_message": raw_msg, 
            "rich_document": rich_document,
            "files": files,
            "confidence": confidence
        })

    print("Clustering architecture vectors...")
    num_clusters = min(5, len(analyzed_commits)) 
    kmeans = KMeans(n_clusters=num_clusters, random_state=42, n_init='auto')
    cluster_labels = kmeans.fit_predict(all_commit_vectors)

    print("Saving enriched Rich Documents to Vector DB...")
    collection.add(
        ids=[c["hash"] for c in analyzed_commits],
        documents=[c["rich_document"] for c in analyzed_commits],
        metadatas=[{
            "author": c["author"],
            "original_message": c["raw_message"],
            "confidence": float(c["confidence"]),
            "cluster_group": f"Component {int(cluster_labels[i]) + 1}",
            "files_changed": ", ".join(c["files"])[:100] 
        } for i, c in enumerate(analyzed_commits)]
    )
    print("✅ Universal Pipeline Complete!")

if __name__ == "__main__":
    process_repository("tiny-music-player_story.json")