import hashlib


def clean_text(value):
    """
    Normalizuje białe znaki.
    """

    if not value:
        return None

    value = " ".join(
        value.split()
    )

    return (
        value
        if value
        else None
    )


def generate_source_id(url):
    """
    Tworzy stabilny identyfikator oferty
    na podstawie URL.

    Parametry po '?' są ignorowane.
    """

    normalized_url = (
        url
        .split("?")[0]
        .rstrip("/")
    )

    return hashlib.sha256(
        normalized_url.encode("utf-8")
    ).hexdigest()