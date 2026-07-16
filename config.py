"""
MantisBT Bulk Bug Import Tool - Configuration
"""

import os

HOST = '0.0.0.0'
PORT = 5030

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
SESSION_DIR = os.path.join(BASE_DIR, 'sessions')
DEFAULT_DELAY = 0.5  # seconds between requests
CSRF_REFRESH_EVERY = 10  # refresh CSRF token every N bugs

# Ensure sessions directory exists
os.makedirs(SESSION_DIR, exist_ok=True)

# Required CSV columns
REQUIRED_COLUMNS = ['summary', 'description', 'category_id']

# Optional CSV columns
OPTIONAL_COLUMNS = [
    'severity', 'priority', 'platform', 'os', 'os_build',
    'version', 'handler_id', 'steps_to_reproduce',
    'additional_info', 'view_state', 'project_id', 'tags'
]
