"""Static contract check for the app-creation state machine definition.

Parses the `definition = jsonencode({...})` block from main.tf (a small,
machine-styled HCL subset) and enforces the payload contract between the
workflow and the worker handlers:

  1. Every Task using the `lambda:invoke` SDK integration MUST carry
     `OutputPath = "$.Payload"`. The SDK integration returns the raw
     InvokeResponse — the handler's return dict is nested under `Payload` —
     and every downstream Parameters/Choice template ($.request_id, $.job_id,
     $.ready, $.attempt) is written against the unwrapped payload. Missing
     OutputPath fails the execution at the first consumer with
     "The JSONPath '$.job_id' ... could not be found in the input
     '{ExecutedVersion..., Payload..., StatusCode...}'".
  2. No template references `$.Payload...` (would double-unwrap after rule 1).
  3. Every state is reachable from StartAt via Next/Choices/Default, and every
     transition target exists.

Run:  python _smoke_sfn_contract.py            (exit 0 = contract holds)
"""
import json
import re
import sys
from pathlib import Path

MAIN_TF = Path(__file__).resolve().parent / "main.tf"

SDK_INVOKE = "arn:aws:states:::lambda:invoke"
EXPECTED_OUTPUT_PATH = "$.Payload"

# Terraform refs appearing as leaf values inside the definition block.
REF_PATTERN = r"\b(?:var|data|aws_lambda_function|aws_secretsmanager_secret)\.[A-Za-z0-9_.]+"


def _rendered_definition(source: str) -> dict:
    """Extract the definition = jsonencode(...) block and convert HCL -> JSON.

    A single string-aware token scan does everything at once: '=' -> ':',
    bareword keys quoted, HCL's newline-separated object members given their
    JSON commas, `#`/`//` comments dropped. Token boundaries are what make the
    comma insertion safe (numbers like 10, strings like "arn:aws:..." and
    "States.MathAdd($.attempt, 1)" pass through untouched).
    """
    start = source.index("definition = jsonencode(")
    # Balanced-paren scan from the opening paren of jsonencode(.
    depth = 0
    block = None
    for i in range(start + len("definition = jsonencode(") - 1, len(source)):
        if source[i] == "(":
            depth += 1
        elif source[i] == ")":
            depth -= 1
            if depth == 0:
                block = source[start + len("definition = jsonencode(") : i]
                break
    if block is None:
        raise AssertionError("unbalanced jsonencode( block")

    # HCL interpolation inside string values (${var.x} renders at plan time):
    # neutralise it before the ref-token guard below, which would otherwise
    # (correctly, but unhelpfully) refuse to parse the string.
    block = re.sub(r"\$\{[^{}]*\}", "__INTERP__", block)

    # Terraform refs -> inert string scalars, BEFORE the scan (the scanner's
    # bareword handling would otherwise split e.g. aws_lambda_function.step1.arn
    # into fragments). Guard: refuse if any string VALUE contains a ref token,
    # which this plain substitution would corrupt.
    for quoted in re.finditer(r'"(?:[^"\\]|\\.)*"', block):
        if re.search(REF_PATTERN, quoted.group(0)):
            raise AssertionError(
                f"ref-like token inside a string value — cannot parse safely: "
                f"{quoted.group(0)[:60]}"
            )
    block = re.sub(REF_PATTERN, '"__REF__"', block)

    def _peek_nonws(j: int) -> str:
        while j < n and block[j] in " \t\r\n":
            j += 1
        return block[j] if j < n else ""

    out = []
    in_string = False
    escaped = False
    i = 0
    n = len(block)
    while i < n:
        ch = block[i]
        if in_string:
            out.append(ch)
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
                # String token complete. A KEY is followed by ':' or '='; a
                # VALUE is followed by the next member or a closing bracket.
                nxt = _peek_nonws(i + 1)
                if nxt not in (":", "=", "}", "]", ",", ")", ""):
                    out.append(",")
            i += 1
            continue
        if ch == '"':
            in_string = True
            out.append(ch)
            i += 1
            continue
        if ch == "#" or block[i : i + 2] == "//":
            # HCL line comment — the ASL block carries explanatory comments
            # inside jsonencode (e.g. the OutputPath note).
            while i < n and block[i] != "\n":
                i += 1
            continue
        if ch == "=":
            out.append(":")
            i += 1
            continue
        if ch in " \t\r\n":
            out.append(ch)
            i += 1
            continue
        if ch in "}]":
            out.append(ch)
            nxt = _peek_nonws(i + 1)
            if nxt not in ("}", "]", ",", ")", ""):
                out.append(",")
            i += 1
            continue
        match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", block[i:])
        if match:
            word = match.group(0)
            j = i + len(word)
            k = j
            while k < n and block[k] in " \t\r\n":
                k += 1
            nxt = block[k] if k < n else ""
            if nxt in (":", "="):
                out.append('"' + word + '"')  # bareword key
            else:
                out.append(word)  # value (true/false) or '.'-joined ref fragment
                if nxt not in ("}", "]", ",", ".", ")", ""):
                    out.append(",")
            i = j
            continue
        if ch.isdigit():
            # Number token: consume the digits (one comma after the whole
            # number, never inside it).
            j = i
            while j < n and (block[j].isdigit() or block[j] == "."):
                j += 1
            out.append(block[i:j])
            nxt = _peek_nonws(j)
            if nxt not in ("}", "]", ",", ".", ")", ""):
                out.append(",")
            i = j
            continue
        out.append(ch)
        i += 1
    text = "".join(out)

    # Trailing commas are legal HCL, illegal JSON.
    text = re.sub(r",(\s*[}\]])", r"\1", text)
    return json.loads(text)


