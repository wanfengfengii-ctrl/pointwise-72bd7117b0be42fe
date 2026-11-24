from rules.catalog import RuleCatalog
from rules.validation import validate_rules


def register(catalog: RuleCatalog, code: str, rules: dict) -> int:
    definition = validate_rules(code, rules)
    return catalog.append_revision(definition)
