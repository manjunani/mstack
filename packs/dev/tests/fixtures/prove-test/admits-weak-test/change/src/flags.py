DEFAULTS = {"dark_mode": False, "beta_reports": False}


def enabled(name, overrides=None):
    return (overrides or {}).get(name, DEFAULTS.get(name, False))
