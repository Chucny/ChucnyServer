import os
import sys
import subprocess
from time import *
print("Installing ChucnyServer requirements automatically. Please wait and do not close this program")

sleep(3)

# Define the required networking and geospatial libraries
LIBRARIES = [
    "s2sphere", 
    "requests", 
    "certifi"
]

def run_command(command):
    """Executes a system command and prints its output."""
    try:
        print(f"Running: {' '.join(command)}")
        subprocess.check_call(command)
    except subprocess.CalledProcessError as e:
        print(f"Error executing command: {e}", file=sys.stderr)
    except FileNotFoundError:
        print(f"Command not found. Ensure required tools are installed.", file=sys.stderr)

def install_packages():
    """Detects the OS and installs the specified libraries."""
    current_os = sys.platform
    print(f"Detected Operating System: {current_os}")

    # base pip command using the current Python executable
    base_pip = [sys.executable, "-m", "pip", "install"]

    if current_os.startswith("linux"):
        print("Linux detected. Proceeding with user and sudo profile installations.")
        
        # 1. Install to User Profile
        print("\n--- Installing to User Profile ---")
        user_cmd = base_pip + ["--user"] + LIBRARIES
        run_command(user_cmd)
        
        # 2. Install to Sudo Profile
        print("\n--- Installing to Sudo Profile ---")
        sudo_cmd = ["sudo", sys.executable, "-m", "pip", "install"] + LIBRARIES
        run_command(sudo_cmd)

    elif current_os in ("win32", "darwin"):
        # Windows or macOS standard installation
        print(f"\n--- Installing libraries for {current_os} ---")
        standard_cmd = base_pip + LIBRARIES
        run_command(standard_cmd)
        
    else:
        print(f"Unsupported OS: {current_os}. Attempting standard installation...", file=sys.stderr)
        standard_cmd = base_pip + LIBRARIES
        run_command(standard_cmd)

if __name__ == "__main__":
    install_packages()
