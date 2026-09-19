"""Classify explicit HTTP reads, independently of provider and credentials.

This is an effect classifier, not network authorization or an assertion that a
server implements GET correctly. Unknown options retain normal write checks.
"""

from urllib.parse import urlsplit


def curl_read_only(args: list[str]) -> bool:
    """Accept GET/HEAD to stdout without hidden curlrc actions or output files."""
    return curl_effect(args)[0] == "read_only"


def curl_effect(args: list[str]) -> tuple[str, str]:
    """Explain unsupported input separately from a recognized request/file write."""
    # curl only disables its implicit config when -q/--disable is FIRST.
    if not args or args[0] not in {"-q", "--disable"}:
        return "unknown", "implicit curl configuration may change request or output behavior; put -q first"
    flags = {"--silent", "--show-error", "--fail", "--fail-with-body",
             "--location", "--head", "--compressed", "--ipv4", "--ipv6",
             "--no-progress-meter", "--globoff", "--get"}
    values = {"--header", "--user", "--connect-timeout", "--max-time",
              "--retry", "--retry-delay", "--retry-max-time", "--user-agent",
              "--cacert", "--capath", "--proxy", "--noproxy"}
    short_flags = set("sSfLIgG46")
    short_values = {"H", "u", "A", "m", "x"}
    writes = {"--upload-file", "--form", "--form-string", "--remote-name",
              "--remote-name-all", "--dump-header", "--trace", "--trace-ascii",
              "--cookie-jar", "--alt-svc", "--hsts", "--libcurl"}
    urls = []
    index = 1
    while index < len(args):
        token = args[index]
        index += 1
        option, equals, value = token.partition("=")
        if token == "--":
            urls.extend(args[index:])
            break
        if option.startswith("--"):
            if option in writes:
                return "mutating", "curl upload or file-output option"
            if option in flags and not equals:
                continue
            if option not in values | {"--request", "--url", "--output"}:
                return "unknown", "curl option has no verified effect contract"
            if not equals:
                if index == len(args):
                    return "unknown", "curl option is missing its value"
                value = args[index]
                index += 1
            effect = _value_effect(option, value, urls)
            if effect != "read_only":
                return effect, "curl method or output destination is not a verified read"
        elif token.startswith("-"):
            cluster = token[1:]
            if not cluster:
                return "unknown", "incomplete curl option"
            while cluster:
                flag, cluster = cluster[0], cluster[1:]
                if flag in short_flags:
                    continue
                if flag in {"T", "F", "O", "D", "c"}:
                    return "mutating", "curl upload or file-output option"
                if flag not in short_values | {"X", "o"}:
                    return "unknown", "curl option has no verified effect contract"
                value = cluster
                if not value:
                    if index == len(args):
                        return "unknown", "curl option is missing its value"
                    value = args[index]
                    index += 1
                option = {"X": "--request", "o": "--output"}.get(flag, "--value")
                effect = _value_effect(option, value, urls)
                if effect != "read_only":
                    return effect, "curl method or output destination is not a verified read"
                break
        else:
            urls.append(token)
    if not urls or not all(_http_url(url) for url in urls):
        return "unknown", "missing or unsupported HTTP URL"
    return "read_only", ""


def _value_effect(option: str, value: str, urls: list[str]) -> str:
    if not value:
        return "unknown"
    if option == "--request":
        if value in {"GET", "HEAD"}:
            return "read_only"
        return "mutating" if value in {"POST", "PUT", "PATCH", "DELETE"} else "unknown"
    if option == "--output":
        return "read_only" if value == "-" else "mutating"
    if option == "--url":
        urls.append(value)
    return "read_only"


def _http_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return url.scheme.lower() in {"http", "https"} and bool(url.hostname)
    except ValueError:
        return False
