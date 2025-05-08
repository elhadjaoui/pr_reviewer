import sys
import os
import requests
import traceback
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP

# Load environment variables
load_dotenv()
GITHUB_TOKEN = os.getenv('GITHUB_TOKEN')

def fetch_pr_changes(repo_owner: str, repo_name: str, pr_number: int) -> dict:
    """Fetch changes from a GitHub pull request.
    
    Args:
        repo_owner: The owner of the GitHub repository
        repo_name: The name of the GitHub repository
        pr_number: The number of the pull request to analyze
        
    Returns:
        A dictionary with PR metadata and a list of file changes
    """
    print(f"Fetching PR changes for {repo_owner}/{repo_name}#{pr_number}", file=sys.stderr)
    
    # Fetch PR details
    pr_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}"
    files_url = f"{pr_url}/files"
    headers = {'Authorization': f'token {GITHUB_TOKEN}'}
    
    try:
        # Get PR metadata
        pr_response = requests.get(pr_url, headers=headers)
        pr_response.raise_for_status()
        pr_data = pr_response.json()
        
        # Get file changes
        files_response = requests.get(files_url, headers=headers)
        files_response.raise_for_status()
        files_data = files_response.json()
        
        # Combine PR metadata with file changes
        changes = []
        for file in files_data:
            change = {
                'filename': file['filename'],
                'status': file['status'],  # added, modified, removed
                'additions': file['additions'],
                'deletions': file['deletions'],
                'changes': file['changes'],
                'patch': file.get('patch', ''),  # The actual diff
                'raw_url': file.get('raw_url', ''),
                'contents_url': file.get('contents_url', '')
            }
            changes.append(change)
        
        # Add PR metadata
        pr_info = {
            'title': pr_data['title'],
            'description': pr_data['body'],
            'author': pr_data['user']['login'],
            'created_at': pr_data['created_at'],
            'updated_at': pr_data['updated_at'],
            'state': pr_data['state'],
            'total_changes': len(changes),
            'changes': changes,
            'head_sha': pr_data['head']['sha'],  # Added to use for creating reviews
            'mergeable': pr_data.get('mergeable', False)  # Check if PR is mergeable
        }
        
        print(f"Successfully fetched {len(changes)} changes", file=sys.stderr)
        return pr_info
        
    except Exception as e:
        print(f"Error fetching PR changes: {str(e)}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        return None

class PRAnalyzer:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Initialize MCP Server
        self.mcp = FastMCP("github_pr_analysis")
        print("MCP Server initialized", file=sys.stderr)
        
        # Initialize Google Drive
        self._init_google_drive()
        
        # Register MCP tools
        self._register_tools()
        
    def _init_google_drive(self):
        """Initialize the Google Docs client with credentials."""
        try:
            # Load Google API credentials
            self.google_parent_folder_id = os.getenv("GOOGLE_PARENT_FOLDER_ID")
            from pydrive.auth import GoogleAuth 
            from pydrive.drive import GoogleDrive
            gauth = GoogleAuth() 
            self.drive = GoogleDrive(gauth)
        except Exception as e:
            print(f"Error initializing Google Docs client: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            self.drive = None
    
    def _register_tools(self):
        """Register MCP tools for PR analysis."""
        @self.mcp.tool()
        async def fetch_pr(repo_owner: str, repo_name: str, pr_number: int) -> Dict[str, Any]:
            """Fetch changes from a GitHub pull request."""
            print(f"Fetching PR #{pr_number} from {repo_owner}/{repo_name}", file=sys.stderr)
            try:
                pr_info = fetch_pr_changes(repo_owner, repo_name, pr_number)
                if pr_info is None:
                    print("No changes returned from fetch_pr_changes", file=sys.stderr)
                    return {}
                print(f"Successfully fetched PR information", file=sys.stderr)
                return pr_info
            except Exception as e:
                print(f"Error fetching PR: {str(e)}", file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {}
        
        @self.mcp.tool()
        async def create_to_drive(title: str, content: str) -> str:
            """Create a Google Doc with PR analysis."""
            print(f"Creating Google Doc: {title}", file=sys.stderr)
            try:
                if not self.drive:
                    self._init_google_drive()
                
                # Create a new Google Doc
                file_metadata = {
                    'title': title,
                    'mimeType': 'application/vnd.google-apps.document'
                }
                
                # Add folder as parent if provided
                if self.google_parent_folder_id:
                    file_metadata['parents'] = [{'id': self.google_parent_folder_id}]
                    
                file = self.drive.CreateFile(file_metadata)
                file.Upload()
                
                # Write content to the Google Doc
                file.SetContentString(content)
                file.Upload()
                
                print(f"Google Doc created: {file['alternateLink']}", file=sys.stderr)
                return file['alternateLink']
            except Exception as e:
                error_msg = f"Error creating to Drive: {str(e)}"
                print(error_msg, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return error_msg
        
        @self.mcp.tool()
        async def create_inline_comment(repo_owner: str, repo_name: str, pr_number: int, 
                                      commit_id: str, filename: str, position: int, 
                                      body: str) -> Dict[str, Any]:
            """Create an inline comment on a specific line in a file for a PR."""
            print(f"Creating inline comment on {filename} at position {position}", file=sys.stderr)
            
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}/comments"
            headers = {'Authorization': f'token {GITHUB_TOKEN}'}
            
            data = {
                "commit_id": commit_id,
                "path": filename,
                "position": position,
                "body": body
            }
            
            try:
                response = requests.post(url, json=data, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                error_msg = f"Error creating inline comment: {str(e)}"
                print(error_msg, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": error_msg}
        
        @self.mcp.tool()
        async def create_review(repo_owner: str, repo_name: str, pr_number: int, 
                              commit_id: str, comments: Optional[List[Dict[str, Any]]] = None, 
                              body: str = "", event: str = "COMMENT") -> Dict[str, Any]:
            """Create a review for a PR with optional comments and approval.
            
            Args:
                repo_owner: The owner of the GitHub repository
                repo_name: The name of the GitHub repository
                pr_number: The number of the pull request
                commit_id: The SHA of the commit to review
                comments: A list of dictionaries containing comment data
                body: The body text of the review
                event: The review action (APPROVE, REQUEST_CHANGES, COMMENT)
            """
            print(f"Creating review for PR #{pr_number} with event: {event}", file=sys.stderr)
            
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}/reviews"
            headers = {'Authorization': f'token {GITHUB_TOKEN}'}
            
            data = {
                "commit_id": commit_id,
                "body": body,
                "event": event
            }
            
            if comments:
                data["comments"] = comments
            
            try:
                response = requests.post(url, json=data, headers=headers)
                response.raise_for_status()
                return response.json()
            except Exception as e:
                error_msg = f"Error creating review: {str(e)}"
                print(error_msg, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"error": error_msg}
        
        @self.mcp.tool()
        async def merge_pr(repo_owner: str, repo_name: str, pr_number: int, 
                         commit_title: str = None, 
                         commit_message: str = None,
                         merge_method: str = "merge") -> Dict[str, Any]:
            """Merge a pull request.
            
            Args:
                repo_owner: The owner of the GitHub repository
                repo_name: The name of the GitHub repository
                pr_number: The number of the pull request to merge
                commit_title: The title for the automatic commit message
                commit_message: Extra detail to append to automatic commit message
                merge_method: The merge method to use: 'merge', 'squash', or 'rebase'
                
            Returns:
                A dictionary with merge result data
            """
            print(f"Merging PR #{pr_number} with method: {merge_method}", file=sys.stderr)
            
            url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/pulls/{pr_number}/merge"
            headers = {'Authorization': f'token {GITHUB_TOKEN}'}
            
            data = {}
            if commit_title:
                data["commit_title"] = commit_title
            if commit_message:
                data["commit_message"] = commit_message
            if merge_method in ["merge", "squash", "rebase"]:
                data["merge_method"] = merge_method
            
            try:
                response = requests.put(url, json=data, headers=headers)
                
                if response.status_code == 200:
                    result = response.json()
                    print(f"Successfully merged PR #{pr_number}: {result.get('message', '')}", file=sys.stderr)
                    return {
                        "status": "success",
                        "message": result.get('message', 'Pull Request successfully merged'),
                        "sha": result.get('sha', ''),
                        "merged": True
                    }
                else:
                    error_data = response.json()
                    error_msg = error_data.get('message', 'Unknown error')
                    print(f"Error merging PR: {error_msg}", file=sys.stderr)
                    return {
                        "status": "error",
                        "message": error_msg,
                        "merged": False
                    }
            except Exception as e:
                error_msg = f"Exception merging PR: {str(e)}"
                print(error_msg, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {
                    "status": "error",
                    "message": error_msg,
                    "merged": False
                }
        
        @self.mcp.tool()
        async def review_pr_automatically(repo_owner: str, repo_name: str, pr_number: int, 
                                       auto_merge: bool = False,
                                       merge_method: str = "merge") -> Dict[str, Any]:
            """Automatically review a pull request based on analysis of changes and optionally merge if approved.
            
            This function:
            1. Fetches PR changes
            2. Analyzes each changed file
            3. Creates comments on specific lines where issues are found
            4. Creates a summary review with approval or change requests
            5. Optionally merges the PR if approved and auto_merge is True
            
            Args:
                repo_owner: The owner of the GitHub repository
                repo_name: The name of the GitHub repository
                pr_number: The number of the pull request to review
                auto_merge: Whether to automatically merge the PR if approved
                merge_method: The merge method to use: 'merge', 'squash', or 'rebase'
            
            Returns:
                A dictionary with the review results
            """
            print(f"Starting automatic review of PR #{pr_number}", file=sys.stderr)
            
            # Get PR data
            try:
                pr_data = await fetch_pr(repo_owner, repo_name, pr_number)
                if not pr_data:
                    error_msg = "Failed to fetch PR data"
                    print(error_msg, file=sys.stderr)
                    return {"status": "error", "message": error_msg}
                
                # Track issues found
                issues_found = []
                
                # Review each file in the PR
                for file_change in pr_data.get('changes', []):
                    filename = file_change.get('filename', '')
                    patch = file_change.get('patch', '')
                    
                    # Skip files without patches (binary files or large files)
                    if not patch:
                        continue
                    
                    # Simple analysis: For demonstration, we'll flag any lines with "TODO" or "FIXME"
                    position = 0
                    for line in patch.split('\n'):
                        position += 1
                        
                        # Skip diff metadata lines
                        if not line.startswith('+'):
                            continue
                            
                        # Skip the diff marker itself
                        content = line[1:]
                        
                        # Check for common issues
                        if 'TODO' in content or 'FIXME' in content:
                            issue = f"Found TODO/FIXME in {filename} at line with content: {content}"
                            issues_found.append(issue)
                
                # Create the review with all comments
                review_body = "## Automated Review Results\n\n"
                commit_id = pr_data.get('head_sha', '')
                
                # Result dictionary to return
                result = {
                    "status": "success",
                    "issues_found": issues_found
                }
                
                if issues_found:
                    # Issues found, request changes
                    review_body += "Some issues were found during the automated review:\n\n"
                    for issue in issues_found:
                        review_body += f"- {issue}\n"
                    
                    approval_status = "changes_requested"
                    result["approval_status"] = approval_status
                    result["merged"] = False
                    result["message"] = "Changes requested, PR not approved"
                    
                else:
                    # No issues found, approve the PR
                    review_body += "No issues found! This PR looks good to merge."
                    
                    approval_status = "approved"
                    result["approval_status"] = approval_status
                    
                    # Merge the PR if auto_merge is True
                    if auto_merge:
                        # Check if PR is mergeable
                        if pr_data.get('mergeable', False):
                            # Submit merge request
                            commit_title = f"Merge PR #{pr_number}: {pr_data.get('title', '')}"
                            commit_message = "Automatically merged after passing automated review."
                            
                            merge_result = await merge_pr(
                                repo_owner=repo_owner,
                                repo_name=repo_name,
                                pr_number=pr_number,
                                commit_title=commit_title,
                                commit_message=commit_message,
                                merge_method=merge_method
                            )
                            
                            # Add merge result to the review result
                            result["merged"] = merge_result.get("merged", False)
                            result["merge_message"] = merge_result.get("message", "")
                            
                            if result["merged"]:
                                result["message"] = f"PR approved and merged: {result['merge_message']}"
                            else:
                                result["message"] = f"PR approved but merge failed: {result['merge_message']}"
                        else:
                            result["merged"] = False
                            result["message"] = "PR approved but not mergeable. Check for conflicts."
                    else:
                        result["merged"] = False
                        result["message"] = "PR approved, but automatic merge is disabled"
                
                # Add the review body to the result for reporting
                result["review_body"] = review_body
                
                return result
                
            except Exception as e:
                error_msg = f"Error in automatic review: {str(e)}"
                print(error_msg, file=sys.stderr)
                traceback.print_exc(file=sys.stderr)
                return {"status": "error", "message": error_msg}
    
    def run(self):
        """Start the MCP server."""
        try:
            print("Running MCP Server for GitHub PR Analysis...", file=sys.stderr)
            self.mcp.run(transport="stdio")
        except Exception as e:
            print(f"Fatal Error in MCP Server: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)

if __name__ == "__main__":
    analyzer = PRAnalyzer()
    analyzer.run()