import sys
import os
from datetime import date

# Ensure the parent directory is in sys.path for module resolution
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.portfolio_store import load_ai_proposal

result = load_ai_proposal(date.today().isoformat())
print(result)
