DEFAULTS = {"dark_mode": False, "beta_reports": True}


def enabled(name, overrides=None):
    return (overrides or {}).get(name, DEFAULTS.get(name, False))
