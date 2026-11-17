Change Log
##########

..
   All enhancements and patches to forum will be documented
   in this file.  It adheres to the structure of https://keepachangelog.com/ ,
   but in reStructuredText instead of Markdown (for ease of incorporation into
   Sphinx documentation and the PyPI description).

   This project adheres to Semantic Versioning (https://semver.org/).

.. There should always be an "Unreleased" section for changes pending release.

Unreleased
**********

*

0.7.6 – 2026-11-16
******************

Fixed
-----

* MySQL backend: listing a course's threads no longer loads every thread in the
  course. The page is now selected in the database, and the vote and comment
  counts used for sorting come from subqueries, not joins that multiplied the
  rows per thread. In large courses the "All posts" list took about 45 seconds
  to load (LP-1549).
* MySQL backend: the votes sort now orders threads by their vote total (up
  minus down, 0 without votes), as with the MongoDB backend. It summed distinct
  vote values, so every thread with up votes scored the same.
* MySQL backend: building one page of threads no longer runs queries per vote,
  per edit or per thread for read state, endorsement and abuse flags. The thread
  serializer reuses the read state already computed for the page.
* MySQL backend: threads with an endorsed response are now listed as endorsed,
  as they are with the MongoDB backend.

0.7.5 – 2026-10-29
******************

Added
-----

* ``forum.api.get_usernames_with_course_stats`` returns the usernames in a
  course that match a search string and have discussion stats there, including
  users who posted in the course without being enrolled in it.

Security
--------

* The forum HTTP API under ``/forum/api/v1/`` and ``/forum/api/v2/`` is no
  longer routed unless ``FORUM_ENABLE_HTTP_API`` is set to ``True``, and when
  routed it only accepts callers authenticated as a staff account. See
  `GHSA-c6fp-f54c-6cv4
  <https://github.com/openedx/forum/security/advisories/GHSA-c6fp-f54c-6cv4>`_.

0.3.4 – 2025-08-13
******************

Added
-----

* CI check to validate the Python package.

Fixed
-----

* CHANGELOG header formatting.

0.3.3 – 2025-08-12
******************

Fixed
-----

* Do not raise runtime errors if an incorrect course ID is provided when
  checking if the MySQL backend is enabled.


0.3.0 – 2025-04-23
******************

* Add support for django 5.2

*

0.1.0 – 2024-11-12
******************

* First release on PyPI.
