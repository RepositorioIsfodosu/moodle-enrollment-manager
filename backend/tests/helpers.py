PASSWORD = "test-password-very-long"


def login(client, email, password=PASSWORD):
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    return {"Authorization": "Bearer " + response.json()["access_token"]}


def create(client, headers, role="operador", email="operator@example.com"):
    return client.post(
        "/api/v1/users",
        headers=headers,
        json={"email": email, "password": PASSWORD, "roles": [role]},
    )
