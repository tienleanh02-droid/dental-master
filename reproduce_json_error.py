import json
import re

raw_json = """
[
  {
    "question_type": "spot",
    "question": "...",
    "options": {
      "A": "...",
      "B": "...",
      "C": "...",
      "D": "Nang sừng do răng (OKC)"
    },
    "correct_answer": "B",
    "explanation": "...",
    "mnemonic": "...",
    "ref_page_keys": ["P3"],
    "primary_ref_page_key": "P3",
    "confidence": 1.0
  },
  {
    "question_type": "spot",
    "options": {
      "A": "...",
      "D": "Vùng thấu quang giới hạn không rõ, tiêu xương dạng 'mọt gặm'",
    },
    "correct_answer": "B"
  }
]
"""

print("--- Attempting standard load ---")
try:
    json.loads(raw_json)
    print("Standard load SUCCESS")
except Exception as e:
    print(f"Standard load FAILED: {e}")

print("\n--- Attempting Regex Fix ---")
# Regex to remove trailing commas
# Look for comma, followed by optional whitespace, followed by ] or }
fixed_json = re.sub(r',(\s*[\]\}])', r'\1', raw_json)
print(f"Fixed JSON snippet: {fixed_json[-200:]}")

try:
    tokens = json.loads(fixed_json)
    print(f"Fixed load SUCCESS. Items: {len(tokens)}")
except Exception as e:
    print(f"Fixed load FAILED: {e}")
