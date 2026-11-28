"""Import-only probe used to validate JobSpy's frozen dependency graph."""

from jobspy import scrape_jobs


if __name__ == "__main__":
    print(f"JobSpy import probe passed: {scrape_jobs.__name__}")
