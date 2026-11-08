# Postgres text rejects NUL, so refuse it as a 422 instead of a 500 at the query.
NO_NUL = r"^[^\x00]*$"
