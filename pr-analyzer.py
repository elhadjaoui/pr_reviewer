import sys
import os
import traceback
from pydrive.auth import GoogleAuth 
from pydrive.drive import GoogleDrive


from typing import Any, List, Dict
from mcp.server.fastmcp import FastMCP
from github_integration import fetch_pr_changes
from dotenv import load_dotenv

class PRAnalyzer:
    def __init__(self):
        # Load environment variables
        load_dotenv()
        
        # Initialize MCP Server
        self.mcp = FastMCP("github_pr_analysis")
        print("MCP Server initialized", file=sys.stderr)
        
        # Initialize Notion client
        self._init_google_drive()
        
        # Register MCP tools
        self._register_tools()
        self.drive = None
    
    def _init_google_drive(self):
        """Initialize the Google Docs client with credentials."""
        try:
            # Load Google API credentials
            # self.google_credentials_path = os.getenv("GOOGLE_CREDENTIALS_PATH")
            self.google_parent_folder_id = os.getenv("GOOGLE_PARENT_FOLDER_ID")
            gauth = GoogleAuth() 
            self.drive = GoogleDrive(gauth)
        except Exception as e:
            print(f"Error initializing Google Docs client: {str(e)}", file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
            sys.exit(1)
    
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