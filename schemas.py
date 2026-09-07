"""
Gemini API response schemas (OpenAPI subset).

Types must be UPPERCASE strings: STRING, NUMBER, INTEGER, BOOLEAN, ARRAY, OBJECT.
Use nullable=True for fields the prompt says can be null.

Design decisions:
  • All top-level fields are listed in "required" — without this, Gemini treats
    every property as optional and silently omits fields it is uncertain about,
    producing incomplete JSON instead of null-filled JSON.
  • jurisdictions/scheduled_payments — facts-only (không có câu văn); mọi enum
    KHÔNG nullable (enum + nullable không ổn định trên preview models);
    object con balance_due/overpayment nullable ở cấp ngoài.
"""

# ── Task 2: client cover-letter FACTS extraction ─────────────────────────────
TASK2_RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "required": [
        "client", "cpa_firm", "tax_year", "next_year",
        "return_type", "jurisdictions", "scheduled_payments",
    ],
    "properties": {
        "client": {
            "type": "OBJECT",
            "required": ["name"],
            "properties": {"name": {"type": "STRING", "nullable": True}},
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
        "jurisdictions": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": [
                    "jurisdiction_name", "state_abbreviation", "display_label",
                    "outcome", "balance_due", "overpayment",
                    "source_quote", "other_note",
                ],
                "properties": {
                    "jurisdiction_name":  {"type": "STRING"},
                    "state_abbreviation": {"type": "STRING", "nullable": True},
                    "display_label":      {"type": "STRING", "nullable": True},
                    "outcome": {
                        "type": "STRING",
                        "enum": ["balance_due", "refund_or_credit", "no_tax", "other"],
                    },
                    "balance_due": {
                        "type": "OBJECT",
                        "nullable": True,
                        "required": ["amount", "payment_method", "withdrawal_date", "due_date"],
                        "properties": {
                            "amount": {"type": "NUMBER"},
                            "payment_method": {
                                "type": "STRING",
                                "enum": ["direct_debit", "mail_check", "other"],
                            },
                            "withdrawal_date": {"type": "STRING", "nullable": True},
                            "due_date":        {"type": "STRING", "nullable": True},
                        },
                    },
                    "overpayment": {
                        "type": "OBJECT",
                        "nullable": True,
                        "required": ["total", "credited_next_year", "refunded"],
                        "properties": {
                            "total":              {"type": "NUMBER", "nullable": True},
                            "credited_next_year": {"type": "NUMBER"},
                            "refunded":           {"type": "NUMBER"},
                        },
                    },
                    "source_quote": {"type": "STRING"},
                    "other_note":   {"type": "STRING", "nullable": True},
                },
            },
        },
        "scheduled_payments": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "required": [
                    "type", "jurisdiction", "amount", "date",
                    "payment_method", "ordinal", "source_quote", "note",
                ],
                "properties": {
                    "type": {
                        "type": "STRING",
                        "enum": ["estimated", "annual", "pte", "other"],
                    },
                    "jurisdiction": {"type": "STRING"},
                    "amount":       {"type": "NUMBER"},
                    "date":         {"type": "STRING"},
                    "payment_method": {
                        "type": "STRING",
                        "enum": ["direct_debit", "mail_voucher", "electronic", "unspecified"],
                    },
                    "ordinal":      {"type": "STRING", "nullable": True},
                    "source_quote": {"type": "STRING"},
                    "note":         {"type": "STRING", "nullable": True},
                },
            },
        },
    },
}
