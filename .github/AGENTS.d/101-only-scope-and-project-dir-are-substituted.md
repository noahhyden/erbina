## Only ${scope} and ${project_dir} are substituted

_subst expands just those two; any other ${...} or an unterminated ${ reaches the executed command literally, so validate_recipe must reject it, and an mcp-server configure step must reference ${scope} or it cannot target a scope.
