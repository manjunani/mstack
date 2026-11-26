from app.fmt import format_line, render_total


def invoice_text(lines):
    body = [format_line(n, a) for n, a in lines]
    body.append("Total " + render_total(sum(a for _, a in lines)))
    return "\n".join(body)
