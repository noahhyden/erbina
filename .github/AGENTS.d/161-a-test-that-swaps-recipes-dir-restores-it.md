## A test that swaps server.RECIPES_DIR must restore it

prototype.registry() points server.RECIPES_DIR at a temp dir and restores it in a finally block; a test that repoints it by hand and leaks it makes every later test resolve throwaway recipes instead of the real registry.
