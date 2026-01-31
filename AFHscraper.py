import httpx
from bs4 import BeautifulSoup
import re
import os
import sys
import time
import json
import hashlib
import logging
import argparse
import asyncio
from pathlib import Path
from urllib.parse import quote_plus

class AFHScraper:
    def __init__(self, download_dir="afh_archive", mirror_preference="USA", max_retries=2):
        self.base_url = "https://androidfilehost.com"
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(exist_ok=True)
        self.mirror_preference = mirror_preference
        self.max_retries = max_retries
        
        # Setup logging
        self.logger = logging.getLogger('AFHScraper')
        
        # Progress tracking for concurrent downloads
        self.progress_lock = asyncio.Lock()
        self.download_progress = {}  # {task_id: {'filename': str, 'progress': float, 'speed': float}}
        
        # HTTP client (initialized in __aenter__)
        self.client = None

    async def __aenter__(self):
        self.client = httpx.AsyncClient(
            http2=True,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            timeout=httpx.Timeout(10.0, connect=10.0, read=120.0, write=30.0, pool=10.0)
        )
        return self
        
    async def __aexit__(self, exc_type, exc_value, traceback):
        if self.client:
            await self.client.aclose()
        
    # Search for files by name with pagination and sorting
    async def search_files(self, search_term, page=1, sort_by='date'):
        encoded_term = quote_plus(search_term)
        search_url = f"{self.base_url}/?w=search&s={encoded_term}&type=files"
        
        if sort_by == 'downloads':
            search_url += "&sort_by=downloads&sort_dir=DESC"
        
        if page > 1:
            search_url += f"&page={page}"
        
        self.logger.info(f"Searching page {page}: {search_url}")
        
        try:
            response = await self.client.get(search_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            files = []
            
            file_items = soup.select('li.list-group-item.file')
            
            for item in file_items:
                file_link = item.select_one('div.file-name h3 a')
                if not file_link:
                    continue
                    
                filename = file_link.text.strip()
                href = file_link.get('href', '')
                
                fid_match = re.search(r'fid=(\d+)', href)
                if not fid_match:
                    continue
                    
                fid = fid_match.group(1)
                
                downloads = item.select_one('div.file-attr:nth-of-type(1) span.file-attr-value')
                size = item.select_one('div.file-attr:nth-of-type(2) span.file-attr-value')
                upload_date = item.select_one('div.file-attr:nth-of-type(3) span.file-attr-value')
                
                downloads_text = downloads.contents[0].strip() if downloads and downloads.contents else 'N/A'
                size_text = size.contents[0].strip() if size and size.contents else 'N/A'
                upload_date_text = upload_date.contents[0].strip() if upload_date and upload_date.contents else 'N/A'
                
                files.append({
                    'fid': fid,
                    'filename': filename,
                    'downloads': downloads_text,
                    'size': size_text,
                    'upload_date': upload_date_text,
                    'url': f"{self.base_url}/?fid={fid}"
                })
            
            return files
            
        except Exception as e:
            self.logger.error(f"Error searching: {e}")
            return []
    
    # Fetch MD5 from file's download page
    async def fetch_md5(self, fid):
        file_url = f"{self.base_url}/?fid={fid}"
        
        try:
            response = await self.client.get(file_url)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            file_attrs = soup.select('div.file-attr')
            
            for attr in file_attrs:
                label = attr.select_one('span.file-attr-label')
                if label and 'MD5' in label.text:
                    value = attr.select_one('span.file-attr-value')
                    if value and value.contents:
                        md5 = value.contents[0].strip()
                        return md5
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error fetching MD5: {e}")
            return None
    
    # Calculate MD5 hash of a file
    def calculate_file_md5(self, filepath):
        md5_hash = hashlib.md5()
        try:
            with open(filepath, "rb") as f:
                for chunk in iter(lambda: f.read(8192), b""):
                    md5_hash.update(chunk)
            return md5_hash.hexdigest()
        except Exception as e:
            self.logger.error(f"Error calculating MD5: {e}")
            return None
    
    # Get download mirrors for a file via API
    async def get_download_mirrors(self, fid):
        mirrors_api = f"{self.base_url}/libs/otf/mirrors.otf.php"
        
        try:
            post_data = {
                'submit': 'submit',
                'action': 'getdownloadmirrors',
                'fid': fid
            }
            
            response = await self.client.post(mirrors_api, data=post_data)
            response.raise_for_status()
            
            try:
                data = response.json()
            except json.JSONDecodeError:
                self.logger.error(f"API returned invalid JSON.")
                self.logger.debug(f"Response text: {response.text}")
                return []
            
            if data.get('STATUS') != '1' or data.get('CODE') != '200':
                self.logger.error(f"API returned error: {data.get('MESSAGE')}")
                return []
            
            mirrors_data = data.get('MIRRORS', [])
            if not mirrors_data:
                self.logger.error("No mirrors in API response")
                return []
            
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
            self.logger.error(f"Error getting mirrors: {e}")
            return []
    
    # Select the best mirror based on preference
    def select_mirror(self, mirrors):
        if not mirrors:
            return None
        
        preferred = [m for m in mirrors if self.mirror_preference in m['location']]
        if preferred:
            return preferred[0]['url']
        
        primary = [m for m in mirrors if m['is_primary']]
        if primary:
            return primary[0]['url']
        
        return mirrors[0]['url']
    
    # Format download speed for display
    def _format_speed(self, bytes_per_second):
        if bytes_per_second >= 1024 * 1024:
            return f"{bytes_per_second / (1024 * 1024):.1f} MB/s"
        elif bytes_per_second >= 1024:
            return f"{bytes_per_second / 1024:.1f} KB/s"
        else:
            return f"{bytes_per_second:.0f} B/s"
    
    # Download a file with MD5 verification, size validation, and retry logic
    async def download_file(self, fid, filename, retry_count=0, task_id=None):
        output_path = self.download_dir / filename
        part_path = output_path.with_suffix(output_path.suffix + '.part')

        # Check if already downloaded
        if output_path.exists():
            self.logger.info(f"File already exists: {filename}")
            expected_md5 = await self.fetch_md5(fid)
            if expected_md5:
                self.logger.info(f"Verifying existing file...")
                calculated_md5 = self.calculate_file_md5(output_path)
                if calculated_md5 and calculated_md5.lower() == expected_md5.lower():
                    self.logger.info(f"MD5 verified: {calculated_md5}")
                    return True
                else:
                    self.logger.warning(f"MD5 mismatch for existing file. Expected: {expected_md5}, Got: {calculated_md5}")
                    self.logger.info(f"Deleting corrupted file and re-downloading...")
                    output_path.unlink()
            else:
                self.logger.info(f"Skipping download (file exists, no MD5 available)")
                return True

        # Fetch MD5
        self.logger.info(f"Fetching MD5...")
        expected_md5 = await self.fetch_md5(fid)
        if expected_md5:
            self.logger.info(f"Expected MD5: {expected_md5}")
        else:
            self.logger.warning(f"MD5 not found on page")
        
        # Get mirrors
        self.logger.info(f"Getting mirrors for: {filename}")
        mirrors = await self.get_download_mirrors(fid)
        
        if not mirrors:
            self.logger.error(f"No mirrors found for: {filename}")
            return False
        
        download_url = self.select_mirror(mirrors)
        if not download_url:
            self.logger.error(f"Could not select mirror for: {filename}")
            return False
        
        self.logger.info(f"Downloading to: {part_path}")
        
        try:
            downloaded = 0
            if part_path.exists():
                downloaded = part_path.stat().st_size
                self.logger.info(f"Resuming download from {downloaded} bytes")

            headers = {'Range': f'bytes={downloaded}-'} if downloaded > 0 else {}
            
            # Track download speed
            start_time = time.monotonic()
            last_speed_update = start_time
            bytes_since_last_update = 0
            current_speed = 0.0
            expected_total_size = None

            async with self.client.stream("GET", download_url, headers=headers) as response:
                if response.status_code == 416:  # Range Not Satisfiable
                    self.logger.info(f"File already fully downloaded in .part file: {filename}")
                elif response.status_code == 200 and downloaded > 0:  # Server doesn't support range requests
                    self.logger.warning(f"Server doesn't support range requests. Restarting download.")
                    part_path.unlink()
                    downloaded = 0
                    start_time = time.monotonic()
                    async with self.client.stream("GET", download_url) as new_response:
                        new_response.raise_for_status()
                        expected_total_size = int(new_response.headers.get('content-length', 0))
                        await self._process_download(
                            new_response, part_path, downloaded, task_id, filename,
                            start_time, expected_total_size
                        )
                else:
                    response.raise_for_status()
                    content_length = int(response.headers.get('content-length', 0))
                    expected_total_size = content_length + downloaded
                    await self._process_download(
                        response, part_path, downloaded, task_id, filename,
                        start_time, expected_total_size
                    )

            # Clear task progress
            if task_id is not None:
                async with self.progress_lock:
                    if task_id in self.download_progress:
                        del self.download_progress[task_id]
                await self._display_concurrent_progress()

            print()  # New line after progress
            self.logger.info(f"Downloaded: {filename}")
            
            # File size validation
            if expected_total_size and expected_total_size > 0:
                actual_size = part_path.stat().st_size
                if actual_size != expected_total_size:
                    self.logger.error(f"Size mismatch! Expected: {expected_total_size}, Got: {actual_size}")
                    if retry_count < self.max_retries:
                        self.logger.warning(f"Deleting incomplete file and retrying (attempt {retry_count + 1}/{self.max_retries})...")
                        part_path.unlink()
                        await asyncio.sleep(2)
                        return await self.download_file(fid, filename, retry_count + 1, task_id)
                    else:
                        self.logger.error(f"Max retries reached. File may be incomplete!")
                        part_path.unlink()
                        return False

            # Verify MD5
            if expected_md5:
                self.logger.info(f"Verifying MD5...")
                calculated_md5 = self.calculate_file_md5(part_path)
                if calculated_md5:
                    if calculated_md5.lower() == expected_md5.lower():
                        self.logger.info(f"MD5 verified: {calculated_md5}")
                        # Atomic file rename
                        os.replace(str(part_path), str(output_path))
                        self.logger.info(f"Renamed {part_path} to {output_path}")
                        return True
                    else:
                        self.logger.error(f"MD5 MISMATCH! Expected: {expected_md5}, Got: {calculated_md5}")
                        
                        # Retry logic
                        if retry_count < self.max_retries:
                            self.logger.warning(f"Deleting corrupted file and retrying (attempt {retry_count + 1}/{self.max_retries})...")
                            part_path.unlink()
                            await asyncio.sleep(2)
                            return await self.download_file(fid, filename, retry_count + 1, task_id)
                        else:
                            self.logger.error(f"Max retries reached. File may be corrupted!")
                            part_path.unlink()
                            return False
            else:
                # No MD5 to verify, just rename atomically
                os.replace(str(part_path), str(output_path))
                self.logger.info(f"Renamed {part_path} to {output_path}")

            return True

        except Exception as e:
            self.logger.error(f"Error downloading: {e}")
            
            # Clear task progress on error
            if task_id is not None:
                async with self.progress_lock:
                    if task_id in self.download_progress:
                        del self.download_progress[task_id]
            
            # Retry on error
            if retry_count < self.max_retries:
                self.logger.warning(f"Retrying download (attempt {retry_count + 1}/{self.max_retries})...")
                await asyncio.sleep(2)
                return await self.download_file(fid, filename, retry_count + 1, task_id)
            
            return False

    # Process download stream with speed tracking
    async def _process_download(self, response, part_path, downloaded, task_id, filename, start_time, expected_total_size):
        total_size = expected_total_size if expected_total_size else 0
        mode = 'ab' if downloaded > 0 else 'wb'
        
        last_speed_update = start_time
        bytes_since_last_update = 0
        current_speed = 0.0

        with open(part_path, mode) as f:
            async for chunk in response.aiter_bytes(chunk_size=8192):
                f.write(chunk)
                chunk_len = len(chunk)
                downloaded += chunk_len
                bytes_since_last_update += chunk_len
                
                # Update speed every 0.5 seconds
                now = time.monotonic()
                time_since_update = now - last_speed_update
                if time_since_update >= 0.5:
                    current_speed = bytes_since_last_update / time_since_update
                    last_speed_update = now
                    bytes_since_last_update = 0
                
                if total_size > 0:
                    progress = (downloaded / total_size) * 100
                    speed_str = self._format_speed(current_speed)
                    
                    if task_id is not None:
                        # Update progress for concurrent downloads
                        async with self.progress_lock:
                            self.download_progress[task_id] = {
                                'filename': filename,
                                'progress': progress,
                                'speed': current_speed
                            }
                        await self._display_concurrent_progress()
                    else:
                        # Single download progress
                        print(f"\r[{filename}] {progress:.1f}% @ {speed_str}", end='', flush=True)
    
    # Display progress for all concurrent downloads on one line
    async def _display_concurrent_progress(self):
        async with self.progress_lock:
            if not self.download_progress:
                return
            
            progress_parts = []
            for task_id in sorted(self.download_progress.keys()):
                info = self.download_progress[task_id]
                # Truncate filename if too long
                short_name = info['filename'][:15] + '...' if len(info['filename']) > 18 else info['filename']
                speed_str = self._format_speed(info.get('speed', 0))
                progress_parts.append(f"[T{task_id}] {short_name}: {info['progress']:.1f}% @ {speed_str}")
            
            progress_line = " | ".join(progress_parts)
            # Clear line and print
            print(f"\r{progress_line:<180}", end='', flush=True)
    
    # Search and download files with async concurrency
    async def batch_download(self, search_terms, num_pages=1, sort_by='date', max_files=None, delay=2, threads=1):
        all_results = []
        
        for term in search_terms:
            self.logger.info(f"\n{'='*70}")
            self.logger.info(f"Searching for: {term}")
            self.logger.info(f"{'='*70}")
            
            # Collect all files to download
            files_to_download = []
            
            for page in range(1, num_pages + 1):
                if max_files and len(files_to_download) >= max_files:
                    break
                
                files = await self.search_files(term, page=page, sort_by=sort_by)
                
                if not files:
                    self.logger.info(f"No files found on page {page}")
                    break
                
                self.logger.info(f"Found {len(files)} files on page {page}")
                
                for file_info in files:
                    if max_files and len(files_to_download) >= max_files:
                        break
                    files_to_download.append(file_info)
            
            if max_files:
                files_to_download = files_to_download[:max_files]
            
            self.logger.info(f"\nPreparing to download {len(files_to_download)} files")
            
            # Download files (concurrent or sequential)
            if threads > 1:
                self.logger.info(f"Using {threads} concurrent download tasks\n")
                results = await self._download_concurrent(files_to_download, threads, delay, term)
            else:
                self.logger.info(f"Downloading sequentially\n")
                results = await self._download_sequential(files_to_download, delay, term)
            
            all_results.extend(results)
        
        return all_results
    
    # Download files one by one
    async def _download_sequential(self, files_to_download, delay, search_term):
        results = []
        
        for i, file_info in enumerate(files_to_download, 1):
            self.logger.info(f"\n[{i}/{len(files_to_download)}] File: {file_info['filename']}")
            self.logger.info(f"  Size: {file_info['size']} | Downloads: {file_info['downloads']} | Date: {file_info['upload_date']}")
            self.logger.info(f"  FID: {file_info['fid']}")
            
            success = await self.download_file(file_info['fid'], file_info['filename'])
            
            results.append({
                'search_term': search_term,
                'filename': file_info['filename'],
                'fid': file_info['fid'],
                'size': file_info['size'],
                'success': success
            })
            
            if delay > 0:
                await asyncio.sleep(delay)
        
        return results
    
    # Download files using async concurrency with semaphore
    async def _download_concurrent(self, files_to_download, max_concurrent, delay, search_term):
        results = []
        semaphore = asyncio.Semaphore(max_concurrent)
        task_counter = 0
        
        async def download_task(file_info, index, task_id):
            async with semaphore:
                self.logger.info(f"\n[{index}/{len(files_to_download)}] File: {file_info['filename']}")
                self.logger.info(f"  Size: {file_info['size']} | Downloads: {file_info['downloads']} | Date: {file_info['upload_date']}")
                self.logger.info(f"  FID: {file_info['fid']}")
                
                success = await self.download_file(file_info['fid'], file_info['filename'], task_id=task_id)
                
                if delay > 0:
                    await asyncio.sleep(delay)
                
                return {
                    'search_term': search_term,
                    'filename': file_info['filename'],
                    'fid': file_info['fid'],
                    'size': file_info['size'],
                    'success': success
                }
        
        tasks = []
        for i, file_info in enumerate(files_to_download, 1):
            task_counter += 1
            task = asyncio.create_task(download_task(file_info, i, task_counter))
            tasks.append(task)
        
        # Gather all results
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        
        for i, result in enumerate(completed):
            if isinstance(result, Exception):
                file_info = files_to_download[i]
                self.logger.error(f"Task error for {file_info['filename']}: {result}")
                results.append({
                    'search_term': search_term,
                    'filename': file_info['filename'],
                    'fid': file_info['fid'],
                    'size': file_info['size'],
                    'success': False
                })
            else:
                results.append(result)
        
        return results


# Setup logging configuration
def setup_logging(log_level):
    # Create logger
    logger = logging.getLogger('AFHScraper')
    logger.setLevel(getattr(logging, log_level.upper()))
    
    # Console handler
    console_handler = logging.StreamHandler()
    console_handler.setLevel(getattr(logging, log_level.upper()))
    console_format = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_format)
    
    # File handler
    file_handler = logging.FileHandler('afh_scraper.log')
    file_handler.setLevel(logging.DEBUG)
    file_format = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_format)
    
    # Add handlers
    logger.addHandler(console_handler)
    logger.addHandler(file_handler)
    
    return logger


