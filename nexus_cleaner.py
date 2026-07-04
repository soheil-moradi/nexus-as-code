import requests
from requests.auth import HTTPBasicAuth

class NexusCleaner:
    def __init__(self, nexus_url, username, password):
        self.nexus_url = nexus_url.rstrip('/')
        self.auth = HTTPBasicAuth(username, password)
        self.headers = {'Content-Type': 'application/json'}
    
    def get_all_repositories(self):
        endpoint = f"{self.nexus_url}/service/rest/v1/repositories"
        response = requests.get(endpoint, auth=self.auth)
        if response.status_code == 200:
            return response.json()
        return []
    
    def delete_repository(self, repo_name):
        endpoint = f"{self.nexus_url}/service/rest/v1/repositories/{repo_name}"
        response = requests.delete(endpoint, auth=self.auth)
        return response
    
    def get_all_blobstores(self):
        endpoint = f"{self.nexus_url}/service/rest/v1/blobstores"
        response = requests.get(endpoint, auth=self.auth)
        if response.status_code == 200:
            return response.json()
        return []
    
    def delete_blobstore(self, blobstore_name):
        endpoint = f"{self.nexus_url}/service/rest/v1/blobstores/{blobstore_name}"
        response = requests.delete(endpoint, auth=self.auth)
        return response
    
    def clean_nexus(self):
        # First delete all repositories
        print("Deleting repositories...")
        repositories = self.get_all_repositories()
        for repo in repositories:
            print(f"Deleting repository: {repo['name']}")
            response = self.delete_repository(repo['name'])
            print(f"Status: {response.status_code} - {response.reason}")
        
        # Then delete all blobstores (except default)
        print("\nDeleting blobstores...")
        blobstores = self.get_all_blobstores()
        for blobstore in blobstores:
            if blobstore['name'] != 'default':  # Don't delete the default blobstore
                print(f"Deleting blobstore: {blobstore['name']}")
                response = self.delete_blobstore(blobstore['name'])
                print(f"Status: {response.status_code} - {response.reason}")
            else:
                print(f"Skipping default blobstore")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description='Clean Nexus Repository - delete all repositories and blobstores')
    parser.add_argument('--url', required=True, help='Nexus server URL (e.g., http://localhost:8081)')
    parser.add_argument('--username', required=True, help='Nexus admin username')
    parser.add_argument('--password', required=True, help='Nexus admin password')
    parser.add_argument('--confirm', action='store_true', help='Confirm you want to delete all content')
    
    args = parser.parse_args()
    
    if not args.confirm:
        print("WARNING: This will delete ALL repositories and blobstores (except default) from your Nexus instance!")
        print("Add --confirm flag to proceed")
        exit(1)
    
    cleaner = NexusCleaner(
        nexus_url=args.url,
        username=args.username,
        password=args.password
    )
    
    cleaner.clean_nexus()