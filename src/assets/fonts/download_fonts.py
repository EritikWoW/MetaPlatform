"""Run this once to download Roboto fonts into this directory."""
import urllib.request, pathlib, sys

FONTS = {
    "Roboto-Regular.ttf": "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Regular.ttf",
    "Roboto-Bold.ttf":    "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Bold.ttf",
    "Roboto-Medium.ttf":  "https://github.com/google/fonts/raw/main/apache/roboto/static/Roboto-Medium.ttf",
}

here = pathlib.Path(__file__).parent
for name, url in FONTS.items():
    dest = here / name
    if dest.exists():
        print(f"  skip  {name}")
        continue
    print(f"  dl    {name} ...", end=" ", flush=True)
    urllib.request.urlretrieve(url, dest)
    print("ok")

print("Done.")
