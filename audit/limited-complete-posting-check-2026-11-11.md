# Limited complete-posting check — not a release acceptance pass

Three complete employer PDFs were independently read before a scoped description-path replay. Two are historical 2024 postings and are **not** evidence of active vacancies. The replay supplied title, employer, source URL, and city as test inputs, so those provider fields and original application-link behavior were **not** evaluated. The applicant résumé was kept outside the repository. The complete PDF text was not copied into this repository.

Originals: [Villa Charities ECE, January 2026](https://wp.villacharities.com/wp-content/uploads/2026/01/Registered-Early-Childhood-Educator-Jan-2026.pdf), [Mothercraft RECE Float, June 2024](https://mothercraft.ca/wp-content/uploads/2024/06/20240614-RECE-Float-All-CEDs.pdf), [Cobblestone RECE, April 2024](https://professionallearninghub.ca/wp-content/uploads/2024/04/Cobblestone-RECE-Job-Posting.pdf).

| Field in this limited sample | Correctness of extracted values | Coverage of source-stated values | Observed error or limit |
|---|---:|---:|---|
| Advertised salary endpoints and hourly unit | 3/3 | 3/3 | Mothercraft has both hiring and wider salary ranges; the hiring range was selected. |
| Annualized salary where weekly hours are stated | 1/1 after fix | 1/1 | Mothercraft states 35 hours/week; the former 40-hour assumption overstated annualized pay. The other two PDFs do not establish weekly hours, so their annualization is unverified. |
| Distinct workplace street addresses | N/A (none extracted) | 0/7 | Villa names two sites; Mothercraft names five float sites. A single-workplace field cannot represent them without losing alternatives. |
| Workplace postal codes | N/A (none extracted) | 0/2 | Villa states a different postal code for each site. |
| Explicit numeric experience range | 1/1 | 1/1 | Mothercraft's 1–2 years was retained. Villa's organizational longevity was falsely treated as 50 years of job experience before the focused fix; after the fix it is not. |
| Benefits as separate structured values | N/A (none extracted) | 0/2 postings with stated benefits | Benefits remain in source descriptions, not a dedicated extracted field. |
| Title, employer, application URL, arrangement, credentials and technical skills | N/A | N/A | Provider identity/URL were supplied to this replay; no live provider result or independently adjudicated structured-field sample was available. Villa and Mothercraft imply physical attendance, but the replay returned arrangement Unknown. |

Correctness is not reported as 100% when nothing is extracted. Address and postal coverage use individual stated workplaces/codes as denominators. These metrics are only for the three named PDFs, not for an ECE/SWE acceptance sample.

## Source-backed distance check

The [Villa Charities PDF](https://wp.villacharities.com/wp-content/uploads/2026/01/Registered-Early-Childhood-Educator-Jan-2026.pdf) names 70 Playfair Avenue, Toronto, ON M6B 2P9 and 340 Falstaff Avenue, Toronto, ON M6L 3E7 as distinct childcare workplaces. The [City of Toronto](https://www.toronto.ca/services-payments/venues-facilities-bookings/booking-city-facilities/civic-centres/) lists Toronto City Hall at 100 Queen Street West, Toronto, ON M5H 2N2; it is a public test origin, **not** the applicant's address. Nominatim returned matching street numbers and postal codes for all three, at (43.7110390, -79.4594629), (43.7205044, -79.4822959), and origin (43.6536032, -79.3840055). Great-circle distances from that one origin are 8.81 km and 10.85 km, respectively. The app distance function rounds them to 9 km and 11 km with address-level inputs; a city-level input produces unknown distance and a separate city estimate. This verifies the calculation on supplied precise coordinates, **not** end-to-end extraction of those coordinates from the PDF.

## Remaining gates

The cloud command proxy returned CONNECT 403 for `jobs.ashbyhq.com`, `jobs.lever.co`, and `www.jobbank.gc.ca`. Public research opened these three PDFs, but ATS pages returned 403 or JavaScript-only content and Job Bank originals timed out. No 15-posting SWE holdout, original-link check, or representative provider-to-database field audit was completed. SWE precision, recall, false positives, false negatives, and unverified-technology rates therefore remain unmeasured. Do not merge or release on the basis of this limited check.
