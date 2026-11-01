## A harvester proposes, a human merges; a wrong id or installer runs the WRONG software

winget_candidates.py and curl_candidates.py emit tiered proposals (curl is a vetted allowlist, never a repo-probing guess); nothing is committed automatically, and a human reviews the diff before any key lands in recipe_data.json.
