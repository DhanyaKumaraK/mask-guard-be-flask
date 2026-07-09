MASKING_STYLES = {
    1: {
        "name": "placeholder",
        "description": "Replace PII with label placeholders like [name], [phone_number]",
        "example": "Name: [name] | Phone: [phone_number] | Email: [email]"
    },
    2: {
        "name": "redacted",
        "description": "Replace PII with explicit redaction labels like [redacted name]",
        "example": "Name: [redacted name] | Phone: [redacted phone_number]"
    },
    3: {
        "name": "asterisk",
        "description": "Replace PII with asterisks matching the original value's length",
        "example": "Name: [**** ****** *] | Phone: [**********]"
    }
}