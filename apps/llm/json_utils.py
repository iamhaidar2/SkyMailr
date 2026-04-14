"""Extract JSON objects from LLM text (pattern from BrainList studio.providers)."""


def extract_json_object(content: str) -> str:
    start = content.find("{")
    if start == -1:
        raise ValueError("No JSON object found")

    brace_count = 0
    in_string = False
    escape_next = False

    for i in range(start, len(content)):
        char = content[i]

        if escape_next:
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == '"' and not escape_next:
            in_string = not in_string
            continue

        if not in_string:
            if char == "{":
                brace_count += 1
            elif char == "}":
                brace_count -= 1
                if brace_count == 0:
                    return content[start : i + 1]

    raise ValueError("Unbalanced braces")
