import re
import unicodedata

whitespace = re.compile(r"\s+")
nonletters = re.compile(r"[^a-z 0-9]")


def normalize(name):
    nfkd_form = unicodedata.normalize("NFKD", name)
    only_ascii = nfkd_form.encode("ASCII", "ignore")
    decoded = only_ascii.decode().strip().lower()
    only_letters = nonletters.sub("", decoded)
    single_space = whitespace.sub(" ", only_letters)
    return single_space