# Parse command line arguments
def parse_arguments():
    parser = argparse.ArgumentParser(
        description='AndroidFileHost Scraper by fl0w',
        epilog='If no arguments provided, interactive mode will be used.'
    )
    
    parser.add_argument('-s', '--search', type=str,
                       help='Search terms (comma-separated)')
    parser.add_argument('--sort', type=str, choices=['newest', 'popular'],
                       help='Sort order (newest or popular)')
    parser.add_argument('-n', '--files', type=int,
                       help='Maximum files to download per search term')
    parser.add_argument('-m', '--mirror', type=str, choices=['usa', 'germany'],
                       help='Preferred mirror location')
    parser.add_argument('-t', '--threads', type=int, default=1,
                       help='Number of concurrent downloads (default: 1)')
    parser.add_argument('-o', '--output', type=str,
                       help='Download directory')
    parser.add_argument('-l', '--log-level', type=str, 
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR'],
                       default='INFO',
                       help='Logging level (default: INFO)')
    
    return parser.parse_args()


# Run in interactive mode
def interactive_mode():
    print("="*70)
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
        return None
    
    # Get sort preference
    print("\nHow should files be sorted?")
    print("1. Newest first")
    print("2. Most popular (by downloads)")
    sort_choice = input("Enter choice (1 or 2): ").strip()
    sort_by = 'downloads' if sort_choice == '2' else 'date'
    
    # Get max files
    print("\nHow many files should be downloaded per search term?")
    max_files = int(input("Enter number: ").strip())
    
    # Get threading preference
    print("\nEnable concurrent downloads?")
    print("1. No (download one at a time)")
    print("2. Yes (download multiple files simultaneously)")
    thread_choice = input("Enter choice (1 or 2): ").strip()
    
    threads = 1
    if thread_choice == '2':
        print("\nHow many files should be downloaded simultaneously?")
        print("Recommended: 3-5 (higher may cause rate limiting)")
        threads = int(input("Enter number (1-10): ").strip())
        threads = max(1, min(10, threads))  # Clamp between 1-10
    
    # Get mirror preference
    print("\nWhich mirror should be used primarily?")
    print("1. USA")
    print("2. Germany")
    mirror_choice = input("Enter choice (1 or 2): ").strip()
    mirror_pref = "Germany" if mirror_choice == '2' else "USA"
    
    # Get log level
    print("\nSelect logging level:")
    print("1. INFO (normal)")
    print("2. DEBUG (detailed)")
    log_choice = input("Enter choice (1 or 2): ").strip()
    log_level = 'DEBUG' if log_choice == '2' else 'INFO'
    
    return {
        'search_terms': search_terms,
        'sort_by': sort_by,
        'max_files': max_files,
        'threads': threads,
        'mirror_pref': mirror_pref,
        'log_level': log_level
    }


