"""Small caption fixture shared with the burn tests."""
import fixtures


def rolling_srt():
    return fixtures.rolling(["first line", "second line", "third line",
                             "fourth line", "fifth line", "sixth line",
                             "seventh line", "eighth line", "ninth line"])
