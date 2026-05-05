"""
Gemini API response schemas (OpenAPI subset).

Types must be UPPERCASE strings: STRING, NUMBER, INTEGER, BOOLEAN, ARRAY, OBJECT.
Use nullable=True for fields the prompt says can be null.

Design decisions:
  • All top-level fields are listed in "required" — without this, Gemini treats
    every property as optional and silently omits fields it is uncertain about,
    producing incomplete JSON instead of null-filled JSON.
  • return_type  — enum WITHOUT nullable: enum + nullable is unreliable on preview models.
  • estimated_payments.federal / .state — NUMBER, not nullable: prompt says "Set missing to 0".
  • tax_summary  — object NOT nullable at outer level; only federal_sentence inside is nullable.
"""

# ── Task 2: client cover-letter extraction ──────────────────────────────────
TASK2_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": [
        "client", "cpa_firm", "tax_year", "next_year",
        "return_type", "tax_summary", "estimated_payments", "pte_payments",
    ],
    "properties": {
        "client": {
            "type": "OBJECT",
            "required": ["name"],
            "properties": {
                "name": {"type": "STRING", "nullable": True},
            },
        },
        "cpa_firm": {
            "type": "OBJECT",
            "required": ["name", "sharefile_subdomain"],
            "properties": {
                "name": {"type": "STRING", "nullable": True},
                "sharefile_subdomain": {"type": "STRING", "nullable": True},
            },
        },
        "tax_year":  {"type": "STRING", "nullable": True},
        "next_year": {"type": "STRING", "nullable": True},
        "return_type": {
            "type": "STRING",
            "enum": [
                "Individual (1040)",
                "S-Corporation (1120S)",
                "C-Corporation (1120)",
                "Partnership (1065)",
                "Trust/Estate (1041)",
                "Non-Profit (990)",
            ],
        },
        "tax_summary": {
            "type": "OBJECT",
            "required": ["federal_sentence", "state_sentences"],
            "properties": {
                "federal_sentence": {"type": "STRING", "nullable": True},
                "state_sentences": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "required": ["state_name", "state_abbreviation", "sentence"],
                        "properties": {
                            "state_name":         {"type": "STRING"},
                            "state_abbreviation": {"type": "STRING"},
                            "sentence":           {"type": "STRING"},
                        },
                    },
                },
            },
        },
        "estimated_payments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": ["date", "federal", "state", "state_name"],
                "properties": {
                    "date":       {"type": "STRING"},
                    "federal":    {"type": "NUMBER"},
                    "state":      {"type": "NUMBER"},
                    "state_name": {"type": "STRING", "nullable": True},
                },
            },
        },
        "pte_payments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": ["sentence"],
                "properties": {
                    "sentence": {"type": "STRING"},
                },
            },
        },
    },
}
