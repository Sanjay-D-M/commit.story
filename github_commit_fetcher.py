import requests
import json
from urllib.parse import urlparse

def extract_owner_repo(repo_url):
    """Parses the GitHub URL to extract the owner and repository name."""
    path = urlparse(repo_url).path.strip('/')
    parts = path.split('/')
    if len(parts) >= 2:
        # Handles standard URLs like https://github.com/owner/repo
        return parts[0], parts[1].replace('.git', '')
    return None, None

def fetch_all_commits(repo_url, token=None):
    owner, repo = extract_owner_repo(repo_url)
    if not owner or not repo:
        print("Error: Invalid GitHub URL.")
        return

    api_url = f"https://api.github.com/repos/{owner}/{repo}/commits"
    
    # Using the recommended GitHub API header
    headers = {'Accept': 'application/vnd.github.v3+json'}
    
    # If a token is provided, add it to headers to bypass strict rate limits
    if token:
        headers['Authorization'] = f'token {token}'

    all_commits = []
    page = 1
    per_page = 100  # GitHub API allows a maximum of 100 commits per page

    print(f"Fetching commits for '{owner}/{repo}'...")

    while True:
        params = {'page': page, 'per_page': per_page}
        response = requests.get(api_url, headers=headers, params=params)

        # Handle rate limiting
        if response.status_code == 403:
            print("\nError: GitHub API rate limit exceeded.")
            print("Tip: Pass a GitHub Personal Access Token (PAT) to increase your limit from 60 to 5000 requests per hour.")
            break
        elif response.status_code != 200:
            print(f"\nFailed to fetch data: {response.status_code} - {response.text}")
            break

        commits = response.json()
        
        # If the returned list is empty, we've reached the end of the commit history
        if not commits:
            break 

        for commit in commits:
            # Structuring the log data for a cleaner JSON output
            commit_data = {
                "sha": commit.get("sha"),
                "author_name": commit.get("commit", {}).get("author", {}).get("name"),
                "author_email": commit.get("commit", {}).get("author", {}).get("email"),
                "date": commit.get("commit", {}).get("author", {}).get("date"),
                "message": commit.get("commit", {}).get("message"),
                "url": commit.get("html_url")
            }
            all_commits.append(commit_data)

        print(f"Fetched page {page} ({len(commits)} commits processed)...")
        page += 1

    if all_commits:
        # Save the extracted logs to a JSON file
        output_file = f"{repo}_commits.json"
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(all_commits, f, indent=4)
        print(f"\nSuccess! {len(all_commits)} commits saved to '{output_file}'.")

if __name__ == "__main__":
    repo_link = input("Enter the GitHub repository URL: ")
    
    # Optional: If you are fetching a massive repository, generate a classic Personal Access Token 
    # in your GitHub Developer Settings and paste it below.
    # github_token = "ghp_YourPersonalAccessTokenHere"
    
    fetch_all_commits(repo_link, token=None)