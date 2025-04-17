#!/usr/bin/env python3
"""
Deployment checker for Pinterest Image Generator
Run this script to diagnose common deployment issues.
"""

import os
import sys
import tempfile
import subprocess
import requests
import platform
import socket
import json
from pathlib import Path

# Color codes for terminal output
class Colors:
    OK = '\033[92m'      # Green
    WARNING = '\033[93m' # Yellow
    ERROR = '\033[91m'   # Red
    RESET = '\033[0m'    # Reset color
    INFO = '\033[94m'    # Blue
    HEADER = '\033[95m'  # Purple

def print_status(status, message):
    """Print a formatted status message"""
    if status == "OK":
        print(f"{Colors.OK}[✓] {message}{Colors.RESET}")
    elif status == "WARN":
        print(f"{Colors.WARNING}[!] {message}{Colors.RESET}")
    elif status == "ERROR":
        print(f"{Colors.ERROR}[✗] {message}{Colors.RESET}")
    elif status == "INFO":
        print(f"{Colors.INFO}[i] {message}{Colors.RESET}")
    elif status == "HEADER":
        print(f"\n{Colors.HEADER}=== {message} ==={Colors.RESET}")

def check_system_info():
    """Check system information"""
    print_status("HEADER", "SYSTEM INFORMATION")
    
    print_status("INFO", f"Python version: {sys.version.split()[0]}")
    print_status("INFO", f"Operating system: {platform.platform()}")
    
    try:
        # Get hostname and IP address
        hostname = socket.gethostname()
        ip_address = socket.gethostbyname(hostname)
        print_status("INFO", f"Hostname: {hostname}")
        print_status("INFO", f"IP address: {ip_address}")
    except:
        print_status("WARN", "Could not determine hostname/IP")
    
    # Check if we're on a VPS or local machine
    is_vps = False
    try:
        with open('/proc/1/cgroup', 'r') as f:
            if 'docker' in f.read() or 'lxc' in f.read():
                is_vps = True
    except:
        pass
    
    if is_vps:
        print_status("INFO", "Running on a containerized environment (Docker/LXC)")
    else:
        print_status("INFO", "Running on a regular operating system")

def check_directories():
    """Check if directories exist and have correct permissions"""
    print_status("HEADER", "DIRECTORY PERMISSIONS")
    
    # Check current directory
    current_dir = os.getcwd()
    print_status("INFO", f"Current working directory: {current_dir}")
    
    # Check if app.py exists
    app_path = os.path.join(current_dir, 'app.py')
    if os.path.exists(app_path):
        print_status("OK", "Found app.py in current directory")
    else:
        print_status("ERROR", "app.py not found in current directory")
    
    # Check static directory
    static_dir = os.path.join(current_dir, 'static')
    if os.path.exists(static_dir):
        print_status("OK", f"Static directory exists at {static_dir}")
        
        # Check if static directory is writable
        try:
            test_file = os.path.join(static_dir, 'test_write.txt')
            with open(test_file, 'w') as f:
                f.write('test')
            os.remove(test_file)
            print_status("OK", "Static directory is writable")
        except Exception as e:
            print_status("ERROR", f"Static directory is not writable: {e}")
    else:
        print_status("WARN", "Static directory does not exist")
        try:
            os.makedirs(static_dir, exist_ok=True)
            print_status("OK", "Created static directory")
        except Exception as e:
            print_status("ERROR", f"Could not create static directory: {e}")
    
    # Check if temp directory is writable
    try:
        with tempfile.NamedTemporaryFile() as tmp:
            print_status("OK", f"Temp directory is writable: {tempfile.gettempdir()}")
    except Exception as e:
        print_status("ERROR", f"Temp directory is not writable: {e}")

def check_configuration():
    """Check configuration files"""
    print_status("HEADER", "CONFIGURATION")
    
    # Check .env file
    env_path = os.path.join(os.getcwd(), '.env')
    if os.path.exists(env_path):
        print_status("OK", "Found .env file")
        
        # Check if Runware API key is set
        try:
            from dotenv import load_dotenv
            load_dotenv()
            api_key = os.getenv('RUNWARE_API_KEY')
            if api_key:
                masked_key = api_key[:4] + '*' * (len(api_key) - 8) + api_key[-4:]
                print_status("OK", f"Runware API key is set: {masked_key}")
            else:
                print_status("ERROR", "Runware API key is not set in .env file")
        except ImportError:
            print_status("WARN", "Could not load dotenv, make sure python-dotenv is installed")
        
        # Check proxy configuration
        proxy_path = os.getenv('PROXY_PATH')
        if proxy_path:
            print_status("INFO", f"Proxy path is set to: {proxy_path}")
        else:
            print_status("INFO", "No proxy path is set (PROXY_PATH not defined)")
    else:
        print_status("WARN", ".env file not found")