def _contract_failures(definition: dict) -> list[str]:
    failures = []
    states = definition["States"]

    # Rules 1 + 2: the SDK-invoke unwrap contract.
    for name, state in states.items():
        if state.get("Type") != "Task" or state.get("Resource") != SDK_INVOKE:
            continue
        if state.get("OutputPath") != EXPECTED_OUTPUT_PATH:
            failures.append(
                f"state '{name}' uses the lambda:invoke SDK integration without "
                f'OutputPath = "{EXPECTED_OUTPUT_PATH}" — its output is the raw '
                f"InvokeResponse and every downstream $.field reference will fail "
                f"at the first consumer"
            )
        for key, value in (state.get("Parameters") or {}).items():
            if key.endswith(".$") and "$.Payload" in str(value):
                failures.append(
                    f"state '{name}' parameter {key} references {value} — after "
                    f"OutputPath unwrapping the payload IS the input; '$.Payload' "
                    f"would double-unwrap"
                )

    # Rule 3: every non-terminal state reachable from StartAt; transitions valid.
    fail_states = {
        name for name, state in states.items() if state.get("Type") == "Fail"
    }
    reachable = set()

    def _walk(state_name):
        if state_name in reachable:
            return
        reachable.add(state_name)
        state = states.get(state_name)
        if state is None:
            return
        for field in ("Next", "Default"):
            if field in state:
                _walk(state[field])
        for choice in state.get("Choices") or []:
            _walk(choice["Next"])

    _walk(definition["StartAt"])
    for name in states:
        if name not in reachable and name not in fail_states:
            failures.append(f"state '{name}' is unreachable from StartAt")
    for name, state in states.items():
        for field in ("Next", "Default"):
            if field in state and state[field] not in states:
                failures.append(
                    f"state '{name}' {field} target '{state[field]}' does not exist"
                )
        for choice in state.get("Choices") or []:
            if choice["Next"] not in states:
                failures.append(
                    f"state '{name}' choice target '{choice['Next']}' does not exist"
                )
    return failures


def main() -> int:
    source = MAIN_TF.read_text(encoding="utf-8")
    try:
        definition = _rendered_definition(source)
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL  could not parse the definition block: {exc}")
        return 1
    failures = _contract_failures(definition)
    if failures:
        for failure in failures:
            print("FAIL  " + failure)
        return 1
    task_count = sum(
        1 for s in definition["States"].values() if s.get("Type") == "Task"
    )
    print(
        f"sfn definition contract: ALL PASS ({task_count} Task states, "
        "unwrap + reachability OK)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