# Async main entry point
async def async_main():
    args = parse_arguments()
    
    # Check if running in CLI mode or interactive mode
    if args.search:
        # CLI mode
        search_terms = [term.strip() for term in args.search.split(',')]
        sort_by = 'downloads' if args.sort == 'popular' else 'date'
        max_files = args.files
        threads = args.threads
        mirror_pref = args.mirror.upper() if args.mirror else "USA"
        log_level = args.log_level
        
        if args.output:
            download_dir = args.output
        else:
            if getattr(sys, 'frozen', False):
                download_dir = os.path.dirname(sys.executable)
            else:
                download_dir = os.path.dirname(os.path.abspath(__file__))
    else:
        # Interactive mode
        config = interactive_mode()
        if not config:
            return
        
        search_terms = config['search_terms']
        sort_by = config['sort_by']
        max_files = config['max_files']
        threads = config['threads']
        mirror_pref = config['mirror_pref']
        log_level = config['log_level']
        
        if getattr(sys, 'frozen', False):
            download_dir = os.path.dirname(sys.executable)
        else:
            download_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Setup logging
    logger = setup_logging(log_level)
    
    # Calculate pages needed
    num_pages = (max_files + 14) // 15 if max_files else 1
    
    # Initialize scraper
    async with AFHScraper(
        download_dir=download_dir,
        mirror_preference=mirror_pref
    ) as scraper:
        scraper.client.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        })
        logger.info(f"\n{'='*70}")
        logger.info(f"Download directory: {scraper.download_dir.absolute()}")
        logger.info(f"Mirror preference: {scraper.mirror_preference}")
        logger.info(f"Sort by: {'Most popular' if sort_by == 'downloads' else 'Newest'}")
        logger.info(f"Max files per search: {max_files}")
        logger.info(f"Concurrent downloads: {threads}")
        logger.info(f"Search terms: {', '.join(search_terms)}")
        logger.info(f"{'='*70}")

        # Start downloading
        results = await scraper.batch_download(
            search_terms,
            num_pages=num_pages,
            sort_by=sort_by,
            max_files=max_files,
            delay=3,
            threads=threads
        )

    # Summary
    successful = sum(1 for r in results if r['success'])
    logger.info(f"\n{'='*70}")
    logger.info(f"Summary: {successful}/{len(results)} files downloaded successfully")
    logger.info(f"{'='*70}")


# Main entry point - runs the async main
def main():
    asyncio.run(async_main())


if __name__ == "__main__":
    main()