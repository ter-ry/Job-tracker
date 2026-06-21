from __future__ import annotations

from jobspy import scrape_jobs


SOURCES = ["linkedin", "indeed", "google", "zip_recruiter"]


def run_source(source: str) -> None:
    print(f"\n=== {source} ===")
    try:
        jobs = scrape_jobs(
            site_name=source,
            search_term="early childhood educator",
            google_search_term="early childhood educator jobs near Toronto Ontario",
            location="Toronto, Ontario",
            country_indeed="Canada",
            results_wanted=30,
            hours_old=336,
            linkedin_fetch_description=False,
            verbose=0,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return

    print(f"count: {len(jobs)}")
    for _, row in jobs.head(10).iterrows():
        data = row.to_dict()
        description = data.get("description")
        salary = data.get("salary") or data.get("min_amount") or data.get("max_amount") or ""
        print("-" * 60)
        print(f"title: {data.get('title') or ''}")
        print(f"company: {data.get('company') or ''}")
        print(f"location: {data.get('location') or ''}")
        print(f"job_url: {data.get('job_url') or data.get('job_url_direct') or ''}")
        print(f"salary: {salary}")
        print(f"description_available: {bool(description)}")


def main() -> None:
    for source in SOURCES:
        run_source(source)


if __name__ == "__main__":
    main()
