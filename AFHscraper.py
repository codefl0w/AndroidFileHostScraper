import requests
from bs4 import BeautifulSoup
import re
import os
import time
from pathlib import Path
from urllib.parse import quote_plus

class AFHScraper:
    def __init__(self, download_dir="afh_archive", mirror_preference="USA"):
        self.base_url = "https://androidfilehost.com"
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.mirror_preference = mirror_preference  # "USA" or "Germany"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        
    def search_files(self, search_term, page=1, sort_by='date'):
        """Search for files by name with pagination and sorting
        
        Args:
            search_term: Search query
            page: Page number (1-based)
            sort_by: 'date' for newest, 'downloads' for most popular
        """
        encoded_term = quote_plus(search_term)
        search_url = f"{self.base_url}/?w=search&s={encoded_term}&type=files"
        
        # Add sorting
        if sort_by == 'downloads':
            search_url += "&sort_by=downloads&sort_dir=DESC"
        
        # Add pagination
        if page > 1:
            search_url += f"&page={page}"
        
        print(f"Searching page {page}: {search_url}")
        
        try:
            response = self.session.get(search_url, timeout=30)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            files = []
            
            # Find all file list items
            file_items = soup.select('li.list-group-item.file')
            
            for item in file_items:
                # Extract file name and FID
                file_link = item.select_one('div.file-name h3 a')
                if not file_link:
                    continue
                    
                filename = file_link.text.strip()
                href = file_link.get('href', '')
                
                # Extract FID from href (format: /?fid=12495398787939834307)
                fid_match = re.search(r'fid=(\d+)', href)
                if not fid_match:
                    continue
                    
                fid = fid_match.group(1)
                
                # Extract file metadata
                downloads = item.select_one('div.file-attr:nth-of-type(1) span.file-attr-value')
                size = item.select_one('div.file-attr:nth-of-type(2) span.file-attr-value')
                upload_date = item.select_one('div.file-attr:nth-of-type(3) span.file-attr-value')
                
                files.append({
                    'fid': fid,
                    'filename': filename,
                    'downloads': downloads.text.split('\n')[0].strip() if downloads else 'N/A',
                    'size': size.text.split('\n')[0].strip() if size else 'N/A',
                    'upload_date': upload_date.text.split('\n')[0].strip() if upload_date else 'N/A',
                    'url': f"{self.base_url}/?fid={fid}"
                })
            
            return files
            
        except Exception as e:
            print(f"Error searching: {e}")
            return []
    
    def get_download_mirrors(self, fid):
        # Get download mirrors for a file via API
        mirrors_api = f"{self.base_url}/libs/otf/mirrors.otf.php"
        
        try:
            # POST to the mirrors API
            post_data = {
                'submit': 'submit',
                'action': 'getdownloadmirrors',
                'fid': fid
            }
            
            response = self.session.post(mirrors_api, data=post_data, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if data.get('STATUS') != '1' or data.get('CODE') != '200':
                print(f"API returned error: {data.get('MESSAGE')}")
                return []
            
            mirrors_data = data.get('MIRRORS', [])
            if not mirrors_data:
                print("No mirrors in API response")
                return []
            
            # Parse mirrors from JSON
            mirrors = []
            for mirror in mirrors_data:
                url = mirror.get('url')
                name = mirror.get('name', '')
                
                if not url:
                    continue
                
                location = "Unknown"
                if 'Virginia' in name or 'USA' in name:
                    location = "USA"
                elif 'Germany' in name:
                    location = "Germany"
                
                # Higher weight = primary mirror
                weight = int(mirror.get('weight', 0))
                is_primary = weight >= 100000
                
                mirrors.append({
                    'url': url,
                    'location': location,
                    'is_primary': is_primary,
                    'name': name
                })
            
            return mirrors
            
        except Exception as e:
            print(f"Error getting mirrors: {e}")
            return []
    
    def select_mirror(self, mirrors):
        # Try selecting a mirror. Falls back to the primary mirror if Germany fails
        if not mirrors:
            return None
        
        # Try to find preferred location
        preferred = [m for m in mirrors if self.mirror_preference in m['location']]
        if preferred:
            return preferred[0]['url']
        
        # Fall back to primary
        primary = [m for m in mirrors if m['is_primary']]
        if primary:
            return primary[0]['url']
        
        # Fall back to first available
        return mirrors[0]['url']
    
    def download_file(self, fid, filename):
        
        output_path = self.download_dir / filename
        
        # Check if already downloaded
        if output_path.exists():
            print(f"Already exists: {filename}")
            return True
        
        print(f"Getting mirrors for: {filename}")
        mirrors = self.get_download_mirrors(fid)
        
        if not mirrors:
            print(f"No mirrors found for: {filename}")
            return False
        
        download_url = self.select_mirror(mirrors)
        if not download_url:
            print(f"Could not select mirror for: {filename}")
            return False
        
        print(f"Downloading from: {download_url}")
        
        try:
            response = self.session.get(download_url, stream=True, timeout=120)
            response.raise_for_status()
            
            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            progress = (downloaded / total_size) * 100
                            print(f"\rProgress: {progress:.1f}%", end='', flush=True)
            
            print(f"\nDownloaded: {filename}")
            return True
            
        except Exception as e:
            print(f"\nError downloading: {e}")
            if output_path.exists():
                output_path.unlink()
            return False
    
    def batch_download(self, search_terms, num_pages=1, sort_by='date', max_files=None, delay=2):
        """Search and download files for multiple terms with pagination
        
        Args:
            search_terms: List of search queries
            num_pages: Number of pages to scrape per search term
            sort_by: 'date' for newest, 'downloads' for most popular
            max_files: Maximum files to download per search term (None = unlimited)
            delay: Seconds to wait between downloads
        """
        all_results = []
        
        for term in search_terms:
            print(f"\n{'='*70}")
            print(f"Searching for: {term}")
            print(f"{'='*70}")
            
            files_downloaded = 0
            
            for page in range(1, num_pages + 1):
                if max_files and files_downloaded >= max_files:
                    break
                
                files = self.search_files(term, page=page, sort_by=sort_by)
                
                if not files:
                    print(f"No files found on page {page}")
                    break
                
                print(f"Found {len(files)} files on page {page}\n")
                
                for file_info in files:
                    if max_files and files_downloaded >= max_files:
                        print(f"Reached maximum of {max_files} files for this search term")
                        break
                    
                    print(f"File: {file_info['filename']}")
                    print(f"  Size:{file_info ['size']} | Downloads: {file_info ['downloads']} | Date: {file_info ['upload_date']}")
                    print(f"  FID: {file_info['fid']}")
                    
                    success = self.download_file(file_info['fid'], file_info['filename'])
                    
                    all_results.append({
                        'search_term': term,
                        'page': page,
                        'filename': file_info['filename'],
                        'fid': file_info['fid'],
                        'size': file_info['size'],
                        'success': success
                    })
                    
                    if success:
                        files_downloaded += 1
                    
                    print()
                    time.sleep(delay)
        
        return all_results


def main():
    print("AndroidFileHost Scraper by fl0w")
    print("github.com/codefl0w")
    print("https://xdaforums.com/m/fl0w.12361087/")
    print("="*70)
    
    # Get search terms
    print("\nEnter search terms (comma-separated):")
    print("Example: lineage, twrp, magisk")
    search_input = input("Search terms: ").strip()
    search_terms = [term.strip() for term in search_input.split(',') if term.strip()]
    
    if not search_terms:
        print("No search terms provided. Exiting.")
        return
    
    # Get user preferences
    print("\nHow should files be sorted?")
    print("1. Newest first")
    print("2. Most popular (by downloads)")
    sort_choice = input("Enter choice (1 or 2): ").strip()
    sort_by = 'downloads' if sort_choice == '2' else 'date'
    
    print("\nHow many files should be downloaded per search term?")
    max_files = int(input("Enter number: ").strip())
    
    # Calculate pages needed (15 files per page)
    num_pages = (max_files + 14) // 15
    
    print("\nWhich mirror should be used primarily?")
    print("1. USA")
    print("2. Germany")
    mirror_choice = input("Enter choice (1 or 2): ").strip()
    mirror_pref = "Germany" if mirror_choice == '2' else "USA"
    
    # Initialize scraper

    scraper = AFHScraper(
        download_dir=os.path.dirname(os.path.abspath(__file__)),
        mirror_preference=mirror_pref
    )
    
    print(f"\n{'='*70}")
    print(f"Download directory: {scraper.download_dir.absolute()}")
    print(f"Mirror preference: {scraper.mirror_preference}")
    print(f"Sort by: {'Most popular' if sort_by == 'downloads' else 'Newest'}")
    print(f"Max files per search: {max_files}")
    print(f"Search terms: {', '.join(search_terms)}")
    print("="*70)
    
    results = scraper.batch_download(search_terms, num_pages=num_pages, sort_by=sort_by, 
                                     max_files=max_files, delay=3)

    
    # Summary
    successful = sum(1 for r in results if r['success'])
    print(f"\n{'='*70}")
    print(f"Summary: {successful}/{len(results)} files downloaded successfully")
    print(f"{'='*70}")


if __name__ == "__main__":   
    main()
