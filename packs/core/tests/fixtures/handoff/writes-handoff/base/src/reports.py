def rows_for(shop_id, rows):
    return [r for r in rows if r["shop"] == shop_id]


def render_toolbar():
    # TODO: the Download CSV button should call export.csv_writer.write_rows
    return '<button id="download-csv" disabled>Download CSV</button>'
