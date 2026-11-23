def greet(name, formal=False):
    name = name.strip()
    if formal:
        return "Good day, " + name + "."
    return "Hello " + name
