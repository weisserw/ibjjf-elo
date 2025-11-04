from sqlalchemy.orm import Session


def generate_slug(session: Session, model, normalized_name: str) -> str:
    """
    Generate a URL-friendly slug for an athlete based on their name.
    Ensures the slug is unique within the athletes table.

    normalized_name is lowercased, ascii letters only and each word separated by a single space.
    we start by using first and last name only, then add middle names if needed to ensure uniqueness.
    finally if the slug is still not unique we append a number at the end.
    """

    words = [w for w in normalized_name.split() if len(w) > 1]

    if len(words) == 0:
        base_slug = "athlete"
    else:
        base_slug = "-".join(words)

    slug = base_slug
    unique_index = 2

    # Check for uniqueness and modify slug if necessary
    while session.query(model).filter(model.slug == slug).first() is not None:
        # Append a number to the slug
        slug = f"{base_slug}-{unique_index}"
        unique_index += 1

    return slug
