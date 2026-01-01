#!/usr/bin/env python3
"""
PixelOS Build Script
Automated ROM building with Telegram notifications and GoFile upload
"""

import os
import sys
import json
import subprocess
import threading
import time
import re
import hashlib
import platform
import argparse
import shutil
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
import requests

# Constants
ROM_NAME = "PixelOS"
SCRIPT_DIR = Path(__file__).parent.resolve()
DEFAULT_BUILD_DIR = Path.home() / "pos"
MANIFEST_URL = "https://github.com/PixelOS-AOSP/android_manifest.git"
MANIFEST_BRANCH = "sixteen-qpr1"
SYNC_JOBS = 24

# Android version mapping
ANDROID_VERSIONS = {
    "bp3a": "16 QPR1",
    "bp2a": "16",
    "ap3a": "15 QPR3",
    "ap2a": "15 QPR2",
    "ap1a": "15 QPR1",
}

# ANSI color codes
class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    NC = '\033[0m'  # No Color

def print_status(msg: str):
    """Print info message"""
    print(f"{Colors.BLUE}[INFO]{Colors.NC} {msg}")

def print_success(msg: str):
    """Print success message"""
    print(f"{Colors.GREEN}[SUCCESS]{Colors.NC} {msg}")

def print_warning(msg: str):
    """Print warning message"""
    print(f"{Colors.YELLOW}[WARNING]{Colors.NC} {msg}")

def print_error(msg: str):
    """Print error message"""
    print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")


class BuildConfig:
    """Loads and validates JSON device configuration"""

    def __init__(self, device_or_path: str):
        self.config_data: Dict[str, Any] = {}
        self._load_config(device_or_path)
        self._validate()

    def _load_config(self, device_or_path: str):
        """Load configuration from device codename or JSON path"""
        # Check if it's a direct path to JSON file
        config_path = Path(device_or_path)
        if not config_path.exists():
            # Try devices/ directory
            config_path = SCRIPT_DIR / "devices" / f"{device_or_path}.json"

        if not config_path.exists():
            raise FileNotFoundError(f"Device config not found: {device_or_path}")

        print_status(f"Loading device configuration from {config_path}")

        with open(config_path, 'r') as f:
            self.config_data = json.load(f)

        device_name = self.get_device_name()
        print_success(f"Device configuration loaded: {self.get_device_codename()} ({device_name})")

    def _validate(self):
        """Validate required fields in config"""
        required_fields = ["device", "build", "repositories"]
        for field in required_fields:
            if field not in self.config_data:
                raise ValueError(f"Missing required field in config: {field}")

    def get_device_codename(self) -> str:
        return self.config_data["device"]["codename"]

    def get_device_name(self) -> str:
        return self.config_data["device"]["full_name"]

    def get_build_variant(self) -> str:
        return self.config_data["build"]["variant"]

    def get_target_release(self) -> str:
        return self.config_data["build"]["target_release"]

    def get_repositories(self) -> Dict[str, Any]:
        return self.config_data.get("repositories", {})

    def get_environment_vars(self) -> Dict[str, str]:
        return self.config_data.get("environment", {})


