## The offline suite cannot catch a renamed brew formula; real-bootstrap is that check

Offline pytest never runs a real package manager, so a renamed formula, dead URL, wrong go path or teardown that leaves state behind only breaks in real-bootstrap.yml, which stays weekly/manual and must never gate a PR.
