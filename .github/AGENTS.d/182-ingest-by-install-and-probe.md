## Recipe metadata cannot tell a CLI from a library, so ingest by install-and-probe

ingest_validated.py installs each candidate, finds the real binary and a version flag that exits 0, and emits a row only if it runs; brew candidate lists are a starting point, never proof.
