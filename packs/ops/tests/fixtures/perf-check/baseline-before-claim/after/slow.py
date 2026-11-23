"""Count how many ships in the arrivals list are on the watch list."""


def load(n):
    arrivals = [f"ship-{i * 7 % 20000}" for i in range(n)]
    watch = [f"ship-{i}" for i in range(0, 20000, 3)]
    return arrivals, watch


def count_watched(arrivals, watch):
    lookup = {name: True for name in watch}
    return sum(1 for name in arrivals if name in lookup)


if __name__ == "__main__":
    arrivals, watch = load(8000)
    print(count_watched(arrivals, watch))
