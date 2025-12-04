import sys
import re

print("name,mat,day,url")

for line in sys.stdin:
    title = re.search(r'aria-label="([^"]+)"', line)

    link = re.search(r'href="([^"&]+)', line)

    name = re.split(r"\s+\|\s+", title.group(1))[0].strip()

    url = "https://www.youtube.com" + link.group(1)

    mat = re.search(r"Mat\s+(\d+)", title.group(1))
    day = re.search(r"Day\s+(\d+)", title.group(1))

    if not mat:
        print(line, file=sys.stderr)
        continue

    if not day:
        day = 1
    else:
        day = day.group(1)

    print(f"{name},{mat.group(1)},{day},{url}")
