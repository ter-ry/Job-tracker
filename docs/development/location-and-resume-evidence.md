# Location and résumé evidence

Job Tracker treats a street address or workplace postal code as the strongest
available workplace evidence. A city-only provider result is retained as
`location_precision=city`, but its city-centre estimate is shown only as an
estimate. It is not used for strict radius eligibility or precise ranking;
the distance remains unknown until a more precise workplace is available.

Canadian postal-code geocoding uses geocoder.ca's documented JSON endpoint by
default, with Nominatim as a fallback. City and general address lookups retain
Nominatim. An installation may explicitly select either provider with
`JOB_TRACKER_GEOCODING_PROVIDER=geocoder.ca` or `nominatim`; geocoder.ca may
also use `JOB_TRACKER_GEOCODER_CA_TOKEN` when its current service requires it.
Users must review the provider's current terms, quotas, attribution, privacy
handling, and any token requirements. The application does not embed
credentials or claim that a free endpoint is unlimited. A future Canada
Post/StatsCan PCCF integration would require licensed data and an explicit
product decision; it must not be silently added.

Résumé-assisted matching is separate from keyword retrieval. The selected
candidate profile is used only to evaluate returned postings. Matched skills
are `Demonstrated` or `Familiar`; absent résumé evidence is `Unverified`, not
`No experience`. The latter requires an explicit negative skill confirmation.
Projects are evidence of project work, not inferred years of professional
experience. Title-search results remain résumé-independent.
