"""Classify explicit HTTP reads, independently of provider and credentials.

This is an effect classifier, not network authorization or an assertion that a
server implements GET correctly. Unknown options retain normal write checks.
"""

from urllib.parse import urlsplit


def curl_read_only(args: list[str]) -> bool:
    """Accept GET/HEAD to stdout without hidden curlrc actions or output files."""
    # curl only disables its implicit config when -q/--disable is FIRST.
    if not args or args[0] not in {"-q", "--disable"}:
        return False
    flags = {"--silent", "--show-error", "--fail", "--fail-with-body",
             "--location", "--head", "--compressed", "--ipv4", "--ipv6",
             "--no-progress-meter", "--globoff", "--get"}
    values = {"--header", "--user", "--connect-timeout", "--max-time",
              "--retry", "--retry-delay", "--retry-max-time", "--user-agent",
              "--cacert", "--capath", "--proxy", "--noproxy"}
    short_flags = set("sSfLIgG46")
    short_values = {"H", "u", "A", "m", "x"}
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
            if option in flags and not equals:
                continue
            if option not in values | {"--request", "--url", "--output"}:
                return False
            if not equals:
                if index == len(args):
                    return False
                value = args[index]
                index += 1
            if not _value_allowed(option, value, urls):
                return False
        elif token.startswith("-"):
            cluster = token[1:]
            if not cluster:
                return False
            while cluster:
                flag, cluster = cluster[0], cluster[1:]
                if flag in short_flags:
                    continue
                if flag not in short_values | {"X", "o"}:
                    return False
                value = cluster
                if not value:
                    if index == len(args):
                        return False
                    value = args[index]
                    index += 1
                option = {"X": "--request", "o": "--output"}.get(flag, "--value")
                if not _value_allowed(option, value, urls):
                    return False
                break
        else:
            urls.append(token)
    return bool(urls) and all(_http_url(url) for url in urls)


def _value_allowed(option: str, value: str, urls: list[str]) -> bool:
    if not value:
        return False
    if option == "--request":
        return value in {"GET", "HEAD"}
    if option == "--output":
        return value == "-"
    if option == "--url":
        urls.append(value)
    return True


def _http_url(value: str) -> bool:
    try:
        url = urlsplit(value)
        return url.scheme.lower() in {"http", "https"} and bool(url.hostname)
    except ValueError:
        return False
