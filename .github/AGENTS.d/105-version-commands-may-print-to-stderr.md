## Version commands may print to stderr

Many tools (dot -V, JVM tools, some GNU tools) print --version on stderr; read stdout first but fall back to stderr, or update_available is silently null and check_updates is dead weight.
