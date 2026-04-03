import asyncio
import json
import sys
import os

# Add parser/ to path so we can import project modules directly
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "parser"))

from parser import extract_raw_text, clean_text
from extractor import extract_fields


async def main():
    resume_path = "Varun_Vangar_Resume.pdf"

    with open(resume_path, "rb") as f:
        file_bytes = f.read()

    print(f"Extracting text from {resume_path}...")
    raw_text = extract_raw_text(resume_path, file_bytes)
    raw_text = clean_text(raw_text)
    print(f"Extracted {len(raw_text)} characters\n")

    print("Sending to LLM for structured extraction...")
    data = await extract_fields(raw_text)

    print("\n── Parsed Resume ──────────────────────────")
    print(json.dumps(data, indent=2, default=str))


asyncio.run(main())