class TelegramNotifier:
    """Handles Telegram API communication for build notifications"""

    def __init__(self, bot_token: str, chat_id: str, config: BuildConfig, orchestrator=None):
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.chat_id = chat_id
        self.message_id: Optional[int] = None
        self.config = config
        self.orchestrator = orchestrator

    def send_message(self, text: str) -> bool:
        """Send initial message and store message_id"""
        try:
            response = requests.post(
                f"{self.base_url}/sendMessage",
                json={
                    "chat_id": self.chat_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            if response.ok:
                self.message_id = response.json()["result"]["message_id"]
                return True
            else:
                print_warning(f"Telegram API error: {response.text}")
        except Exception as e:
            print_warning(f"Failed to send Telegram message: {e}")
        return False

    def update_message(self, text: str) -> bool:
        """Update existing message"""
        if not self.message_id:
            return False
        try:
            requests.post(
                f"{self.base_url}/editMessageText",
                json={
                    "chat_id": self.chat_id,
                    "message_id": self.message_id,
                    "text": text,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            return True
        except Exception as e:
            print_warning(f"Failed to update message: {e}")
            return False

    def send_document(self, file_path: Path, caption: str = "") -> bool:
        """Send document file to Telegram"""
        try:
            with open(file_path, 'rb') as f:
                response = requests.post(
                    f"{self.base_url}/sendDocument",
                    data={
                        "chat_id": self.chat_id,
                        "caption": caption,
                        "parse_mode": "HTML"
                    },
                    files={"document": f},
                    timeout=30
                )
            if response.ok:
                print_success("Error log sent to Telegram")
                return True
            else:
                print_warning(f"Failed to send document: {response.text}")
        except Exception as e:
            print_warning(f"Failed to send document to Telegram: {e}")
        return False

    def build_message(self, status: str, progress_display: str = "") -> str:
        """Build formatted HTML message with device info and progress"""
        # Get device info
        device = self.config.get_device_codename()
        device_name = self.config.get_device_name()
        variant = self.config.get_build_variant()

        # Get system info
        username = os.getenv('USER', 'unknown')
        arch = platform.machine()

        # Map Android version
        target_release = self.config.get_target_release()
        android_version = ANDROID_VERSIONS.get(target_release, "Unknown")

        # Get ROM version
        version = "Building..."
        if self.orchestrator and self.orchestrator.output_file:
            version = self._extract_version() or "Building..."

        # Build status text
        status_text = self._format_status(status, progress_display)

        # Build HTML message
        message = f"""🚀 <b>Build {status}</b> for <b>{ROM_NAME}</b>
━━━━━━━━━━━━━━━━━━━━━━━
📱 <b>Device:</b> {device} ({device_name})
👤 <b>User:</b> {username}
🔢 <b>Ver:</b> {version}
🔧 <b>Variant:</b> {variant}
📦 <b>Android:</b> {android_version}
🏗 <b>Arch:</b> {arch}
━━━━━━━━━━━━━━━━━━━━━━━
📊 <b>Status:</b> {status_text}"""

        return message

    def _extract_version(self) -> Optional[str]:
        """Extract ROM version from output filename"""
        if not self.orchestrator or not self.orchestrator.output_file:
            return None

        filename = self.orchestrator.output_file.name
        match = re.search(r'PixelOS[_-](.+?)\.zip', filename)
        return match.group(1) if match else None

    def _format_status(self, status: str, progress_display: str) -> str:
        """Format status line with progress"""
        if status == "Checking":
            if progress_display:
                return progress_display
            return "⏳ Checking requirements"
        elif status == "Syncing":
            if progress_display:
                return f"⏳ Syncing {progress_display}"
            return "⏳ Syncing sources"
        elif status == "Cloning":
            if progress_display:
                return progress_display
            return "⏳ Cloning repos"
        elif status == "Compiling":
            if progress_display:
                return f"⏳ Compiling {progress_display}"
            return "⏳ Compiling ROM"
        elif status == "Uploading":
            if progress_display:
                return progress_display
            return "⏳ Uploading to GoFile"
        elif status == "Done":
            if progress_display:
                return progress_display
            return "✅ Build complete"
        elif status == "Failed":
            if progress_display:
                return progress_display
            return "❌ Build failed"
        return progress_display or status


class ProgressMonitor:
    """Background thread that monitors build logs and updates Telegram"""

    def __init__(self, log_file: Path, notifier: TelegramNotifier, status: str):
        self.log_file = log_file
        self.notifier = notifier
        self.status = status
        self.last_progress_display = ""
        self.running = False
        self.thread: Optional[threading.Thread] = None

    def start(self):
        """Start monitoring in background thread"""
        self.running = True
        self.thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self.thread.start()

    def stop(self):
        """Stop monitoring and wait for thread"""
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _monitor_loop(self):
        """Background loop: tail log, extract progress, update Telegram"""
        while self.running:
            time.sleep(3)  # Update every 3 seconds

            progress_display = self._extract_progress()
            if progress_display and progress_display != self.last_progress_display:
                message = self.notifier.build_message(self.status, progress_display)
                self.notifier.update_message(message)
                self.last_progress_display = progress_display

    def _extract_progress(self) -> str:
        """Extract progress from log file"""
        if not self.log_file.exists():
            return ""

        try:
            # Read last 200 lines
            with open(self.log_file, 'r', errors='ignore') as f:
                lines = f.readlines()[-200:]

            # Search from end to start
            for line in reversed(lines):
                if self.status == "Compiling":
                    # Match ninja format: [ 93% 137/147 2m29s remaining] or [ 93% 137/147]
                    # Don't require ] immediately after numbers - allow optional time remaining
                    match = re.search(r'\[\s*(\d+)%\s+(\d+)/(\d+)', line)
                    if match:
                        percent, current, total = match.groups()
                        return f"[{percent}% {current}/{total}]"

                elif self.status == "Syncing":
                    # Match: Fetching: 45%
                    match = re.search(r'Fetching.*?(\d+)%', line)
                    if match:
                        return f"{match.group(1)}%"

            return ""
        except Exception:
            return ""


class BuildOrchestrator:
    """Main build workflow coordinator"""

    def __init__(self, config: BuildConfig, notifier: Optional[TelegramNotifier], build_dir: Path):
        self.config = config
        self.notifier = notifier
        self.start_time = time.time()
        self.output_file: Optional[Path] = None
        self.build_dir = build_dir
        self.gofile_download_link: Optional[str] = None
        self.current_log_file: Optional[Path] = None
        self.error_log_file = Path(f"/tmp/build_error_{os.getpid()}.txt")

        # Set notifier's orchestrator reference
        if self.notifier:
            self.notifier.orchestrator = self

    def run(self, skip_sync: bool, skip_clone: bool, skip_upload: bool,
            clean: bool, clean_repos: bool):
        """Main build pipeline"""
        try:
            # Check requirements
            self._notify("Checking", "⏳ Checking requirements")
            self._check_requirements()
            self._notify("Checking", "✅ Requirements OK")

            # Setup build directory
            self.build_dir.mkdir(parents=True, exist_ok=True)

            # Sync sources
            if not skip_sync:
                self._notify("Syncing", "🔄 Starting source sync")
                log_sync = Path(f"/tmp/build_sync_{os.getpid()}.log")
                self.current_log_file = log_sync
                monitor = ProgressMonitor(log_sync, self.notifier, "Syncing")
                monitor.start()
                self._sync_sources(log_sync)
                monitor.stop()
                self._notify("Syncing", "✅ Complete")
            else:
                if not (self.build_dir / ".repo").exists():
                    raise FileNotFoundError(f"No existing repo found in {self.build_dir}. Cannot skip sync.")
                self._notify("Syncing", "⏭️ Skipped")

            # Clone device repos
            if not skip_clone:
                if clean_repos:
                    self._notify("Cloning", "🧹 Cleaning existing repos")
                    self._clean_repos()

                self._notify("Cloning", "⏳ Cloning repos")
                self._clone_repos()
                self._notify("Cloning", "✅ Complete")
            else:
                # Verify device tree exists
                device_tree_path = self.config.get_repositories().get("device_tree", {}).get("path")
                if device_tree_path and not (self.build_dir / device_tree_path).exists():
                    raise FileNotFoundError(f"Device tree not found at {device_tree_path}. Cannot skip cloning.")
                self._notify("Cloning", "⏭️ Skipped")

            # Build ROM
            self._notify("Compiling", "🔨 Starting compilation")
            log_build = Path(f"/tmp/build_mka_{os.getpid()}.log")
            self.current_log_file = log_build
            monitor = ProgressMonitor(log_build, self.notifier, "Compiling")
            monitor.start()
            self._build_rom(log_build, clean)
            monitor.stop()
            self._notify("Compiling", "✅ Complete")

            # Upload to GoFile
            if not skip_upload and self.output_file:
                self._notify("Uploading", "⏳ Uploading to GoFile")
                self._upload_gofile()
                if self.gofile_download_link:
                    self._notify("Done", f"🔗 <a href=\"{self.gofile_download_link}\">Download ROM</a>")
                else:
                    self._notify("Done", "⚠️ Upload failed")
            else:
                if skip_upload:
                    self._notify("Done", "⏭️ Upload skipped")
                else:
                    self._notify("Done", "✅ Build complete")

            # Show summary
            self._show_summary()

        except KeyboardInterrupt:
            print()
            print_error("Build interrupted by user")
            self._notify("Failed", "⚠️ Build interrupted by user")
            self.cleanup()
            sys.exit(1)
        except Exception as e:
            print_error(f"Build failed: {e}")
            self._notify("Failed", f"❌ Error: {str(e)}")

            # Send error logs to Telegram
            self._send_error_logs(e)
            raise
        finally:
            # Cleanup temporary files on successful completion
            if not hasattr(self, '_error_occurred'):
                self.cleanup()

    def _send_error_logs(self, exception: Exception):
        """Send error logs to Telegram (both out/error.log and generated report)"""
        if not self.notifier:
            print_warning("Notifier not configured, skipping error log upload")
            return

        error_log_path = self.build_dir / "out" / "error.log"
        device_name = self.config.get_device_codename()

        # Always try to send out/error.log if it exists
        if error_log_path.exists() and error_log_path.stat().st_size > 0:
            print_status(f"Found out/error.log ({error_log_path.stat().st_size} bytes), sending to Telegram...")
            try:
                success = self.notifier.send_document(
                    error_log_path,
                    caption=f"❌ <b>Build failed for {device_name}</b>\n\n<b>Error:</b> {str(exception)}\n\nSee attached <code>error.log</code> from build system."
                )
                if success:
                    print_success("out/error.log sent successfully")
                else:
                    print_warning("Failed to send out/error.log")
            except Exception as send_error:
                print_warning(f"Exception while sending out/error.log: {send_error}")

        # Always generate and send detailed error report
        print_status("Generating detailed error report...")
        if self._capture_error_log(exception):
            if self.error_log_file.exists():
                print_status(f"Sending detailed error report to Telegram ({self.error_log_file.stat().st_size} bytes)...")
                try:
                    success = self.notifier.send_document(
                        self.error_log_file,
                        caption=f"❌ <b>Detailed error report for {device_name}</b>\n\n<b>Error:</b> {str(exception)}\n\nThis report includes build log tail and error keyword matches."
                    )
                    if success:
                        print_success("Detailed error report sent successfully")
                    else:
                        print_warning("Failed to send detailed error report")
                except Exception as send_error:
                    print_warning(f"Exception while sending error report: {send_error}")
        else:
            print_warning("Failed to generate detailed error report")

    def _capture_error_log(self, exception: Exception):
        """Capture error details and save to error log file"""
        try:
            with open(self.error_log_file, 'w', encoding='utf-8') as error_file:
                # Write exception details
                error_file.write("=" * 60 + "\n")
                error_file.write("BUILD ERROR REPORT\n")
                error_file.write("=" * 60 + "\n\n")
                error_file.write(f"Error: {str(exception)}\n")
                error_file.write(f"Type: {type(exception).__name__}\n")
                error_file.write(f"Device: {self.config.get_device_codename()}\n")
                error_file.write(f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}\n\n")

                # If there's a current log file, extract relevant lines
                if self.current_log_file and self.current_log_file.exists():
                    error_file.write("=" * 60 + "\n")
                    error_file.write("BUILD LOG (Last 500 lines)\n")
                    error_file.write("=" * 60 + "\n\n")

                    # Read file once and process both sections
                    with open(self.current_log_file, 'r', encoding='utf-8', errors='replace') as log:
                        all_lines = log.readlines()

                    # Get last 500 lines
                    last_lines = all_lines[-500:] if len(all_lines) > 500 else all_lines
                    error_file.writelines(last_lines)

                    # Add error keywords search from all lines
                    error_file.write("\n" + "=" * 60 + "\n")
                    error_file.write("ERROR LINES FROM BUILD LOG\n")
                    error_file.write("=" * 60 + "\n\n")

                    error_keywords = ['error:', 'Error:', 'ERROR:', 'FAILED', 'failed:', 'ninja: build stopped']
                    error_lines = [line for line in all_lines if any(keyword in line for keyword in error_keywords)]

                    if error_lines:
                        error_file.writelines(error_lines)
                    else:
                        error_file.write("No specific error keywords found in log.\n")

            print_status(f"Error log saved to {self.error_log_file}")
            return True
        except Exception as e:
            print_warning(f"Failed to capture error log: {e}")
            return False

    def cleanup(self):
        """Clean up temporary log files"""
        temp_files = [self.error_log_file]

        # Add current log file if it's a temp file in /tmp
        if self.current_log_file and str(self.current_log_file).startswith('/tmp/'):
            temp_files.append(self.current_log_file)

        for temp_file in temp_files:
            if temp_file and Path(temp_file).exists():
                try:
                    Path(temp_file).unlink()
                    print_status(f"Cleaned up temporary file: {temp_file}")
                except Exception as e:
                    print_warning(f"Failed to clean up {temp_file}: {e}")

    def _notify(self, status: str, extra_info: str = ""):
        """Helper to send/update notification (non-blocking)"""
        try:
            if self.notifier:
                msg = self.notifier.build_message(status, extra_info)
                if self.notifier.message_id:
                    self.notifier.update_message(msg)
                else:
                    self.notifier.send_message(msg)
        except Exception as e:
            print_warning(f"Telegram notification failed: {e}")

    def _check_requirements(self):
        """Check if required commands are available"""
        required_commands = ["repo", "git", "jq"]
        for cmd in required_commands:
            if not shutil.which(cmd):
                raise FileNotFoundError(f"Required command not found: {cmd}")
        print_status("System requirements check completed")

    def _sync_sources(self, log_file: Path):
        """Initialize and sync ROM sources"""
        os.chdir(self.build_dir)

        # Initialize repo
        print_status("Initializing repository...")
        result = subprocess.run(
            ["repo", "init", "-u", MANIFEST_URL, "-b", MANIFEST_BRANCH, "--git-lfs"],
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to initialize repository: {result.stderr}")

        # Sync sources (use tee to show output and log it)
        print_status(f"Syncing sources with {SYNC_JOBS} jobs (this may take a while)...")
        sync_cmd = f"repo sync -c --force-sync --optimized-fetch --no-tags --no-clone-bundle --prune -j{SYNC_JOBS} 2>&1 | tee {log_file}"
        result = subprocess.run(
            ["bash", "-c", sync_cmd],
            cwd=self.build_dir
        )
        if result.returncode != 0:
            raise RuntimeError("Failed to sync sources")

        print_success("ROM sources synced successfully")

    def _clean_repos(self):
        """Clean existing device repositories"""
        print_status("Cleaning existing device repositories...")
        for repo_name, repo_info in self.config.get_repositories().items():
            repo_path = self.build_dir / repo_info.get("path", "")
            if repo_path.exists():
                shutil.rmtree(repo_path)
                print_status(f"Removed {repo_name} at {repo_path}")

    def _clone_repos(self):
        """Clone device-specific repositories"""
        repos = self.config.get_repositories()
        total = len(repos)
        current = 0

        for repo_name, repo_info in repos.items():
            current += 1
            url = repo_info.get("url")
            branch = repo_info.get("branch")
            path = repo_info.get("path")

            if not all([url, branch, path]):
                print_warning(f"Skipping {repo_name}: incomplete config")
                continue

            target_path = self.build_dir / path
            target_path.parent.mkdir(parents=True, exist_ok=True)

            print_status(f"[{current}/{total}] Cloning {repo_name} to {path}...")

            result = subprocess.run(
                ["git", "clone", "-b", branch, url, str(target_path)]
            )
            if result.returncode != 0:
                raise RuntimeError(f"Failed to clone {repo_name}")

        print_success(f"Successfully cloned {total} repositories")

    def _build_rom(self, log_file: Path, clean: bool):
        """Build ROM with mka"""
        os.chdir(self.build_dir)

        # Set environment variables from config
        env = os.environ.copy()
        for key, value in self.config.get_environment_vars().items():
            env[key] = value
            print_status(f"Exported: {key}={value}")

        # Source build environment and lunch
        device = self.config.get_device_codename()
        variant = self.config.get_build_variant()
        target_release = self.config.get_target_release()
        lunch_target = f"custom_{device}-{target_release}-{variant}"

        print_status("Sourcing build environment...")
        print_status(f"Running lunch {lunch_target}...")

        # Build command
        cores = os.cpu_count() or 8
        print_status(f"Starting build with {cores} parallel jobs...")
        print_status("Building ROM (this will take several hours)...")

        # Run build in bash with sourcing (use tee to show output and log it)
        build_script = f"""
set -e
cd {self.build_dir}
source build/envsetup.sh
lunch {lunch_target}
{'make installclean' if clean else ''}
mka pixelos -j{cores} 2>&1 | tee {log_file}
"""

        result = subprocess.run(
            ["bash", "-c", build_script],
            env=env
        )

        if result.returncode != 0:
            raise RuntimeError("ROM build failed!")

        # Find output file
        output_dir = self.build_dir / "out" / "target" / "product" / device
        zip_files = list(output_dir.glob("*PixelOS*.zip")) + list(output_dir.glob("*pixelos*.zip"))

        if zip_files:
            self.output_file = zip_files[0]
            print_success(f"ROM file created: {self.output_file}")
            # Show file size
            size_bytes = self.output_file.stat().st_size
            size_mb = size_bytes / (1024 * 1024)
            print_status(f"File size: {size_mb:.2f} MB")
        else:
            print_warning("ROM file not found in output directory")

    def _upload_gofile(self):
        """Upload ROM to GoFile and return download link"""
        if not self.output_file:
            print_warning("No output file to upload")
            return

        print_status("Calculating SHA256 checksum...")
        sha256_hash = self._calculate_sha256(self.output_file)

        # Try to get best server from API, then fall back to hardcoded list
        servers = []
        try:
            print_status("Getting optimal GoFile server...")
            response = requests.get("https://api.gofile.io/servers", timeout=10)
            data = response.json()
            if data.get("status") == "ok" and data.get("data", {}).get("servers"):
                servers = [srv["name"] for srv in data["data"]["servers"]]
                print_status(f"Got {len(servers)} servers from API")
        except Exception as e:
            print_warning(f"Could not fetch servers from API: {e}")

        # Add hardcoded fallback servers
        fallback_servers = ["store1", "store2", "store3", "store4", "store5", "store6"]
        for server in fallback_servers:
            if server not in servers:
                servers.append(server)

        if not servers:
            print_error("No GoFile servers available")
            return

        # Try each server until one succeeds
        upload_success = False
        for i, server in enumerate(servers):
            print_status(f"Trying server {server} ({i+1}/{len(servers)})...")
            try:
                with open(self.output_file, 'rb') as f:
                    response = requests.post(
                        f"https://{server}.gofile.io/uploadFile",
                        files={"file": f},
                        timeout=3600  # 1 hour timeout for large files
                    )

                result = response.json()
                if result.get("status") == "ok":
                    self.gofile_download_link = result["data"]["downloadPage"]
                    upload_success = True

                    # Display file details
                    file_size = self.output_file.stat().st_size / (1024 * 1024)
                    print()
                    print(f"{Colors.GREEN}Upload successful to {server}!{Colors.NC}")
                    print(f"{Colors.GREEN}File Details:{Colors.NC}")
                    print(f"  File: {self.output_file.name}")
                    print(f"  Size: {file_size:.2f} MB")
                    print(f"  SHA256: {sha256_hash}")
                    print(f"  Download: {self.gofile_download_link}")
                    print()
                    break
                else:
                    print_warning(f"Server {server} returned error: {result.get('error', 'Unknown')}")

            except Exception as e:
                print_warning(f"Failed to upload to {server}: {e}")
                continue

        if not upload_success:
            print_error("Upload failed on all available servers")

    def _calculate_sha256(self, file_path: Path) -> str:
        """Calculate SHA256 checksum of file"""
        sha256 = hashlib.sha256()
        with open(file_path, 'rb') as f:
            for chunk in iter(lambda: f.read(8192), b''):
                sha256.update(chunk)
        return sha256.hexdigest()

    def _show_summary(self):
        """Display build summary"""
        end_time = time.time()
        build_time = end_time - self.start_time

        hours = int(build_time // 3600)
        minutes = int((build_time % 3600) // 60)
        seconds = int(build_time % 60)

        print()
        print(f"{Colors.GREEN}================================{Colors.NC}")
        print(f"{Colors.GREEN}       BUILD COMPLETED!         {Colors.NC}")
        print(f"{Colors.GREEN}================================{Colors.NC}")
        print(f"{Colors.GREEN}Total build time: {hours}h {minutes}m {seconds}s{Colors.NC}")
        if self.gofile_download_link:
            print(f"{Colors.GREEN}Download link: {self.gofile_download_link}{Colors.NC}")
        print()


def get_telegram_credentials() -> Tuple[Optional[str], Optional[str]]:
    """Prompt for Telegram credentials if not in environment"""
    if os.getenv("TELEGRAM_DISABLE") == "true":
        return None, None

    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        print("━" * 40)
        print("  Telegram Build Notifications")
        print("━" * 40)
        response = input("Enable Telegram notifications? (y/N): ").strip().lower()
        if response == 'y':
            token = input("Enter Telegram Bot Token: ").strip()
            chat_id = input("Enter Telegram Chat ID: ").strip()
        else:
            return None, None

    return token, chat_id


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="PixelOS Build Script with Telegram notifications and GoFile upload"
    )
    parser.add_argument("device", help="Device codename or path to JSON config")
    parser.add_argument("--skip-sync", action="store_true",
                       help="Skip source sync")
    parser.add_argument("--skip-clone", action="store_true",
                       help="Skip device repo cloning")
    parser.add_argument("--skip-upload", action="store_true",
                       help="Skip GoFile upload")
    parser.add_argument("--clean", action="store_true",
                       help="Clean build (make installclean)")
    parser.add_argument("--clean-repos", action="store_true",
                       help="Clean device repos before cloning")
    parser.add_argument("--build-dir", type=Path, default=DEFAULT_BUILD_DIR,
                       help=f"Build directory (default: {DEFAULT_BUILD_DIR})")

    args = parser.parse_args()

    # Display header
    print(f"{Colors.BLUE}================================{Colors.NC}")
    print(f"{Colors.BLUE}  PixelOS Custom ROM Builder  {Colors.NC}")
    print(f"{Colors.BLUE}================================{Colors.NC}")
    print()

    # Load config
    try:
        config = BuildConfig(args.device)
    except Exception as e:
        print_error(f"Failed to load device config: {e}")
        sys.exit(1)

    # Display build configuration
    print("Build Configuration:")
    print(f"  ROM: {ROM_NAME}")
    print(f"  Device: {config.get_device_codename()} ({config.get_device_name()})")
    print(f"  Build Directory: {args.build_dir}")
    print(f"  Manifest Branch: {MANIFEST_BRANCH}")
    print(f"  Sync Jobs: {SYNC_JOBS}")
    print(f"  Build Variant: {config.get_build_variant()}")
    print(f"  Target Release: {config.get_target_release()}")
    print(f"  Skip Sync: {args.skip_sync}")
    print(f"  Skip Clone: {args.skip_clone}")
    print(f"  Skip Upload: {args.skip_upload}")
    print()

    # Get Telegram credentials
    bot_token, chat_id = get_telegram_credentials()
    if bot_token and chat_id:
        print_status("Telegram notifications enabled")
    else:
        print_status("Telegram notifications disabled for this build")

    # Confirmation
    response = input("Continue with build? (y/N): ").strip().lower()
    if response != 'y':
        print_status("Build cancelled")
        sys.exit(0)

    # Create notifier
    notifier = None
    if bot_token and chat_id:
        notifier = TelegramNotifier(bot_token, chat_id, config)

    # Run build
    orchestrator = BuildOrchestrator(config, notifier, args.build_dir)
    orchestrator.run(
        skip_sync=args.skip_sync,
        skip_clone=args.skip_clone,
        skip_upload=args.skip_upload,
        clean=args.clean,
        clean_repos=args.clean_repos
    )


if __name__ == "__main__":
    main()
