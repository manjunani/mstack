CREATE TABLE berths (
    id serial PRIMARY KEY,
    pier text NOT NULL,
    length_m numeric(5, 2) NOT NULL
);
