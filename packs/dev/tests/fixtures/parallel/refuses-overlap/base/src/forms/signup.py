def handle_signup(form, store):
    store.append({"email": form.get("email"), "name": form.get("name")})
    return {"ok": True}
