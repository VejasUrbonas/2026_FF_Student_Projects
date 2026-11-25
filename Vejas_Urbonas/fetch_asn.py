import asyncio
import random
from pathlib import Path
import pandas as pd
from playwright.async_api import async_playwright

BASE_DIR = Path(__file__).resolve().parent if "__file__" in globals() else Path.cwd()
OUT_DIR = BASE_DIR / "asn_html_1990_2020"
OUT_CSV = (
    BASE_DIR / "Vejas_Urbonas" / "data" / "ASN_data_1990-2020.csv"
    if (BASE_DIR / "Vejas_Urbonas").exists()
    else BASE_DIR / "data" / "ASN_data_1990-2020.csv"
)

MAX_PAGES_PER_YEAR = 10
MAX_RETRIES_429 = 4
DROP_COL_INDICES = [6, 8, 9]


async def collect_html() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    consecutive_blocks = 0

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        for year in range(1990, 2021):
            for page_num in range(1, MAX_PAGES_PER_YEAR + 1):
                url = f"https://aviation-safety.net/database/year/{year}/{page_num}"
                retries = 0
                saved_or_empty = False

                while True:
                    response = await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await page.wait_for_timeout(random.randint(5000, 8000))

                    status = response.status if response else None
                    html = await page.content()
                    has_table = "acc. date" in html.lower()

                    print(f"{year} p{page_num} | status={status} | bytes={len(html)} | has_table={has_table}")

                    if status == 429:
                        retries += 1
                        if retries > MAX_RETRIES_429:
                            print(f"Skipping {year} p{page_num} after {MAX_RETRIES_429}x 429.")
                            consecutive_blocks += 1
                            break
                        wait_ms = random.randint(12000, 20000)
                        print(f"429 on {year} p{page_num} — cooling down {wait_ms / 1000:.1f}s (retry {retries}/{MAX_RETRIES_429})...")
                        await page.wait_for_timeout(wait_ms)
                        continue

                    if status == 403:
                        print(f"403 on {year} p{page_num} — skipping page.")
                        consecutive_blocks += 1
                        break

                    consecutive_blocks = 0
                    if has_table:
                        (OUT_DIR / f"asn_{year}_p{page_num}.html").write_text(html, encoding="utf-8")
                    saved_or_empty = True
                    break

                if consecutive_blocks >= 5:
                    print("Too many consecutive blocks/rate-limits — stopping early to avoid a longer ban.")
                    await browser.close()
                    return

                # If we got a normal 200 response with no table, we've passed the last page for this year
                if saved_or_empty and not has_table:
                    break

        await browser.close()
    print("Collection pass finished.")


def build_dataset() -> tuple[pd.DataFrame, object]:
    frames = []

    for html_path in sorted(OUT_DIR.glob("asn_*_p*.html")):
        parts = html_path.stem.split("_")
        year = int(parts[1])
        page_num = int(parts[2].removeprefix("p"))

        tables = pd.read_html(html_path)
        for idx, tbl in enumerate(tables):
            df_sub = tbl.copy()
            df_sub.columns = [str(c).strip() for c in df_sub.columns]
            df_sub = df_sub.dropna(axis=1, how="all").dropna(how="all")

            if "acc. date" not in df_sub.columns:
                continue

            drop_cols = [
                df_sub.columns[i] for i in DROP_COL_INDICES if i < len(df_sub.columns)
            ]
            if drop_cols:
                df_sub = df_sub.drop(columns=drop_cols)

            df_sub["year"] = year
            df_sub["page"] = page_num
            df_sub["table_idx"] = idx
            frames.append(df_sub)

    if not frames:
        empty_df = pd.DataFrame()
        return empty_df, empty_df.to_numpy()

    df = pd.concat(frames, ignore_index=True)
    if "fat." in df.columns:
        df["fat_num"] = pd.to_numeric(df["fat."], errors="coerce")

    OUT_CSV.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT_CSV, index=False, encoding="utf-8-sig")

    arr_2d = df.to_numpy()
    print(f"Saved CSV: {OUT_CSV} | Rows: {len(df)} | 2D array shape: {arr_2d.shape}")
    return df, arr_2d


def main() -> None:
    asyncio.run(collect_html())
    accidents_df, accidents_array = build_dataset()
    _ = (accidents_df, accidents_array)


if __name__ == "__main__":
    main()