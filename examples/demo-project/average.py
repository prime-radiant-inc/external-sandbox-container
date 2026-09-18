"""A deliberately small bug for the sandbox demo."""


def average(values):
    if not values:
        raise ValueError("average needs at least one value")
    return sum(values) // len(values)
