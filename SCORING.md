# Scoring Formula

Previous formula:

- Salary: 30%
- Location: 30%
- Role: 15%
- Skills: 15%
- Simple seniority heuristic: 10%
- Suspicious-posting penalty applied after the weighted score

New formula:

- Required and preferred skills match: 30%
- Responsibilities and experience match: 20%
- Existing location/work arrangement score: 15%
- Salary score: 10%
- Target seniority and years-of-experience fit: 15%
- Role/title relevance: 10%
- Coding-assessment, application-effort, suspicious-posting, salary, location, management, and stretch-role concerns remain visible in the breakdown and may apply penalties or warnings.

Semantic matching:

- Preferred local model: `sentence-transformers/all-MiniLM-L6-v2`
- Approximate model download size: about 90 MB
- Sentence Transformers are loaded only when semantic analysis or local draft generation is requested.
- Normal save/re-score paths can use exact keyword and lexical-overlap fallback.
- Automated tests mock embeddings and do not require live model downloads.

Caching:

- Resume/job comparison results are cached under `data/semantic_cache/` by resume hash plus job hash.
- The cache, uploaded resumes, local SQLite database, generated documents, and downloaded model/cache folders are ignored by Git.
