# ---------------------------------------------------------------------------
# PII Knowledge Base  (Rubric §4.1 — defined knowledge base / source collection)
# Each entry describes a PII type, provides examples, and defines masking rules
# for each of the three supported masking styles.
# ---------------------------------------------------------------------------
PII_REGISTRY = [
    {
        "pii_type": "name",
        "description": "Full name, first name, last name, or any personal name identifier",
        "examples": ["John Doe", "Alice Smith", "Dhanya Kumara K"],
        "masking_guide": {
            "placeholder": "Replace with [name]",
            "redacted":     "Replace with [redacted name]",
            "asterisk":     "Replace each non-space character with *, preserve spaces, wrap in brackets e.g. [**** ****** *]"
        }
    },
    {
        "pii_type": "phone_number",
        "description": "Phone numbers, mobile numbers, cell numbers in any format",
        "examples": ["4545789889", "+1-555-123-4567", "(555) 123-4567"],
        "masking_guide": {
            "placeholder": "Replace with [phone_number]",
            "redacted":     "Replace with [redacted phone_number]",
            "asterisk":     "Replace each digit with *, preserve separators, wrap in brackets"
        }
    },
    {
        "pii_type": "email",
        "description": "Email addresses in any standard format",
        "examples": ["user@example.com", "john.doe@company.org"],
        "masking_guide": {
            "placeholder": "Replace with [email]",
            "redacted":     "Replace with [redacted email]",
            "asterisk":     "Replace each character with *, preserve @ and dots, wrap in brackets"
        }
    },
    {
        "pii_type": "passport_number",
        "description": "Passport numbers and travel document identifiers",
        "examples": ["8787-8788-989", "A12345678", "P1234567"],
        "masking_guide": {
            "placeholder": "Replace with [passport_number]",
            "redacted":     "Replace with [redacted passport_number]",
            "asterisk":     "Replace each alphanumeric character with *, preserve hyphens, wrap in brackets"
        }
    },
    {
        "pii_type": "ssn",
        "description": "Social Security Numbers and national ID numbers",
        "examples": ["123-45-6789", "123456789"],
        "masking_guide": {
            "placeholder": "Replace with [ssn]",
            "redacted":     "Replace with [redacted ssn]",
            "asterisk":     "Replace each digit with *, preserve hyphens, wrap in brackets"
        }
    },
    {
        "pii_type": "address",
        "description": "Home address, street address, or mailing address",
        "examples": ["123 Main St, Springfield, IL 62701"],
        "masking_guide": {
            "placeholder": "Replace with [address]",
            "redacted":     "Replace with [redacted address]",
            "asterisk":     "Replace each alphanumeric character with *, preserve spaces/commas, wrap in brackets"
        }
    },
    {
        "pii_type": "date_of_birth",
        "description": "Date of birth, birthday, or DOB in any format",
        "examples": ["01/15/1990", "1990-01-15", "January 15, 1990"],
        "masking_guide": {
            "placeholder": "Replace with [date_of_birth]",
            "redacted":     "Replace with [redacted date_of_birth]",
            "asterisk":     "Replace each character with *, preserve date separators, wrap in brackets"
        }
    },
    {
        "pii_type": "credit_card",
        "description": "Credit card numbers or debit card numbers",
        "examples": ["4111-1111-1111-1111", "4111111111111111"],
        "masking_guide": {
            "placeholder": "Replace with [credit_card]",
            "redacted":     "Replace with [redacted credit_card]",
            "asterisk":     "Replace each digit with *, preserve hyphens/spaces, wrap in brackets"
        }
    },
    {
        "pii_type": "ip_address",
        "description": "IPv4 or IPv6 addresses",
        "examples": ["192.168.1.1", "2001:db8::1"],
        "masking_guide": {
            "placeholder": "Replace with [ip_address]",
            "redacted":     "Replace with [redacted ip_address]",
            "asterisk":     "Replace each character with *, preserve dots/colons, wrap in brackets"
        }
    }
]
