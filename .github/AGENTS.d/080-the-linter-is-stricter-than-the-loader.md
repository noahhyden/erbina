## The linter is stricter than the loader, deliberately

validate_recipe is the schema contract enforced at LOAD time, so anything linting clean here `bootstrap` accepts; lint_recipe_policy adds curated rules (non-empty title/description, guarded install) that must not block test recipes.
