import requests

from pkg.models import Node


class OrderService:
    def __init__(self):
        self.repo = Node()

    def check(self):
        return True

    def save(self, item):
        n = Node()
        n.validate()
        self.check()
        render()
        return requests.get(item)
