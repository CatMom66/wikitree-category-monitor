import urllib.request

url = (
    "https://plus.wikitree.com/function/WTCatNavigate/Category.htm"
    "?Category=Brandenburg%2C_Preu%C3%9Fen&Levels=2&Details=Edit"
)

try:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "Mozilla/5.0"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        html = response.read().decode("utf-8", errors="replace")

    print("Report retrieved successfully.")
    print("Characters received:", len(html))
    print("Contains Brandenburg:", "Brandenburg" in html)
    print("Contains Last Edit column:", "Last Edit" in html)

except Exception as error:
    print("Could not retrieve the report:", error)
    raise
