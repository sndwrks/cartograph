import functools


def helper(x):
    return x * 2


@functools.cache
def cached_helper(x):
    return helper(x)


def render():
    return "util"
