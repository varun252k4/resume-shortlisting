import json
import re
from litellm import acompletion

from config import LLM_MODEL, LLM_API_KEY, MAX_TOKENS

# Models that support response_format=json_object natively
JSON_MODE_PROVIDERS = ("groq/", "openai/", "azure/", "mistral/")

EXTRACTION_PROMPT = """You are a resume parser. Extract structured information from the resume text below.

Return ONLY a valid JSON object with this exact structure (no markdown, no explanation):
{{
  "name": "Full Name or null",
  "contact": {{
    "email": "email or null",
    "phone": "phone or null",
    "location": "city/country or null",
    "linkedin": "linkedin URL or null"
  }},
  "skills": ["skill1", "skill2"],
  "work_experience": [
    {{
      "company": "Company Name",
      "role": "Job Title",
      "duration": "Jan 2020 - Mar 2022 or null",
      "description": "brief summary or null"
    }}
  ],
  "education": [
    {{
      "institution": "University Name",
      "degree": "Degree and field",
      "year": "graduation year or null"
    }}
  ],
  "certifications": ["cert1", "cert2"]
}}

Rules:
- Return null for missing fields, empty arrays [] for missing lists
- Keep skills as individual items, not combined strings
- List work experience in reverse chronological order
- Do not invent or guess data not present in the resume
- Even if the resume has no clear section labels, infer fields from context
- Very Important: Return ONLY the JSON object, no explanations, no markdown, no extra text.

Resume text:
{resume_text}"""


def _supports_json_mode(model: str) -> bool:
    return any(model.startswith(p) for p in JSON_MODE_PROVIDERS)


def _parse_json(content: str) -> dict:
    """
    Robustly extract a JSON object from LLM output.
    Tries 4 strategies before giving up.
    """
    content = content.strip()

    # 1. Clean JSON straight away
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        pass

    # 2. Inside ```json ... ``` or ``` ... ``` fences
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", content, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except json.JSONDecodeError:
            pass

    # 3. First { ... } block anywhere in the response
    brace_match = re.search(r"\{.*\}", content, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group())
        except json.JSONDecodeError:
            pass

    # 4. LLM returned key-value pairs WITHOUT outer braces — wrap and retry
    #    e.g.  "name": "John",\n  "skills": [...]
    if content.startswith('"') or content.startswith('\n"'):
        try:
            return json.loads("{" + content.strip().rstrip(",") + "}")
        except json.JSONDecodeError:
            pass

    # Nothing worked — surface the raw output so it's easy to debug
    preview = content[:400].replace("\n", " ")
    raise ValueError(f"LLM did not return valid JSON. Raw output preview: {preview}")


async def extract_fields(raw_text: str) -> dict:
    """
    Send resume text to the configured LLM and return structured fields.
    Switches between json_object mode (for supported providers) and
    prompt-only mode (for others like Anthropic/Ollama).
    """
    prompt = EXTRACTION_PROMPT.format(resume_text=raw_text[:8000])

    kwargs = {
        "model": LLM_MODEL,
        "max_tokens": MAX_TOKENS,
        "messages": [{"role": "user", "content": prompt}],
    }

    if LLM_API_KEY:
        kwargs["api_key"] = LLM_API_KEY

    # Force JSON output on providers that support it (Groq, OpenAI, Mistral, Azure)
    if _supports_json_mode(LLM_MODEL):
        kwargs["response_format"] = {"type": "json_object"}

    response = await acompletion(**kwargs)
    content = response.choices[0].message.content.strip()

    return _parse_json(content)