def check_flask_status():
    """Check if Flask server is running"""
    print_status("HEADER", "FLASK SERVER STATUS")
    
    # Try to connect to the Flask server
    try:
        response = requests.get('http://localhost:5000', timeout=2)
        print_status("OK", f"Flask server is running on port 5000 (Status: {response.status_code})")
    except requests.exceptions.ConnectionError:
        print_status("WARN", "Could not connect to Flask server on port 5000")
        
        # Check if a different port is specified in .env
        try:
            from dotenv import load_dotenv
            load_dotenv()
            port = os.getenv('PORT', '5000')
            if port != '5000':
                try:
                    response = requests.get(f'http://localhost:{port}', timeout=2)
                    print_status("OK", f"Flask server is running on port {port} (Status: {response.status_code})")
                except:
                    print_status("WARN", f"Could not connect to Flask server on port {port}")
        except ImportError:
            pass
    
    # Check if the process is running
    try:
        if os.name == 'posix':  # Linux/Unix
            output = subprocess.check_output(["ps", "aux"]).decode('utf-8')
            if 'python' in output and 'app.py' in output:
                print_status("OK", "Flask process is running")
            else:
                print_status("WARN", "Flask process does not appear to be running")
        elif os.name == 'nt':  # Windows
            output = subprocess.check_output(["tasklist"]).decode('utf-8')
            if 'python' in output:
                print_status("OK", "Python process is running (could be Flask)")
            else:
                print_status("WARN", "No Python process appears to be running")
    except Exception as e:
        print_status("INFO", f"Could not check process status: {e}")

def test_image_generation():
    """Test image generation API"""
    print_status("HEADER", "IMAGE GENERATION TEST")
    
    url = 'http://localhost:5000/generate-image'
    
    # Check if a different port is specified in .env
    try:
        from dotenv import load_dotenv
        load_dotenv()
        port = os.getenv('PORT', '5000')
        if port != '5000':
            url = f'http://localhost:{port}/generate-image'
    except ImportError:
        pass
    
    # Prepare the request
    data = {
        "image_prompt": "test landscape with mountains and sunset",
        "title": "Test Image",
        "Style": "style1"
    }
    
    print_status("INFO", f"Sending test request to {url}")
    print_status("INFO", f"Request data: {json.dumps(data)}")
    
    try:
        response = requests.post(url, json=data, timeout=30)
        
        if response.status_code == 200:
            # Parse the result
            result = response.json()
            print_status("OK", f"Request successful (Status: {response.status_code})")
            print_status("INFO", f"Response: {json.dumps(result)}")
            
            if 'image_url' in result:
                # Try to download the image
                try:
                    img_response = requests.get(result['image_url'], timeout=5)
                    if img_response.status_code == 200:
                        print_status("OK", f"Image URL is accessible: {result['image_url']}")
                    else:
                        print_status("ERROR", f"Could not access image URL (Status: {img_response.status_code})")
                except Exception as e:
                    print_status("ERROR", f"Error accessing image URL: {e}")
            else:
                print_status("ERROR", "No image URL in response")
            
            # If full_path exists in response, check if it exists
            if 'full_path' in result:
                if os.path.exists(result['full_path']):
                    print_status("OK", f"Image file exists at: {result['full_path']}")
                else:
                    print_status("ERROR", f"Image file does not exist at: {result['full_path']}")
        else:
            print_status("ERROR", f"Request failed (Status: {response.status_code})")
            print_status("INFO", f"Response: {response.text}")
    except Exception as e:
        print_status("ERROR", f"Error sending test request: {e}")

def check_nginx_config():
    """Check Nginx configuration if it exists"""
    print_status("HEADER", "NGINX CONFIGURATION")
    
    # Check if nginx is installed
    try:
        nginx_version = subprocess.check_output(["nginx", "-v"], stderr=subprocess.STDOUT).decode('utf-8')
        print_status("INFO", f"Nginx version: {nginx_version.strip()}")
        
        # Check if sites-available contains our config
        nginx_config_paths = [
            '/etc/nginx/sites-available/pinterest-generator',
            '/etc/nginx/conf.d/pinterest-generator.conf'
        ]
        
        config_found = False
        for path in nginx_config_paths:
            if os.path.exists(path):
                print_status("OK", f"Found Nginx configuration at {path}")
                config_found = True
                
                # Read the config
                try:
                    with open(path, 'r') as f:
                        config = f.read()
                        
                        # Check for static file configuration
                        if 'location /static/' in config:
                            print_status("OK", "Nginx configuration includes static file handling")
                        else:
                            print_status("WARN", "Nginx configuration does not include static file handling")
                except Exception as e:
                    print_status("WARN", f"Could not read Nginx configuration: {e}")
        
        if not config_found:
            print_status("WARN", "No Nginx configuration found for the application")
            
        # Check if nginx service is running
        try:
            subprocess.check_output(["systemctl", "is-active", "nginx"])
            print_status("OK", "Nginx service is running")
        except:
            print_status("WARN", "Nginx service may not be running")
            
    except subprocess.CalledProcessError:
        print_status("INFO", "Nginx command failed, may not be installed")
    except FileNotFoundError:
        print_status("INFO", "Nginx not found, likely not installed")

def main():
    """Run all checks"""
    print_status("HEADER", "PINTEREST IMAGE GENERATOR DEPLOYMENT CHECKER")
    print("This tool will check the deployment status of your application.\n")
    
    check_system_info()
    check_directories()
    check_configuration()
    check_flask_status()
    
    # Ask if user wants to run a test generation
    test_gen = input("\nDo you want to test image generation? This might take some time. (y/n): ")
    if test_gen.lower() == 'y':
        test_image_generation()
    
    # Check Nginx only on Linux
    if os.name == 'posix':
        nginx_check = input("\nDo you want to check Nginx configuration? (y/n): ")
        if nginx_check.lower() == 'y':
            check_nginx_config()
    
    print_status("HEADER", "DIAGNOSTICS COMPLETE")
    print("\nIf you're still having issues, check the following:")
    print("1. Look at your application logs")
    print("2. Make sure your firewall allows HTTP traffic")
    print("3. If behind a proxy, verify the proxy path configuration")
    print("4. Check the file permissions in your deployment directory")

if __name__ == "__main__":
    main() 