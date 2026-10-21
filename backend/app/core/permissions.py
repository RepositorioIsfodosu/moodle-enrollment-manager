ROLE_PERMISSIONS = {
    "administrador": frozenset(
        {
            "users:manage",
            "audit:read",
            "connections:manage",
            "jobs:read",
            "jobs:write",
            "imports:write",
            "reports:read",
        }
    ),
    "operador": frozenset({"jobs:read", "jobs:write", "imports:write", "reports:read"}),
    "supervisor": frozenset({"jobs:read", "reports:read", "audit:read"}),
    "consulta": frozenset({"jobs:read"}),
}


def permissions_for(roles: list[str]) -> list[str]:
    return sorted(set().union(*(ROLE_PERMISSIONS.get(role, frozenset()) for role in roles)))
