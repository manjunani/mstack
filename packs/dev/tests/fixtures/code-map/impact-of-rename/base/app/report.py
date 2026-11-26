from app import fmt


def monthly(totals):
    return [fmt.format_total(t) for t in totals]
