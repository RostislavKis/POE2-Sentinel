"""
Test runner for POE2 Flask Bot - Terrain Overlay.

Usage:
    py run_tests.py           # Run all tests
    py run_tests.py -v        # Run with verbose output
    py run_tests.py -k test_  # Run tests matching pattern
"""

import subprocess
import sys
import os

def main():
    # Change to project directory
    project_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(project_dir)
    
    # Build pytest command
    cmd = [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"]
    
    # Add any additional arguments
    cmd.extend(sys.argv[1:])
    
    print("=" * 60)
    print("Running POE2 Flask Bot Tests")
    print("=" * 60)
    print(f"Command: {' '.join(cmd)}")
    print()
    
    # Run tests
    result = subprocess.run(cmd)
    
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
