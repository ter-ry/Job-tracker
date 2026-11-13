# Location and résumé evidence

Job Tracker treats a street address or workplace postal code as the strongest
available workplace evidence. A city-only provider result is retained as
`location_precision=city`, but its city-centre estimate is shown only as an
estimate. It is not used for strict radius eligibility or precise ranking;
the distance remains unknown until a more precise workplace is available.

Nominatim remains the default geocoder. The installation owner can explicitly
select `JOB_TRACKER_GEOCODING_PROVIDER=geocoder.ca` after registering and
confirming eligibility for geocoder.ca's noncommercial free tier, whitelisting,
limits, attribution, and privacy terms. The optional
`JOB_TRACKER_GEOCODER_CA_TOKEN` supplies the registered token. Postal results
are accepted only when the provider returns the exact requested six-character
code. A failed lookup leaves the origin unresolved. The application does not
embed credentials or claim that a free endpoint is unlimited. A future Canada
Post/StatsCan PCCF integration would require licensed data and an explicit
product decision; it must not be silently added.

Résumé-assisted matching is separate from keyword retrieval. The selected
candidate profile is used only to evaluate returned postings. Matched skills
are `Demonstrated` or `Familiar`; absent résumé evidence is `Unverified`, not
`No experience`. The latter requires an explicit negative skill confirmation.
Projects are evidence of project work, not inferred years of professional
experience. Title-search results remain résumé-independent.
